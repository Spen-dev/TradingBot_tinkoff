"""Самообучение: подбор параметров стратегий по истории и сохранение в learned_params."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from tinkoff.invest import CandleInterval

from .broker import TinkoffBroker
from .config import InstrumentConfig
from .learned_params import update_learned_params, load_learned_params, save_learned_params
from .strategy import build_strategy, Signal

logger = logging.getLogger(__name__)

DEFAULT_GRID = {
  "lookback": [15, 20, 25, 30],
  "threshold": [0.02, 0.03, 0.04, 0.05],
  "trend_threshold": [0.03, 0.04, 0.05],
  "strategy": ["adaptive", "momentum", "mean_reversion", "rsi", "breakout"],
  "period": [10, 14, 18],
  "overbought": [65, 70, 75],
  "oversold": [25, 30, 35],
  "fast_period": [8, 10, 12],
  "slow_period": [25, 30, 35],
}


class _BrokerWithData:
  """Обёртка: get_historical_candles возвращает срез df до current_time."""
  def __init__(self, broker: TinkoffBroker, figi: str, df: pd.DataFrame):
    self._broker = broker
    self._figi = figi
    self._df = df
    self._current_time: datetime | None = None

  def set_current_time(self, t: datetime) -> None:
    self._current_time = t

  def get_historical_candles(
    self, figi: str, from_dt: datetime, to_dt: datetime,
    interval: CandleInterval = CandleInterval.CANDLE_INTERVAL_DAY,
  ) -> pd.DataFrame:
    if figi != self._figi or self._current_time is None:
      return self._broker.get_historical_candles(figi, from_dt, to_dt, interval)
    mask = (
      (self._df.index >= from_dt)
      & (self._df.index <= to_dt)
      & (self._df.index <= self._current_time)
    )
    return self._df.loc[mask].copy()

  def __getattr__(self, name: str) -> Any:
    return getattr(self._broker, name)


def _count_trades(signals: List[Signal]) -> int:
  """Число смен позиции (покупка или продажа)."""
  if len(signals) < 2:
    return 0
  n = 0
  for i in range(1, len(signals)):
    if signals[i].side != signals[i - 1].side and signals[i].side != "hold":
      n += 1
  return n


def _simulate_pnl(
  df: pd.DataFrame,
  signals: List[Signal],
  commission_rate: float = 0.0,
) -> float:
  pnl, _, _ = _simulate_pnl_and_dd(df, signals, commission_rate)
  return pnl


def _simulate_pnl_and_dd(
  df: pd.DataFrame,
  signals: List[Signal],
  commission_rate: float = 0.0,
) -> Tuple[float, float, int, List[float]]:
  """Симуляция PnL, max drawdown, числа сделок и дневных доходностей. Комиссия: commission_rate с оборота за каждую сделку (вход и выход отдельно)."""
  if len(df) < 2 or len(signals) < 2:
    return 0.0, 0.0, 0, []
  closes = df["close"].values
  n = min(len(closes), len(signals) + 1)
  position = 0
  equity = 1.0
  peak = 1.0
  max_dd = 0.0
  daily_returns: List[float] = []
  prev_equity = 1.0
  for i in range(1, n):
    ret = (closes[i] - closes[i - 1]) / closes[i - 1] if closes[i - 1] else 0.0
    commission = 0.0
    sig = signals[i - 1] if i - 1 < len(signals) else signals[-1]
    if sig.side == "buy" and position == 0:
      position = 1
      commission += commission_rate
    elif sig.side == "sell" and position == 1:
      position = 0
      commission += commission_rate
    if position == 1:
      equity *= 1 + ret
    equity -= commission
    peak = max(peak, equity)
    dd = (peak - equity) / peak if peak else 0
    max_dd = max(max_dd, dd)
    day_ret = (equity - prev_equity) / prev_equity if prev_equity else 0.0
    daily_returns.append(day_ret)
    prev_equity = equity
  n_trades = _count_trades(signals[: n - 1])
  return equity - 1.0, max_dd, n_trades, daily_returns


def _compute_sharpe(returns: List[float], risk_free: float = 0.0) -> float:
  """Годовой Sharpe (доходности за день)."""
  if not returns or len(returns) < 2:
    return 0.0
  arr = np.array(returns)
  excess = arr - risk_free / 252
  std = np.std(excess)
  if std < 1e-12:
    return 0.0
  mean = np.mean(excess)
  return float(mean / std * np.sqrt(252))


def _volatility_regime(df: pd.DataFrame, atr_period: int = 14) -> str:
  """Режим волатильности: 'high' если ATR(close) выше медианы за окно."""
  if len(df) < atr_period + 5:
    return "normal"
  close = df["close"]
  high = df["high"] if "high" in df.columns else close
  low = df["low"] if "low" in df.columns else close
  tr = np.maximum(
    high - low,
    np.maximum(abs(high - close.shift(1)), abs(low - close.shift(1))),
  )
  atr = tr.rolling(atr_period).mean().iloc[-1]
  atr_pct = (atr / close.iloc[-1] * 100) if close.iloc[-1] else 0
  atr_hist = tr.rolling(atr_period).mean()
  atr_hist = atr_hist[atr_hist.notna()]
  median_atr = np.median(atr_hist.values)
  median_atr_pct = (median_atr / close.iloc[-1] * 100) if close.iloc[-1] else 0
  return "high" if atr_pct > median_atr_pct * 1.1 else "low"


def _get_signals_for_df(
  broker: TinkoffBroker,
  instrument: InstrumentConfig,
  df: pd.DataFrame,
  params_override: Dict[str, Any],
) -> List[Signal]:
  """Сигналы по свечам с переданными параметрами (данные из df)."""
  effective_params = {**(instrument.strategy_params or {}), **params_override}
  strategy_used = effective_params.pop("strategy", instrument.strategy)
  if isinstance(strategy_used, list):
    strategy_used = instrument.strategy
  effective_cfg = InstrumentConfig(
    figi=instrument.figi, ticker=instrument.ticker, strategy=strategy_used,
    target_weight=instrument.target_weight, strategy_params=effective_params,
    lot=getattr(instrument, "lot", 1) or 1,
  )
  wrapper = _BrokerWithData(broker, instrument.figi, df)
  strat = build_strategy(strategy_used, effective_cfg, wrapper)
  signals = []
  for idx in range(len(df)):
    t = df.index[idx]
    if hasattr(t, "to_pydatetime"):
      t = t.to_pydatetime()
    wrapper.set_current_time(t)
    try:
      sig = strat.compute_signal(t)
      signals.append(sig)
    except Exception:
      signals.append(Signal(figi=instrument.figi, side="hold", strength=0.0))
  return signals


# Стратегии, по которым выбираем лучшую по бэктесту
STRATEGY_CANDIDATES = ["momentum", "mean_reversion", "rsi", "breakout", "adaptive"]


def _score_deepseek_vs_validation(
  inst: InstrumentConfig,
  df_val: pd.DataFrame,
  rec: Dict[str, Any],
) -> Tuple[float, float]:
  """Оценка рекомендации DeepSeek по совпадению с движением цены на валидации. Возвращает (combined_score, display_value)."""
  if len(df_val) < 2:
    return -1e9, 0.0
  val_return = float(df_val["close"].iloc[-1] / df_val["close"].iloc[0] - 1.0)
  action = (rec.get("action") or "hold").lower()
  if action == "hold":
    score = 0.5
    display = 0.0
  elif action == "buy":
    score = 0.5 + 0.5 * (1.0 if val_return > 0 else -1.0)
    display = val_return
  elif action == "sell":
    score = 0.5 + 0.5 * (1.0 if val_return < 0 else -1.0)
    display = -val_return
  else:
    score = 0.5
    display = 0.0
  combined = (score - 0.5) * 2.0
  return combined, display


def run_strategy_selection(
  broker: TinkoffBroker,
  instruments: List[InstrumentConfig],
  days: int = 90,
  commission_rate: float = 0.0003,
  train_ratio: float = 0.7,
  use_sharpe: bool = True,
  min_trades: int = 5,
  risk_penalty: float = 0.5,
  allow_deepseek: bool = False,
  deepseek_model: str = "deepseek-chat",
  strategy_change_min_delta: float = 0.05,
  strategy_diversity_max_share: float = 0.0,
) -> Tuple[str, List[Tuple[str, str, str]]]:
  """Для каждого инструмента перебирает стратегии, выбирает лучшую, пишет в learned_params. Возвращает (сообщение, список (ticker, old_strategy, new_strategy))."""
  to_dt = datetime.now()
  from_dt = to_dt - timedelta(days=days)
  lines = ["Выбор стратегий завершён."]
  grid = DEFAULT_GRID
  learned_before = load_learned_params()
  changes: List[Tuple[str, str, str]] = []
  weight_by_strategy: Dict[str, float] = {}
  deepseek_recs: Dict[str, Dict[str, Any]] = {}
  if allow_deepseek:
    try:
      positions = broker.get_portfolio()
      cash = broker.get_cash_balance()
      equity = cash + sum(getattr(p, "value", 0) for p in positions.values())
      last_prices: Dict[str, float] = {}
      for i in instruments:
        pos = positions.get(i.figi)
        last_prices[i.figi] = getattr(pos, "current_price", None) or broker.get_last_price(i.figi) or 0.0
      from .deepseek_advisor import get_recommendations as get_deepseek_recommendations
      deepseek_recs = get_deepseek_recommendations(
        instruments=instruments,
        positions=positions,
        equity=equity,
        cash=cash,
        last_prices=last_prices,
        model=deepseek_model,
      )
    except Exception as e:
      logger.warning("DeepSeek при выборе стратегий: %s", e)
  for inst in instruments:
    try:
      df = broker.get_historical_candles(inst.figi, from_dt, to_dt)
    except Exception as e:
      logger.warning("Не удалось загрузить свечи для %s: %s", inst.ticker, e)
      lines.append(f"  {inst.ticker}: нет данных")
      continue
    if len(df) < 40:
      lines.append(f"  {inst.ticker}: мало свечей ({len(df)})")
      continue
    split = int(len(df) * max(0.5, min(0.9, train_ratio)))
    df_train = df.iloc[:split]
    df_val = df.iloc[split:]
    candidates = list(STRATEGY_CANDIDATES)
    if isinstance(inst.strategy_params, dict) and inst.strategy_params.get("rl_model_path"):
      rl_path = Path(inst.strategy_params["rl_model_path"])
      if rl_path.exists():
        candidates.append("rl")
    if allow_deepseek and inst.figi in deepseek_recs:
      candidates.append("deepseek")
    eff = learned_before.get(inst.figi, {}).get("strategy", inst.strategy)
    current_strategy = eff if isinstance(eff, str) else (eff[0] if isinstance(eff, list) and eff else "adaptive")
    tw = getattr(inst, "target_weight", 1.0 / max(len(instruments), 1))
    best_name: Optional[str] = None
    best_score = -1e9
    best_sharpe = 0.0
    current_score = -1e9
    for strat_name in candidates:
      try:
        if strategy_diversity_max_share > 0:
          would_be = weight_by_strategy.get(strat_name, 0) + tw
          if would_be > strategy_diversity_max_share:
            diversity_penalty = 0.2
          else:
            diversity_penalty = 0.0
        else:
          diversity_penalty = 0.0
        if strat_name == "deepseek":
          rec = deepseek_recs.get(inst.figi)
          if not rec:
            continue
          combined, display_val = _score_deepseek_vs_validation(inst, df_val, rec)
          combined -= diversity_penalty
          if combined > best_score:
            best_score = combined
            best_name = "deepseek"
            best_sharpe = display_val
          if strat_name == current_strategy:
            current_score = combined
          continue
        params: Dict[str, Any] = {"strategy": strat_name}
        for key, vals in grid.items():
          if key != "strategy" and vals and key not in params:
            params[key] = vals[0]
        sig_train = _get_signals_for_df(broker, inst, df_train, params)
        sig_val = _get_signals_for_df(broker, inst, df_val, params)
        _, dd_t, nt_t, ret_t = _simulate_pnl_and_dd(df_train, sig_train, commission_rate)
        _, dd_v, nt_v, ret_v = _simulate_pnl_and_dd(df_val, sig_val, commission_rate)
        if nt_t < min_trades or nt_v < min_trades:
          continue
        if use_sharpe:
          sh_t = _compute_sharpe(ret_t)
          sh_v = _compute_sharpe(ret_v)
          score_t = sh_t - risk_penalty * dd_t
          score_v = sh_v - risk_penalty * dd_v
        else:
          pnl_t, _, _, _ = _simulate_pnl_and_dd(df_train, sig_train, commission_rate)
          pnl_v, _, _, _ = _simulate_pnl_and_dd(df_val, sig_val, commission_rate)
          score_t = pnl_t - risk_penalty * dd_t
          score_v = pnl_v - risk_penalty * dd_v
          sh_v = pnl_v
        combined = 0.5 * score_t + 0.5 * score_v - diversity_penalty
        if combined > best_score:
          best_score = combined
          best_name = strat_name
          best_sharpe = _compute_sharpe(ret_v) if use_sharpe else sh_v
        if strat_name == current_strategy:
          current_score = combined
      except Exception as e:
        logger.debug("Стратегия %s для %s: %s", strat_name, inst.ticker, e)
        continue
    if best_name:
      should_switch = best_name != current_strategy and (best_score - current_score) >= strategy_change_min_delta
      chosen = best_name if should_switch else current_strategy
      if should_switch:
        update_learned_params(inst.figi, {"strategy": best_name})
        changes.append((inst.ticker, current_strategy, best_name))
      weight_by_strategy[chosen] = weight_by_strategy.get(chosen, 0) + tw
      if best_name == "deepseek":
        lines.append(f"  {inst.ticker}: deepseek (совпадение с валидацией)")
      else:
        lines.append(f"  {inst.ticker}: {best_name} (Sharpe≈{best_sharpe:.3f})")
    else:
      lines.append(f"  {inst.ticker}: не выбрана (мало сделок или ошибки)")
  return "\n".join(lines), changes


def tune_instrument_params(
  broker: TinkoffBroker,
  instrument: InstrumentConfig,
  days: int = 60,
  param_grid: Dict[str, List[Any]] | None = None,
  risk_penalty: float = 0.5,
  commission_rate: float = 0.0003,
  train_ratio: float = 0.7,
  use_sharpe: bool = True,
  min_trades: int = 5,
  atr_period: int = 14,
  optuna_trials: int = 0,
  regime_filter: str | None = None,
  n_val_slices: int = 1,
) -> Dict[str, Any]:
  """Подбор параметров: walk-forward (train/val), комиссии, Sharpe, мин. сделок. n_val_slices > 1: валидация по нескольким срезам, усреднение combined."""
  to_dt = datetime.now()
  from_dt = to_dt - timedelta(days=days)
  try:
    df = broker.get_historical_candles(instrument.figi, from_dt, to_dt)
  except Exception as e:
    logger.warning("Не удалось загрузить свечи для %s: %s", instrument.ticker, e)
    return {}

  if len(df) < 30:
    logger.warning("Мало свечей для %s: %d", instrument.ticker, len(df))
    return {}

  if regime_filter in ("trend", "range"):
    try:
      from .market_regime import adx
      adx_ser = adx(df, atr_period)
      thresh = 25.0
      if regime_filter == "trend":
        mask = adx_ser > thresh
      else:
        mask = adx_ser <= thresh
      df = df.loc[mask].dropna(how="all")
      if len(df) < 20:
        return {}
    except Exception:
      return {}

  regime = _volatility_regime(df, atr_period)
  split = int(len(df) * max(0.5, min(0.9, train_ratio)))
  df_train = df.iloc[:split]
  df_val = df.iloc[split:]
  if n_val_slices > 1 and len(df_val) >= n_val_slices:
    val_slices = []
    step = len(df_val) // n_val_slices
    for i in range(n_val_slices):
      start = i * step
      end = (i + 1) * step if i < n_val_slices - 1 else len(df_val)
      if end - start >= 5:
        val_slices.append(df_val.iloc[start:end])
  else:
    val_slices = [df_val]

  grid = param_grid or DEFAULT_GRID
  strategy_type = instrument.strategy if isinstance(instrument.strategy, str) else "adaptive"
  if strategy_type == "adaptive":
    keys_to_tune = ["strategy", "lookback", "threshold", "trend_threshold"]
  elif strategy_type == "momentum":
    keys_to_tune = ["lookback", "threshold", "trend_threshold"]
  elif strategy_type == "rsi":
    keys_to_tune = ["period", "overbought", "oversold"]
  elif strategy_type == "ma_crossover":
    keys_to_tune = ["fast_period", "slow_period"]
  elif strategy_type == "rl":
    keys_to_tune = ["threshold"]
  else:
    keys_to_tune = ["lookback", "threshold"]

  best_params: Dict[str, Any] = {}
  best_score: float = -1e9
  tried = 0

  def score_params(params: Dict[str, Any]) -> Tuple[float, float, float, int]:
    """(train_score, val_score, combined_score, n_trades_val). При нескольких val_slices — усреднение combined."""
    try:
      sig_train = _get_signals_for_df(broker, instrument, df_train, params)
      pnl_t, dd_t, nt_t, ret_t = _simulate_pnl_and_dd(df_train, sig_train, commission_rate)
      if use_sharpe:
        sharpe_t = _compute_sharpe(ret_t)
        s_t = sharpe_t - risk_penalty * dd_t
      else:
        s_t = pnl_t - risk_penalty * dd_t
      combined_sum = 0.0
      nt_v_total = 0
      for dv in val_slices:
        sig_val = _get_signals_for_df(broker, instrument, dv, params)
        pnl_v, dd_v, nt_v, ret_v = _simulate_pnl_and_dd(dv, sig_val, commission_rate)
        nt_v_total += nt_v
        if nt_t < min_trades and nt_v < min_trades:
          combined_sum += -1e9
          continue
        if use_sharpe:
          sharpe_v = _compute_sharpe(ret_v)
          s_v = sharpe_v - risk_penalty * dd_v
        else:
          s_v = pnl_v - risk_penalty * dd_v
        combined_sum += 0.5 * s_t + 0.5 * s_v
      combined = combined_sum / len(val_slices) if val_slices else -1e9
      # Для порога min_trades в переборе: не только val (иначе при «тихом» хвосте nt=0 при живом train)
      nt_v_avg = nt_v_total // max(len(val_slices), 1)
      nt_gate = max(nt_t, nt_v_avg)
      return s_t, combined, combined, nt_gate
    except Exception:
      return -1e9, -1e9, -1e9, 0

  if optuna_trials > 0:
    try:
      import optuna
      def objective(trial: Any) -> float:
        nonlocal tried
        params = {}
        for key in keys_to_tune:
          vals = grid.get(key)
          if not vals:
            continue
          params[key] = trial.suggest_categorical(key, list(vals))
        _, _, combined, _ = score_params(params)
        tried += 1
        return -combined
      study = optuna.create_study(direction="minimize")
      study.optimize(objective, n_trials=optuna_trials, show_progress_bar=False)
      if study.best_params:
        best_params = dict(study.best_params)
        _, _, best_score, _ = score_params(best_params)
    except ImportError:
      logger.warning("Optuna не установлена, используется перебор по сетке")
      optuna_trials = 0

  if optuna_trials == 0 or not best_params:
    def recurse(keys: List[str], idx: int, current: Dict[str, Any]) -> None:
      nonlocal best_score, best_params, tried
      if idx >= len(keys):
        _, _, combined, nt = score_params(current)
        tried += 1
        if combined > best_score and nt >= min_trades:
          best_score = combined
          best_params = dict(current)
        return
      key = keys[idx]
      values = grid.get(key)
      if not values:
        recurse(keys, idx + 1, current)
        return
      for v in values:
        current[key] = v
        recurse(keys, idx + 1, current)
      if key in current:
        del current[key]

    recurse(keys_to_tune, 0, {})

  # Для RL с моделью перебор по threshold не меняет сигналы; если ничего не подобрали — примем текущие параметры при хотя бы одной сделке
  if strategy_type == "rl" and not best_params:
    try:
      current_params = dict(instrument.strategy_params or {})
      _, _, combined, nt = score_params(current_params)
      # combined может быть -1e9 из-за жёсткого окна val; при наличии сделок на train всё равно сохраняем текущие params
      if nt >= 1:
        best_params = current_params
        best_score = combined
        logger.info("Самообучение %s (rl): приняты текущие параметры, nt_gate=%d score=%.4f", instrument.ticker, nt, combined)
    except Exception as e:
      logger.debug("RL fallback для %s: %s", instrument.ticker, e)

  if best_params and regime:
    best_params["_volatility_regime"] = regime
  logger.info(
    "Самообучение %s: перебрано %d, лучший score %.4f, params %s",
    instrument.ticker, tried, best_score, best_params,
  )
  return best_params


def run_retrain(
  broker: TinkoffBroker,
  instruments: List[InstrumentConfig],
  days: int = 60,
  commission_rate: float = 0.0003,
  train_ratio: float = 0.7,
  use_sharpe: bool = True,
  min_trades: int = 5,
  risk_penalty: float = 0.5,
  risk_penalty_mult: float = 1.0,
  optuna_trials: int = 0,
  optimize_weights: bool = False,
  weight_cap: float = 0.4,
  atr_period: int = 14,
  tune_by_regime: bool = False,
  run_strategy_selection_first: bool = False,
  strategy_selection_days: int = 90,
) -> str:
  """Самообучение по всем инструментам. tune_by_regime: подбор отдельно для тренда и флэта. run_strategy_selection_first: сначала выбрать лучшую стратегию, затем подбирать параметры для неё."""
  effective_penalty = risk_penalty * risk_penalty_mult
  if run_strategy_selection_first:
    run_strategy_selection(
      broker, instruments, days=strategy_selection_days,
      commission_rate=commission_rate, train_ratio=train_ratio,
      use_sharpe=use_sharpe, min_trades=min_trades, risk_penalty=effective_penalty,
    )
  lines = ["Самообучение завершено."]
  results: List[Tuple[InstrumentConfig, Dict[str, Any], float, List[float]]] = []
  learned = load_learned_params()
  for inst in instruments:
    try:
      eff = learned.get(inst.figi, {}).get("strategy", inst.strategy)
      eff_strategy = eff if isinstance(eff, str) else (eff[0] if isinstance(eff, list) and eff else "adaptive")
      # Для RL сетка почти только threshold (сигналы часто те же); порог сделок мягче, иначе часто «параметры не подобраны»
      effective_min_trades = max(1, min(2, min_trades)) if eff_strategy == "rl" else min_trades
      inst_for_tune = InstrumentConfig(
        figi=inst.figi, ticker=inst.ticker, strategy=eff_strategy,
        target_weight=inst.target_weight, strategy_params=dict(inst.strategy_params or {}),
        lot=getattr(inst, "lot", 1) or 1,
      )
      best = tune_instrument_params(
        broker, inst_for_tune, days=days,
        risk_penalty=effective_penalty,
        commission_rate=commission_rate,
        train_ratio=train_ratio,
        use_sharpe=use_sharpe,
        min_trades=effective_min_trades,
        optuna_trials=optuna_trials,
        atr_period=atr_period,
      )
      if tune_by_regime:
        best_trend = tune_instrument_params(broker, inst, days=days, risk_penalty=effective_penalty, commission_rate=commission_rate, train_ratio=train_ratio, use_sharpe=use_sharpe, min_trades=min_trades, optuna_trials=0, atr_period=atr_period, regime_filter="trend")
        best_range = tune_instrument_params(broker, inst, days=days, risk_penalty=effective_penalty, commission_rate=commission_rate, train_ratio=train_ratio, use_sharpe=use_sharpe, min_trades=min_trades, optuna_trials=0, atr_period=atr_period, regime_filter="range")
        if best_trend:
          update_learned_params(inst.figi, {"strategy_trend": best_trend.get("strategy", inst.strategy), "params_trend": {k: v for k, v in best_trend.items() if k != "_volatility_regime"}})
        if best_range:
          update_learned_params(inst.figi, {"strategy_range": best_range.get("strategy", inst.strategy), "params_range": {k: v for k, v in best_range.items() if k != "_volatility_regime"}})
      if best:
        # Guard-rail: не принимать параметры, если новый Sharpe значительно хуже старого
        prev_info = (learned.get(inst.figi, {}) or {}).get("retrain_info") or {}
        old_sharpe = float(prev_info.get("sharpe", 0.0) or 0.0)
        sharpe_degradation_limit = 0.2  # допустимое ухудшение Sharpe
        if old_sharpe > 0 and sharpe < old_sharpe - sharpe_degradation_limit:
          lines.append(f"  {inst.ticker}: лучшие найденные параметры хуже старых (Sharpe≈{sharpe:.3f} < {old_sharpe:.3f}), пропущено")
          continue
        update_learned_params(inst.figi, best)
        # Оценка для весов: симулируем PnL с лучшими параметрами за весь период
        rets: List[float] = []
        try:
          to_dt = datetime.now()
          from_dt = to_dt - timedelta(days=days)
          df = broker.get_historical_candles(inst.figi, from_dt, to_dt)
          if len(df) >= 20:
            sigs = _get_signals_for_df(broker, inst, df, best)
            _, _, _, rets = _simulate_pnl_and_dd(df, sigs, commission_rate)
            sharpe = _compute_sharpe(rets)
          else:
            sharpe = 0.0
        except Exception:
          sharpe = 0.0
        results.append((inst, best, sharpe, rets))
        lines.append(f"  {inst.ticker}: {best} (Sharpe≈{sharpe:.3f})")
        try:
          # Сохраняем краткую метаинформацию о последнем обучении в learned_params
          update_learned_params(inst.figi, {
            "retrain_info": {
              "days": days,
              "sharpe": float(sharpe),
              "ts": datetime.now().isoformat(),
            },
          })
        except Exception:
          pass
      else:
        lines.append(f"  {inst.ticker}: параметры не подобраны")
    except Exception as e:
      logger.exception("Ошибка самообучения для %s", inst.ticker)
      lines.append(f"  {inst.ticker}: ошибка — {e}")

  if optimize_weights and results:
    figi_order = [inst.figi for inst, _, _, _ in results]
    sharpes = [(inst.figi, max(0.0, sharpe)) for inst, _, sharpe, _ in results]
    total = sum(s for _, s in sharpes)
    if total > 0:
      learned = load_learned_params()
      # Корреляции: штрафуем вес при высокой корреляции с другими
      returns_list = [rets for (_, _, _, rets) in results]
      min_len = min(len(r) for r in returns_list) if returns_list else 0
      corr_penalty: Dict[str, float] = {}
      if min_len > 10 and len(returns_list) > 1:
        try:
          aligned = np.array([r[-min_len:] for r in returns_list])
          corr = np.corrcoef(aligned)
          for i, figi in enumerate(figi_order):
            if i < corr.shape[0]:
              other_corr = [corr[i, j] for j in range(len(figi_order)) if j != i]
              max_corr = max(other_corr, default=0.0)
              corr_penalty[figi] = max(0.0, min(0.5, max_corr * 0.7))
            else:
              corr_penalty[figi] = 0.0
        except Exception:
          pass
      # Реальный PnL по инструментам: снижаем вес при устойчивом убытке
      real_pnl_penalty: Dict[str, float] = {}
      try:
        from .trade_history import get_per_instrument_stats
        get_price = getattr(broker, "get_last_price", None)
        if get_price:
          real_stats = get_per_instrument_stats(get_price, horizon_days=min(60, days))
          for figi in figi_order:
            if figi in real_stats and real_stats[figi].get("pnl", 0) < 0 and real_stats[figi].get("trades", 0) >= 3:
              real_pnl_penalty[figi] = 0.6
            else:
              real_pnl_penalty[figi] = 1.0
      except Exception:
        real_pnl_penalty = {f: 1.0 for f in figi_order}
      for figi, sh in sharpes:
        w = (sh / total) if total else (1.0 / len(sharpes))
        w *= (1.0 - corr_penalty.get(figi, 0.0))
        w *= real_pnl_penalty.get(figi, 1.0)
        w = min(w, weight_cap)
        learned[figi] = learned.get(figi) or {}
        learned[figi]["target_weight"] = round(w, 4)
      figis_with_w = [f for f, _ in sharpes if learned.get(f, {}).get("target_weight") is not None]
      ws = [learned[f]["target_weight"] for f in figis_with_w]
      if ws and abs(sum(ws) - 1.0) > 0.01:
        scale = 1.0 / sum(ws)
        for figi in figis_with_w:
          learned[figi]["target_weight"] = round(learned[figi]["target_weight"] * scale, 4)
      save_learned_params(learned)
      lines.append("  Веса пересчитаны по Sharpe (корреляции и реальный PnL учтены, cap=%.0f%%)." % (weight_cap * 100))

  return "\n".join(lines)

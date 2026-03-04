"""Самообучение: подбор параметров стратегий по истории и сохранение в learned_params."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
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
      return s_t, combined, combined, nt_v_total // max(len(val_slices), 1)
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
) -> str:
  """Самообучение по всем инструментам. tune_by_regime: подбор отдельно для тренда и флэта (strategy_trend/params_trend, strategy_range/params_range)."""
  effective_penalty = risk_penalty * risk_penalty_mult
  lines = ["Самообучение завершено."]
  results: List[Tuple[InstrumentConfig, Dict[str, Any], float, List[float]]] = []
  for inst in instruments:
    try:
      best = tune_instrument_params(
        broker, inst, days=days,
        risk_penalty=effective_penalty,
        commission_rate=commission_rate,
        train_ratio=train_ratio,
        use_sharpe=use_sharpe,
        min_trades=min_trades,
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

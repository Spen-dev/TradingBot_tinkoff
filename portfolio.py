from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional
import json
import logging
import math

import numpy as np
from tinkoff.invest import OrderDirection, OrderType

from .config import InstrumentConfig, PortfolioConfig
from .broker import TinkoffBroker, Position
from .risk import RiskManager, RiskState
from .strategy import build_strategy, Signal
from .learned_params import load_learned_params, get_effective_params, get_effective_strategy, get_effective_target_weight

logger = logging.getLogger(__name__)

_BASE_DIR = Path(__file__).resolve().parent
_DATA_DIR = _BASE_DIR / "data"
LAST_TRADES_FILE = _DATA_DIR / "last_trades.json"
POSITION_PEAKS_FILE = _DATA_DIR / "position_peaks.json"
AUDIT_ORDERS_FILE = _DATA_DIR / "audit_orders.log"
REBALANCE_DECISIONS_FILE = _DATA_DIR / "logs" / "rebalance_decisions.log"


def _log_rebalance_decisions(
  equity: float,
  entries: List[Dict[str, Any]],
  orders: List["RebalanceOrder"],
) -> None:
  """Запись решений ребаланса: по инструментам (стратегия, сигнал, целевая/текущая сумма) и заявки."""
  try:
    REBALANCE_DECISIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().isoformat()
    lines = [f"# {ts} equity={equity:.0f} RUB", ""]
    for e in entries:
      lines.append(f"  {e.get('ticker', '')}: strategy={e.get('strategy', '')} signal={e.get('signal', '')} target={e.get('target_rub', 0):.0f} current={e.get('current_rub', 0):.0f}")
    lines.append("")
    for o in orders:
      dir_str = "BUY" if o.direction == OrderDirection.ORDER_DIRECTION_BUY else "SELL"
      lines.append(f"  ORDER {o.ticker} {dir_str} qty={o.quantity} price={o.execution_price:.2f} strategy={getattr(o, 'strategy_used', '')}")
    lines.append("")
    with open(REBALANCE_DECISIONS_FILE, "a", encoding="utf-8") as f:
      f.write("\n".join(lines))
  except Exception as e:
    logger.debug("rebalance_decisions log: %s", e)


def _audit_order(action: str, figi: str, ticker: str, direction: str, quantity: int, price: float, order_id: str = "") -> None:
  """Запись в аудит-лог заявок (placement/cancel)."""
  try:
    AUDIT_ORDERS_FILE.parent.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().isoformat()
    line = f"{ts}\t{action}\t{figi}\t{ticker}\t{direction}\tqty={quantity}\tprice={price}\torder_id={order_id}\n"
    with open(AUDIT_ORDERS_FILE, "a", encoding="utf-8") as f:
      f.write(line)
  except Exception as e:
    logger.debug("audit_order: %s", e)


@dataclass
class RebalanceOrder:
  figi: str
  ticker: str
  quantity: int
  direction: OrderDirection
  execution_price: float
  signal_strength: float = 1.0
  strategy_used: str = ""


def _load_last_trades() -> Dict[str, str]:
  try:
    if LAST_TRADES_FILE.exists():
      return json.loads(LAST_TRADES_FILE.read_text(encoding="utf-8"))
  except Exception:
    pass
  return {}


def _load_position_peaks() -> Dict[str, float]:
  try:
    if POSITION_PEAKS_FILE.exists():
      data = json.loads(POSITION_PEAKS_FILE.read_text(encoding="utf-8"))
      return {k: float(v) for k, v in (data or {}).items()}
  except Exception:
    pass
  return {}


def _save_position_peaks(peaks: Dict[str, float]) -> None:
  try:
    POSITION_PEAKS_FILE.parent.mkdir(parents=True, exist_ok=True)
    POSITION_PEAKS_FILE.write_text(json.dumps(peaks, indent=2), encoding="utf-8")
  except Exception as e:
    logger.debug("Не удалось сохранить position_peaks: %s", e)


def _volatility_factor(
  broker, figi: str, atr_period: int, percentile_days: int = 0,
) -> float:
  """Коэффициент размера позиции: при высокой ATR уменьшаем долю. При percentile_days>0 — по перцентилям ATR (90-й → 0.7x, 25-й → 1.1x)."""
  try:
    days = max(atr_period + 20, percentile_days + 5) if percentile_days else atr_period + 20
    to_dt = datetime.now()
    from_dt = to_dt - timedelta(days=days)
    df = broker.get_historical_candles(figi, from_dt, to_dt)
    if df is None or len(df) < atr_period + 5:
      return 1.0
    close = df["close"]
    high = df["high"] if "high" in df.columns else close
    low = df["low"] if "low" in df.columns else close
    tr = np.maximum(high - low, np.maximum(abs(high - close.shift(1)), abs(low - close.shift(1))))
    atr_roll = tr.rolling(atr_period).mean()
    atr_pct = (atr_roll / close * 100).replace([np.inf, -np.inf], np.nan).dropna()
    if percentile_days > 0 and len(atr_pct) >= percentile_days:
      recent = atr_pct.iloc[-percentile_days:]
      p90 = np.percentile(recent.values, 90)
      p25 = np.percentile(recent.values, 25)
      current = atr_pct.iloc[-1]
      if current >= p90:
        return 0.7
      if current <= p25:
        return min(1.2, 1.1)
    atr_pct_val = atr_pct.iloc[-1] if len(atr_pct) else 0
    factor = 1.0 / (1.0 + atr_pct_val / 10.0)
    return float(max(0.5, min(1.2, factor)))
  except Exception:
    return 1.0


def _signal_confirmed(broker, figi: str, direction: OrderDirection, n_candles: int) -> bool:
  """Проверка: последние n_candles свечей подтверждают направление (BUY — зелёные, SELL — красные)."""
  if n_candles <= 0:
    return True
  try:
    to_dt = datetime.now()
    from_dt = to_dt - timedelta(days=n_candles + 5)
    df = broker.get_historical_candles(figi, from_dt, to_dt)
    if df is None or len(df) < n_candles:
      return True
    df = df.tail(n_candles)
    if "close" not in df.columns or "open" not in df.columns:
      return True
    if direction == OrderDirection.ORDER_DIRECTION_BUY:
      return (df["close"] >= df["open"]).all()
    return (df["close"] <= df["open"]).all()
  except Exception:
    return True


def _volume_factor(broker, figi: str, min_ratio: float) -> float:
  """Коэффициент 0..1 при низком объёме: если объём дня < min_ratio * средний за 20 дней — снижаем размер."""
  if min_ratio <= 0:
    return 1.0
  try:
    to_dt = datetime.now()
    from_dt = to_dt - timedelta(days=25)
    df = broker.get_historical_candles(figi, from_dt, to_dt)
    if df is None or len(df) < 5 or "volume" not in df.columns:
      return 1.0
    vol = df["volume"]
    if vol.isna().all() or vol.iloc[-1] == 0:
      return 1.0
    last_vol = float(vol.iloc[-1])
    avg_vol = float(vol.iloc[:-1].mean())
    if avg_vol <= 0:
      return 1.0
    ratio = last_vol / avg_vol
    if ratio >= min_ratio:
      return 1.0
    return max(0.0, ratio / min_ratio)
  except Exception:
    return 1.0


def _save_last_trade(figi: str) -> None:
  data = _load_last_trades()
  data[figi] = datetime.now().isoformat()
  try:
    LAST_TRADES_FILE.parent.mkdir(parents=True, exist_ok=True)
    LAST_TRADES_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
  except Exception as e:
    logger.warning("Не удалось сохранить last_trades: %s", e)


class PortfolioManager:
  def __init__(
    self,
    cfg: PortfolioConfig,
    instruments: List[InstrumentConfig],
    broker: TinkoffBroker,
    risk: RiskManager,
  ):
    self.cfg = cfg
    self.instruments_cfg = {i.figi: i for i in instruments}
    self.broker = broker
    self.risk = risk

  def _compute_equity(self, positions: Dict[str, Position], cash: float) -> float:
    return cash + sum(p.value for p in positions.values())

  def _target_values(self, equity: float, prices: Optional[Dict[str, float]] = None) -> Dict[str, float]:
    """Целевые суммы в рублях. Веса из learned_params (если optimize_weights), иначе из конфига."""
    if getattr(self.cfg, "rebalance_by_price", False) and prices:
      total_price = sum(prices.get(f, 0.0) for f in self.instruments_cfg)
      if total_price > 0:
        return {figi: equity * (prices.get(figi, 0.0) / total_price) for figi in self.instruments_cfg}
    learned = load_learned_params()
    targets = {}
    for ins in self.instruments_cfg.values():
      w = get_effective_target_weight(ins, learned)
      targets[ins.figi] = equity * w
    return targets

  def rebalance_needed(self, day_start_equity: float, drift_pct: float) -> bool:
    """Ребаланс нужен, если какая-то доля отклонилась от целевой больше чем на drift_pct (0.05 = 5%)."""
    positions = self.broker.get_portfolio()
    cash = self.broker.get_cash_balance()
    equity = self._compute_equity(positions, cash)
    if equity <= 0:
      return False
    risk_state: RiskState = self.risk.update_equity(equity, day_start_equity)
    if not self.risk.is_trading_allowed(risk_state):
      return False
    prices_for_target: Optional[Dict[str, float]] = None
    if getattr(self.cfg, "rebalance_by_price", False):
      prices_for_target = {}
      for figi in self.instruments_cfg:
        pos = positions.get(figi)
        prices_for_target[figi] = pos.current_price if pos else self.broker.get_last_price(figi)
    targets = self._target_values(equity, prices_for_target)
    for figi in self.instruments_cfg:
      current_value = positions[figi].value if positions.get(figi) else 0.0
      target_value = targets.get(figi, 0.0)
      current_w = current_value / equity
      target_w = target_value / equity
      if abs(current_w - target_w) >= drift_pct:
        return True
    return False

  def _round_quantity(self, value_diff: float, price: float, lot: int) -> int:
    """Количество в лотах: округляем до кратного lot, для покупки минимум 1 лот."""
    qty = value_diff / price
    if qty >= 0:  # покупка
      lots = max(1, int(math.floor(qty / lot)))
      return lots * lot
    # продажа
    lots = int(math.floor(abs(qty) / lot))
    return lots * lot if lots > 0 else 0

  def build_rebalance_orders(self, day_start_equity: float) -> List[RebalanceOrder]:
    positions = self.broker.get_portfolio()
    cash = self.broker.get_cash_balance()
    equity = self._compute_equity(positions, cash)
    risk_state: RiskState = self.risk.update_equity(equity, day_start_equity)

    if not self.risk.is_trading_allowed(risk_state):
      return []

    # Мягкая деградация: при дневном убытке выше soft-лимита уменьшаем размер заявок.
    size_scale = 1.0
    try:
      size_scale = getattr(self.risk, "get_size_scale", lambda _: 1.0)(risk_state)
    except Exception:
      size_scale = 1.0

    prices_for_target: Optional[Dict[str, float]] = None
    if getattr(self.cfg, "rebalance_by_price", False):
      prices_for_target = {}
      for figi in self.instruments_cfg:
        pos = positions.get(figi)
        prices_for_target[figi] = pos.current_price if pos else self.broker.get_last_price(figi)
    targets = self._target_values(equity, prices_for_target)

    # Рекомендации DeepSeek для инструментов со стратегией deepseek
    deepseek_recommendations: Dict[str, Dict[str, Any]] = {}
    use_deepseek = getattr(self.cfg, "use_deepseek_advisor", False)
    instruments_list = list(self.instruments_cfg.values())
    has_deepseek = any(
      (getattr(c, "strategy", None) == "deepseek") or (isinstance(getattr(c, "strategy", None), list) and "deepseek" in getattr(c, "strategy", []))
      for c in instruments_list
    )
    if use_deepseek and has_deepseek:
      last_prices = {}
      for figi in self.instruments_cfg:
        pos = positions.get(figi)
        last_prices[figi] = pos.current_price if pos and getattr(pos, "current_price", None) else self.broker.get_last_price(figi)
      history_summary: Optional[Dict[str, str]] = None
      history_days = getattr(self.cfg, "deepseek_history_days", 0) or 0
      if history_days > 0:
        to_dt = datetime.now()
        from_dt = to_dt - timedelta(days=history_days)
        history_summary = {}
        # История по инструментам портфеля
        for ins in instruments_list:
          try:
            df = self.broker.get_historical_candles(ins.figi, from_dt, to_dt)
            if df is not None and len(df) >= 2 and "close" in df.columns:
              close = df["close"]
              r5 = (float(close.iloc[-1]) / float(close.iloc[-min(5, len(close))]) - 1) * 100 if len(close) >= 5 else 0
              r10 = (float(close.iloc[-1]) / float(close.iloc[0]) - 1) * 100
              high = df["high"].values if "high" in df.columns else close.values
              low = df["low"].values if "low" in df.columns else close.values
              peak = float(close.iloc[0])
              dd = 0.0
              for i in range(len(close)):
                p = float(close.iloc[i])
                peak = max(peak, p)
                if peak > 0:
                  dd = max(dd, (peak - p) / peak * 100)
              atr_pct = 0.0
              if len(close) >= 14 and "high" in df.columns and "low" in df.columns:
                prev = close.shift(1).bfill().values
                tr = np.maximum(high - low, np.maximum(np.abs(high - prev), np.abs(low - prev)))
                atr = float(np.mean(tr[-14:])) if len(tr) >= 14 else 0
                atr_pct = (atr / float(close.iloc[-1]) * 100) if close.iloc[-1] else 0
              history_summary[ins.ticker] = f"return_5d={r5:.1f}% return_10d={r10:.1f}% atr_pct={atr_pct:.1f}% dd_10d={dd:.1f}%"
            else:
              history_summary[ins.ticker] = "нет данных"
          except Exception:
            history_summary[getattr(ins, "ticker", "")] = "ошибка"
        # Сводка по рынку РФ (индекс)
        index_figi = getattr(self.cfg, "market_index_figi", "") or ""
        if index_figi:
          label = "IMOEX" if index_figi == "BBG004730JJ5" else index_figi
          key = f"MARKET_{label}"
          try:
            df_idx = self.broker.get_historical_candles(index_figi, from_dt, to_dt)
            if df_idx is not None and len(df_idx) >= 2 and "close" in df_idx.columns:
              close = df_idx["close"]
              r5 = (float(close.iloc[-1]) / float(close.iloc[-min(5, len(close))]) - 1) * 100 if len(close) >= 5 else 0
              r10 = (float(close.iloc[-1]) / float(close.iloc[0]) - 1) * 100
              high = df_idx["high"].values if "high" in df_idx.columns else close.values
              low = df_idx["low"].values if "low" in df_idx.columns else close.values
              peak = float(close.iloc[0])
              dd = 0.0
              for i in range(len(close)):
                p = float(close.iloc[i])
                peak = max(peak, p)
                if peak > 0:
                  dd = max(dd, (peak - p) / peak * 100)
              atr_pct = 0.0
              if len(close) >= 14 and "high" in df_idx.columns and "low" in df_idx.columns:
                prev = close.shift(1).bfill().values
                tr = np.maximum(high - low, np.maximum(np.abs(high - prev), np.abs(low - prev)))
                atr = float(np.mean(tr[-14:])) if len(tr) >= 14 else 0
                atr_pct = (atr / float(close.iloc[-1]) * 100) if close.iloc[-1] else 0
              # Режим рынка по индексу (trend/range/weak_trend)
              regime_str = ""
              try:
                from .market_regime import get_regime_by_index
                adx_period = getattr(self.cfg, "adx_period", 14)
                adx_threshold = getattr(self.cfg, "adx_threshold", 25.0)
                adx_threshold_low = getattr(self.cfg, "adx_threshold_low", 0.0) or 0.0
                adx_threshold_low = (adx_threshold_low if adx_threshold_low > 0 else None)
                regime_str = get_regime_by_index(
                  self.broker, index_figi, days=30, adx_period=adx_period,
                  adx_threshold=adx_threshold, adx_threshold_low=adx_threshold_low,
                )
              except Exception:
                regime_str = ""
              summary = f"return_5d={r5:.1f}% return_10d={r10:.1f}% atr_pct={atr_pct:.1f}% dd_10d={dd:.1f}%"
              if regime_str:
                summary += f" regime={regime_str}"
              history_summary[key] = summary
            else:
              history_summary[key] = "нет данных по индексу"
          except Exception:
            history_summary[key] = "ошибка при получении индекса"
      try:
        from .deepseek_advisor import get_recommendations as get_deepseek_recommendations
        recs = get_deepseek_recommendations(
          instruments=instruments_list,
          positions=positions,
          equity=equity,
          cash=cash,
          last_prices=last_prices,
          model=getattr(self.cfg, "deepseek_model", "deepseek-chat"),
          cache_hours=getattr(self.cfg, "deepseek_cache_hours", 0) or 0,
          history_summary=history_summary,
        )
        for figi, r in recs.items():
          if figi in targets:
            tw = r.get("target_weight")
            if tw is not None:
              targets[figi] = equity * max(0.0, min(1.0, float(tw)))
        deepseek_recommendations = recs
      except Exception as e:
        logger.warning("DeepSeek advisor: %s", e)

    # Тейк-профит и трейлинг прибыли: обновить пики, выявить принудительную продажу
    peaks = _load_position_peaks()
    force_sell: set = set()
    for figi, pos in positions.items():
      if figi not in self.instruments_cfg:
        continue
      peak = max(peaks.get(figi, 0.0), pos.current_price)
      peaks[figi] = peak
      if self.risk.should_take_profit(pos.average_price, pos.current_price) or self.risk.should_trailing_take_profit(peak, pos.current_price):
        force_sell.add(figi)
    _save_position_peaks(peaks)

    # Режим рынка по ADX для выбора стратегии/параметров
    use_regime = getattr(self.cfg, "use_market_regime", True)
    regimes: Dict[str, str] = {}
    if use_regime:
      try:
        from .market_regime import get_regime, get_regime_by_index
        adx_period = getattr(self.cfg, "adx_period", 14)
        adx_threshold = getattr(self.cfg, "adx_threshold", 25.0)
        adx_threshold_low = getattr(self.cfg, "adx_threshold_low", 0) or 0
        adx_threshold_low = (adx_threshold_low if adx_threshold_low > 0 else None)
        index_figi = getattr(self.cfg, "market_index_figi", "") or ""
        use_regime_by_index = getattr(self.cfg, "use_market_regime_by_index", False) and bool(index_figi)
        if use_regime_by_index:
          r = get_regime_by_index(
            self.broker, index_figi, days=30, adx_period=adx_period,
            adx_threshold=adx_threshold, adx_threshold_low=adx_threshold_low,
          )
          for figi in self.instruments_cfg:
            regimes[figi] = r
        else:
          for figi in self.instruments_cfg:
            regimes[figi] = get_regime(
              self.broker, figi, days=30, adx_period=adx_period,
              adx_threshold=adx_threshold, adx_threshold_low=adx_threshold_low,
            )
      except Exception:
        pass

    pending_buys: List[RebalanceOrder] = []
    sells: List[RebalanceOrder] = []
    remaining_cash = cash
    SAFETY = 0.75
    now = datetime.now()
    last_trades = _load_last_trades()
    learned = load_learned_params()
    atr_period = getattr(self.cfg, "volatility_atr_period", 14) or 14
    atr_percentile_days = getattr(self.cfg, "atr_percentile_days", 0) or 0
    volume_min_ratio = getattr(self.cfg, "volume_filter_min_ratio", 0.0) or 0.0
    max_position_pct = getattr(self.cfg, "max_position_pct", 0.0) or 0.0
    single_trade_max_pct = getattr(self.cfg, "single_trade_max_pct", 0.0) or 0.0
    hold_timeout_days = getattr(self.cfg, "hold_timeout_days", 0) or 0
    signal_confirmation_candles = getattr(self.cfg, "signal_confirmation_candles", 0) or 0
    signal_strength_mult = getattr(self.cfg, "signal_strength_mult", 0.2) or 0.2
    signal_strength_min = getattr(self.cfg, "signal_strength_min", 0.3) or 0.3
    max_overweight_pct = getattr(self.cfg, "max_overweight_without_signal_pct", 0.0) or 0.0
    try:
      from .instrument_pause import is_paused as instrument_is_paused
    except Exception:
      instrument_is_paused = lambda _: False
    last_buy_dates: Dict[str, str] = {}
    if hold_timeout_days > 0:
      try:
        from .trade_history import get_last_buy_date_per_figi
        last_buy_dates = get_last_buy_date_per_figi(horizon_days=hold_timeout_days + 30)
      except Exception:
        pass

    # Режим защиты от ночных гэпов: не открывать новые позиции близко к закрытию для «гэповых» бумаг
    gap_risk_enabled = getattr(self.cfg, "gap_risk_enabled", False)
    gap_min_pct = getattr(self.cfg, "gap_min_pct", 0.03) or 0.03
    gap_close_minutes = getattr(self.cfg, "gap_close_minutes", 60) or 60
    gap_risky: Dict[str, bool] = {}
    window_end_mins = getattr(self.cfg, "rebalance_window_end_minutes", 24 * 60)
    now_mins = now.hour * 60 + now.minute
    no_new_before_end = getattr(self.cfg, "no_new_orders_before_end_minutes", 0) or 0
    no_new_orders = no_new_before_end > 0 and (window_end_mins - now_mins <= no_new_before_end)
    near_close = gap_risk_enabled and (window_end_mins - now_mins <= gap_close_minutes)

    def _is_gap_risky(figi: str) -> bool:
      if figi in gap_risky:
        return gap_risky[figi]
      try:
        to_dt = datetime.now()
        from_dt = to_dt - timedelta(days=40)
        df = self.broker.get_historical_candles(figi, from_dt, to_dt)
        if df is None or len(df) < 5 or "open" not in df.columns or "close" not in df.columns:
          gap_risky[figi] = False
          return False
        closes = df["close"].values
        opens = df["open"].values
        gaps = []
        for i in range(1, min(len(closes), len(opens))):
          if closes[i - 1] > 0:
            gaps.append(abs(opens[i] - closes[i - 1]) / closes[i - 1])
        has_big_gap = any(g >= gap_min_pct for g in gaps[-20:])
        gap_risky[figi] = has_big_gap
        return has_big_gap
      except Exception:
        gap_risky[figi] = False
        return False

    rebalance_log_entries: List[Dict[str, Any]] = []
    for figi, cfg in self.instruments_cfg.items():
      if instrument_is_paused(figi):
        continue
      regime = regimes.get(figi)
      signal = None
      strategy_used = "—"
      if getattr(cfg, "strategy", None):
        try:
          effective_strategy = get_effective_strategy(cfg, learned, regime)
          effective_params = get_effective_params(cfg, learned, regime)
          use_deepseek = (
            effective_strategy == "deepseek"
            or (isinstance(effective_strategy, list) and effective_strategy and effective_strategy[0] == "deepseek")
          )
          if use_deepseek:
            if figi in deepseek_recommendations:
              rec = deepseek_recommendations[figi]
              signal = Signal(figi=figi, side=rec.get("action", "hold"), strength=float(rec.get("strength", 0.7)))
              logger.debug("Signal %s (deepseek): %s strength=%.2f", cfg.ticker, signal.side, signal.strength)
            else:
              signal = Signal(figi=figi, side="hold", strength=0.0)
            strategy_used = "deepseek"
          else:
            effective_cfg = InstrumentConfig(
              figi=cfg.figi, ticker=cfg.ticker, strategy=effective_strategy,
              target_weight=cfg.target_weight, strategy_params=effective_params,
              lot=getattr(cfg, "lot", 1) or 1,
            )
            strat = build_strategy(effective_strategy, effective_cfg, self.broker)
            signal = strat.compute_signal(now)
            strategy_used = str(effective_strategy) if isinstance(effective_strategy, str) else "combined"
            logger.debug("Signal %s: %s strength=%.2f", cfg.ticker, signal.side, signal.strength)
        except (ValueError, Exception) as e:
          logger.debug("Strategy error for %s: %s", cfg.ticker, e)
      min_strength = cfg.strategy_params.get("min_strength", 0.0)
      cooldown_days = cfg.strategy_params.get("cooldown_days", 0)
      if signal is not None and signal.side not in ("hold",):
        if signal.strength < min_strength:
          continue
        if cooldown_days > 0 and figi in last_trades:
          try:
            last_dt = datetime.fromisoformat(last_trades[figi])
            if (now - last_dt).days < cooldown_days:
              continue
          except (ValueError, TypeError):
            pass
      lot = getattr(cfg, "lot", 1) or 1
      pos = positions.get(figi)
      current_value = pos.value if pos else 0.0
      base_target = targets[figi]
      if figi in force_sell and pos and current_value > 0:
        base_target = 0.0
      if hold_timeout_days > 0 and pos and current_value > 0 and figi in last_buy_dates:
        try:
          buy_ts = last_buy_dates[figi][:10]
          buy_dt = datetime.strptime(buy_ts, "%Y-%m-%d")
          if (now - buy_dt).days >= hold_timeout_days:
            base_target = 0.0
        except Exception:
          pass
      # Per-trade stop-loss / take-profit: при достижении уровней полностью закрываем позицию.
      if pos and current_value > 0:
        try:
          cur_price = pos.current_price
          if cur_price and cur_price > 0 and getattr(self.risk, "stop_loss_price", None):
            sl = self.risk.stop_loss_price(pos.average_price)
            tp = self.risk.take_profit_price(pos.average_price)
            if cur_price <= sl or cur_price >= tp:
              base_target = 0.0
        except Exception:
          pass
      if max_position_pct > 0:
        cap_value = equity * max_position_pct
        if base_target > cap_value:
          base_target = cap_value
      strength_mult = 1.0
      if signal is not None and signal.side != "hold":
        if signal.side == "buy":
          strength_mult = 1.0 + signal_strength_mult * signal.strength
        else:
          strength_mult = 1.0 - signal_strength_mult * signal.strength
      vol_factor = _volatility_factor(self.broker, figi, atr_period, atr_percentile_days)
      vol_filter = _volume_factor(self.broker, figi, volume_min_ratio)
      target_value = base_target * strength_mult * vol_factor * vol_filter
      if getattr(self.cfg, "rebalance_decisions_log", True):
        rebalance_log_entries.append({
          "ticker": cfg.ticker,
          "strategy": strategy_used,
          "signal": signal.side if signal else "hold",
          "target_rub": round(target_value, 0),
          "current_rub": round(current_value, 0),
        })
      diff = target_value - current_value
      if abs(diff) / max(equity, 1e-9) < 0.01:
        continue
      if signal is not None:
        if diff > 0 and signal.side == "sell":
          continue
        if diff < 0 and signal.side == "buy":
          continue
        if diff < 0 and signal.side != "sell" and max_overweight_pct > 0:
          overweight_pct = (current_value - base_target) / max(equity, 1e-9)
          if overweight_pct <= max_overweight_pct:
            continue
      price = pos.current_price if pos else self.broker.get_last_price(figi)
      if price <= 0:
        continue
      direction = OrderDirection.ORDER_DIRECTION_BUY if diff > 0 else OrderDirection.ORDER_DIRECTION_SELL
      # В последние минуты окна не выставлять новые лимитные покупки (только продажи)
      if no_new_orders and direction == OrderDirection.ORDER_DIRECTION_BUY:
        continue
      # Защита от гэпов: близко к закрытию не открываем новые позиции по гэповых бумагах
      if near_close and direction == OrderDirection.ORDER_DIRECTION_BUY and _is_gap_risky(figi) and not positions.get(figi):
        continue
      qty = self._round_quantity(diff, price, lot)
      if qty == 0:
        continue
      strength = signal.strength if signal and signal.side != "hold" else 1.0
      if strength < signal_strength_min:
        strength = signal_strength_min
      qty = max(lot, int(math.floor(qty * strength * size_scale / lot)) * lot)
      if direction == OrderDirection.ORDER_DIRECTION_BUY:
        max_cost = remaining_cash * SAFETY
        if single_trade_max_pct > 0:
          max_cost = min(max_cost, equity * single_trade_max_pct)
        max_qty = int(math.floor(max_cost / price / lot)) * lot
        if max_qty < lot:
          continue
        qty = min(qty, max_qty)
      max_lots_per_order = (cfg.strategy_params or {}).get("max_lots_per_order", 0) or 0
      if max_lots_per_order > 0:
        qty = min(qty, max_lots_per_order * lot)
      if qty < lot:
        continue
      cost = qty * price
      if signal_confirmation_candles > 0 and not _signal_confirmed(self.broker, figi, direction, signal_confirmation_candles):
        continue
      order = RebalanceOrder(
        figi=figi, ticker=cfg.ticker, quantity=qty, direction=direction,
        execution_price=price, signal_strength=strength, strategy_used=strategy_used,
      )
      if direction == OrderDirection.ORDER_DIRECTION_BUY:
        pending_buys.append(order)
        remaining_cash -= cost
      else:
        sells.append(order)

    # Сначала продажи, потом покупки (от дешёвых к дорогим)
    pending_buys.sort(key=lambda o: o.quantity * o.execution_price)
    all_orders = sells + pending_buys
    if getattr(self.cfg, "rebalance_decisions_log", True) and rebalance_log_entries:
      _log_rebalance_decisions(equity, rebalance_log_entries, all_orders)
    return all_orders

  def execute_rebalance(self, day_start_equity: float) -> List[dict]:
    orders = self.build_rebalance_orders(day_start_equity)
    trades: List[dict] = []
    dry_run = getattr(self.cfg, "dry_run", False)
    base_currency = getattr(self.cfg, "base_currency", "RUB") or "RUB"
    limit_pct_default = getattr(self.cfg, "limit_price_pct", 0.001) or 0.001
    limit_pct_buy = getattr(self.cfg, "limit_price_pct_buy", 0) or 0
    limit_pct_sell = getattr(self.cfg, "limit_price_pct_sell", 0) or 0
    if limit_pct_buy <= 0:
      limit_pct_buy = limit_pct_default
    if limit_pct_sell <= 0:
      limit_pct_sell = limit_pct_default

    # Отмена старых лимитных заявок по тем же FIGI, чтобы не копились зависшие ордера.
    # Управляется флагом cancel_open_orders_before_rebalance.
    if getattr(self.cfg, "cancel_open_orders_before_rebalance", True):
      figis_in_orders = {o.figi for o in orders}
      if figis_in_orders:
        try:
          open_orders = self.broker.get_open_orders()
          to_cancel: list[str] = []
          for x in open_orders:
            if x.get("figi") not in figis_in_orders:
              continue
            otype = str(x.get("order_type", "") or "")
            # Отменяем только лимитные заявки, чтобы не трогать другие типы ордеров.
            if "LIMIT" not in otype.upper():
              continue
            oid = x.get("order_id")
            if oid:
              to_cancel.append(oid)
              _audit_order("cancel", x.get("figi", ""), "", "?", 0, 0.0, oid)
          if to_cancel:
            self.broker.cancel_orders(to_cancel)
        except Exception as e:
          logger.debug("Отмена старых заявок: %s", e)

    for o in orders:
      qty = o.quantity
      if o.direction == OrderDirection.ORDER_DIRECTION_BUY:
        cash = self.broker.get_cash_balance(currency=base_currency)
        lot = getattr(self.instruments_cfg.get(o.figi), "lot", 1) or 1
        price = o.execution_price
        max_qty = int(math.floor(cash * 0.95 / price / lot)) * lot
        if max_qty < lot:
          continue
        qty = min(qty, max_qty)
      # Обновляем цену перед выставлением: лимит считаем от текущей цены.
      # При включённом флаге use_order_book_for_limits используем стакан (bid/ask/mid).
      use_ob = getattr(self.cfg, "use_order_book_for_limits", False)
      expected_price = o.execution_price
      if use_ob:
        bid, ask, mid = self.broker.get_order_book_mid(o.figi)
        if o.direction == OrderDirection.ORDER_DIRECTION_BUY:
          ref = ask or mid
        else:
          ref = bid or mid
        if ref and ref > 0:
          expected_price = ref
        else:
          fresh_price = self.broker.get_last_price(o.figi)
          if fresh_price and fresh_price > 0:
            expected_price = fresh_price
      else:
        fresh_price = self.broker.get_last_price(o.figi)
        if fresh_price and fresh_price > 0:
          expected_price = fresh_price
      is_buy = o.direction == OrderDirection.ORDER_DIRECTION_BUY
      limit_pct = limit_pct_buy if is_buy else limit_pct_sell
      limit_price = expected_price * (1 - limit_pct) if is_buy else expected_price * (1 + limit_pct)
      if dry_run:
        logger.info("DRY-RUN: %s %s qty=%d @ %.2f (limit %.2f)", o.ticker, "BUY" if is_buy else "SELL", qty, expected_price, limit_price)
        trades.append({
          "order_id": "dry_run",
          "figi": o.figi,
          "ticker": o.ticker,
          "direction": "ПОКУПКА" if is_buy else "ПРОДАЖА",
          "quantity": qty,
          "price": limit_price,
          "expected_price": expected_price,
          "amount": qty * limit_price,
          "commission": 0,
          "strategy": o.strategy_used or "",
        })
        _save_last_trade(o.figi)
        continue
      order_id = None
      for attempt in range(3):
        try:
          order_id = self.broker.place_order(
            figi=o.figi,
            quantity=qty,
            direction=o.direction,
            order_type=OrderType.ORDER_TYPE_LIMIT,
            price=limit_price,
          )
          break
        except Exception as e:
          err_str = str(e).lower()
          if "not available for trading" in err_str or "instrument is not available" in err_str:
            logger.warning("Пропуск заявки %s: бумага недоступна для торговли (%s)", o.ticker, e)
            order_id = None
            break
          if any(
            x in err_str
            for x in (
              "insufficient",
              "недостаточно",
              "30035",
              "30034",
              "funds",
              "money",
              "средств",
              "not enough",
              "balance",
            )
          ):
            logger.warning("Пропуск заявки %s: недостаточно средств (%s)", o.ticker, e)
            order_id = None
            break
          logger.warning("place_order %s попытка %d/3: %s", o.ticker, attempt + 1, e)
          if attempt == 2:
            raise
          import time
          time.sleep(2 * (attempt + 1))
      if order_id is None:
        continue
      direction_str = "BUY" if is_buy else "SELL"
      _audit_order("place", o.figi, o.ticker, direction_str, qty, limit_price, order_id)
      _save_last_trade(o.figi)
      amount = qty * expected_price
      commission = amount * self.cfg.commission_rate
      try:
        from .metrics import observe_slippage_pct
        slippage_abs = float(limit_price - expected_price)
        slippage_pct = float(slippage_abs / expected_price) if expected_price else 0.0
        observe_slippage_pct("buy" if is_buy else "sell", slippage_pct)
        slog = logging.getLogger("slippage")
        slog.info(
          "slippage %s %s qty=%d expected=%.4f limit=%.4f abs=%.4f pct=%.4f",
          o.ticker, direction_str, qty, expected_price, limit_price, slippage_abs, slippage_pct,
        )
      except Exception as ex:
        logger.debug("slippage log: %s", ex)
      direction_str_ru = "ПОКУПКА" if is_buy else "ПРОДАЖА"
      trades.append({
        "order_id": order_id,
        "figi": o.figi,
        "ticker": o.ticker,
        "direction": direction_str_ru,
        "quantity": qty,
        "price": limit_price,
        "expected_price": expected_price,
        "amount": amount,
        "commission": commission,
        "strategy": o.strategy_used or "",
      })
    for t in trades:
      try:
        from .trade_history import record_trade
        side = "buy" if "ПОКУПКА" in t.get("direction", "") else "sell"
        record_trade(
          t["figi"], t["ticker"], side,
          float(t["quantity"]), float(t["price"]),
          t.get("strategy", ""),
          expected_price=t.get("expected_price"),
        )
      except Exception as e:
        logger.warning("trade_history.record_trade: %s", e)
    return trades


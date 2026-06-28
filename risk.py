import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Sequence

import numpy as np

from .config import RiskConfig

logger = logging.getLogger(__name__)
RISK_STATE_FILE = Path(__file__).resolve().parent / "data" / "risk_state.json"


@dataclass
class RiskState:
  equity: float
  max_equity_seen: float
  daily_pnl: float


def _load_risk_state() -> dict:
  if not RISK_STATE_FILE.exists():
    return {}
  try:
    import json
    return json.loads(RISK_STATE_FILE.read_text(encoding="utf-8"))
  except Exception as e:
    logger.debug("risk_state load: %s", e)
    return {}


def _save_risk_state(
  pause_until: datetime | None,
  max_equity_seen: float,
  daily_equity_start: float | None,
  daily_equity_date: str | None,
) -> None:
  RISK_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
  import json
  data = {
    "pause_until": pause_until.isoformat() if pause_until else None,
    "max_equity_seen": max_equity_seen,
    "daily_equity_start": daily_equity_start,
    "daily_equity_date": daily_equity_date,
  }
  RISK_STATE_FILE.write_text(json.dumps(data), encoding="utf-8")


class RiskManager:
  def __init__(self, cfg: RiskConfig):
    self.cfg = cfg
    data = _load_risk_state()
    self._max_equity_seen = float(data.get("max_equity_seen") or 0.0)
    today = datetime.now().strftime("%Y-%m-%d")
    self._daily_equity_date = data.get("daily_equity_date")
    des = data.get("daily_equity_start")
    # Дневной базис восстанавливаем только если он от сегодняшней даты, иначе сбросим при первом update_equity.
    if des is not None and self._daily_equity_date == today:
      self._daily_equity_start = float(des)
    else:
      self._daily_equity_start = None
      self._daily_equity_date = None
    self._pause_until = None
    pause_s = data.get("pause_until")
    if pause_s:
      try:
        self._pause_until = datetime.fromisoformat(pause_s)
      except Exception:
        self._pause_until = None

  def _persist(self) -> None:
    _save_risk_state(self._pause_until, self._max_equity_seen, self._daily_equity_start, self._daily_equity_date)

  def update_equity(self, equity: float, day_start_equity: float) -> RiskState:
    if self._max_equity_seen == 0.0:
      self._max_equity_seen = equity
    self._max_equity_seen = max(self._max_equity_seen, equity)
    if self._daily_equity_start is None:
      self._daily_equity_start = day_start_equity
      self._daily_equity_date = datetime.now().strftime("%Y-%m-%d")
    daily_pnl = equity - self._daily_equity_start
    self._persist()
    return RiskState(equity=equity, max_equity_seen=self._max_equity_seen, daily_pnl=daily_pnl)

  def reset_daily(self, new_day_start: float) -> None:
    """Сброс дневного старта (например в полночь)."""
    self._daily_equity_start = new_day_start
    self._daily_equity_date = datetime.now().strftime("%Y-%m-%d")
    self._persist()

  def reset_equity_baseline(self, equity: float) -> None:
    """Полный сброс базового equity (для sandbox reset / смены счёта).

    Обнуляет историю просадки и дневной старт так, будто торговля началась с заданного equity.
    """
    self._max_equity_seen = equity
    self._daily_equity_start = equity
    self._daily_equity_date = datetime.now().strftime("%Y-%m-%d")
    self._persist()

  def set_pause_until(self, hours: float) -> None:
    """Вручную установить паузу на N часов (например из Telegram /pause)."""
    self._pause_until = datetime.now() + timedelta(hours=hours)
    self._persist()

  def update_consecutive_losses(self, count: int) -> bool:
    """Вызвать с числом подряд убыточных сделок; при count >= N включает паузу на pause_hours. Возвращает True если пауза только что включена."""
    pause_after = getattr(self.cfg, "pause_after_consecutive_losses", 0) or 0
    if pause_after <= 0 or count < pause_after:
      if self._pause_until and datetime.now() > self._pause_until:
        self._pause_until = None
        self._persist()
      return False
    pause_hours = getattr(self.cfg, "pause_hours", 24) or 24
    self._pause_until = datetime.now() + timedelta(hours=pause_hours)
    self._persist()
    return True

  def get_pause_until(self) -> datetime | None:
    """Время до которого действует пауза (или None)."""
    if self._pause_until and datetime.now() < self._pause_until:
      return self._pause_until
    return None

  def get_block_reason(self, state: RiskState) -> str | None:
    """Причина блокировки торговли или None, если разрешено."""
    if self._pause_until and datetime.now() < self._pause_until:
      return f"пауза до {self._pause_until.strftime('%H:%M %d.%m')}"
    if self._max_equity_seen > 0:
      drawdown = (self._max_equity_seen - state.equity) / max(self._max_equity_seen, 1e-9)
      if drawdown > self.cfg.max_drawdown:
        return f"просадка {drawdown:.1%} > лимит {self.cfg.max_drawdown:.0%}"
    if self._daily_equity_start is not None and self._daily_equity_start > 0:
      daily_loss = (self._daily_equity_start - state.equity) / max(self._daily_equity_start, 1e-9)
      if daily_loss > self.cfg.daily_loss_limit:
        return f"дневной убыток {daily_loss:.1%} > лимит {self.cfg.daily_loss_limit:.0%}"
    return None

  def get_size_scale(self, state: RiskState) -> float:
    """Мягкое снижение размера заявок при дневном убытке выше soft-лимита.

    daily_loss <= soft_limit  -> 1.0 (без изменений)
    soft_limit < daily_loss < daily_loss_limit -> daily_loss_soft_scale (например 0.5)
    daily_loss >= daily_loss_limit -> 0.0 (торговля всё равно будет заблокирована is_trading_allowed)
    """
    soft_limit = getattr(self.cfg, "daily_loss_soft_limit", 0.0) or 0.0
    scale = getattr(self.cfg, "daily_loss_soft_scale", 0.5) or 0.5
    if soft_limit <= 0 or self._daily_equity_start is None or self._daily_equity_start <= 0:
      return 1.0
    daily_loss = (self._daily_equity_start - state.equity) / max(self._daily_equity_start, 1e-9)
    if daily_loss <= soft_limit:
      return 1.0
    if daily_loss >= self.cfg.daily_loss_limit:
      return 0.0
    return max(0.0, min(scale, 1.0))

  def is_trading_allowed(self, state: RiskState) -> bool:
    if self._pause_until and datetime.now() < self._pause_until:
      return False
    if self._pause_until and datetime.now() >= self._pause_until:
      self._pause_until = None
      self._persist()
    if self._max_equity_seen <= 0:
      return True
    drawdown = (self._max_equity_seen - state.equity) / max(self._max_equity_seen, 1e-9)
    if drawdown > self.cfg.max_drawdown:
      return False
    if self._daily_equity_start is not None and self._daily_equity_start > 0:
      daily_loss = (self._daily_equity_start - state.equity) / max(self._daily_equity_start, 1e-9)
      if daily_loss > self.cfg.daily_loss_limit:
        return False
    return True

  def stop_loss_price(self, entry_price: float) -> float:
    return entry_price * (1.0 - self.cfg.default_stop_loss_pct)

  def trailing_stop_price(self, peak_price: float) -> float:
    return peak_price * (1.0 - self.cfg.trailing_stop_pct)

  def take_profit_price(self, entry_price: float) -> float:
    """Цена тейк-профита (фиксация части прибыли)."""
    pct = getattr(self.cfg, "take_profit_pct", 0.03) or 0.03
    return entry_price * (1.0 + pct)

  def should_take_profit(self, entry_price: float, current_price: float) -> bool:
    """Текущая цена достигла уровня тейк-профита."""
    if entry_price <= 0:
      return False
    tp = self.take_profit_price(entry_price)
    return current_price >= tp

  def should_trailing_take_profit(self, peak_price: float, current_price: float) -> bool:
    """Цена откатила от пика на trailing_take_profit_pct — фиксировать прибыль."""
    if peak_price <= 0:
      return False
    pct = getattr(self.cfg, "trailing_take_profit_pct", 0.02) or 0.02
    return current_price <= peak_price * (1.0 - pct)

  def compute_var(self, returns: Sequence[float]) -> float:
    if not returns:
      return 0.0
    sorted_r = np.sort(np.array(returns))
    idx = int((1 - self.cfg.var_confidence) * len(sorted_r))
    return float(abs(sorted_r[idx]))

  def kelly_position_fraction(self, win_rate: float, reward_risk: float) -> float:
    b = reward_risk
    p = win_rate
    q = 1 - p
    frac = (b * p - q) / b if b > 0 else 0.0
    frac = max(0.0, min(frac, 1.0))
    return min(frac, self.cfg.kelly_fraction_cap)

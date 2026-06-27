"""Единый клиент истории цен: Finam → MOEX ISS."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from .moex_client import MoexClient

logger = logging.getLogger(__name__)


class CompositeMarketClient:
  """Пробует Finam, при отсутствии данных — MOEX ISS."""

  def __init__(self, finam_client: Any = None, moex_client: Optional[MoexClient] = None):
    self.finam = finam_client
    self.moex = moex_client or MoexClient()

  @property
  def configured(self) -> bool:
    finam_ok = bool(self.finam and getattr(self.finam, "configured", False))
    moex_ok = bool(self.moex and getattr(self.moex, "configured", True))
    return finam_ok or moex_ok

  def get_daily_bars(self, ticker: str, days: int = 90) -> List[Dict[str, float]]:
    ticker = ticker.upper().strip()
    if self.finam and getattr(self.finam, "configured", False):
      try:
        bars = self.finam.get_daily_bars(ticker, days=days)
        if len(bars) >= 5:
          return bars
      except Exception as e:
        logger.debug("Finam bars %s: %s", ticker, e)
    if self.moex:
      try:
        return self.moex.get_daily_bars(ticker, days=days)
      except Exception as e:
        logger.debug("MOEX bars %s: %s", ticker, e)
    return []

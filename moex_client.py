"""Клиент MOEX ISS — бесплатные исторические свечи (iss.moex.com)."""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, timedelta
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


class MoexClient:
  """Дневные свечи акций с основного режима TQBR через ISS API."""

  def __init__(
    self,
    base_url: str = "https://iss.moex.com/iss",
    board: str = "TQBR",
    timeout: float = 20.0,
  ):
    self.base_url = base_url.rstrip("/")
    self.board = board
    self.timeout = timeout

  @property
  def configured(self) -> bool:
    return True

  def get_daily_bars(self, ticker: str, days: int = 90) -> List[Dict[str, float]]:
    ticker = ticker.upper().strip()
    if not ticker:
      return []
    from_date = (date.today() - timedelta(days=max(days, 5) + 15)).isoformat()
    path = (
      f"/engines/stock/markets/shares/boards/{self.board}/securities/"
      f"{urllib.parse.quote(ticker)}/candles.json"
    )
    params = urllib.parse.urlencode({"from": from_date, "interval": 24})
    url = f"{self.base_url}{path}?{params}"
    try:
      req = urllib.request.Request(url, headers={"User-Agent": "tinkoff_bot/1.0"})
      with urllib.request.urlopen(req, timeout=self.timeout) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
      logger.debug("MOEX ISS %s: %s", ticker, e)
      return []

    block = payload.get("candles") or {}
    columns = block.get("columns") or []
    rows = block.get("data") or []
    if not columns or not rows:
      return []

    idx = {name: i for i, name in enumerate(columns)}
    need = ("open", "high", "low", "close", "volume")
    if not all(k in idx for k in need):
      return []

    bars: List[Dict[str, float]] = []
    for row in rows:
      try:
        close = float(row[idx["close"]])
        if close <= 0:
          continue
        bars.append(
          {
            "open": float(row[idx["open"]]),
            "high": float(row[idx["high"]]),
            "low": float(row[idx["low"]]),
            "close": close,
            "volume": float(row[idx["volume"]] or 0),
          }
        )
      except (TypeError, ValueError, IndexError):
        continue

    if days > 0 and len(bars) > days:
      bars = bars[-days:]
    return bars

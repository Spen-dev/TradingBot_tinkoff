"""Кэш свечей на диск: подгрузка только новых данных."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

from .broker import TinkoffBroker
from tinkoff.invest import CandleInterval

logger = logging.getLogger(__name__)

CACHE_DIR = Path(__file__).resolve().parent / "data" / "candles"


def _cache_path(figi: str) -> Path:
  CACHE_DIR.mkdir(parents=True, exist_ok=True)
  safe = figi.replace("/", "_")
  return CACHE_DIR / f"{safe}.csv"


def get_candles_cached(
  broker: TinkoffBroker,
  figi: str,
  from_dt: datetime,
  to_dt: datetime,
  interval: CandleInterval = CandleInterval.CANDLE_INTERVAL_DAY,
  max_cache_days: int = 60,
) -> pd.DataFrame:
  """Получить свечи: из кэша + догрузка только новых с API."""
  path = _cache_path(figi)
  if path.exists():
    try:
      df = pd.read_csv(path, index_col=0, parse_dates=True)
      if not df.empty and hasattr(df.index, "max") and df.index.max() >= pd.Timestamp(to_dt):
        mask = (df.index >= from_dt) & (df.index <= to_dt)
        return df.loc[mask].copy()
      last_ts = df.index.max() if hasattr(df.index, "max") else None
    except Exception as e:
      logger.debug("Cache read %s: %s", figi, e)
      last_ts = None
  else:
    last_ts = None
  df = broker.get_historical_candles(figi, from_dt, to_dt, interval)
  if df is None or df.empty:
    return pd.DataFrame()
  if last_ts is not None and len(df) and df.index.max() > last_ts:
    try:
      new_part = df[df.index > last_ts]
      old = pd.read_csv(path, index_col=0, parse_dates=True)
      combined = pd.concat([old, new_part]).drop_duplicates().sort_index()
      cutoff = datetime.now() - timedelta(days=max_cache_days)
      if hasattr(combined.index, "tzinfo") and combined.index.tzinfo:
        cutoff = cutoff.replace(tzinfo=combined.index.tzinfo)
      combined = combined[combined.index >= cutoff]
      combined.to_csv(path)
    except Exception as e:
      logger.debug("Cache merge %s: %s", figi, e)
  else:
    try:
      df.to_csv(path)
    except Exception as e:
      logger.debug("Cache write %s: %s", figi, e)
  return df


class CachingBroker:
  """Обёртка над брокером: get_historical_candles через кэш при use_cache=True."""
  def __init__(self, broker: TinkoffBroker, use_cache: bool = False, max_cache_days: int = 60):
    self._broker = broker
    self._use_cache = use_cache
    self._max_cache_days = max_cache_days

  def get_historical_candles(self, figi: str, from_dt: datetime, to_dt: datetime, interval=CandleInterval.CANDLE_INTERVAL_DAY):
    if self._use_cache and interval == CandleInterval.CANDLE_INTERVAL_DAY:
      return get_candles_cached(self._broker, figi, from_dt, to_dt, interval, self._max_cache_days)
    return self._broker.get_historical_candles(figi, from_dt, to_dt, interval)

  def __getattr__(self, name: str):
    return getattr(self._broker, name)

"""Режим рынка (тренд / weak_trend / флэт) по ADX для переключения стратегий и параметров."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd

if TYPE_CHECKING:
  from .broker import TinkoffBroker


def adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
  """ADX (Average Directional Index). Возвращает Series с индексом как у df."""
  if df is None or len(df) < period + 5:
    return pd.Series(dtype=float)
  high = df["high"] if "high" in df.columns else df["close"]
  low = df["low"] if "low" in df.columns else df["close"]
  close = df["close"]
  plus_dm = high.diff()
  minus_dm = -low.diff()
  plus_dm = plus_dm.where((plus_dm > minus_dm) & (plus_dm > 0), 0.0)
  minus_dm = minus_dm.where((minus_dm > plus_dm) & (minus_dm > 0), 0.0)
  tr = np.maximum(high - low, np.maximum(abs(high - close.shift(1)), abs(low - close.shift(1))))
  atr = tr.rolling(period).mean()
  plus_di = 100 * (plus_dm.rolling(period).mean() / atr.replace(0, np.nan))
  minus_di = 100 * (minus_dm.rolling(period).mean() / atr.replace(0, np.nan))
  dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di.replace(0, np.nan))
  adx_ser = dx.rolling(period).mean()
  return adx_ser


def get_regime(
  broker: "TinkoffBroker",
  figi: str,
  days: int = 30,
  adx_period: int = 14,
  adx_threshold: float = 25.0,
  adx_threshold_low: float | None = None,
) -> str:
  """Режим рынка по ADX: 'trend' если ADX > adx_threshold, 'range' если ADX < adx_threshold_low (или < adx_threshold если не задан), иначе 'weak_trend'."""
  to_dt = datetime.now()
  from_dt = to_dt - timedelta(days=days + adx_period + 5)
  try:
    df = broker.get_historical_candles(figi, from_dt, to_dt)
  except Exception:
    return "range"
  if df is None or len(df) < adx_period + 5:
    return "range"
  adx_ser = adx(df, adx_period)
  if adx_ser.empty or pd.isna(adx_ser.iloc[-1]):
    return "range"
  val = adx_ser.iloc[-1]
  low = adx_threshold_low if adx_threshold_low is not None else adx_threshold * 0.8
  if val > adx_threshold:
    return "trend"
  if val < low:
    return "range"
  return "weak_trend"


def get_regime_by_index(
  broker: "TinkoffBroker",
  index_figi: str,
  days: int = 30,
  adx_period: int = 14,
  adx_threshold: float = 25.0,
  adx_threshold_low: float | None = None,
) -> str:
  """Режим рынка по индексу (например IMOEX). Использовать для всех инструментов как единый режим."""
  return get_regime(
    broker, index_figi, days=days, adx_period=adx_period,
    adx_threshold=adx_threshold, adx_threshold_low=adx_threshold_low,
  )

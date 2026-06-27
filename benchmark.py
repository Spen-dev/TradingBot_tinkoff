"""Бенчмарк equal-weight buy&hold для сравнения с ботом."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, List, Optional, Tuple

logger = logging.getLogger(__name__)


def equal_weight_buy_hold_return(
  broker: Any,
  instruments: List[Any],
  days: int = 30,
  commission_rate: float = 0.0003,
) -> Optional[Tuple[float, str]]:
  """
  Доходность равновесного портфеля (buy&hold) за days календарных дней.
  Возвращает (return_pct как доля, e.g. 0.05 = 5%, описание) или None.
  """
  if not instruments:
    return None
  to_dt = datetime.now()
  from_dt = to_dt - timedelta(days=max(days, 10) + 5)
  rets: List[float] = []
  tickers: List[str] = []
  for ins in instruments:
    figi = getattr(ins, "figi", "")
    ticker = getattr(ins, "ticker", figi)
    if not figi:
      continue
    try:
      df = broker.get_historical_candles(figi, from_dt, to_dt)
      if df is None or len(df) < 5 or "close" not in df.columns:
        continue
      close = df["close"]
      p0 = float(close.iloc[0])
      p1 = float(close.iloc[-1])
      if p0 <= 0:
        continue
      gross = p1 / p0 - 1.0
      rets.append(gross - 2 * commission_rate)
      tickers.append(ticker)
    except Exception as e:
      logger.debug("benchmark %s: %s", ticker, e)
  if not rets:
    return None
  avg = sum(rets) / len(rets)
  desc = f"equal-weight ({', '.join(tickers[:6])}{'…' if len(tickers) > 6 else ''}, n={len(rets)})"
  return avg, desc


def load_observation_baseline(base_dir: Any) -> Optional[dict]:
  path = Path(base_dir) / "data" / "observation_baseline.json"
  if not path.exists():
    return None
  try:
    import json

    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else None
  except Exception:
    return None


def format_weekly_benchmark_block(
  broker: Any,
  instruments: List[Any],
  equity: float,
  base_dir: Any,
  commission_rate: float = 0.0003,
) -> str:
  """Текст для недельного отчёта: бот vs equal-weight B&H."""
  lines: List[str] = []
  baseline = load_observation_baseline(base_dir)
  if baseline and float(baseline.get("equity") or 0) > 0:
    beq = float(baseline["equity"])
    bot_ret = (equity - beq) / beq
    started = (baseline.get("started_at") or "")[:10]
    lines.append(f"🤖 Бот с baseline ({started}): {bot_ret * 100:+.2f}%")
  for days in (7, 30):
    row = equal_weight_buy_hold_return(broker, instruments, days=days, commission_rate=commission_rate)
    if row:
      ret, desc = row
      lines.append(f"📊 B&H equal-weight {days}д: {ret * 100:+.2f}% ({desc})")
  return "\n".join(lines) if lines else "нет данных для сравнения с бенчмарком"

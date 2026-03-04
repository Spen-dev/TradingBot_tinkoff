"""История сделок для оценки качества сигналов и серии убытков."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

TRADE_HISTORY_FILE = Path(__file__).resolve().parent / "data" / "trade_history.json"


@dataclass
class TradeRecord:
  id: str
  figi: str
  ticker: str
  side: str  # buy / sell
  quantity: float
  price: float
  ts: str  # ISO
  strategy: str


def _ensure_dir() -> None:
  TRADE_HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)


def _load_all() -> List[dict]:
  if not TRADE_HISTORY_FILE.exists():
    return []
  try:
    with open(TRADE_HISTORY_FILE, "r", encoding="utf-8") as f:
      data = json.load(f)
    return data if isinstance(data, list) else []
  except Exception as e:
    logger.warning("Не удалось загрузить trade_history: %s", e)
    return []


def _save_all(records: List[dict]) -> None:
  _ensure_dir()
  with open(TRADE_HISTORY_FILE, "w", encoding="utf-8") as f:
    json.dump(records, f, ensure_ascii=False, indent=2)


def record_trade(
  figi: str,
  ticker: str,
  side: str,
  quantity: float,
  price: float,
  strategy: str = "",
  expected_price: float | None = None,
) -> None:
  """Записать сделку (вызывать после исполнения)."""
  records = _load_all()
  tid = f"{figi}_{datetime.now().isoformat()}"
  rec = {
    "id": tid,
    "figi": figi,
    "ticker": ticker,
    "side": side.lower(),
    "quantity": quantity,
    "price": price,
    "ts": datetime.now().isoformat(),
    "strategy": strategy or "unknown",
  }
  if expected_price is not None:
    rec["expected_price"] = expected_price
  records.append(rec)
  _save_all(records[-500:])  # храним последние 500


def get_trades(limit: int = 200) -> List[TradeRecord]:
  """Последние записи сделок."""
  records = _load_all()
  out = []
  for r in records[-limit:]:
    try:
      tr = TradeRecord(
        id=r.get("id", ""),
        figi=r["figi"],
        ticker=r["ticker"],
        side=r.get("side", "buy"),
        quantity=float(r.get("quantity", 0)),
        price=float(r.get("price", 0)),
        ts=r.get("ts", ""),
        strategy=r.get("strategy", "unknown"),
      )
      out.append(tr)
    except (KeyError, TypeError):
      continue
  return out


def evaluate_realized_pnl(
  trades: List[TradeRecord],
  get_price: Callable[[str], float],
  horizon_days: int = 5,
) -> List[tuple]:
  """По сделкам старше horizon_days вычислить реализованный PnL (цена входа vs текущая цена).
  get_price(figi) -> float. Возвращает список (trade, pnl_rub)."""
  from datetime import datetime as dt
  now = dt.now()
  cutoff = (now - timedelta(days=horizon_days)).isoformat()
  result = []
  for t in trades:
    if t.ts < cutoff:
      try:
        current_price = get_price(t.figi)
        if t.side == "buy":
          pnl = (current_price - t.price) * t.quantity
        else:
          pnl = (t.price - current_price) * t.quantity
        result.append((t, pnl))
      except Exception:
        pass
  return result


def get_consecutive_losses(
  get_price: Callable[[str], float],
  horizon_days: int = 5,
  max_trades: int = 50,
  min_pnl_rub: float = 0.0,
) -> int:
  """Число подряд идущих убыточных сделок (от новых к старым). Убытки меньше min_pnl_rub по модулю не учитываются."""
  trades = get_trades(limit=max_trades)
  if not trades:
    return 0
  evaluated = evaluate_realized_pnl(trades, get_price, horizon_days)
  if not evaluated:
    return 0
  evaluated.sort(key=lambda x: x[0].ts, reverse=True)
  count = 0
  for _, pnl in evaluated:
    if pnl < 0 and (min_pnl_rub <= 0 or abs(pnl) >= min_pnl_rub):
      count += 1
    else:
      break
  return count


def get_strategy_stats(
  get_price: Callable[[str], float],
  horizon_days: int = 5,
) -> Dict[str, Dict[str, Any]]:
  """По стратегиям: количество сделок, прибыльных, суммарный и средний PnL."""
  trades = get_trades(limit=300)
  evaluated = evaluate_realized_pnl(trades, get_price, horizon_days)
  stats: Dict[str, Dict[str, Any]] = {}
  for t, pnl in evaluated:
    s = t.strategy or "unknown"
    if s not in stats:
      stats[s] = {"trades": 0, "wins": 0, "pnl": 0.0}
    stats[s]["trades"] += 1
    stats[s]["pnl"] += pnl
    if pnl > 0:
      stats[s]["wins"] += 1
  for s in stats:
    n = stats[s]["trades"]
    stats[s]["avg_pnl"] = stats[s]["pnl"] / n if n else 0.0
    stats[s]["win_rate"] = (stats[s]["wins"] / n) if n else 0.0
  return stats


def get_per_instrument_stats(
  get_price: Callable[[str], float],
  horizon_days: int = 30,
  max_trades: int = 200,
) -> Dict[str, Dict[str, Any]]:
  """По инструментам (figi): trades, wins, pnl, win_rate для учёта в весах и самообучении."""
  trades = get_trades(limit=max_trades)
  evaluated = evaluate_realized_pnl(trades, get_price, horizon_days)
  stats: Dict[str, Dict[str, Any]] = {}
  for t, pnl in evaluated:
    figi = t.figi
    if figi not in stats:
      stats[figi] = {"trades": 0, "wins": 0, "pnl": 0.0, "ticker": getattr(t, "ticker", figi)}
    stats[figi]["trades"] += 1
    stats[figi]["pnl"] += pnl
    if pnl > 0:
      stats[figi]["wins"] += 1
  for figi in stats:
    n = stats[figi]["trades"]
    stats[figi]["win_rate"] = (stats[figi]["wins"] / n) if n else 0.0
  return stats


def get_consecutive_losses_per_figi(
  get_price: Callable[[str], float],
  horizon_days: int = 10,
  min_pnl_rub: float = 0.0,
) -> Dict[str, int]:
  """По каждому figi: число подряд убыточных сделок (для блокировки инструмента)."""
  trades = get_trades(limit=200)
  evaluated = evaluate_realized_pnl(trades, get_price, horizon_days)
  if not evaluated:
    return {}
  evaluated.sort(key=lambda x: x[0].ts, reverse=True)
  by_figi: Dict[str, List[tuple]] = {}
  for t, pnl in evaluated:
    by_figi.setdefault(t.figi, []).append((t, pnl))
  out: Dict[str, int] = {}
  for figi, lst in by_figi.items():
    c = 0
    for _, pnl in lst:
      if pnl < 0 and (min_pnl_rub <= 0 or abs(pnl) >= min_pnl_rub):
        c += 1
      else:
        break
    out[figi] = c
  return out


def get_last_buy_date_per_figi(horizon_days: int = 365) -> Dict[str, str]:
  """По каждому figi: дата последней покупки (ISO), для таймаута удержания."""
  trades = get_trades(limit=500)
  cutoff = (datetime.now() - timedelta(days=horizon_days)).isoformat()
  out: Dict[str, str] = {}
  for t in sorted(trades, key=lambda x: x.ts, reverse=True):
    if t.figi in out:
      continue
    if t.side == "buy" and t.ts >= cutoff:
      out[t.figi] = t.ts
  return out

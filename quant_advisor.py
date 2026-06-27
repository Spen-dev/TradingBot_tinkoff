"""Общая количественная логика советников (momentum + Sharpe)."""

from __future__ import annotations

import logging
import math
from typing import Any, Callable, Dict, List, Tuple

logger = logging.getLogger(__name__)


def _compute_sharpe(returns: List[float]) -> float:
  if len(returns) < 3:
    return 0.0
  mean = sum(returns) / len(returns)
  var = sum((r - mean) ** 2 for r in returns) / max(len(returns) - 1, 1)
  std = math.sqrt(var)
  if std <= 1e-12:
    return 0.0
  return mean / std * math.sqrt(252)


def _max_drawdown(closes: List[float]) -> float:
  if not closes:
    return 0.0
  peak = closes[0]
  max_dd = 0.0
  for c in closes:
    peak = max(peak, c)
    if peak > 0:
      max_dd = max(max_dd, (peak - c) / peak)
  return max_dd


def score_bars(bars: List[Dict[str, float]]) -> Dict[str, float]:
  """Метрики тикера по дневным свечам."""
  closes = [b["close"] for b in bars if b.get("close", 0) > 0]
  if len(closes) < 10:
    return {"score": -1e9, "return_20d": 0.0, "sharpe": 0.0, "max_dd": 1.0}
  rets = [(closes[i] / closes[i - 1] - 1) for i in range(1, len(closes))]
  r20 = (closes[-1] / closes[-min(20, len(closes))] - 1) if len(closes) >= 2 else 0.0
  sharpe = _compute_sharpe(rets[-60:])
  max_dd = _max_drawdown(closes[-60:])
  score = r20 * 100 + sharpe * 0.5 - max_dd * 50
  return {"score": score, "return_20d": r20, "sharpe": sharpe, "max_dd": max_dd}


def select_portfolio_quant(
  get_bars: Callable[[str], List[Dict[str, float]]],
  candidates: List[str],
  min_instruments: int,
  max_instruments: int,
  max_weight: float,
  *,
  source_label: str = "quant",
) -> Tuple[List[Dict[str, Any]], str]:
  """Ранжирование кандидатов по свечам, выбор top-N с весами."""
  ranked: List[Dict[str, Any]] = []
  for ticker in candidates:
    try:
      bars = get_bars(ticker.upper())
      m = score_bars(bars)
      if m["score"] <= -1e8:
        continue
      ranked.append(
        {
          "ticker": ticker.upper(),
          "score": m["score"],
          "return_20d": m["return_20d"],
          "sharpe": m["sharpe"],
          "max_dd": m["max_dd"],
        }
      )
    except Exception as e:
      logger.debug("%s advisor %s: %s", source_label, ticker, e)

  if not ranked:
    return [], f"{source_label}: нет данных по кандидатам"

  ranked.sort(key=lambda x: x["score"], reverse=True)
  top = ranked[: max(1, max_instruments)]
  if len(top) < min_instruments:
    logger.warning("%s: только %d инструментов с данными (мин %d)", source_label, len(top), min_instruments)

  max_score = max(r["score"] for r in top)
  exp_w = [math.exp((r["score"] - max_score) * 0.05) for r in top]
  total_exp = sum(exp_w) or 1.0
  cap = max(0.05, min(1.0, max_weight))
  selections = []
  for r, w in zip(top, exp_w):
    tw = min(cap, w / total_exp)
    selections.append(
      {
        "ticker": r["ticker"],
        "target_weight": tw,
        "reason": (
          f"{source_label} score={r['score']:.2f} r20={r['return_20d']:.1%} sharpe={r['sharpe']:.2f}"
        ),
      }
    )
  wsum = sum(s["target_weight"] for s in selections) or 1.0
  for s in selections:
    s["target_weight"] /= wsum

  leaders = ", ".join(f"{r['ticker']}({r['score']:.1f})" for r in top[:3])
  summary = f"{source_label}: momentum+Sharpe, лидеры: {leaders}"
  return selections, summary


def get_recommendations_quant(
  get_bars: Callable[[str], List[Dict[str, float]]],
  instruments: List[Any],
  *,
  source: str = "quant",
) -> Dict[str, Dict[str, Any]]:
  """Сигналы buy/sell/hold по momentum на свечах."""
  out: Dict[str, Dict[str, Any]] = {}
  for ins in instruments:
    ticker = getattr(ins, "ticker", "")
    figi = getattr(ins, "figi", "")
    if not ticker or not figi:
      continue
    try:
      bars = get_bars(ticker.upper())
      m = score_bars(bars)
      r20 = m["return_20d"]
      sharpe = m["sharpe"]
      if r20 > 0.02 and sharpe > 0:
        action = "buy"
        strength = min(1.0, max(0.4, 0.5 + r20 * 5 + sharpe * 0.1))
      elif r20 < -0.02:
        action = "sell"
        strength = min(1.0, max(0.4, 0.5 + abs(r20) * 5))
      else:
        action = "hold"
        strength = 0.5
      tw = float(getattr(ins, "target_weight", 0))
      out[figi] = {"action": action, "target_weight": tw, "strength": strength, "source": source}
    except Exception as e:
      logger.debug("%s rec %s: %s", source, ticker, e)
  return out

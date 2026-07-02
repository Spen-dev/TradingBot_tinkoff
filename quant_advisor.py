"""Общая количественная логика советников (momentum + Sharpe)."""

from __future__ import annotations

import logging
import math
from typing import Any, Callable, Dict, List, Optional, Tuple

from .sector_map import enforce_sector_caps

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


def _returns_from_bars(bars: List[Dict[str, float]]) -> List[float]:
  closes = [b["close"] for b in bars if b.get("close", 0) > 0]
  if len(closes) < 2:
    return []
  return [closes[i] / closes[i - 1] - 1 for i in range(1, len(closes))]


def _correlation(a: List[float], b: List[float]) -> float:
  n = min(len(a), len(b))
  if n < 5:
    return 0.0
  xs, ys = a[-n:], b[-n:]
  mx = sum(xs) / n
  my = sum(ys) / n
  num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
  den_x = math.sqrt(sum((x - mx) ** 2 for x in xs))
  den_y = math.sqrt(sum((y - my) ** 2 for y in ys))
  if den_x <= 1e-12 or den_y <= 1e-12:
    return 0.0
  return num / (den_x * den_y)


def _regime_momentum_scale(index_bars: Optional[List[Dict[str, float]]]) -> float:
  """Снижает momentum в боковике (|r20| < 3%)."""
  if not index_bars:
    return 1.0
  m = score_bars(index_bars)
  if abs(m.get("return_20d", 0.0)) < 0.03:
    return 0.5
  return 1.0


def score_bars(bars: List[Dict[str, float]], *, momentum_scale: float = 1.0) -> Dict[str, float]:
  """Метрики тикера по дневным свечам."""
  closes = [b["close"] for b in bars if b.get("close", 0) > 0]
  if len(closes) < 10:
    return {"score": -1e9, "return_20d": 0.0, "sharpe": 0.0, "max_dd": 1.0, "avg_volume": 0.0}
  rets = [(closes[i] / closes[i - 1] - 1) for i in range(1, len(closes))]
  volumes = [float(b.get("volume", 0) or 0) for b in bars if b.get("close", 0) > 0]
  avg_vol = sum(volumes[-20:]) / max(len(volumes[-20:]), 1)
  r20 = (closes[-1] / closes[-min(20, len(closes))] - 1) if len(closes) >= 2 else 0.0
  sharpe = _compute_sharpe(rets[-60:])
  max_dd = _max_drawdown(closes[-60:])
  score = r20 * 100 * momentum_scale + sharpe * 0.5 - max_dd * 50
  return {"score": score, "return_20d": r20, "sharpe": sharpe, "max_dd": max_dd, "avg_volume": avg_vol}


def select_portfolio_quant(
  get_bars: Callable[[str], List[Dict[str, float]]],
  candidates: List[str],
  min_instruments: int,
  max_instruments: int,
  max_weight: float,
  *,
  source_label: str = "quant",
  min_avg_volume: float = 0.0,
  max_sector_weight: float = 0.0,
  max_pair_correlation: float = 0.0,
  index_bars: Optional[List[Dict[str, float]]] = None,
) -> Tuple[List[Dict[str, Any]], str]:
  """Ранжирование кандидатов по свечам, выбор top-N с весами."""
  momentum_scale = _regime_momentum_scale(index_bars)
  ranked: List[Dict[str, Any]] = []
  returns_cache: Dict[str, List[float]] = {}

  for ticker in candidates:
    try:
      bars = get_bars(ticker.upper())
      m = score_bars(bars, momentum_scale=momentum_scale)
      if m["score"] <= -1e8:
        continue
      if min_avg_volume > 0 and m.get("avg_volume", 0) < min_avg_volume:
        continue
      rets = _returns_from_bars(bars)
      returns_cache[ticker.upper()] = rets
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
  top: List[Dict[str, Any]] = []
  corr_limit = max(0.0, min(0.99, max_pair_correlation))
  for row in ranked:
    if len(top) >= max(1, max_instruments):
      break
    if corr_limit > 0 and top:
      t_rets = returns_cache.get(row["ticker"], [])
      if any(abs(_correlation(t_rets, returns_cache.get(p["ticker"], []))) > corr_limit for p in top):
        continue
    top.append(row)

  if len(top) < min_instruments:
    top = ranked[: max(1, max_instruments)]
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

  if max_sector_weight > 0:
    selections = enforce_sector_caps(selections, max_sector_weight)

  leaders = ", ".join(f"{r['ticker']}({r['score']:.1f})" for r in top[:3])
  regime_note = " sideways↓mom" if momentum_scale < 1.0 else ""
  summary = f"{source_label}: momentum+Sharpe{regime_note}, лидеры: {leaders}"
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

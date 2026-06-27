"""Выбор лучшего советника среди DeepSeek, Finam, MOEX, Gemini, Groq, OpenRouter."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

from . import finam_advisor, moex_advisor
from .market_data_client import CompositeMarketClient
from .quant_advisor import score_bars

logger = logging.getLogger(__name__)


def _portfolio_daily_returns(
  client: CompositeMarketClient,
  selections: List[Dict[str, Any]],
  history_days: int = 90,
) -> List[float]:
  """Взвешенная дневная доходность портфеля по историческим свечам."""
  if not selections:
    return []
  weights = {s["ticker"].upper(): float(s["target_weight"]) for s in selections}
  series: Dict[str, List[float]] = {}
  min_len = 10**9
  for ticker in weights:
    try:
      bars = client.get_daily_bars(ticker, days=history_days)
      closes = [b["close"] for b in bars if b.get("close", 0) > 0]
      if len(closes) < 5:
        continue
      rets = [closes[i] / closes[i - 1] - 1 for i in range(1, len(closes))]
      series[ticker] = rets
      min_len = min(min_len, len(rets))
    except Exception:
      continue
  if not series or min_len <= 0 or min_len >= 10**9:
    return []
  min_len = min(min_len, 60)
  port_rets: List[float] = []
  for i in range(-min_len, 0):
    day_ret = 0.0
    wsum = 0.0
    for ticker, rets in series.items():
      w = weights.get(ticker, 0.0)
      day_ret += w * rets[i]
      wsum += w
    if wsum > 0:
      port_rets.append(day_ret / wsum)
  return port_rets


def score_portfolio_proposal(
  client: CompositeMarketClient,
  selections: List[Dict[str, Any]],
  history_days: int = 90,
) -> float:
  """Sharpe портфеля на истории (выше — лучше)."""
  rets = _portfolio_daily_returns(client, selections, history_days)
  if len(rets) < 5:
    return -1e9
  from .quant_advisor import _compute_sharpe

  sharpe = _compute_sharpe(rets)
  mean = sum(rets) / len(rets)
  return sharpe + mean * 10


def pick_best_portfolio(
  proposals: List[Tuple[str, List[Dict[str, Any]], str]],
  market_client: CompositeMarketClient,
  history_days: int = 90,
) -> Tuple[str, List[Dict[str, Any]], str, float]:
  """
  proposals: [(source_name, selections, summary), ...]
  Возвращает (winner_source, selections, message, score).
  """
  best_name = ""
  best_sel: List[Dict[str, Any]] = []
  best_summary = ""
  best_score = -1e18

  for name, sel, summary in proposals:
    if not sel:
      continue
    if market_client.configured:
      score = score_portfolio_proposal(market_client, sel, history_days)
    else:
      score = sum(float(s.get("target_weight", 0)) for s in sel)
    logger.info("Advisor %s: score=%.4f n=%d", name, score, len(sel))
    if score > best_score:
      best_score = score
      best_name = name
      best_sel = sel
      best_summary = summary

  if not best_name:
    return "", [], "Нет предложений от советников", best_score

  tickers = ", ".join(f"{s['ticker']} {s['target_weight']:.0%}" for s in best_sel)
  msg = f"Выбран {best_name} (score={best_score:.3f}): {tickers}"
  if best_summary:
    msg += f". {best_summary}"
  return best_name, best_sel, msg, best_score


def get_best_recommendations(
  instruments: List[Any],
  positions: Dict[str, Any],
  equity: float,
  cash: float,
  last_prices: Dict[str, float],
  *,
  use_deepseek: bool = True,
  use_finam: bool = True,
  use_moex: bool = True,
  use_gemini: bool = True,
  use_groq: bool = True,
  use_openrouter: bool = True,
  deepseek_kwargs: Optional[Dict[str, Any]] = None,
  gemini_kwargs: Optional[Dict[str, Any]] = None,
  groq_kwargs: Optional[Dict[str, Any]] = None,
  openrouter_kwargs: Optional[Dict[str, Any]] = None,
  market_client: Optional[CompositeMarketClient] = None,
  finam_history_days: int = 30,
) -> Tuple[Dict[str, Dict[str, Any]], str]:
  """Сравнивает рекомендации всех советников, возвращает лучший набор."""
  deepseek_kwargs = deepseek_kwargs or {}
  gemini_kwargs = gemini_kwargs or {}
  groq_kwargs = groq_kwargs or {}
  openrouter_kwargs = openrouter_kwargs or {}
  proposals: List[Tuple[str, Dict[str, Dict[str, Any]]]] = []

  if use_deepseek:
    try:
      from .deepseek_advisor import get_recommendations as ds_get

      ds = ds_get(
        instruments=instruments,
        positions=positions,
        equity=equity,
        cash=cash,
        last_prices=last_prices,
        **deepseek_kwargs,
      )
      if ds:
        proposals.append(("deepseek", ds))
    except Exception as e:
      logger.warning("DeepSeek recommendations: %s", e)

  if use_gemini:
    try:
      from .gemini_advisor import get_recommendations as gm_get

      gm = gm_get(
        instruments=instruments,
        positions=positions,
        equity=equity,
        cash=cash,
        last_prices=last_prices,
        **gemini_kwargs,
      )
      if gm:
        proposals.append(("gemini", gm))
    except Exception as e:
      logger.warning("Gemini recommendations: %s", e)

  if use_groq:
    try:
      from .groq_advisor import get_recommendations as gq_get

      gq = gq_get(
        instruments=instruments,
        positions=positions,
        equity=equity,
        cash=cash,
        last_prices=last_prices,
        **groq_kwargs,
      )
      if gq:
        proposals.append(("groq", gq))
    except Exception as e:
      logger.warning("Groq recommendations: %s", e)

  if use_openrouter:
    try:
      from .openrouter_advisor import get_recommendations as or_get

      or_recs = or_get(
        instruments=instruments,
        positions=positions,
        equity=equity,
        cash=cash,
        last_prices=last_prices,
        **openrouter_kwargs,
      )
      if or_recs:
        proposals.append(("openrouter", or_recs))
    except Exception as e:
      logger.warning("OpenRouter recommendations: %s", e)

  client = market_client or CompositeMarketClient()
  if use_finam and client.finam and getattr(client.finam, "configured", False):
    try:
      fm = finam_advisor.get_recommendations(client.finam, instruments, history_days=finam_history_days)
      if fm:
        proposals.append(("finam", fm))
    except Exception as e:
      logger.warning("Finam recommendations: %s", e)

  if use_moex:
    try:
      mx = moex_advisor.get_recommendations(client.moex, instruments, history_days=finam_history_days)
      if mx:
        proposals.append(("moex", mx))
    except Exception as e:
      logger.warning("MOEX recommendations: %s", e)

  if not proposals:
    return {}, "none"
  if len(proposals) == 1:
    return proposals[0][1], proposals[0][0]

  best_name = ""
  best_recs: Dict[str, Dict[str, Any]] = {}
  best_score = -1e18
  for name, recs in proposals:
    score = 0.0
    for _figi, r in recs.items():
      action = r.get("action", "hold")
      strength = float(r.get("strength", 0.5))
      sign = 1.0 if action == "buy" else (-1.0 if action == "sell" else 0.0)
      score += sign * strength
    if client.configured:
      for ins in instruments:
        if getattr(ins, "figi", "") in recs:
          try:
            bars = client.get_daily_bars(getattr(ins, "ticker", ""), days=finam_history_days)
            score += score_bars(bars).get("score", 0) * 0.01
          except Exception:
            pass
    if score > best_score:
      best_score = score
      best_name = name
      best_recs = recs

  return best_recs, best_name

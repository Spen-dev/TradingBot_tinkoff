"""Выбор лучшего советника: количественные (Finam, MOEX) + LLM через OpenRouter."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

from . import finam_advisor, moex_advisor
from .market_data_client import CompositeMarketClient
from .quant_advisor import score_bars
from .strategy_names import is_ai_strategy

logger = logging.getLogger(__name__)

# Имена советников на базе LLM (приоритет при pick_best)
AI_ADVISOR_SOURCES = frozenset({"llm", "macro", "ai"})
# Небольшой бонус к score: AI побеждает при близких результатах, quant — при явном отрыве
AI_PRIORITY_SCORE_BONUS = 0.05

_REGIME_STRATEGY_KEYS = ("strategy_trend", "strategy_range", "strategy_weak_trend")


def _advisor_score_with_ai_priority(name: str, score: float, ai_priority: bool) -> float:
  if ai_priority and name in AI_ADVISOR_SOURCES:
    return score + AI_PRIORITY_SCORE_BONUS
  return score


def _config_uses_llm_strategy(instrument: Any) -> bool:
  return is_ai_strategy(getattr(instrument, "strategy", None))


def _learned_uses_llm_strategy(learned_entry: Dict[str, Any]) -> bool:
  if not learned_entry:
    return False
  if is_ai_strategy(learned_entry.get("strategy")):
    return True
  return any(is_ai_strategy(learned_entry.get(key)) for key in _REGIME_STRATEGY_KEYS)


def instruments_use_llm_strategy(
  instruments: List[Any],
  learned: Optional[Dict[str, Dict[str, Any]]] = None,
) -> bool:
  """True, если хотя бы один инструмент торгуется через LLM (strategy=ai) по конфигу или learned."""
  learned = learned or {}
  for ins in instruments:
    if _config_uses_llm_strategy(ins):
      return True
    figi = getattr(ins, "figi", "")
    if figi and _learned_uses_llm_strategy(learned.get(figi, {})):
      return True
  return False


def resolve_rebalance_advisor_flags(
  *,
  use_finam: bool,
  use_moex: bool,
  use_openrouter: bool,
  instruments: List[Any],
  learned: Optional[Dict[str, Dict[str, Any]]] = None,
  ai_mode: bool = False,
  llm_in_pick_best: bool = False,
) -> Tuple[bool, bool, bool, bool]:
  """
  Флаги для ребаланса: (run_ensemble, use_finam, use_moex, use_openrouter).
  LLM на ребалансе — только если есть инструменты со стратегией ai; Finam/MOEX — всегда при включении.
  ai_mode: LLM primary на ребалансе; MOEX/Finam — fallback и pick_best портфеля.
  """
  if ai_mode:
    llm_enabled = bool(use_openrouter)
    run = bool(use_finam) or bool(use_moex) or llm_enabled
    return run, bool(use_finam), bool(use_moex), llm_enabled
  llm_strategy = instruments_use_llm_strategy(instruments, learned)
  llm_enabled = bool(use_openrouter) and (llm_strategy or llm_in_pick_best)
  run_ensemble = use_finam or use_moex or llm_enabled
  return run_ensemble, bool(use_finam), bool(use_moex), bool(llm_enabled)


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
  ai_priority: bool = False,
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
    adj = _advisor_score_with_ai_priority(name, score, ai_priority)
    logger.info("Advisor %s: score=%.4f adj=%.4f n=%d", name, score, adj, len(sel))
    if adj > best_score:
      best_score = adj
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


def _proposal_tickers_line(sel: List[Dict[str, Any]], limit: int = 6) -> str:
  parts = [f"{s['ticker']} {float(s.get('target_weight', 0)):.0%}" for s in sel[:limit]]
  return ", ".join(parts)


def _proposal_score(
  name: str,
  sel: List[Dict[str, Any]],
  market_client: CompositeMarketClient,
  history_days: int,
  ai_priority: bool,
) -> Tuple[float, float]:
  if not sel:
    return 0.0, 0.0
  if market_client.configured:
    raw = score_portfolio_proposal(market_client, sel, history_days)
  else:
    raw = sum(float(s.get("target_weight", 0)) for s in sel)
  adj = _advisor_score_with_ai_priority(name, raw, ai_priority)
  return raw, adj


def format_advisor_pick_comparison(
  proposals: List[Tuple[str, List[Dict[str, Any]], str]],
  winner: str,
  market_client: CompositeMarketClient,
  *,
  history_days: int = 90,
  ai_priority: bool = False,
) -> str:
  """Текст для Telegram: сравнение macro / moex / finam и победитель pick_best."""
  labels = {"macro": "Macro (RSS+LLM)", "moex": "MOEX", "finam": "Finam"}
  if not proposals:
    return ""

  scored: List[Tuple[str, float, float, str, str]] = []
  for name, sel, summary in proposals:
    raw, adj = _proposal_score(name, sel, market_client, history_days, ai_priority)
    tickers = _proposal_tickers_line(sel) if sel else "—"
    scored.append((name, raw, adj, tickers, summary or ""))
  scored.sort(key=lambda row: -row[2])

  lines = ["📊 Macro vs MOEX (pick_best по Sharpe):"]
  for name, raw, adj, tickers, summary in scored:
    label = labels.get(name, name)
    mark = "✅" if name == winner else "·"
    if market_client.configured:
      lines.append(f"{mark} {label}: adj={adj:.3f} (raw={raw:.3f})")
    else:
      lines.append(f"{mark} {label}: score={adj:.3f}")
    lines.append(f"   {tickers}")
    if name == "macro" and summary:
      short = summary.replace("\n", " ")[:140]
      if short:
        lines.append(f"   {short}")

  missing = [labels.get(k, k) for k in ("macro", "moex") if k not in {p[0] for p in proposals}]
  if missing:
    lines.append(f"   (нет предложения: {', '.join(missing)})")

  if winner:
    lines.append(f"→ Выбран: {labels.get(winner, winner)}")
  return "\n".join(lines)


def _pick_best_recommendation_proposals(
  proposals: List[Tuple[str, Dict[str, Dict[str, Any]]]],
  instruments: List[Any],
  client: CompositeMarketClient,
  finam_history_days: int,
  ai_priority: bool = False,
) -> Tuple[Dict[str, Dict[str, Any]], str]:
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
    adj = _advisor_score_with_ai_priority(name, score, ai_priority)
    if adj > best_score:
      best_score = adj
      best_name = name
      best_recs = recs
  return best_recs, best_name


def get_best_recommendations(
  instruments: List[Any],
  positions: Dict[str, Any],
  equity: float,
  cash: float,
  last_prices: Dict[str, float],
  *,
  use_finam: bool = True,
  use_moex: bool = True,
  use_openrouter: bool = True,
  openrouter_kwargs: Optional[Dict[str, Any]] = None,
  market_client: Optional[CompositeMarketClient] = None,
  finam_history_days: int = 30,
  ai_mode: bool = False,
  ai_priority: bool = False,
) -> Tuple[Dict[str, Dict[str, Any]], str]:
  """Сравнивает рекомендации советников (LLM, Finam, MOEX), возвращает лучший набор."""
  openrouter_kwargs = openrouter_kwargs or {}
  proposals: List[Tuple[str, Dict[str, Dict[str, Any]]]] = []

  if use_openrouter:
    try:
      from .openrouter_advisor import get_recommendations as llm_get

      llm_kwargs = dict(openrouter_kwargs)
      llm_kwargs.setdefault("cache_hours", llm_kwargs.get("cache_hours", 0))
      recs = llm_get(
        instruments=instruments,
        positions=positions,
        equity=equity,
        cash=cash,
        last_prices=last_prices,
        **llm_kwargs,
      )
      if recs:
        proposals.append(("llm", recs))
    except Exception as e:
      logger.warning("LLM (OpenRouter) recommendations: %s", e)

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

  if ai_mode:
    for name, recs in proposals:
      if name == "llm" and recs:
        logger.info("ai_mode: рекомендации LLM (%d инструментов)", len(recs))
        return recs, "llm"
    quant = [(n, r) for n, r in proposals if n != "llm" and r]
    if not quant:
      return {}, "none"
    if len(quant) == 1:
      logger.info("ai_mode: LLM недоступен — fallback %s", quant[0][0])
      return quant[0][1], quant[0][0]
    logger.info("ai_mode: LLM недоступен — pick_best среди quant")
    best_recs, best_name = _pick_best_recommendation_proposals(
      quant, instruments, client, finam_history_days, ai_priority=False
    )
    return best_recs, best_name

  if len(proposals) == 1:
    return proposals[0][1], proposals[0][0]

  best_recs, best_name = _pick_best_recommendation_proposals(
    proposals, instruments, client, finam_history_days, ai_priority=ai_priority
  )
  if ai_priority and best_name:
    logger.info("pick_best ребаланс: выбран %s (ai_priority=%s)", best_name, ai_priority)
  return best_recs, best_name

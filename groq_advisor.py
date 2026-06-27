"""Groq/Llama через OpenRouter (meta-llama/* модели)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .openrouter_advisor import get_recommendations as _or_get


def get_recommendations(
  instruments: List[Any],
  positions: Dict[str, Any],
  equity: float,
  cash: float,
  last_prices: Dict[str, float],
  *,
  model: str = "meta-llama/llama-3.3-70b-instruct",
  api_key: str = "",
  cache_hours: float = 0.0,
  history_summary: Optional[Dict[str, str]] = None,
  **kwargs: Any,
) -> Dict[str, Dict[str, Any]]:
  return _or_get(
    instruments,
    positions,
    equity,
    cash,
    last_prices,
    model=model,
    api_key_override=api_key,
    cache_hours=cache_hours,
    history_summary=history_summary,
    **kwargs,
  )


def select_universe_via_groq(
  candidates: List[str],
  candidate_summary: Dict[str, str],
  min_instruments: int,
  max_instruments: int,
  max_weight: float,
  *,
  model: str = "meta-llama/llama-3.3-70b-instruct",
  api_key: str = "",
  equity: float = 0.0,
  market_context: str = "",
  **kwargs: Any,
):
  from .openrouter_advisor import select_universe_via_openrouter

  return select_universe_via_openrouter(
    candidates,
    candidate_summary,
    min_instruments,
    max_instruments,
    max_weight,
    model=model,
    api_key_override=api_key,
    equity=equity,
    market_context=market_context,
    **kwargs,
  )

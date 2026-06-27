# LLM-советник: все запросы идут через OpenRouter (OPENROUTER_API_KEY).

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .openrouter_advisor import get_recommendations as _or_get


def get_recommendations(
  instruments: List[Any],
  positions: Dict[str, Any],
  equity: float,
  cash: float,
  last_prices: Dict[str, float],
  model: str = "deepseek/deepseek-chat",
  cache_hours: float = 0.0,
  history_summary: Optional[Dict[str, str]] = None,
  **kwargs: Any,
) -> Dict[str, Dict[str, Any]]:
  """DeepSeek через OpenRouter (deepseek/deepseek-chat или :free fallback)."""
  return _or_get(
    instruments,
    positions,
    equity,
    cash,
    last_prices,
    model=model,
    cache_hours=cache_hours,
    history_summary=history_summary,
    **kwargs,
  )

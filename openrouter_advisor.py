"""LLM-советник через OpenRouter (единый шлюз для всех моделей)."""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional, Tuple

from .llm_advisor_base import get_recommendations_via_llm, select_universe_via_llm
from .openrouter_client import (
  DEFAULT_FALLBACK_MODELS,
  api_key,
  chat,
  map_legacy_model,
  resolve_model_chain,
)

logger = logging.getLogger(__name__)

_llm_cache: Optional[tuple] = None  # (cache_key, data, ts)


def _recommendations_cache_key(
  instruments: List[Any],
  equity: float,
  cash: float,
) -> tuple:
  """Ключ кэша: состав портфеля + грубое изменение equity/cash."""
  members = tuple(
    sorted(
      (getattr(i, "figi", ""), getattr(i, "ticker", ""), round(float(getattr(i, "target_weight", 0) or 0), 4))
      for i in instruments
    )
  )
  return (members, int(equity // 5000), int(cash // 5000))


def _make_chat_fn(
  model: str,
  models: Optional[List[str]],
  api_key_override: str,
  base_url: str,
  site_url: str,
  app_name: str,
  max_tokens: int = 2048,
):
  chain = resolve_model_chain(model, models)

  def chat_fn(system: str, user: str) -> str:
    text, _used = chat(
      system,
      user,
      model=chain[0],
      models=chain[1:],
      api_key_override=api_key_override,
      base_url=base_url,
      site_url=site_url,
      app_name=app_name,
      max_tokens=max_tokens,
    )
    return text

  return chat_fn


def select_universe_via_openrouter(
  candidates: List[str],
  candidate_summary: Dict[str, str],
  min_instruments: int,
  max_instruments: int,
  max_weight: float,
  *,
  model: str = "google/gemini-2.5-flash-lite",
  models: Optional[List[str]] = None,
  api_key_override: Optional[str] = None,
  base_url: str = "https://openrouter.ai/api/v1",
  site_url: str = "",
  app_name: str = "Tinkoff Trading Bot",
  equity: float = 0.0,
  market_context: str = "",
) -> Tuple[List[Dict[str, Any]], str]:
  key = api_key(api_key_override)
  if not key:
    return [], "OPENROUTER_API_KEY не задан"

  primary = map_legacy_model(model)
  chat_fn = _make_chat_fn(primary, models, key, base_url, site_url, app_name, max_tokens=1536)
  sel, summary = select_universe_via_llm(
    chat_fn,
    candidates=candidates,
    candidate_summary=candidate_summary,
    min_instruments=min_instruments,
    max_instruments=max_instruments,
    max_weight=max_weight,
    equity=equity,
    market_context=market_context,
    provider_label="OpenRouter",
  )
  if sel and summary:
    return sel, summary
  if sel:
    return sel, f"OpenRouter ({primary}): {len(sel)} инструментов"
  return sel, summary


def get_recommendations(
  instruments: List[Any],
  positions: Dict[str, Any],
  equity: float,
  cash: float,
  last_prices: Dict[str, float],
  *,
  model: str = "google/gemini-2.5-flash-lite",
  models: Optional[List[str]] = None,
  api_key_override: Optional[str] = None,
  base_url: str = "https://openrouter.ai/api/v1",
  site_url: str = "",
  app_name: str = "Tinkoff Trading Bot",
  cache_hours: float = 0.0,
  history_summary: Optional[Dict[str, str]] = None,
) -> Dict[str, Dict[str, Any]]:
  global _llm_cache
  cache_key = _recommendations_cache_key(instruments, equity, cash)
  if cache_hours > 0 and _llm_cache is not None:
    cached_key, cached, ts = _llm_cache
    if cached_key == cache_key and (time.time() - ts) < cache_hours * 3600:
      return dict(cached)

  key = api_key(api_key_override)
  if not key:
    logger.debug("OPENROUTER_API_KEY не задан, LLM-советник отключён")
    return {}

  primary = map_legacy_model(model)
  chat_fn = _make_chat_fn(primary, models, key, base_url, site_url, app_name)
  out = get_recommendations_via_llm(
    chat_fn,
    instruments,
    positions,
    equity,
    cash,
    last_prices,
    history_summary=history_summary,
    provider_label="OpenRouter",
  )
  if cache_hours > 0 and out:
    _llm_cache = (cache_key, out, time.time())
  return out


# Алиасы для обратной совместимости
select_universe_via_llm_gateway = select_universe_via_openrouter
get_llm_recommendations = get_recommendations

__all__ = [
  "select_universe_via_openrouter",
  "get_recommendations",
  "get_llm_recommendations",
  "DEFAULT_FALLBACK_MODELS",
]

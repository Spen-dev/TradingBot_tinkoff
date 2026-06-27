"""Советник OpenRouter (free :free модели, OPENROUTER_API_KEY, OpenAI-compatible API)."""

from __future__ import annotations

import logging
import os
import time
from typing import Any, Dict, List, Optional, Tuple

from .llm_advisor_base import get_recommendations_via_llm, select_universe_via_llm

logger = logging.getLogger(__name__)

_openrouter_cache: Optional[tuple] = None


def _api_key(explicit: str = "") -> str:
  return (explicit or os.environ.get("OPENROUTER_API_KEY", "")).strip()


def _openrouter_chat(
  system: str,
  user: str,
  model: str,
  api_key: str,
  base_url: str = "https://openrouter.ai/api/v1",
  site_url: str = "",
  app_name: str = "Tinkoff Trading Bot",
) -> str:
  if not api_key:
    return ""
  from openai import OpenAI

  headers: Dict[str, str] = {}
  if site_url:
    headers["HTTP-Referer"] = site_url
  if app_name:
    headers["X-Title"] = app_name

  client = OpenAI(
    api_key=api_key,
    base_url=base_url.rstrip("/"),
    default_headers=headers or None,
  )
  resp = client.chat.completions.create(
    model=model,
    messages=[
      {"role": "system", "content": system},
      {"role": "user", "content": user},
    ],
    temperature=0.35,
    max_tokens=2048,
  )
  return (resp.choices[0].message.content or "").strip()


def select_universe_via_openrouter(
  candidates: List[str],
  candidate_summary: Dict[str, str],
  min_instruments: int,
  max_instruments: int,
  max_weight: float,
  *,
  model: str = "meta-llama/llama-3.3-70b-instruct:free",
  api_key: str = "",
  base_url: str = "https://openrouter.ai/api/v1",
  site_url: str = "",
  app_name: str = "Tinkoff Trading Bot",
  equity: float = 0.0,
  market_context: str = "",
) -> Tuple[List[Dict[str, Any]], str]:
  key = _api_key(api_key)
  chat = lambda s, u: _openrouter_chat(s, u, model, key, base_url, site_url, app_name)
  return select_universe_via_llm(
    chat,
    candidates=candidates,
    candidate_summary=candidate_summary,
    min_instruments=min_instruments,
    max_instruments=max_instruments,
    max_weight=max_weight,
    equity=equity,
    market_context=market_context,
    provider_label="OpenRouter",
  )


def get_recommendations(
  instruments: List[Any],
  positions: Dict[str, Any],
  equity: float,
  cash: float,
  last_prices: Dict[str, float],
  *,
  model: str = "meta-llama/llama-3.3-70b-instruct:free",
  api_key: str = "",
  base_url: str = "https://openrouter.ai/api/v1",
  site_url: str = "",
  app_name: str = "Tinkoff Trading Bot",
  cache_hours: float = 0.0,
  history_summary: Optional[Dict[str, str]] = None,
) -> Dict[str, Dict[str, Any]]:
  global _openrouter_cache
  if cache_hours > 0 and _openrouter_cache is not None:
    cached, ts = _openrouter_cache
    if (time.time() - ts) < cache_hours * 3600:
      return dict(cached)

  key = _api_key(api_key)
  chat = lambda s, u: _openrouter_chat(s, u, model, key, base_url, site_url, app_name)
  out = get_recommendations_via_llm(
    chat,
    instruments,
    positions,
    equity,
    cash,
    last_prices,
    history_summary=history_summary,
    provider_label="OpenRouter",
  )
  if cache_hours > 0 and out:
    _openrouter_cache = (out, time.time())
  return out

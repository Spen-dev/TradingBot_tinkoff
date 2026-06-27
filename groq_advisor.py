"""Советник Groq (бесплатный tier, GROQ_API_KEY, OpenAI-compatible API)."""

from __future__ import annotations

import logging
import os
import time
from typing import Any, Dict, List, Optional, Tuple

from .llm_advisor_base import get_recommendations_via_llm, select_universe_via_llm

logger = logging.getLogger(__name__)

_groq_cache: Optional[tuple] = None


def _api_key(explicit: str = "") -> str:
  return (explicit or os.environ.get("GROQ_API_KEY", "")).strip()


def _groq_chat(system: str, user: str, model: str, api_key: str) -> str:
  if not api_key:
    return ""
  from openai import OpenAI

  client = OpenAI(api_key=api_key, base_url="https://api.groq.com/openai/v1")
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


def select_universe_via_groq(
  candidates: List[str],
  candidate_summary: Dict[str, str],
  min_instruments: int,
  max_instruments: int,
  max_weight: float,
  *,
  model: str = "llama-3.3-70b-versatile",
  api_key: str = "",
  equity: float = 0.0,
  market_context: str = "",
) -> Tuple[List[Dict[str, Any]], str]:
  key = _api_key(api_key)
  chat = lambda s, u: _groq_chat(s, u, model, key)
  return select_universe_via_llm(
    chat,
    candidates=candidates,
    candidate_summary=candidate_summary,
    min_instruments=min_instruments,
    max_instruments=max_instruments,
    max_weight=max_weight,
    equity=equity,
    market_context=market_context,
    provider_label="Groq",
  )


def get_recommendations(
  instruments: List[Any],
  positions: Dict[str, Any],
  equity: float,
  cash: float,
  last_prices: Dict[str, float],
  *,
  model: str = "llama-3.3-70b-versatile",
  api_key: str = "",
  cache_hours: float = 0.0,
  history_summary: Optional[Dict[str, str]] = None,
) -> Dict[str, Dict[str, Any]]:
  global _groq_cache
  if cache_hours > 0 and _groq_cache is not None:
    cached, ts = _groq_cache
    if (time.time() - ts) < cache_hours * 3600:
      return dict(cached)

  key = _api_key(api_key)
  chat = lambda s, u: _groq_chat(s, u, model, key)
  out = get_recommendations_via_llm(
    chat,
    instruments,
    positions,
    equity,
    cash,
    last_prices,
    history_summary=history_summary,
    provider_label="Groq",
  )
  if cache_hours > 0 and out:
    _groq_cache = (out, time.time())
  return out

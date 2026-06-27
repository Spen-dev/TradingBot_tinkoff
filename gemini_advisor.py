"""Советник Google Gemini (бесплатный tier, GEMINI_API_KEY)."""

from __future__ import annotations

import json
import logging
import os
import time
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

from .llm_advisor_base import get_recommendations_via_llm, select_universe_via_llm

logger = logging.getLogger(__name__)

_gemini_cache: Optional[tuple] = None


def _api_key(explicit: str = "") -> str:
  return (explicit or os.environ.get("GEMINI_API_KEY", "")).strip()


def _gemini_chat(system: str, user: str, model: str, api_key: str) -> str:
  if not api_key:
    return ""
  url = (
    f"https://generativelanguage.googleapis.com/v1beta/models/"
    f"{model}:generateContent?key={urllib.parse.quote(api_key)}"
  )
  body = {
    "contents": [{"role": "user", "parts": [{"text": f"{system}\n\n{user}"}]}],
    "generationConfig": {"temperature": 0.35, "maxOutputTokens": 2048},
  }
  data = json.dumps(body).encode("utf-8")
  req = urllib.request.Request(
    url,
    data=data,
    headers={"Content-Type": "application/json", "User-Agent": "tinkoff_bot/1.0"},
    method="POST",
  )
  with urllib.request.urlopen(req, timeout=45) as resp:
    payload = json.loads(resp.read().decode("utf-8"))
  candidates = payload.get("candidates") or []
  if not candidates:
    return ""
  parts = (candidates[0].get("content") or {}).get("parts") or []
  return "".join(str(p.get("text", "")) for p in parts).strip()


def select_universe_via_gemini(
  candidates: List[str],
  candidate_summary: Dict[str, str],
  min_instruments: int,
  max_instruments: int,
  max_weight: float,
  *,
  model: str = "gemini-2.0-flash",
  api_key: str = "",
  equity: float = 0.0,
  market_context: str = "",
) -> Tuple[List[Dict[str, Any]], str]:
  key = _api_key(api_key)
  chat = lambda s, u: _gemini_chat(s, u, model, key)
  return select_universe_via_llm(
    chat,
    candidates=candidates,
    candidate_summary=candidate_summary,
    min_instruments=min_instruments,
    max_instruments=max_instruments,
    max_weight=max_weight,
    equity=equity,
    market_context=market_context,
    provider_label="Gemini",
  )


def get_recommendations(
  instruments: List[Any],
  positions: Dict[str, Any],
  equity: float,
  cash: float,
  last_prices: Dict[str, float],
  *,
  model: str = "gemini-2.0-flash",
  api_key: str = "",
  cache_hours: float = 0.0,
  history_summary: Optional[Dict[str, str]] = None,
) -> Dict[str, Dict[str, Any]]:
  global _gemini_cache
  if cache_hours > 0 and _gemini_cache is not None:
    cached, ts = _gemini_cache
    if (time.time() - ts) < cache_hours * 3600:
      return dict(cached)

  key = _api_key(api_key)
  chat = lambda s, u: _gemini_chat(s, u, model, key)
  out = get_recommendations_via_llm(
    chat,
    instruments,
    positions,
    equity,
    cash,
    last_prices,
    history_summary=history_summary,
    provider_label="Gemini",
  )
  if cache_hours > 0 and out:
    _gemini_cache = (out, time.time())
  return out

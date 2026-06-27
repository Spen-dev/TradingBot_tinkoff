"""Единый клиент OpenRouter для всех LLM-запросов бота."""

from __future__ import annotations

import logging
import os
import time
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_APP_NAME = "Tinkoff Trading Bot"

# Цепочка моделей при 429/ошибке провайдера: дешёвые, JSON-friendly, разные провайдеры
DEFAULT_FALLBACK_MODELS = [
  "google/gemini-2.0-flash-001",
  "deepseek/deepseek-chat",
]

# Старые имена моделей → OpenRouter slug
LEGACY_MODEL_MAP = {
  "deepseek-chat": "deepseek/deepseek-chat",
  "deepseek-reasoner": "deepseek/deepseek-r1",
  "gemini-2.0-flash": "google/gemini-2.0-flash-001",
  "llama-3.3-70b-versatile": "meta-llama/llama-3.3-70b-instruct",
}


def api_key(explicit: Optional[str] = None) -> str:
  """None — ключ из OPENROUTER_API_KEY; '' — явно без ключа (env не читается)."""
  if explicit is not None:
    return explicit.strip()
  return os.environ.get("OPENROUTER_API_KEY", "").strip()


def map_legacy_model(model: str) -> str:
  model = (model or "").strip()
  if not model:
    return DEFAULT_FALLBACK_MODELS[0]
  if "/" in model:
    return model
  return LEGACY_MODEL_MAP.get(model, model)


def resolve_model_chain(primary: str, fallbacks: Optional[List[str]] = None) -> List[str]:
  """Уникальный список моделей: primary + fallbacks."""
  chain: List[str] = []
  for m in [map_legacy_model(primary), *(fallbacks or DEFAULT_FALLBACK_MODELS)]:
    m = map_legacy_model(m)
    if m and m not in chain:
      chain.append(m)
  return chain or list(DEFAULT_FALLBACK_MODELS)


def _is_retryable(exc: Exception) -> bool:
  msg = str(exc).lower()
  return "429" in msg or "rate" in msg or "timeout" in msg or "503" in msg or "502" in msg


def chat(
  system: str,
  user: str,
  *,
  model: str,
  models: Optional[List[str]] = None,
  api_key_override: Optional[str] = None,
  base_url: str = DEFAULT_BASE_URL,
  site_url: str = "",
  app_name: str = DEFAULT_APP_NAME,
  temperature: float = 0.35,
  max_tokens: int = 2048,
) -> Tuple[str, str]:
  """
  Запрос к OpenRouter. При ошибке пробует следующую модель из цепочки.
  Возвращает (text, model_used).
  """
  key = api_key(api_key_override)
  if not key:
    return "", ""

  chain = resolve_model_chain(model, models)
  from openai import OpenAI

  headers: Dict[str, str] = {}
  if site_url:
    headers["HTTP-Referer"] = site_url
  if app_name:
    headers["X-Title"] = app_name

  client = OpenAI(
    api_key=key,
    base_url=base_url.rstrip("/"),
    default_headers=headers or None,
  )

  last_err: Optional[Exception] = None
  for attempt_model in chain:
    try:
      resp = client.chat.completions.create(
        model=attempt_model,
        messages=[
          {"role": "system", "content": system},
          {"role": "user", "content": user},
        ],
        temperature=temperature,
        max_tokens=max_tokens,
      )
      text = (resp.choices[0].message.content or "").strip()
      if attempt_model != chain[0]:
        logger.info("OpenRouter: использована fallback-модель %s", attempt_model)
      return text, attempt_model
    except Exception as e:
      last_err = e
      if _is_retryable(e):
        logger.warning("OpenRouter %s: %s — пробуем следующую модель", attempt_model, e)
        time.sleep(1.0)
        continue
      logger.warning("OpenRouter %s: %s", attempt_model, e)
      break

  if last_err:
    raise last_err
  return "", ""

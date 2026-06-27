"""Macro-советник: новости/события (RSS) + LLM → состав портфеля MOEX."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .llm_advisor_base import select_universe_via_macro_events
from .news_client import collect_macro_headlines, format_headlines_for_llm
from .openrouter_client import api_key, chat, map_legacy_model, resolve_model_chain

logger = logging.getLogger(__name__)


def select_portfolio_via_macro(
  candidates: List[str],
  candidate_summary: Dict[str, str],
  min_instruments: int,
  max_instruments: int,
  max_weight: float,
  macro_cfg: Any,
  *,
  model: str = "google/gemini-2.5-flash-lite",
  models: Optional[List[str]] = None,
  api_key_override: str = "",
  base_url: str = "https://openrouter.ai/api/v1",
  site_url: str = "",
  app_name: str = "Tinkoff Trading Bot",
  equity: float = 0.0,
  base_dir: Optional[Path] = None,
) -> Tuple[List[Dict[str, Any]], str]:
  """
  Анализирует мировые/макро-события из RSS и выбирает портфель из кандидатов через OpenRouter.
  """
  key = api_key(api_key_override)
  if not key:
    return [], "macro: OPENROUTER_API_KEY не задан"

  rss_urls = list(getattr(macro_cfg, "rss_urls", None) or [])
  headlines = collect_macro_headlines(
    rss_urls or None,
    max_per_feed=int(getattr(macro_cfg, "max_headlines_per_feed", 10) or 10),
    max_total=int(getattr(macro_cfg, "max_headlines_total", 25) or 25),
    cache_hours=float(getattr(macro_cfg, "cache_hours", 6.0) or 0),
    cache_file=str(getattr(macro_cfg, "cache_file", "data/macro_news_cache.json") or "data/macro_news_cache.json"),
    timeout=float(getattr(macro_cfg, "request_timeout_seconds", 20) or 20),
    base_dir=base_dir,
  )
  events_text = format_headlines_for_llm(headlines)
  if not events_text.strip():
    return [], "macro: не удалось загрузить новости (RSS)"

  primary = map_legacy_model(model)
  chain = resolve_model_chain(primary, models)

  def chat_fn(system: str, user: str) -> str:
    text, _ = chat(
      system,
      user,
      model=chain[0],
      models=chain[1:],
      api_key_override=key,
      base_url=base_url,
      site_url=site_url,
      app_name=app_name,
      max_tokens=2048,
    )
    return text

  sel, summary = select_universe_via_macro_events(
    chat_fn,
    candidates=candidates,
    candidate_summary=candidate_summary,
    events_text=events_text,
    min_instruments=min_instruments,
    max_instruments=max_instruments,
    max_weight=max_weight,
    equity=equity,
  )
  n_news = len(headlines)
  prefix = f"macro ({n_news} новостей)"
  if sel and summary:
    return sel, f"{prefix}: {summary}"
  if sel:
    tickers = ", ".join(f"{s['ticker']} {s['target_weight']:.0%}" for s in sel)
    return sel, f"{prefix}: {tickers}"
  return sel, summary or f"{prefix}: LLM не вернул портфель"

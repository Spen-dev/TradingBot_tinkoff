"""Имена стратегий и нормализация (без зависимостей от broker/tinkoff)."""

from __future__ import annotations

from typing import List, Union

# LLM-стратегия (сигналы из OpenRouter). «deepseek» — устаревший alias.
AI_STRATEGY = "ai"
LEGACY_AI_STRATEGY_ALIASES = frozenset({"deepseek"})


def normalize_strategy_name(name: Union[str, List[str], None]) -> Union[str, List[str], None]:
  if isinstance(name, str):
    return AI_STRATEGY if name in LEGACY_AI_STRATEGY_ALIASES else name
  if isinstance(name, list):
    return [normalize_strategy_name(x) if isinstance(x, str) else x for x in name]
  return name


def is_ai_strategy(name: Union[str, List[str], None]) -> bool:
  if name in (AI_STRATEGY, *LEGACY_AI_STRATEGY_ALIASES):
    return True
  if isinstance(name, list):
    return any(is_ai_strategy(x) for x in name)
  return False

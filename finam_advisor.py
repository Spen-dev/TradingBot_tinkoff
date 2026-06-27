"""Количественный советник на данных Finam Trade API."""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from .finam_client import FinamClient
from .quant_advisor import get_recommendations_quant, score_bars, select_portfolio_quant

# re-export для совместимости с advisor_ensemble и тестами
__all__ = ["score_bars", "select_portfolio_via_finam", "get_recommendations"]


def select_portfolio_via_finam(
  client: FinamClient,
  candidates: List[str],
  min_instruments: int,
  max_instruments: int,
  max_weight: float,
  history_days: int = 90,
) -> Tuple[List[Dict[str, Any]], str]:
  """Ранжирование кандидатов по данным Finam, выбор top-N с весами."""
  if not client.configured:
    return [], "FINAM_API_TOKEN не задан"

  def get_bars(ticker: str):
    return client.get_daily_bars(ticker, days=history_days)

  return select_portfolio_quant(
    get_bars,
    candidates,
    min_instruments,
    max_instruments,
    max_weight,
    source_label="Finam",
  )


def get_recommendations(
  client: FinamClient,
  instruments: List[Any],
  history_days: int = 30,
) -> Dict[str, Dict[str, Any]]:
  """Сигналы buy/sell/hold по momentum на свечах Finam."""
  if not client.configured:
    return {}

  def get_bars(ticker: str):
    return client.get_daily_bars(ticker, days=history_days)

  return get_recommendations_quant(get_bars, instruments, source="finam")

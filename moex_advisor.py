"""Количественный советник на данных MOEX ISS (бесплатно, без токена)."""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from .moex_client import MoexClient
from .quant_advisor import get_recommendations_quant, select_portfolio_quant


def select_portfolio_via_moex(
  client: MoexClient,
  candidates: List[str],
  min_instruments: int,
  max_instruments: int,
  max_weight: float,
  history_days: int = 90,
  **quant_kwargs: Any,
) -> Tuple[List[Dict[str, Any]], str]:
  def get_bars(ticker: str):
    return client.get_daily_bars(ticker, days=history_days)

  return select_portfolio_quant(
    get_bars,
    candidates,
    min_instruments,
    max_instruments,
    max_weight,
    source_label="MOEX",
    **quant_kwargs,
  )


def get_recommendations(
  client: MoexClient,
  instruments: List[Any],
  history_days: int = 30,
) -> Dict[str, Dict[str, Any]]:
  def get_bars(ticker: str):
    return client.get_daily_bars(ticker, days=history_days)

  return get_recommendations_quant(get_bars, instruments, source="moex")

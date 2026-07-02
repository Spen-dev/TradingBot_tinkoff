"""Тесты форматирования сравнения macro vs moex для Telegram."""
from types import SimpleNamespace
from unittest.mock import patch

from tinkoff_bot.advisor_ensemble import format_advisor_pick_comparison


def _sel(ticker: str, weight: float):
  return {"ticker": ticker, "target_weight": weight}


def test_format_advisor_pick_comparison_marks_winner_and_scores():
  market = SimpleNamespace(configured=False)
  proposals = [
    ("macro", [_sel("SBER", 0.5), _sel("LKOH", 0.5)], "Рост сектора банков"),
    ("moex", [_sel("PLZL", 0.6), _sel("GMKN", 0.4)], "MOEX momentum"),
  ]
  text = format_advisor_pick_comparison(
    proposals,
    winner="moex",
    market_client=market,
    ai_priority=True,
  )
  assert "Macro vs Quant" in text
  assert "✅ MOEX" in text
  assert "· Macro" in text
  assert "PLZL 60%" in text
  assert "→ Выбран: MOEX" in text
  assert "Рост сектора банков" in text


def test_format_advisor_pick_comparison_shows_missing_advisor():
  market = SimpleNamespace(configured=True)
  proposals = [("moex", [_sel("SBER", 1.0)], "")]
  with patch("tinkoff_bot.advisor_ensemble.score_portfolio_proposal", return_value=-0.5):
    text = format_advisor_pick_comparison(proposals, "moex", market, ai_priority=False)
  assert "нет предложения: Macro (RSS+LLM)" in text
  assert "oos=-0.500" in text


def test_format_advisor_pick_comparison_empty_proposals():
  market = SimpleNamespace(configured=False)
  assert format_advisor_pick_comparison([], "moex", market) == ""

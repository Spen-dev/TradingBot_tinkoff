"""Тесты OpenRouter advisor."""
from tinkoff_bot.openrouter_advisor import select_universe_via_openrouter


def test_select_universe_without_api_key():
  sel, msg = select_universe_via_openrouter(
    candidates=["SBER", "LKOH"],
    candidate_summary={"SBER": "r5=1%", "LKOH": "r5=2%"},
    min_instruments=2,
    max_instruments=2,
    max_weight=0.5,
    api_key_override="",
  )
  assert sel == []
  assert "OPENROUTER" in msg.upper()

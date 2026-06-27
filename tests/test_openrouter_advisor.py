"""Тесты OpenRouter advisor."""
from types import SimpleNamespace

from tinkoff_bot.openrouter_advisor import _recommendations_cache_key, select_universe_via_openrouter


def test_recommendations_cache_key_changes_with_portfolio():
  a = [_Stub("F1", "SBER", 0.5), _Stub("F2", "LKOH", 0.5)]
  b = [_Stub("F1", "SBER", 0.5), _Stub("F3", "GMKN", 0.5)]
  k1 = _recommendations_cache_key(a, 100_000, 50_000)
  k2 = _recommendations_cache_key(b, 100_000, 50_000)
  assert k1 != k2


class _Stub:
  def __init__(self, figi: str, ticker: str, target_weight: float):
    self.figi = figi
    self.ticker = ticker
    self.target_weight = target_weight


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

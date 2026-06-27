"""Тесты OpenRouter advisor."""
from types import SimpleNamespace

from tinkoff_bot.openrouter_advisor import _recommendations_cache_key, get_recommendations


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


def test_get_recommendations_without_api_key():
  recs = get_recommendations(
    instruments=[_Stub("F1", "SBER", 0.5)],
    positions={},
    equity=100_000,
    cash=50_000,
    last_prices={"F1": 250.0},
    api_key_override="",
  )
  assert recs == {}

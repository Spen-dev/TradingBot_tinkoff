"""Тесты динамического портфеля."""
from tinkoff_bot.dynamic_portfolio import normalize_weights, get_candidates
from tinkoff_bot.config import DynamicPortfolioConfig, InstrumentConfig


def test_normalize_weights_caps_and_sums():
  raw = [
    {"ticker": "sber", "target_weight": 0.5},
    {"ticker": "lkoh", "target_weight": 0.4},
    {"ticker": "gmkn", "target_weight": 0.3},
    {"ticker": "plzl", "target_weight": 0.2},
    {"ticker": "mgnt", "target_weight": 0.1},
    {"ticker": "tatn", "target_weight": 0.05},
    {"ticker": "nvtk", "target_weight": 0.05},
  ]
  out = normalize_weights(raw, max_weight=0.30, min_instruments=4, max_instruments=6)
  assert len(out) == 6
  assert all(r["target_weight"] <= 0.30 + 1e-9 for r in out)
  total = sum(r["target_weight"] for r in out)
  assert abs(total - 1.0) < 1e-6
  assert all(r["ticker"].isupper() for r in out)


def test_get_candidates_from_config():
  dp = DynamicPortfolioConfig(enabled=True, candidates=["SBER", "LKOH"])
  fallback = [
    InstrumentConfig(
      figi="F1", ticker="GMKN", strategy="deepseek", target_weight=1.0, strategy_params={}
    )
  ]
  assert get_candidates(dp, fallback) == ["SBER", "LKOH"]


def test_get_candidates_fallback_to_instruments():
  dp = DynamicPortfolioConfig(enabled=True, candidates=[])
  fallback = [
    InstrumentConfig(
      figi="F1", ticker="GMKN", strategy="deepseek", target_weight=1.0, strategy_params={}
    )
  ]
  assert get_candidates(dp, fallback) == ["GMKN"]

"""Тесты имён стратегий: ai и legacy deepseek."""
from unittest.mock import MagicMock

from tinkoff_bot.strategy_names import AI_STRATEGY, is_ai_strategy, normalize_strategy_name
from tinkoff_bot.config import InstrumentConfig


def test_deepseek_alias_normalizes_to_ai():
  assert normalize_strategy_name("deepseek") == AI_STRATEGY
  assert is_ai_strategy("deepseek") is True
  assert is_ai_strategy("momentum") is False


def test_build_strategy_accepts_legacy_deepseek():
  from tinkoff_bot.strategy import build_strategy

  inst = InstrumentConfig(
    figi="F1", ticker="SBER", strategy="deepseek", target_weight=0.5, strategy_params={}, lot=1
  )
  broker = MagicMock()
  strat = build_strategy("deepseek", inst, broker)
  assert strat.__class__.__name__ in ("AIStrategyStub", "DeepSeekStubStrategy")

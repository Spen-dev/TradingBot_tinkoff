"""Тесты флагов советников на ребалансе."""
from types import SimpleNamespace

from tinkoff_bot.advisor_ensemble import (
  instruments_use_llm_strategy,
  resolve_rebalance_advisor_flags,
)


def _inst(ticker: str, strategy: str = "adaptive", figi: str = ""):
  return SimpleNamespace(ticker=ticker, figi=figi or f"FIGI_{ticker}", strategy=strategy)


def test_adaptive_only_skips_llm_but_keeps_quant():
  instruments = [_inst("SBER"), _inst("LKOH")]
  run, finam, moex, or_ = resolve_rebalance_advisor_flags(
    use_finam=True,
    use_moex=True,
    use_openrouter=True,
    instruments=instruments,
    learned={},
  )
  assert run is True
  assert finam is True
  assert moex is True
  assert or_ is False


def test_learned_legacy_deepseek_enables_llm_on_rebalance():
  instruments = [_inst("SBER", strategy="adaptive", figi="F1")]
  learned = {"F1": {"strategy": "deepseek"}}
  assert instruments_use_llm_strategy(instruments, learned) is True
  run, _, _, or_ = resolve_rebalance_advisor_flags(
    use_finam=False,
    use_moex=False,
    use_openrouter=True,
    instruments=instruments,
    learned=learned,
  )
  assert run is True
  assert or_ is True


def test_no_advisors_disabled():
  run, *_ = resolve_rebalance_advisor_flags(
    use_finam=False,
    use_moex=False,
    use_openrouter=False,
    instruments=[_inst("SBER")],
    learned={},
  )
  assert run is False

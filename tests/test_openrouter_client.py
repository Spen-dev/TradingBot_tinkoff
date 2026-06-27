"""Тесты OpenRouter client."""
from tinkoff_bot.openrouter_client import map_legacy_model, resolve_model_chain


def test_map_legacy_model():
  assert map_legacy_model("deepseek-chat") == "deepseek/deepseek-chat"
  assert map_legacy_model("openrouter/free") == "openrouter/free"


def test_resolve_model_chain_dedupes():
  chain = resolve_model_chain("openrouter/free", ["openrouter/free", "deepseek/deepseek-r1:free"])
  assert chain[0] == "openrouter/free"
  assert chain.count("openrouter/free") == 1
  assert "deepseek/deepseek-r1:free" in chain

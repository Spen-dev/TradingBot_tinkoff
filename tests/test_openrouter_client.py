"""Тесты OpenRouter client."""
from tinkoff_bot.openrouter_client import api_key, map_legacy_model, resolve_model_chain


def test_api_key_explicit_empty_skips_env(monkeypatch):
  monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
  assert api_key("") == ""
  assert api_key() == "sk-test"
  assert api_key("sk-explicit") == "sk-explicit"


def test_map_legacy_model():
  assert map_legacy_model("deepseek-chat") == "deepseek/deepseek-chat"
  assert map_legacy_model("openrouter/free") == "openrouter/free"


def test_resolve_model_chain_dedupes():
  chain = resolve_model_chain("openrouter/free", ["openrouter/free", "deepseek/deepseek-r1:free"])
  assert chain[0] == "openrouter/free"
  assert chain.count("openrouter/free") == 1
  assert "deepseek/deepseek-r1:free" in chain

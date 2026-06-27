"""Тесты парсинга LLM-ответов (OpenRouter / llm_advisor_base)."""
from tinkoff_bot.llm_advisor_base import normalize_weights, parse_llm_json


def test_parse_llm_json_strips_markdown():
  raw = '```json\n{"portfolio": [{"ticker": "SBER", "target_weight": 0.5}]}\n```'
  data = parse_llm_json(raw)
  assert data["portfolio"][0]["ticker"] == "SBER"


def test_normalize_weights_caps_and_sums_to_one():
  raw = [
    {"ticker": "SBER", "target_weight": 0.8},
    {"ticker": "LKOH", "target_weight": 0.2},
  ]
  out = normalize_weights(raw, max_weight=0.6, min_instruments=2, max_instruments=2)
  assert len(out) == 2
  assert {x["ticker"] for x in out} == {"SBER", "LKOH"}
  assert abs(sum(x["target_weight"] for x in out) - 1.0) < 1e-6

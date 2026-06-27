"""Тесты macro-советника и RSS-новостей."""
from types import SimpleNamespace
from unittest.mock import patch

from tinkoff_bot.news_client import _parse_rss_xml, format_headlines_for_llm
from tinkoff_bot.macro_advisor import select_portfolio_via_macro


SAMPLE_RSS = """<?xml version="1.0"?>
<rss version="2.0">
  <channel>
    <item>
      <title>Oil prices rise on supply concerns</title>
      <pubDate>Mon, 15 Jun 2026 10:00:00 GMT</pubDate>
      <link>https://example.com/1</link>
    </item>
    <item>
      <title>ЦБ сохранил ключевую ставку</title>
      <pubDate>Mon, 15 Jun 2026 09:00:00 GMT</pubDate>
    </item>
  </channel>
</rss>"""


def test_parse_rss_xml_extracts_titles():
  rows = _parse_rss_xml(SAMPLE_RSS, "test-feed", 5)
  assert len(rows) == 2
  assert "Oil" in rows[0]["title"]
  assert "ЦБ" in rows[1]["title"]


def test_format_headlines_for_llm():
  text = format_headlines_for_llm([{"title": "Test headline", "published": "today"}])
  assert "Test headline" in text
  assert "1." in text


def test_select_portfolio_via_macro_without_openrouter_key():
  macro_cfg = SimpleNamespace(
    rss_urls=[],
    max_headlines_per_feed=5,
    max_headlines_total=10,
    cache_hours=0,
    cache_file="data/test_macro_cache.json",
    request_timeout_seconds=5,
  )
  with patch("tinkoff_bot.macro_advisor.collect_macro_headlines", return_value=[{"title": "News", "published": ""}]):
    sel, msg = select_portfolio_via_macro(
      ["SBER", "LKOH"],
      {"SBER": "r5=1%", "LKOH": "r5=2%"},
      2,
      2,
      0.5,
      macro_cfg,
      api_key_override="",
    )
  assert sel == []
  assert "OPENROUTER" in msg.upper()

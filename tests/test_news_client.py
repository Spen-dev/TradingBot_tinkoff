from datetime import datetime, timedelta, timezone

from tinkoff_bot.news_client import (
  DEFAULT_RSS_URLS,
  _encode_url,
  _filter_and_sort_headlines,
  collect_macro_headlines,
  format_headlines_for_llm,
  _parse_rss_xml,
)


def test_encode_url_cyrillic_query():
  raw = DEFAULT_RSS_URLS[1]
  encoded = _encode_url(raw)
  assert "ЦБ" not in encoded
  assert encoded.startswith("https://")


def test_collect_macro_headlines_with_cyrillic_rss(monkeypatch):
  monkeypatch.setattr(
    "tinkoff_bot.news_client.fetch_rss_headlines",
    lambda url, **kw: [{"title": "Test headline", "published": "", "source": url, "link": ""}],
  )
  headlines = collect_macro_headlines(
    [DEFAULT_RSS_URLS[1]],
    cache_hours=0,
    force_refresh=True,
  )
  assert len(headlines) == 1


SAMPLE_RSS_WITH_DESC = """<?xml version="1.0"?>
<rss version="2.0">
  <channel>
    <item>
      <title>Fresh oil headline</title>
      <pubDate>Mon, 29 Jun 2026 10:00:00 GMT</pubDate>
      <description>Crude rises on &lt;b&gt;supply&lt;/b&gt; fears.</description>
    </item>
  </channel>
</rss>"""


def test_parse_rss_xml_extracts_description():
  rows = _parse_rss_xml(SAMPLE_RSS_WITH_DESC, "test-feed", 5)
  assert len(rows) == 1
  assert rows[0]["description"] == "Crude rises on supply fears."
  assert rows[0].get("published_ts")


def test_filter_and_sort_headlines_drops_old():
  now = datetime.now(timezone.utc)
  fresh = {
    "title": "Fresh",
    "published": now.strftime("%a, %d %b %Y %H:%M:%S GMT"),
    "published_ts": now.isoformat(),
  }
  old_ts = now - timedelta(days=30)
  stale = {
    "title": "Stale",
    "published": old_ts.strftime("%a, %d %b %Y %H:%M:%S GMT"),
    "published_ts": old_ts.isoformat(),
  }
  out = _filter_and_sort_headlines([stale, fresh], max_age_days=14)
  assert [h["title"] for h in out] == ["Fresh"]


def test_format_headlines_for_llm_includes_description():
  text = format_headlines_for_llm(
    [{"title": "Test headline", "published": "today", "description": "More context here."}],
    include_description=True,
  )
  assert "Test headline" in text
  assert "More context here." in text

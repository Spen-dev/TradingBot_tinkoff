from tinkoff_bot.news_client import DEFAULT_RSS_URLS, _encode_url, collect_macro_headlines


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

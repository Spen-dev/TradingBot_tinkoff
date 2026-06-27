from __future__ import annotations

import json
from pathlib import Path

from tinkoff_bot.ops_automation import (
  backup_learned_params,
  headlines_fingerprint,
  load_news_fingerprint,
  save_news_fingerprint,
  should_refresh_portfolio_for_news,
)


def test_headlines_fingerprint_stable():
  h = [{"title": "Oil rises"}, {"title": "CBR rate"}]
  assert headlines_fingerprint(h) == headlines_fingerprint(list(reversed(h)))


def test_news_fingerprint_state(tmp_path: Path):
  p = tmp_path / "fp.json"
  save_news_fingerprint(p, "abc123", 2)
  assert load_news_fingerprint(p) == "abc123"


def test_should_refresh_initial_no_trigger(tmp_path: Path, monkeypatch):
  class MacroCfg:
    rss_urls = ["http://example.com/rss"]
    max_headlines_per_feed = 5
    max_headlines_total = 10
    cache_file = "data/macro_news_cache.json"
    request_timeout_seconds = 5.0

  monkeypatch.setattr(
    "tinkoff_bot.news_client.collect_macro_headlines",
    lambda *a, **k: [{"title": "News A"}, {"title": "News B"}],
  )
  do, reason = should_refresh_portfolio_for_news(MacroCfg(), base_dir=tmp_path)
  assert do is False
  assert reason == "initial_fingerprint"


def test_backup_learned_params(tmp_path: Path):
  src_dir = tmp_path / "learned_params"
  src_dir.mkdir()
  (src_dir / "params.json").write_text('{"x": 1}', encoding="utf-8")
  out = backup_learned_params(tmp_path)
  assert out is not None
  assert Path(out).exists()
  assert json.loads(Path(out).read_text(encoding="utf-8")) == {"x": 1}

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


def test_no_trades_alert_never_traded():
  from datetime import datetime, timedelta
  from tinkoff_bot.ops_automation import no_trades_alert_payload

  started = datetime(2026, 6, 1, 10, 0, 0)
  now = started + timedelta(hours=80)
  send, key, msg = no_trades_alert_payload(
    now,
    no_trades_hours=72,
    last_trade_time=None,
    robot_started_at=started,
    robot_active=True,
    trading_enabled=True,
    already_alerted_for=None,
  )
  assert send is True
  assert key == started
  assert "Ни одной сделки" in msg

  send2, _, _ = no_trades_alert_payload(
    now,
    no_trades_hours=72,
    last_trade_time=None,
    robot_started_at=started,
    robot_active=True,
    trading_enabled=True,
    already_alerted_for=started,
  )
  assert send2 is False


def test_no_trades_alert_after_last_trade():
  from datetime import datetime, timedelta
  from tinkoff_bot.ops_automation import no_trades_alert_payload

  last = datetime(2026, 6, 1, 10, 0, 0)
  started = datetime(2026, 5, 1, 10, 0, 0)
  now = last + timedelta(hours=80)
  send, key, msg = no_trades_alert_payload(
    now,
    no_trades_hours=72,
    last_trade_time=last,
    robot_started_at=started,
    robot_active=True,
    trading_enabled=True,
    already_alerted_for=None,
  )
  assert send is True
  assert key == last
  assert "Нет сделок" in msg


def test_ensure_sandbox_funded_tops_up_delta_not_full_target(monkeypatch):
  from unittest.mock import MagicMock
  from tinkoff_bot.ops_automation import ensure_sandbox_funded

  monkeypatch.setenv("SANDBOX_TARGET_CASH", "100000")
  broker = MagicMock()
  # equity низкий (ниже 5% порога), cash близко к target — need < 1000
  broker.get_equity_snapshot.return_value = (3_000.0, 99_500.0, {})
  amounts = []
  broker.set_sandbox_balance = lambda amt, currency="RUB": amounts.append(amt)
  msg = ensure_sandbox_funded(broker, "RUB")
  assert amounts
  assert amounts[0] == 1000.0
  assert amounts[0] != 100_000.0
  assert msg is not None

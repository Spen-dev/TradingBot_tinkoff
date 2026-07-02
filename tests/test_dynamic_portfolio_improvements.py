"""Тесты улучшений dynamic portfolio: hysteresis, gate, sector, news trigger."""
from datetime import datetime, timedelta

from tinkoff_bot.advisor_ensemble import (
  apply_macro_quant_gate,
  compute_portfolio_turnover,
  pick_best_portfolio,
  score_all_proposals,
)
from tinkoff_bot.dynamic_portfolio import apply_min_hold, update_ticker_hold_since
from tinkoff_bot.market_data_client import CompositeMarketClient
from tinkoff_bot.ops_automation import should_refresh_portfolio_for_news
from tinkoff_bot.sector_map import enforce_sector_caps


class _FakeClient:
  configured = True

  def __init__(self, bars):
    self._bars = bars

  def get_daily_bars(self, ticker: str, days: int = 90):
    return self._bars.get(ticker.upper(), [])


def _bars(n=80, step=0.01):
  return [
    {"open": 100 + i, "high": 101 + i, "low": 99 + i, "close": 100 + i * step, "volume": 5000}
    for i in range(n)
  ]


def test_compute_portfolio_turnover():
  old = [{"ticker": "SBER", "target_weight": 0.5}, {"ticker": "LKOH", "target_weight": 0.5}]
  new = [{"ticker": "SBER", "target_weight": 0.25}, {"ticker": "GMKN", "target_weight": 0.75}]
  t = compute_portfolio_turnover(old, new)
  assert 0.7 < t < 0.8


def test_apply_min_hold_keeps_recent_ticker():
  old = [{"ticker": "SBER", "target_weight": 0.5}, {"ticker": "LKOH", "target_weight": 0.5}]
  new = [{"ticker": "GMKN", "target_weight": 1.0}]
  hold = {"SBER": (datetime.now() - timedelta(days=1)).isoformat()}
  merged = apply_min_hold(new, old, hold, min_hold_days=3, max_instruments=6)
  tickers = {s["ticker"] for s in merged}
  assert "SBER" in tickers


def test_enforce_sector_caps():
  sel = [
    {"ticker": "LKOH", "target_weight": 0.3},
    {"ticker": "ROSN", "target_weight": 0.3},
    {"ticker": "SBER", "target_weight": 0.4},
  ]
  out = enforce_sector_caps(sel, 0.40)
  oil = sum(x["target_weight"] for x in out if x["ticker"] in ("LKOH", "ROSN", "TATN", "NVTK"))
  assert oil <= 0.41
  assert sum(x["target_weight"] for x in out) <= 1.0 + 1e-6


def test_pick_best_hysteresis_keeps_previous():
  market = CompositeMarketClient(finam_client=_FakeClient({"SBER": _bars(), "LKOH": _bars()}))
  good = [{"ticker": "SBER", "target_weight": 0.6}, {"ticker": "LKOH", "target_weight": 0.4}]
  alt = [{"ticker": "SBER", "target_weight": 0.55}, {"ticker": "LKOH", "target_weight": 0.45}]
  proposals = [("finam", good, "a"), ("macro", alt, "b")]
  scores = score_all_proposals(proposals, market, history_days=80, ai_priority=False)
  name, _, _, _, _ = pick_best_portfolio(
    proposals,
    market,
    history_days=80,
    previous_source="finam",
    min_score_delta=10.0,
  )
  assert name == "finam"
  assert "finam" in scores


def test_macro_quant_gate_rejects_weak_macro():
  scores = {"macro": {"raw": -0.5, "adj": -0.5}, "finam": {"raw": 0.2, "adj": 0.2}}
  proposals = [
    ("macro", [{"ticker": "SBER", "target_weight": 1.0}], "m"),
    ("finam", [{"ticker": "LKOH", "target_weight": 1.0}], "f"),
  ]
  name, sel, _ = apply_macro_quant_gate("macro", proposals[0][1], "m", scores, proposals, epsilon=0.05)
  assert name == "finam"
  assert sel[0]["ticker"] == "LKOH"


def test_news_trigger_requires_keywords(tmp_path):
  from unittest.mock import patch

  class _Cfg:
    rss_urls = ["http://example.com/rss"]
    max_headlines_per_feed = 5
    max_headlines_total = 5
    max_age_days = 14
    cache_file = "data/macro_news_cache.json"
    request_timeout_seconds = 5

  state = tmp_path / "data" / "macro_news_fingerprint.json"
  state.parent.mkdir(parents=True)
  state.write_text('{"fingerprint": "aaaaaaaaaaaaaaaa", "headline_count": 1}', encoding="utf-8")

  with patch("tinkoff_bot.news_client.collect_macro_headlines") as mock_collect:
    mock_collect.return_value = [{"title": "Random sports news", "description": ""}]
    ok, reason = should_refresh_portfolio_for_news(
      _Cfg(),
      base_dir=tmp_path,
      trigger_keywords=["нефт", "ставк"],
      refresh_cooldown_days=0,
    )
  assert ok is False
  assert "keyword" in reason

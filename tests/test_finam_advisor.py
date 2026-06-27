"""Тесты Finam advisor и ensemble."""
from tinkoff_bot.finam_advisor import score_bars, select_portfolio_via_finam
from tinkoff_bot.advisor_ensemble import pick_best_portfolio, score_portfolio_proposal
from tinkoff_bot.market_data_client import CompositeMarketClient


class _FakeFinamClient:
  configured = True
  exchange_mic = "MISX"

  def __init__(self, bars_by_ticker: dict):
    self._bars = bars_by_ticker

  def get_daily_bars(self, ticker: str, days: int = 90):
    return self._bars.get(ticker.upper(), [])


def _rising_bars(n: int = 40, start: float = 100.0, step: float = 1.0):
  return [{"open": start + i * step, "high": start + i * step + 1, "low": start + i * step - 0.5, "close": start + i * step, "volume": 1000} for i in range(n)]


def _falling_bars(n: int = 40, start: float = 200.0, step: float = 1.0):
  return [{"open": start - i * step, "high": start - i * step + 0.5, "low": start - i * step - 1, "close": start - i * step, "volume": 1000} for i in range(n)]


def test_score_bars_rising_beats_falling():
  up = score_bars(_rising_bars())
  down = score_bars(_falling_bars())
  assert up["score"] > down["score"]
  assert up["return_20d"] > 0


def test_select_portfolio_via_finam_picks_leaders():
  client = _FakeFinamClient({
    "SBER": _rising_bars(50, 100, 2),
    "LKOH": _rising_bars(50, 200, 1),
    "GAZP": _falling_bars(50),
  })
  sel, summary = select_portfolio_via_finam(client, ["SBER", "LKOH", "GAZP"], 2, 3, 0.5)
  assert len(sel) >= 2
  tickers = {s["ticker"] for s in sel}
  assert "SBER" in tickers or "LKOH" in tickers
  weights = {s["ticker"]: s["target_weight"] for s in sel}
  if "GAZP" in weights and "SBER" in weights:
    assert weights["SBER"] >= weights["GAZP"]
  assert abs(sum(s["target_weight"] for s in sel) - 1.0) < 1e-6
  assert "Finam" in summary


def test_pick_best_portfolio_prefers_higher_sharpe():
  client = _FakeFinamClient({
    "SBER": _rising_bars(60, 100, 2.0),
    "LKOH": _rising_bars(60, 100, 1.8),
    "GMKN": _falling_bars(60, 300, 2.0),
  })
  market = CompositeMarketClient(finam_client=client)
  good = [{"ticker": "SBER", "target_weight": 0.6}, {"ticker": "LKOH", "target_weight": 0.4}]
  weak = [{"ticker": "GMKN", "target_weight": 1.0}]
  assert score_portfolio_proposal(market, good) > score_portfolio_proposal(market, weak)
  name, sel, msg, score = pick_best_portfolio(
    [("deepseek", weak, "ds"), ("finam", good, "fm")],
    market,
  )
  assert name == "finam"
  assert sel == good
  assert score > -1e8
  assert "finam" in msg.lower()

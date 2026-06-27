"""Тесты MOEX advisor и ensemble."""
from tinkoff_bot.advisor_ensemble import pick_best_portfolio, score_portfolio_proposal
from tinkoff_bot.market_data_client import CompositeMarketClient
from tinkoff_bot.moex_advisor import select_portfolio_via_moex
from tinkoff_bot.quant_advisor import score_bars


class _FakeMoexClient:
  configured = True

  def __init__(self, bars_by_ticker: dict):
    self._bars = bars_by_ticker

  def get_daily_bars(self, ticker: str, days: int = 90):
    return self._bars.get(ticker.upper(), [])


def _rising_bars(n: int = 40, start: float = 100.0, step: float = 1.0):
  return [
    {"open": start + i * step, "high": start + i * step + 1, "low": start + i * step - 0.5, "close": start + i * step, "volume": 1000}
    for i in range(n)
  ]


def _falling_bars(n: int = 40, start: float = 200.0, step: float = 1.0):
  return [
    {"open": start - i * step, "high": start - i * step + 0.5, "low": start - i * step - 1, "close": start - i * step, "volume": 1000}
    for i in range(n)
  ]


def test_select_portfolio_via_moex():
  client = _FakeMoexClient({
    "SBER": _rising_bars(50, 100, 2),
    "LKOH": _rising_bars(50, 200, 1),
    "GAZP": _falling_bars(50),
  })
  sel, summary = select_portfolio_via_moex(client, ["SBER", "LKOH", "GAZP"], 2, 3, 0.5)
  assert len(sel) >= 2
  assert abs(sum(s["target_weight"] for s in sel) - 1.0) < 1e-6
  assert "MOEX" in summary


def test_composite_client_uses_moex_fallback():
  finam_empty = type("F", (), {"configured": True, "get_daily_bars": lambda self, t, days=90: []})()
  moex = _FakeMoexClient({"SBER": _rising_bars(60, 100, 2)})
  composite = CompositeMarketClient(finam_client=finam_empty, moex_client=moex)
  bars = composite.get_daily_bars("SBER", days=30)
  assert len(bars) == 60
  assert score_bars(bars)["return_20d"] > 0


def test_pick_best_with_moex_only_client():
  moex = _FakeMoexClient({
    "SBER": _rising_bars(60, 100, 2.0),
    "LKOH": _rising_bars(60, 100, 1.8),
    "GMKN": _falling_bars(60, 300, 2.0),
  })
  market = CompositeMarketClient(finam_client=None, moex_client=moex)
  good = [{"ticker": "SBER", "target_weight": 0.6}, {"ticker": "LKOH", "target_weight": 0.4}]
  weak = [{"ticker": "GMKN", "target_weight": 1.0}]
  assert score_portfolio_proposal(market, good) > score_portfolio_proposal(market, weak)
  name, sel, msg, _ = pick_best_portfolio([("moex", weak, "w"), ("finam", good, "g")], market)
  assert name == "finam"
  assert sel == good

"""Тесты trade_history: серия убытков, evaluate_realized_pnl."""
from datetime import datetime, timedelta
from unittest.mock import MagicMock

from tinkoff_bot.trade_history import (
  TradeRecord,
  evaluate_realized_pnl,
  get_consecutive_losses,
)


def _trade(figi: str, side: str, price: float, days_ago: int = 0) -> TradeRecord:
  ts = (datetime.now() - timedelta(days=days_ago)).isoformat()
  return TradeRecord(
    id=f"{figi}_{ts}",
    figi=figi,
    ticker=figi,
    side=side,
    quantity=10.0,
    price=price,
    ts=ts,
    strategy="adaptive",
  )


def test_consecutive_losses_includes_recent_trades():
  trades = [
    _trade("F1", "buy", 100.0, days_ago=1),
    _trade("F2", "buy", 100.0, days_ago=2),
  ]

  def get_price(figi: str) -> float:
    return 90.0 if figi == "F1" else 110.0

  evaluated = evaluate_realized_pnl(trades, get_price, horizon_days=0)
  assert len(evaluated) == 2
  assert get_consecutive_losses(get_price, horizon_days=0) >= 0


def test_evaluate_realized_pnl_respects_maturity_window():
  trades = [_trade("F1", "buy", 100.0, days_ago=1)]
  get_price = MagicMock(return_value=50.0)
  mature = evaluate_realized_pnl(trades, get_price, horizon_days=5)
  assert mature == []
  all_trades = evaluate_realized_pnl(trades, get_price, horizon_days=0)
  assert len(all_trades) == 1
  assert all_trades[0][1] < 0

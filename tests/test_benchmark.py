from types import SimpleNamespace

import pandas as pd

from tinkoff_bot.benchmark import equal_weight_buy_hold_return


class _StubBroker:
  def get_historical_candles(self, figi, from_dt, to_dt):
    return pd.DataFrame({"close": [100.0, 101.0, 102.0, 105.0, 110.0]})


def test_equal_weight_buy_hold_return():
  inst = SimpleNamespace(figi="F1", ticker="SBER")
  out = equal_weight_buy_hold_return(_StubBroker(), [inst], days=30, commission_rate=0.0)
  assert out is not None
  ret, desc = out
  assert ret > 0.05
  assert "SBER" in desc

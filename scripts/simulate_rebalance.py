"""План заявок без исполнения (диагностика на сервере)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
  sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from t_tech.invest import OrderDirection

from tinkoff_bot.broker import TinkoffBroker
from tinkoff_bot.config import load_config
from tinkoff_bot.portfolio import PortfolioManager
from tinkoff_bot.risk import RiskManager


def main() -> int:
  cfg = load_config(str(ROOT / "config.yaml"))
  dp_path = ROOT / "data" / "dynamic_portfolio.json"
  if dp_path.exists():
    from tinkoff_bot.dynamic_portfolio import instruments_from_state

    inst = instruments_from_state(json.loads(dp_path.read_text(encoding="utf-8")))
    if inst:
      cfg.instruments = inst

  broker = TinkoffBroker(cfg.tinkoff)
  risk = RiskManager(cfg.risk)
  pm = PortfolioManager(cfg.portfolio, list(cfg.instruments), broker, risk)
  eq, cash, pos = broker.get_equity_snapshot(cfg.portfolio.base_currency)
  orders = pm.build_rebalance_orders(eq)
  tickers = [i.ticker for i in cfg.instruments]
  print(f"instruments ({len(tickers)}): {', '.join(tickers)}")
  print(f"equity={eq:.0f} cash={cash:.0f} positions={len(pos)} planned_orders={len(orders)}")
  for o in orders[:12]:
    side = "BUY" if o.direction == OrderDirection.ORDER_DIRECTION_BUY else "SELL"
    print(f"  {o.ticker} {side} qty={o.quantity} @ {o.execution_price:.2f}")
  return 0 if orders else 1


if __name__ == "__main__":
  raise SystemExit(main())

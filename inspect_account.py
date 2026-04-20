"""Быстрая проверка текущего sandbox/real счёта по TINKOFF_ACCOUNT_ID."""
from pathlib import Path

from tinkoff_bot.config import load_config
from tinkoff_bot.broker import TinkoffBroker


def main() -> None:
  base = Path(__file__).resolve().parent
  cfg = load_config(str(base / "config.yaml"))
  print(f"Mode: {getattr(cfg, 'mode', 'sandbox')}, use_sandbox={cfg.tinkoff.use_sandbox}")
  print(f"Account ID: {cfg.tinkoff.account_id}")
  print()

  broker = TinkoffBroker(cfg.tinkoff)
  equity, cash, positions = broker.get_equity_snapshot(currency=cfg.portfolio.base_currency)

  print(f"Equity (total_amount_portfolio − бумаги при согласованном снимке): {equity}")
  print(f"Cash (остаток): {cash}")
  if not positions:
    print("Positions: <none>")
  else:
    print("Positions:")
    for figi, p in positions.items():
      print(f"- {figi}: qty={p.quantity}, avg_price={p.average_price}, cur_price={p.current_price}, value={p.value}")

  print()
  print("Instruments (ticker, target_w, exch_lot, last_price):")
  for inst in cfg.instruments:
    lot = broker.get_lot_size(inst.figi)
    price = broker.get_last_price(inst.figi)
    print(f"- {inst.ticker}: w={inst.target_weight:.3f}, lot={lot}, price={price:.2f}")


if __name__ == "__main__":
  main()


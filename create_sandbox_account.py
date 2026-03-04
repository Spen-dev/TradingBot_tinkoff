#!/usr/bin/env python3
"""Создать новый счёт в песочнице Тинькофф и пополнить на указанную сумму (по умолчанию 100 000 ₽)."""
from pathlib import Path

from tinkoff.invest.sandbox.client import SandboxClient

from tinkoff_bot.config import load_config, TinkoffConfig
from tinkoff_bot.broker import TinkoffBroker


def main() -> None:
  base_dir = Path(__file__).resolve().parent
  cfg = load_config(str(base_dir / "config.yaml"))
  token = cfg.tinkoff.token
  if not token:
    raise SystemExit("В .env задайте TINKOFF_TOKEN (или token в config.yaml).")

  with SandboxClient(token) as client:
    opened = client.sandbox.open_sandbox_account()
    new_account_id = opened.account_id

  print(f"Создан новый счёт песочницы: {new_account_id}")

  tinkoff_cfg = TinkoffConfig(
    token=token,
    account_id=new_account_id,
    use_sandbox=True,
  )
  broker = TinkoffBroker(tinkoff_cfg)
  amount = 120_000.0
  broker.set_sandbox_balance(amount, "RUB")
  print(f"Пополнение на {amount:,.0f} RUB выполнено.")

  cash = broker.get_cash_balance("RUB")
  print(f"Баланс счёта: {cash:,.2f} RUB")

  print("\nЧтобы тестировать бота на этом счёте, в .env укажите:")
  print(f"  TINKOFF_ACCOUNT_ID={new_account_id}")
  print("  SANDBOX_TARGET_CASH=120000")


if __name__ == "__main__":
  main()

#!/usr/bin/env python3
"""Создать новый счёт в песочнице Тинькофф и пополнить (по умолчанию 120 000 ₽).

Сумма: аргумент --amount, иначе переменная SANDBOX_TARGET_CASH из .env, иначе 120000.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path

from dotenv import load_dotenv
from tinkoff.invest.sandbox.client import SandboxClient

from tinkoff_bot.config import load_config, TinkoffConfig
from tinkoff_bot.broker import TinkoffBroker


def main() -> None:
  load_dotenv()
  parser = argparse.ArgumentParser(description="Новый sandbox-счёт + пополнение RUB")
  parser.add_argument(
    "--amount",
    type=float,
    default=None,
    help="Сумма пополнения RUB (если не задано — SANDBOX_TARGET_CASH или 120000)",
  )
  args = parser.parse_args()

  base_dir = Path(__file__).resolve().parent
  cfg = load_config(str(base_dir / "config.yaml"))
  token = cfg.tinkoff.token
  if not token:
    raise SystemExit("В .env задайте TINKOFF_TOKEN (или token в config.yaml).")

  if args.amount is not None:
    amount = float(args.amount)
  else:
    raw = os.getenv("SANDBOX_TARGET_CASH", "120000").strip()
    try:
      amount = float(raw)
    except ValueError:
      amount = 120_000.0
  if amount <= 0:
    raise SystemExit("Сумма пополнения должна быть > 0")

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
  broker.set_sandbox_balance(amount, "RUB")
  print(f"Пополнение на {amount:,.0f} RUB выполнено.")

  cash = broker.get_cash_balance("RUB")
  print(f"Баланс счёта: {cash:,.2f} RUB")

  target_env = int(amount) if amount == int(amount) else amount
  print("\nЧтобы тестировать бота на этом счёте, в .env укажите:")
  print(f"  TINKOFF_ACCOUNT_ID={new_account_id}")
  print(f"  SANDBOX_TARGET_CASH={target_env}")


if __name__ == "__main__":
  main()

"""Сброс песочницы Тинькофф: очистка счетов через API + локальная история сделок и состояние в data/.

Использование:
  python reset_sandbox.py              # API + локальные файлы (только если в конфиге use_sandbox)
  python reset_sandbox.py --local-only # только data/trade_history.json и др. (без брокера)

После полного сброса выведите новый TINKOFF_ACCOUNT_ID в .env (см. вывод скрипта).
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path

from dotenv import load_dotenv
from tinkoff.invest.sandbox.client import SandboxClient

from tinkoff_bot.config import TinkoffConfig, load_config
from tinkoff_bot.broker import TinkoffBroker
from tinkoff_bot.equity_history import clear_equity_history
from tinkoff_bot.trade_history import clear_trade_history


def _clear_local_data(base_dir: Path) -> None:
  clear_trade_history()
  clear_equity_history()
  data = base_dir / "data"
  for name in (
    "last_trades.json",
    "position_peaks.json",
    "instrument_pause.json",
    "risk_state.json",
    "status_snapshot.json",
    "strategy_selection_state.json",
  ):
    p = data / name
    if p.exists():
      try:
        p.unlink()
        print(f"Удалён файл: {p.relative_to(base_dir)}")
      except OSError as e:
        print(f"Не удалось удалить {p}: {e}")
  print("Локальная история сделок (trade_history) и связанное состояние очищены.")


def main() -> None:
  load_dotenv()
  parser = argparse.ArgumentParser(description="Сброс sandbox-счёта и локальных сделок")
  parser.add_argument(
    "--local-only",
    action="store_true",
    help="Только очистить data/* (без запросов к API песочницы)",
  )
  args = parser.parse_args()

  base_dir = Path(__file__).resolve().parent
  cfg = load_config(str(base_dir / "config.yaml"))

  if args.local_only:
    _clear_local_data(base_dir)
    return

  if not cfg.tinkoff.use_sandbox:
    raise SystemExit(
      "В config.yaml tinkoff.use_sandbox=false — сброс брокерского счёта через этот скрипт не выполняется. "
      "Используйте --local-only, чтобы очистить только локальные файлы сделок."
    )

  token = (cfg.tinkoff.token or "").strip()
  if not token:
    raise SystemExit("Задайте токен Tinkoff в .env (TINKOFF_TOKEN) или config.yaml.")

  with SandboxClient(token) as client:
    # Актуальный SDK: список счетов — UsersService (get_sandbox_accounts помечен deprecated).
    # Метода clear_sandbox_account в SandboxService больше нет: позиции сбрасываются закрытием счёта.
    resp = client.users.get_accounts()
    accounts = list(resp.accounts or [])
    if not accounts:
      print("Sandbox-счетов нет — открываем новый.")
    else:
      print("Текущие sandbox-счета (закрытие):")
      for acc in accounts:
        print(f"- {acc.id} ({acc.name})")
      for acc in accounts:
        aid = acc.id
        try:
          client.sandbox.close_sandbox_account(account_id=aid)
          print(f"close_sandbox_account: {aid}")
        except Exception as e:
          print(f"close_sandbox_account failed for {aid}: {e}")

    opened = client.sandbox.open_sandbox_account()
    new_id = opened.account_id
    print(f"\nОткрыт новый счёт песочницы: {new_id}")

  raw = os.getenv("SANDBOX_TARGET_CASH", "120000").strip()
  try:
    amount = float(raw)
  except ValueError:
    amount = 120_000.0
  if amount > 0:
    tinkoff_cfg = TinkoffConfig(
      token=token,
      account_id=new_id,
      use_sandbox=True,
    )
    broker = TinkoffBroker(tinkoff_cfg)
    broker.set_sandbox_balance(amount, cfg.portfolio.base_currency or "RUB")
    print(f"Пополнение ~{amount:,.0f} {cfg.portfolio.base_currency or 'RUB'} выполнено (sandbox_pay_in).")

  _clear_local_data(base_dir)

  print("\nОбновите .env:")
  print(f"  TINKOFF_ACCOUNT_ID={new_id}")
  print(f"  SANDBOX_TARGET_CASH={int(amount) if amount == int(amount) else amount}")
  print("\nПерезапустите бота (docker compose restart / run_bot).")


if __name__ == "__main__":
  main()

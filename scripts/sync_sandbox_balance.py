"""Довести кэш sandbox до SANDBOX_TARGET_CASH (добавить разницу, без сброса счёта)."""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
  sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from tinkoff_bot.broker import TinkoffBroker
from tinkoff_bot.config import load_config


def main() -> int:
  cfg = load_config(str(ROOT / "config.yaml"))
  if not cfg.tinkoff.use_sandbox:
    print("use_sandbox=false — пропуск")
    return 0
  raw = os.getenv("SANDBOX_TARGET_CASH", "200000").strip()
  try:
    target = float(raw)
  except ValueError:
    print(f"Некорректный SANDBOX_TARGET_CASH={raw!r}")
    return 1
  if target <= 0:
    print("SANDBOX_TARGET_CASH <= 0 — пропуск")
    return 0

  broker = TinkoffBroker(cfg.tinkoff)
  currency = cfg.portfolio.base_currency or "RUB"
  equity, cash, positions = broker.get_equity_snapshot(currency=currency)
  print(f"equity={equity:.0f} cash={cash:.0f} positions={len(positions)} target={target:.0f}")

  if cash >= target - 1:
    print("Кэш уже на целевом уровне — пополнение не требуется")
    return 0

  need = target - cash
  if 0 < need < 1000:
    need = 1000.0
  broker.set_sandbox_balance(need, currency=currency)
  equity2, cash2, _ = broker.get_equity_snapshot(currency=currency)
  print(f"Пополнено +{need:.0f} {currency} → cash={cash2:.0f} equity={equity2:.0f}")
  return 0


if __name__ == "__main__":
  raise SystemExit(main())

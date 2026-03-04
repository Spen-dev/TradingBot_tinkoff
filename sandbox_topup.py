"""Пополнение песочницы и проверка баланса."""
from pathlib import Path

from tinkoff_bot.config import load_config
from tinkoff_bot.broker import TinkoffBroker

base = Path(__file__).resolve().parent
cfg = load_config(str(base / "config.yaml"))
b = TinkoffBroker(cfg.tinkoff)

b.set_sandbox_balance(100_000, "RUB")
print("Пополнение 100000 RUB отправлено")

cash = b.get_cash_balance("RUB")
print("Cash после пополнения:", cash)

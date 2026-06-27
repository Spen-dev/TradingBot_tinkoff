"""FIGI и лот по тикерам (для настройки config.yaml)."""
import os
from tinkoff.invest import Client

TICKERS = ["SBER", "LKOH", "GMKN", "PLZL", "MGNT", "TATN", "MOEX"]

with Client(os.environ["TINKOFF_TOKEN"]) as client:
    shares = {i.ticker: i for i in client.instruments.shares().instruments}
    for t in TICKERS:
        i = shares.get(t)
        if i:
            print(f"{t}\t{i.figi}\tlot={i.lot}")
        else:
            print(f"{t}\tNOT_FOUND")

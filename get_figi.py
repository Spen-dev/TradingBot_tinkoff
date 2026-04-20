"""Получить FIGI по тикеру через Tinkoff API."""
import os
from pathlib import Path

from dotenv import load_dotenv
from tinkoff.invest import Client

load_dotenv(Path(__file__).resolve().parent / ".env")
TOKEN = os.getenv("TINKOFF_TOKEN")

TICKERS = ["TCS", "MOEX", "AFLT", "MVID", "MTSS", "RUAL", "IRAO", "AFKS"]


def main():
    with Client(TOKEN) as client:
        instruments = client.instruments.shares()
        by_ticker = {i.ticker: i for i in instruments.instruments}
        for t in TICKERS:
            if t in by_ticker:
                i = by_ticker[t]
                print(f"{t}: {i.figi}")
            else:
                print(f"{t}: NOT FOUND")


if __name__ == "__main__":
    main()

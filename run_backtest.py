#!/usr/bin/env python3
"""Бэктест стратегий по истории без реальных заявок.

Для каждого инструмента:
- подгружает дневные свечи за N дней
- прогоняет текущую стратегию и параметры
- считает PnL, max drawdown, Sharpe и число сделок.
"""
from __future__ import annotations

import argparse
from pathlib import Path
from datetime import datetime, timedelta

from tinkoff_bot.config import load_config
from tinkoff_bot.broker import TinkoffBroker
from tinkoff_bot.learned_params import load_learned_params
from tinkoff_bot.self_learn import (
  _get_signals_for_df,
  _simulate_pnl_and_dd,
  _compute_sharpe,
  instrument_config_for_historical_signals,
)


def main() -> None:
  parser = argparse.ArgumentParser(description="Backtest strategies on historical data")
  parser.add_argument("--days", type=int, default=180, help="History window in days")
  parser.add_argument("--figi", type=str, default=None, help="Test only this FIGI")
  args = parser.parse_args()

  base_dir = Path(__file__).resolve().parent
  cfg = load_config(str(base_dir / "config.yaml"))
  broker = TinkoffBroker(cfg.tinkoff)
  commission = getattr(cfg.portfolio, "commission_rate", 0.0003) or 0.0003

  to_dt = datetime.now()
  from_dt = to_dt - timedelta(days=args.days)

  print(f"Окно бэктеста: {from_dt.date()} .. {to_dt.date()} ({args.days} дней)")
  print(f"Комиссия: {commission:.5f}")
  learned = load_learned_params()
  print("(учтён learned_params; deepseek → суррогат для симуляции)")
  print()

  rows = []
  for inst in cfg.instruments:
    if args.figi and inst.figi != args.figi:
      continue
    try:
      df = broker.get_historical_candles(inst.figi, from_dt, to_dt)
    except Exception as e:
      print(f"{inst.ticker}: error loading candles: {e}")
      continue
    if df is None or len(df) < 40:
      print(f"{inst.ticker}: not enough candles ({0 if df is None else len(df)})")
      continue
    try:
      inst_bt, used_surrogate = instrument_config_for_historical_signals(inst, learned)
      signals = _get_signals_for_df(broker, inst_bt, df, params_override={})
      pnl, max_dd, n_trades, daily_returns = _simulate_pnl_and_dd(df, signals, commission_rate=commission)
      sharpe = _compute_sharpe(daily_returns)
      rows.append((inst.ticker, pnl, max_dd, sharpe, n_trades, used_surrogate))
    except Exception as e:
      print(f"{inst.ticker}: backtest error: {e}")
      continue

  if not rows:
    print("No instruments could be backtested.")
    return

  print("Тикер   Доходн. %   Макс. просадка %   Коэфф. Шарпа   Сделок  Прим.")
  print("-----   ---------   ---------------   -------------   ------  -----")
  for ticker, pnl, max_dd, sharpe, n_trades, used_surrogate in rows:
    pnl_pct = pnl * 100
    dd_pct = max_dd * 100
    note = "суррогат" if used_surrogate else ""
    print(f"{ticker:5}  {pnl_pct:9.2f}  {dd_pct:15.2f}  {sharpe:13.2f}  {n_trades:7d}  {note}")


if __name__ == "__main__":
  main()

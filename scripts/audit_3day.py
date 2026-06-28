"""Трёхдневный аудит на баги (логи + живой портфель).

  python scripts/audit_3day.py
  python scripts/audit_3day.py --days 3 --save
  python scripts/audit_3day.py --live
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
  sys.path.insert(0, str(ROOT))


def main() -> int:
  parser = argparse.ArgumentParser(description="Аудит бота за N дней")
  parser.add_argument("--days", type=int, default=3, help="Глубина окна (дней)")
  parser.add_argument("--save", action="store_true", help="Сохранить отчёт в data/bug_audit/")
  parser.add_argument("--live", action="store_true", help="Проверить портфель через брокера")
  parser.add_argument("--drift-pct", type=float, default=0.05, help="Порог дрейфа весов")
  args = parser.parse_args()

  from dotenv import load_dotenv
  load_dotenv(ROOT / ".env")

  from tinkoff_bot.bug_audit import format_audit_report, run_bug_audit, save_audit_report

  broker = None
  instruments = None
  currency = "RUB"
  if args.live:
    from tinkoff_bot.config import load_config
    from tinkoff_bot.broker import TinkoffBroker

    cfg = load_config(str(ROOT / "config.yaml"))
    broker = TinkoffBroker(cfg.tinkoff)
    instruments = cfg.instruments
    currency = cfg.portfolio.base_currency

  report = run_bug_audit(
    ROOT,
    days=max(1, args.days),
    drift_pct=args.drift_pct,
    broker=broker,
    instruments=instruments,
    currency=currency,
  )
  text = format_audit_report(report)
  print(text)
  if args.save:
    path = save_audit_report(ROOT, report)
    print(f"\nСохранено: {path}")
  return 0 if report.ok else 1


if __name__ == "__main__":
  raise SystemExit(main())

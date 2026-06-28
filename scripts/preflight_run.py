"""Preflight перед длинным прогоном: API, lock наблюдения, дрейф портфеля.

  docker compose exec -T bot python scripts/preflight_run.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
  sys.path.insert(0, str(ROOT))


def main() -> int:
  from dotenv import load_dotenv

  load_dotenv(ROOT / ".env")

  from tinkoff_bot.bug_audit import compute_portfolio_drift, run_bug_audit, save_audit_report
  from tinkoff_bot.config import load_config, validate_config

  import importlib.util
  spec = importlib.util.spec_from_file_location("check_apis", ROOT / "scripts" / "check_apis.py")
  check_apis = importlib.util.module_from_spec(spec)
  assert spec.loader is not None
  spec.loader.exec_module(check_apis)

  cfg = load_config(str(ROOT / "config.yaml"))
  ok_cfg, errs = validate_config(cfg)
  instruments = list(cfg.instruments)
  dp_path = ROOT / "data" / "dynamic_portfolio.json"
  if dp_path.exists():
    try:
      from tinkoff_bot.dynamic_portfolio import instruments_from_state

      dp_inst = instruments_from_state(json.loads(dp_path.read_text(encoding="utf-8")))
      if dp_inst:
        instruments = dp_inst
    except Exception:
      pass
  print("=== Config ===")
  print("OK" if ok_cfg else "FAIL")
  for e in errs:
    print(f"  - {e}")

  lock_path = ROOT / "data" / "observation_lock.json"
  print("\n=== Observation lock ===")
  if lock_path.exists():
    try:
      lock = json.loads(lock_path.read_text(encoding="utf-8"))
      print(f"started_at: {lock.get('started_at')}, audit_days: {lock.get('audit_days', 3)}")
    except Exception as e:
      print(f"FAIL read lock: {e}")
  else:
    print("MISSING — выполните: python scripts/prepare_observation_start.py")

  print("\n=== APIs ===")
  api_code = check_apis.main()

  broker = None
  drift_note = ""
  planned_orders = 0
  trading_today = True
  try:
    from datetime import datetime

    from zoneinfo import ZoneInfo

    tz_name = (getattr(cfg.portfolio, "trading_timezone", None) or "").strip() or "Europe/Moscow"
    today = datetime.now(ZoneInfo(tz_name)).date()
    trading_today = cfg.portfolio.is_rebalance_trading_day(today)
  except Exception:
    pass
  try:
    from tinkoff_bot.broker import TinkoffBroker
    from tinkoff_bot.portfolio import PortfolioManager
    from tinkoff_bot.risk import RiskManager

    broker = TinkoffBroker(cfg.tinkoff)
    equity, cash, positions = broker.get_equity_snapshot(cfg.portfolio.base_currency)
    pm = PortfolioManager(cfg.portfolio, instruments, broker, RiskManager(cfg.risk))
    planned_orders = len(pm.build_rebalance_orders(equity))
    rows, max_dev = compute_portfolio_drift(
      equity, cash, instruments, positions,
      drift_pct=float(getattr(cfg.portfolio, "rebalance_drift_pct", 0.05) or 0.05),
    )
    print("\n=== Portfolio ===")
    print(f"equity={equity:.0f} cash={cash:.0f} positions={len(positions)} max_drift={max_dev:.1%}")
    print(f"trading_day_today={trading_today} planned_orders={planned_orders}")
    if rows:
      for r in rows[:6]:
        print(f"  {r['ticker']}: {r['target_pct']:.1f}% -> {r['current_pct']:.1f}% ({r['dev_pct']:+.1f}%)")
    if len(positions) == 0 and equity > 1000 and max_dev >= 0.05:
      if not trading_today and planned_orders > 0:
        drift_note = (
          f"OK: выходной MOEX — позиции появятся после ребаланса "
          f"(запланировано {planned_orders} заявок)"
        )
      else:
        drift_note = "WARN: цели есть, позиций нет — проверьте ребаланс и bot.log"
      print(f"\n{drift_note}")
  except Exception as e:
    print(f"\n=== Portfolio ===\nSKIP: {e}")

  report = run_bug_audit(
    ROOT,
    days=1,
    drift_pct=float(getattr(cfg.portfolio, "rebalance_drift_pct", 0.05) or 0.05),
    broker=broker,
    instruments=instruments if broker else None,
    currency=cfg.portfolio.base_currency,
  )
  save_audit_report(ROOT, report)
  crit = [f for f in report.findings if f.severity == "critical"]
  if not trading_today and planned_orders > 0:
    crit = [f for f in crit if f.code not in ("DRIFT_NOT_HELD", "PORTFOLIO_ALL_CASH")]
  print("\n=== Audit (1d) ===")
  if crit:
    for f in crit:
      print(f"  CRIT [{f.code}] {f.message}")
  else:
    print("  no critical findings")

  lock_ok = lock_path.exists()
  failed = (not ok_cfg) or api_code != 0 or bool(crit) or not lock_ok
  if drift_note.startswith("WARN:"):
    failed = True
  print("\n=== Result ===")
  if not lock_ok:
    print("NO-GO (нет observation_lock — prepare_observation_start.py)")
  elif failed:
    print("NO-GO")
  else:
    print("GO")
  return 1 if failed else 0


if __name__ == "__main__":
  raise SystemExit(main())

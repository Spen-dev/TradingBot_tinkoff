from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

from tinkoff_bot.bug_audit import (
  compute_portfolio_drift,
  format_audit_report,
  observation_audit_due,
  observation_final_audit_due,
  run_bug_audit,
  save_audit_report,
)


def test_compute_portfolio_drift_empty_positions():
  class Inst:
    def __init__(self, figi, ticker, w):
      self.figi = figi
      self.ticker = ticker
      self.target_weight = w

  instruments = [Inst("F1", "MTSS", 0.231), Inst("F2", "SBER", 0.18)]
  rows, max_dev = compute_portfolio_drift(100_000, 100_000, instruments, {}, drift_pct=0.05)
  assert rows[0]["ticker"] == "MTSS"
  assert rows[0]["dev_pct"] == -23.1
  assert max_dev >= 0.23


def test_run_bug_audit_rebalance_stuck(tmp_path: Path):
  logs = tmp_path / "data" / "logs"
  logs.mkdir(parents=True)
  since = datetime.now() - timedelta(hours=2)
  ts = since.isoformat(timespec="seconds")
  (logs / "rebalance_decisions.log").write_text(
    f"# {ts} equity=100000 RUB\n\n"
    "  MTSS: strategy=adaptive signal=hold target=23000 current=0\n\n"
    f"# {(since + timedelta(hours=1)).isoformat(timespec='seconds')} equity=100000 RUB\n\n"
    "  MTSS: strategy=adaptive signal=hold target=23000 current=0\n\n",
    encoding="utf-8",
  )
  report = run_bug_audit(tmp_path, days=1, since=since - timedelta(minutes=1))
  codes = {f.code for f in report.findings}
  assert "REBALANCE_STUCK" in codes


def test_run_bug_audit_all_cash_history(tmp_path: Path):
  hist = tmp_path / "data" / "equity_history.jsonl"
  hist.parent.mkdir(parents=True)
  since = datetime.now() - timedelta(hours=1)
  lines = []
  for i in range(12):
    ts = (since + timedelta(minutes=i * 5)).isoformat()
    lines.append(json.dumps({"ts": ts, "equity": 100000, "cash": 99000, "positions": 0}))
  hist.write_text("\n".join(lines) + "\n", encoding="utf-8")
  report = run_bug_audit(tmp_path, days=1, since=since - timedelta(minutes=1))
  assert any(f.code == "PORTFOLIO_ALL_CASH" for f in report.findings)


def test_observation_audit_window(tmp_path: Path):
  lock = tmp_path / "data" / "observation_lock.json"
  lock.parent.mkdir(parents=True)
  started = datetime.now() - timedelta(days=1)
  lock.write_text(
    json.dumps({"started_at": started.isoformat(), "audit_days": 3}),
    encoding="utf-8",
  )
  due, days, _ = observation_audit_due(tmp_path)
  assert due is True
  assert days == 3
  assert observation_final_audit_due(tmp_path, now=started + timedelta(days=2)) is True


def test_format_and_save(tmp_path: Path):
  report = run_bug_audit(tmp_path, days=1)
  text = format_audit_report(report)
  assert "Аудит" in text
  path = save_audit_report(tmp_path, report)
  assert path.exists()
  assert (tmp_path / "data" / "bug_audit" / "latest.json").exists()

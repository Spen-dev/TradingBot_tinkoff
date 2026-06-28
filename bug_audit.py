"""Трёхдневный аудит на баги: логи, ребаланс, дрейф портфеля, алерты."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

DEFAULT_AUDIT_DAYS = 3
AUDIT_STATE_DIR = "data/bug_audit"
OBSERVATION_LOCK = "data/observation_lock.json"

_LOG_TS_RE = re.compile(
  r"^(\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2})"
)
_ISO_TS_RE = re.compile(
  r"^#?\s*(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})"
)


@dataclass
class AuditFinding:
  severity: str  # critical | warning | info
  code: str
  message: str
  details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AuditReport:
  days: int
  window_start: str
  window_end: str
  findings: List[AuditFinding] = field(default_factory=list)
  stats: Dict[str, Any] = field(default_factory=dict)

  @property
  def ok(self) -> bool:
    return not any(f.severity == "critical" for f in self.findings)

  @property
  def has_warnings(self) -> bool:
    return any(f.severity == "warning" for f in self.findings)


def _parse_ts(raw: str) -> Optional[datetime]:
  text = (raw or "").strip()[:26].replace(" ", "T")
  if not text:
    return None
  try:
    return datetime.fromisoformat(text)
  except ValueError:
    pass
  try:
    return datetime.strptime(text[:19], "%Y-%m-%dT%H:%M:%S")
  except ValueError:
    return None


def _line_in_window(line: str, since: datetime) -> bool:
  m = _LOG_TS_RE.match(line) or _ISO_TS_RE.match(line.strip())
  if not m:
    return True
  ts = _parse_ts(m.group(1))
  return ts is None or ts >= since


def _read_lines(path: Path) -> List[str]:
  if not path.exists():
    return []
  try:
    return path.read_text(encoding="utf-8", errors="replace").splitlines()
  except OSError:
    return []


def _count_log_levels(log_path: Path, since: datetime) -> Dict[str, int]:
  counts = {"ERROR": 0, "CRITICAL": 0, "WARNING": 0}
  for line in _read_lines(log_path):
    if not _line_in_window(line, since):
      continue
    for level in counts:
      if f" {level} " in line or line.endswith(f" {level}"):
        counts[level] += 1
        break
  return counts


def _count_watchdog_exits(log_path: Path, since: datetime) -> int:
  n = 0
  for line in _read_lines(log_path):
    if not _line_in_window(line, since):
      continue
    low = line.lower()
    if "watchdog" in low and ("выход" in low or "exit" in low or "restart" in low):
      n += 1
  return n


def _parse_rebalance_blocks(text: str, since: datetime) -> List[Dict[str, Any]]:
  blocks: List[Dict[str, Any]] = []
  current: Dict[str, Any] | None = None
  for line in text.splitlines():
    if line.startswith("# "):
      ts = _parse_ts(line[2:].split(" equity=", 1)[0].strip())
      if ts and ts >= since:
        if current:
          blocks.append(current)
        current = {"ts": ts.isoformat(), "entries": [], "orders": 0}
      elif current:
        current = None
      continue
    if current is None:
      continue
    stripped = line.strip()
    if stripped.startswith("ORDER "):
      current["orders"] += 1
    elif ": strategy=" in stripped and " target=" in stripped:
      m = re.match(
        r"\s*(\w+): strategy=\S+ signal=\S+ target=([\d.]+) current=([\d.]+)",
        stripped,
      )
      if m:
        current["entries"].append({
          "ticker": m.group(1),
          "target": float(m.group(2)),
          "current": float(m.group(3)),
        })
  if current:
    blocks.append(current)
  return blocks


def _count_audit_places(audit_path: Path, since: datetime) -> int:
  n = 0
  for line in _read_lines(audit_path):
    if not line.startswith("20"):
      continue
    ts = _parse_ts(line.split("\t", 1)[0])
    if ts is None or ts < since:
      continue
    parts = line.split("\t")
    if len(parts) >= 2 and parts[1] == "place":
      n += 1
  return n


def _scan_alerts(alerts_path: Path, since: datetime) -> Dict[str, int]:
  keys = {
    "config_error": 0,
    "trading_blocked": 0,
    "dynamic_fallback": 0,
    "rebalance_drift_error": 0,
    "watchdog": 0,
  }
  for line in _read_lines(alerts_path):
    if not _line_in_window(line, since):
      continue
    low = line.lower()
    for key in keys:
      if key in low:
        keys[key] += 1
  return keys


def _equity_history_stats(hist_path: Path, since: datetime) -> Dict[str, Any]:
  points: List[Dict[str, Any]] = []
  for line in _read_lines(hist_path):
    try:
      row = json.loads(line)
    except json.JSONDecodeError:
      continue
    ts = _parse_ts(str(row.get("ts", "")))
    if ts is None or ts < since:
      continue
    equity = float(row.get("equity") or 0)
    cash = float(row.get("cash") or 0)
    pos = int(row.get("positions") or 0)
    points.append({
      "ts": ts.isoformat(),
      "equity": equity,
      "cash_ratio": (cash / equity) if equity > 0 else 0.0,
      "positions": pos,
    })
  if not points:
    return {"points": 0}
  cash_ratios = [p["cash_ratio"] for p in points if p["equity"] > 0]
  pos_counts = [p["positions"] for p in points]
  return {
    "points": len(points),
    "avg_cash_ratio": sum(cash_ratios) / len(cash_ratios) if cash_ratios else 0.0,
    "max_cash_ratio": max(cash_ratios) if cash_ratios else 0.0,
    "avg_positions": sum(pos_counts) / len(pos_counts) if pos_counts else 0.0,
    "max_positions": max(pos_counts) if pos_counts else 0,
  }


def compute_portfolio_drift(
  equity: float,
  cash: float,
  instruments: Sequence[Any],
  positions: Dict[str, Any],
  *,
  drift_pct: float = 0.05,
) -> Tuple[List[Dict[str, Any]], float]:
  """Отклонения по инструментам: [{ticker, target_pct, current_pct, dev_pct}]."""
  if equity <= 0:
    return [], 0.0
  rows: List[Dict[str, Any]] = []
  max_dev = 0.0
  for inst in instruments:
    w = float(getattr(inst, "target_weight", 0.0) or 0.0)
    target_pct = w * 100.0
    figi = getattr(inst, "figi", "")
    ticker = getattr(inst, "ticker", figi)
    pos = positions.get(figi)
    cur_val = float(getattr(pos, "value", 0.0) or 0.0) if pos else 0.0
    cur_pct = cur_val / equity * 100.0
    dev = cur_pct - target_pct
    max_dev = max(max_dev, abs(dev / 100.0))
    if abs(dev) >= drift_pct * 100.0 or target_pct >= 1.0:
      rows.append({
        "ticker": ticker,
        "target_pct": round(target_pct, 1),
        "current_pct": round(cur_pct, 1),
        "dev_pct": round(dev, 1),
      })
  rows.sort(key=lambda r: abs(r["dev_pct"]), reverse=True)
  return rows, max_dev


def load_observation_audit_window(base_dir: Path) -> Tuple[Optional[datetime], int]:
  lock_path = base_dir / OBSERVATION_LOCK
  if not lock_path.exists():
    return None, DEFAULT_AUDIT_DAYS
  try:
    data = json.loads(lock_path.read_text(encoding="utf-8"))
  except Exception:
    return None, DEFAULT_AUDIT_DAYS
  started = _parse_ts(str(data.get("started_at", "")))
  days = int(data.get("audit_days") or DEFAULT_AUDIT_DAYS)
  return started, max(1, days)


def run_bug_audit(
  base_dir: Path,
  *,
  days: int = DEFAULT_AUDIT_DAYS,
  since: Optional[datetime] = None,
  drift_pct: float = 0.05,
  broker: Any = None,
  instruments: Optional[Sequence[Any]] = None,
  currency: str = "RUB",
) -> AuditReport:
  """Аудит за последние `days` суток по логам и (опционально) живому портфелю."""
  now = datetime.now()
  window_start = since or (now - timedelta(days=days))
  data_dir = base_dir / "data"
  logs_dir = data_dir / "logs"

  stats: Dict[str, Any] = {}
  findings: List[AuditFinding] = []

  bot_log = logs_dir / "bot.log"
  log_counts = _count_log_levels(bot_log, window_start)
  stats["log_levels"] = log_counts
  if log_counts["CRITICAL"] > 0:
    findings.append(AuditFinding(
      "critical", "LOG_CRITICAL",
      f"CRITICAL в bot.log: {log_counts['CRITICAL']}",
      log_counts,
    ))
  elif log_counts["ERROR"] >= 5:
    findings.append(AuditFinding(
      "warning", "LOG_ERRORS",
      f"Много ERROR в bot.log: {log_counts['ERROR']}",
      log_counts,
    ))

  wd = _count_watchdog_exits(bot_log, window_start)
  stats["watchdog_exits"] = wd
  if wd > 0:
    findings.append(AuditFinding(
      "critical" if wd >= 2 else "warning",
      "WATCHDOG_RESTART",
      f"Watchdog перезапускал процесс: {wd} раз(а)",
      {"count": wd},
    ))

  rebalance_path = logs_dir / "rebalance_decisions.log"
  blocks = _parse_rebalance_blocks(rebalance_path.read_text(encoding="utf-8", errors="replace"), window_start) if rebalance_path.exists() else []
  stats["rebalance_cycles"] = len(blocks)
  stuck_cycles = 0
  for block in blocks:
    needs_buy = any(e["target"] > 1000 and e["current"] < e["target"] * 0.1 for e in block["entries"])
    if needs_buy and block["orders"] == 0:
      stuck_cycles += 1
  stats["rebalance_stuck_cycles"] = stuck_cycles
  if stuck_cycles >= 2:
    findings.append(AuditFinding(
      "critical", "REBALANCE_STUCK",
      f"Ребаланс {stuck_cycles} раз(а) не выставил заявки при большом дрейфе (target≫current)",
      {"cycles": stuck_cycles},
    ))
  elif stuck_cycles == 1:
    findings.append(AuditFinding(
      "warning", "REBALANCE_STUCK",
      "Один цикл ребаланса без заявок при target≫current",
      {"cycles": 1},
    ))

  places = _count_audit_places(data_dir / "audit_orders.log", window_start)
  stats["orders_placed"] = places
  hours = max(1, int((now - window_start).total_seconds() // 3600))
  if places == 0 and hours >= 48 and blocks:
    findings.append(AuditFinding(
      "warning", "NO_TRADES",
      f"За {days} дн. нет исполненных заявок (audit_orders), но ребаланс считался",
      {"hours": hours, "rebalance_cycles": len(blocks)},
    ))

  alert_stats = _scan_alerts(data_dir / "alerts.log", window_start)
  stats["alerts"] = alert_stats
  if alert_stats["config_error"] > 0:
    findings.append(AuditFinding(
      "critical", "CONFIG_ERROR",
      f"Алерты config_error: {alert_stats['config_error']}",
      alert_stats,
    ))
  if alert_stats["trading_blocked"] >= 3:
    findings.append(AuditFinding(
      "warning", "TRADING_BLOCKED",
      f"Частые блокировки торговли: {alert_stats['trading_blocked']}",
      alert_stats,
    ))
  if alert_stats["dynamic_fallback"] >= 2:
    findings.append(AuditFinding(
      "warning", "DYNAMIC_FALLBACK",
      f"Dynamic portfolio часто уходит в fallback: {alert_stats['dynamic_fallback']}",
      alert_stats,
    ))

  eq_stats = _equity_history_stats(data_dir / "equity_history.jsonl", window_start)
  stats["equity_history"] = eq_stats
  if eq_stats.get("points", 0) >= 10:
    if eq_stats.get("max_cash_ratio", 0) > 0.85 and eq_stats.get("max_positions", 0) == 0:
      findings.append(AuditFinding(
        "critical", "PORTFOLIO_ALL_CASH",
        "Портфель почти целиком в кеше при нулевых позициях (история equity)",
        eq_stats,
      ))
    elif eq_stats.get("avg_cash_ratio", 0) > 0.7 and eq_stats.get("avg_positions", 0) < 1:
      findings.append(AuditFinding(
        "warning", "PORTFOLIO_MOSTLY_CASH",
        "Средняя доля кеша >70% при отсутствии позиций",
        eq_stats,
      ))

  if broker is not None and instruments:
    try:
      equity, cash, positions = broker.get_equity_snapshot(currency=currency)
      drift_rows, max_dev = compute_portfolio_drift(
        equity, cash, instruments, positions, drift_pct=drift_pct,
      )
      stats["live"] = {
        "equity": round(equity, 2),
        "cash": round(cash, 2),
        "cash_ratio": round(cash / equity, 3) if equity > 0 else 0.0,
        "positions_count": len(positions),
        "max_drift": round(max_dev, 3),
        "top_drift": drift_rows[:6],
      }
      total_target = sum(float(getattr(i, "target_weight", 0) or 0) for i in instruments)
      if total_target > 0.5 and max_dev >= drift_pct and len(positions) == 0 and equity > 1000:
        top = ", ".join(
          f"{r['ticker']} {r['target_pct']:.0f}%→{r['current_pct']:.0f}%"
          for r in drift_rows[:4]
        )
        findings.append(AuditFinding(
          "critical", "DRIFT_NOT_HELD",
          f"Цели заданы, позиций нет, дрейф до {max_dev:.0%}: {top}",
          stats["live"],
        ))
      elif max_dev >= drift_pct:
        findings.append(AuditFinding(
          "warning", "PORTFOLIO_DRIFT",
          f"Дрейф весов до {max_dev:.0%} (порог {drift_pct:.0%})",
          {"top": drift_rows[:6]},
        ))
    except Exception as e:
      findings.append(AuditFinding(
        "info", "LIVE_CHECK_SKIPPED",
        f"Не удалось проверить живой портфель: {e}",
      ))

  return AuditReport(
    days=days,
    window_start=window_start.isoformat(),
    window_end=now.isoformat(),
    findings=findings,
    stats=stats,
  )


def format_audit_report(report: AuditReport, *, title: str = "Аудит на баги") -> str:
  lines = [
    f"🔍 {title} ({report.days} дн.)",
    f"Окно: {report.window_start[:16]} — {report.window_end[:16]}",
  ]
  if not report.findings:
    lines.append("✅ Замечаний нет.")
  else:
    icon = {"critical": "🔴", "warning": "🟡", "info": "ℹ️"}
    for f in report.findings:
      lines.append(f"{icon.get(f.severity, '•')} [{f.code}] {f.message}")
  stats = report.stats
  if stats.get("orders_placed") is not None:
    lines.append(
      f"\nСтатистика: заявок {stats.get('orders_placed', 0)}, "
      f"ребалансов {stats.get('rebalance_cycles', 0)}, "
      f"ERROR {stats.get('log_levels', {}).get('ERROR', 0)}"
    )
  live = stats.get("live")
  if live:
    lines.append(
      f"Сейчас: equity {live.get('equity', 0):.0f}, "
      f"кеш {live.get('cash_ratio', 0):.0%}, "
      f"позиций {live.get('positions_count', 0)}"
    )
  lines.append("✅ OK" if report.ok else "❌ Есть критические замечания")
  return "\n".join(lines)


def save_audit_report(base_dir: Path, report: AuditReport) -> Path:
  out_dir = base_dir / AUDIT_STATE_DIR
  out_dir.mkdir(parents=True, exist_ok=True)
  stamp = datetime.now().strftime("%Y-%m-%d")
  payload = {
    **asdict(report),
    "ok": report.ok,
    "saved_at": datetime.now().isoformat(),
  }
  day_path = out_dir / f"{stamp}.json"
  day_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
  latest = out_dir / "latest.json"
  latest.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
  return day_path


def observation_audit_due(
  base_dir: Path,
  *,
  audit_days: int = DEFAULT_AUDIT_DAYS,
  now: Optional[datetime] = None,
) -> Tuple[bool, int, Optional[datetime]]:
  """True если период наблюдения активен и аудит ещё не завершён."""
  started, days = load_observation_audit_window(base_dir)
  days = audit_days or days
  if started is None:
    return False, days, None
  now = now or datetime.now()
  elapsed = (now - started).days
  if elapsed >= days:
    return False, days, started
  return True, days, started


def observation_final_audit_due(
  base_dir: Path,
  *,
  audit_days: int = DEFAULT_AUDIT_DAYS,
  now: Optional[datetime] = None,
) -> bool:
  """True в день финального отчёта (день N после старта наблюдения)."""
  started, days = load_observation_audit_window(base_dir)
  days = audit_days or days
  if started is None:
    return False
  now = now or datetime.now()
  return (now.date() - started.date()).days == days - 1

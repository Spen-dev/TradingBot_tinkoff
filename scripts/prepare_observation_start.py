"""Подготовка к периоду наблюдения: baseline, бэкап и сброс learned_params (один раз).

  python scripts/prepare_observation_start.py              # baseline + lock, если ещё не было
  python scripts/prepare_observation_start.py --reset-learned  # + очистка learned_params
  python scripts/prepare_observation_start.py --force      # повторить даже при lock
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
  sys.path.insert(0, str(ROOT))

LOCK_FILE = ROOT / "data" / "observation_lock.json"
BASELINE_FILE = ROOT / "data" / "observation_baseline.json"
LEARNED_FILE = ROOT / "learned_params" / "params.json"
RISK_STATE_FILE = ROOT / "data" / "risk_state.json"
BACKUP_DIR = ROOT / "data" / "backups"


def _git_rev() -> str:
  try:
    return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, text=True).strip()
  except Exception:
    return ""


def _sync_risk_state_to_equity(equity: float) -> None:
  """Синхронизировать max_equity/daily baseline с equity наблюдения (deploy без полного reset)."""
  data: dict = {}
  if RISK_STATE_FILE.exists():
    try:
      data = json.loads(RISK_STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
      pass
  data["max_equity_seen"] = equity
  data["daily_equity_start"] = equity
  data["daily_equity_date"] = datetime.now().strftime("%Y-%m-%d")
  RISK_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
  RISK_STATE_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
  parser = argparse.ArgumentParser(description="Старт периода наблюдения sandbox")
  parser.add_argument("--reset-learned", action="store_true", help="Бэкап и очистка learned_params/params.json")
  parser.add_argument("--force", action="store_true", help="Выполнить даже если observation_lock уже есть")
  parser.add_argument(
    "--update-baseline-only",
    action="store_true",
    help="Только обновить observation_baseline.json (без lock/reset, игнорирует lock)",
  )
  args = parser.parse_args()

  if args.update_baseline_only:
    args.force = True

  if LOCK_FILE.exists() and not args.force:
    print(f"Наблюдение уже начато ({LOCK_FILE}), пропуск. --force для повтора.")
    return 0

  from dotenv import load_dotenv
  load_dotenv(ROOT / ".env")

  from tinkoff_bot.config import load_config
  from tinkoff_bot.broker import TinkoffBroker

  cfg = load_config(str(ROOT / "config.yaml"))
  broker = TinkoffBroker(cfg.tinkoff)
  equity, cash, positions = broker.get_equity_snapshot(cfg.portfolio.base_currency)

  started_at = datetime.now().isoformat()
  git_rev = _git_rev()
  positions_count = len(positions)
  if args.update_baseline_only and BASELINE_FILE.exists():
    try:
      prev = json.loads(BASELINE_FILE.read_text(encoding="utf-8"))
      started_at = prev.get("started_at") or started_at
      git_rev = prev.get("git_rev") or git_rev
      equity = float(prev.get("equity", equity))
      cash = float(prev.get("cash", cash))
      positions_count = int(prev.get("positions_count", positions_count))
    except Exception:
      pass

  dp_path = ROOT / "data" / "dynamic_portfolio.json"
  dp_data: dict = {}
  instruments_for_baseline = list(cfg.instruments)
  if dp_path.exists():
    try:
      dp_data = json.loads(dp_path.read_text(encoding="utf-8"))
      from tinkoff_bot.dynamic_portfolio import instruments_from_state

      dp_inst = instruments_from_state(dp_data)
      if dp_inst:
        instruments_for_baseline = dp_inst
    except Exception:
      pass

  if args.reset_learned and not args.update_baseline_only:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    if LEARNED_FILE.exists():
      stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
      dest = BACKUP_DIR / f"learned_params_pre_observation_{stamp}.json"
      shutil.copy2(LEARNED_FILE, dest)
      print(f"Бэкап learned_params: {dest}")
    LEARNED_FILE.parent.mkdir(parents=True, exist_ok=True)
    LEARNED_FILE.write_text("{}", encoding="utf-8")
    print("learned_params/params.json очищен")

  baseline = {
    "started_at": started_at,
    "git_rev": git_rev,
    "equity": equity,
    "cash": cash,
    "positions_count": positions_count,
    "instruments": [
      {
        "figi": i.figi,
        "ticker": i.ticker,
        "target_weight": i.target_weight,
        "strategy": str(i.strategy),
      }
      for i in instruments_for_baseline
    ],
    "dynamic_portfolio": {
      "updated_at": dp_data.get("updated_at"),
      "advisor_source": dp_data.get("advisor_source"),
      "summary": (dp_data.get("summary") or "")[:500],
    },
  }
  BASELINE_FILE.parent.mkdir(parents=True, exist_ok=True)
  BASELINE_FILE.write_text(json.dumps(baseline, ensure_ascii=False, indent=2), encoding="utf-8")
  print(f"Baseline: {BASELINE_FILE}")

  if args.update_baseline_only:
    baseline["baseline_corrected_at"] = datetime.now().isoformat()
    baseline["git_rev_deploy"] = _git_rev()
    BASELINE_FILE.write_text(json.dumps(baseline, ensure_ascii=False, indent=2), encoding="utf-8")
    _sync_risk_state_to_equity(float(baseline.get("equity", equity)))
    print("Baseline обновлён (--update-baseline-only), lock и equity старта сохранены.")
    print(f"risk_state синхронизирован с equity={baseline.get('equity', equity):.0f}")
    return 0

  # Свежий старт наблюдения: сбрасываем risk_state, иначе старый пик equity
  # даст ложную «просадку» и заблокирует торговлю на новом базисе.
  if RISK_STATE_FILE.exists():
    try:
      RISK_STATE_FILE.unlink()
      print(f"risk_state сброшен: {RISK_STATE_FILE}")
    except Exception as e:
      print(f"Не удалось сбросить risk_state: {e}")

  lock = {"started_at": baseline["started_at"], "git_rev": baseline["git_rev"]}
  LOCK_FILE.write_text(json.dumps(lock, ensure_ascii=False, indent=2), encoding="utf-8")
  print(f"Lock: {LOCK_FILE}")
  return 0


if __name__ == "__main__":
  raise SystemExit(main())

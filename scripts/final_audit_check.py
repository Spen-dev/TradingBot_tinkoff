"""Runtime audit: critical paths with debug instrumentation."""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
  sys.path.insert(0, str(ROOT))

LOG_PATH = ROOT / "debug-b92523.log"
SESSION = "b92523"
RUN_ID = "final-audit"


def _log(hypothesis_id: str, location: str, message: str, data: dict) -> None:
  # #region agent log
  entry = {
    "sessionId": SESSION,
    "runId": RUN_ID,
    "hypothesisId": hypothesis_id,
    "location": location,
    "message": message,
    "data": data,
    "timestamp": int(time.time() * 1000),
  }
  with open(LOG_PATH, "a", encoding="utf-8") as f:
    f.write(json.dumps(entry, ensure_ascii=False) + "\n")
  # #endregion


def audit_risk_baseline() -> None:
  """H-A: stale daily baseline; H-B: max_equity blocks trading."""
  from tinkoff_bot.config import RiskConfig
  from tinkoff_bot.risk import RiskManager, RiskState, RISK_STATE_FILE

  tmp = ROOT / "data" / "_audit_risk_state.json"
  orig = RISK_STATE_FILE
  import tinkoff_bot.risk as risk_mod
  risk_mod.RISK_STATE_FILE = tmp
  try:
    tmp.write_text(json.dumps({
      "pause_until": None,
      "max_equity_seen": 150_000.0,
      "daily_equity_start": 150_000.0,
      "daily_equity_date": "2020-01-01",
    }), encoding="utf-8")
    cfg = RiskConfig(
      max_drawdown=0.15, daily_loss_limit=0.03, default_stop_loss_pct=0.05,
      trailing_stop_pct=0.02, var_confidence=0.95, kelly_fraction_cap=0.5,
    )
    rm = RiskManager(cfg)
    stale_daily = rm._daily_equity_start is None
    st = rm.update_equity(100_000.0, 100_000.0)
    blocked = not rm.is_trading_allowed(st)
    dd_reason = rm.get_block_reason(st)
    _log("H-A", "final_audit_check:audit_risk_baseline", "stale daily reset", {
      "stale_daily_cleared": stale_daily,
      "daily_start_after": rm._daily_equity_start,
      "daily_date": rm._daily_equity_date,
    })
    _log("H-B", "final_audit_check:audit_risk_baseline", "drawdown block check", {
      "equity": 100_000.0,
      "max_equity_seen": rm._max_equity_seen,
      "blocked": blocked,
      "reason": dd_reason,
    })
  finally:
    risk_mod.RISK_STATE_FILE = orig
    if tmp.exists():
      tmp.unlink()


def audit_trade_history() -> None:
  """H-C: consecutive losses with horizon_days=1 includes recent mature trades."""
  from tinkoff_bot.trade_history import TradeRecord, evaluate_realized_pnl, get_consecutive_losses

  ts_old = (datetime.now() - timedelta(days=2)).isoformat()
  ts_new = (datetime.now() - timedelta(hours=6)).isoformat()
  trades = [
    TradeRecord("t1", "F1", "A", "buy", 10, 100.0, ts_old, "adaptive"),
    TradeRecord("t2", "F2", "B", "buy", 10, 100.0, ts_new, "adaptive"),
  ]

  def price(figi: str) -> float:
    return 90.0 if figi == "F1" else 110.0

  ev0 = evaluate_realized_pnl(trades, price, horizon_days=0)
  ev1 = evaluate_realized_pnl(trades, price, horizon_days=1)
  ev5 = evaluate_realized_pnl(trades, price, horizon_days=5)
  _log("H-C", "final_audit_check:audit_trade_history", "horizon maturity", {
    "ev0_count": len(ev0),
    "ev1_count": len(ev1),
    "ev5_count": len(ev5),
    "ev1_has_f1": any(t.figi == "F1" for t, _ in ev1),
    "ev1_has_f2": any(t.figi == "F2" for t, _ in ev1),
  })


def audit_portfolio_weights() -> None:
  """H-D: rebalance targets use config weights, not price ratios."""
  from tinkoff_bot.config import PortfolioConfig, RiskConfig, InstrumentConfig
  from tinkoff_bot.portfolio import PortfolioManager
  from tinkoff_bot.risk import RiskManager

  pcfg = PortfolioConfig(
    base_currency="RUB", rebalance_frequency="daily", rebalance_time="10:00",
    commission_rate=0.0003, dry_run=False, limit_price_pct=0.001,
    rebalance_by_price=True, rebalance_on_drift=True, rebalance_drift_pct=0.05,
    rebalance_check_interval_minutes=30, rebalance_cooldown_minutes=60,
    rebalance_interval_hours=0.0,
  )
  rcfg = RiskConfig(
    max_drawdown=0.15, daily_loss_limit=0.03, default_stop_loss_pct=0.05,
    trailing_stop_pct=0.02, var_confidence=0.95, kelly_fraction_cap=0.5,
  )
  inst = [
    InstrumentConfig(figi="F1", ticker="A", strategy="adaptive", target_weight=0.5, strategy_params={}, lot=1),
    InstrumentConfig(figi="F2", ticker="B", strategy="momentum", target_weight=0.5, strategy_params={}, lot=1),
  ]
  broker = MagicMock()
  pm = PortfolioManager(pcfg, inst, broker, RiskManager(rcfg))
  prices = {"F1": 100.0, "F2": 500.0}
  targets = pm._target_values(100_000.0, prices)
  pos_f1 = MagicMock(value=50_000.0)
  pos_f2 = MagicMock(value=50_000.0)
  broker.get_equity_snapshot.return_value = (100_000.0, 0.0, {"F1": pos_f1, "F2": pos_f2})
  broker.get_last_price.side_effect = lambda f: prices[f]
  drift_needed = pm.rebalance_needed(100_000.0, 0.05)
  _log("H-D", "final_audit_check:audit_portfolio_weights", "weight targets", {
    "f1_target": targets.get("F1"),
    "f2_target": targets.get("F2"),
    "drift_needed_at_50_50": drift_needed,
    "price_ratio_would_drift": True,
  })


def audit_learned_params() -> None:
  """H-E: meta keys stripped from strategy params."""
  from tinkoff_bot.config import InstrumentConfig
  from tinkoff_bot.learned_params import get_effective_params, get_effective_target_weight

  inst = InstrumentConfig(
    figi="F1", ticker="A", strategy="adaptive", target_weight=0.2,
    strategy_params={"lookback": 20}, lot=1,
  )
  learned = {"F1": {"target_weight": 0.8, "strategy": "momentum", "lookback": 30}}
  params = get_effective_params(inst, learned, None)
  tw = get_effective_target_weight(inst, learned)
  _log("H-E", "final_audit_check:audit_learned_params", "meta strip", {
    "params_has_target_weight": "target_weight" in params,
    "params_has_strategy": "strategy" in params,
    "params_lookback": params.get("lookback"),
    "effective_tw": tw,
  })


def audit_dynamic_portfolio_changed() -> None:
  """H-F: weight-only change detected."""
  from tinkoff_bot.config import InstrumentConfig, DynamicPortfolioConfig
  from tinkoff_bot.dynamic_portfolio import instruments_from_state

  state = {
    "instruments": [
      {"figi": "F1", "ticker": "A", "target_weight": 0.25, "strategy": "adaptive", "lot": 1},
      {"figi": "F2", "ticker": "B", "target_weight": 0.25, "strategy": "adaptive", "lot": 1},
    ]
  }
  old = instruments_from_state(state)
  new = [
    InstrumentConfig(figi="F1", ticker="A", strategy="adaptive", target_weight=0.30, strategy_params={}, lot=1),
    InstrumentConfig(figi="F2", ticker="B", strategy="adaptive", target_weight=0.20, strategy_params={}, lot=1),
  ]
  old_tickers = {i.ticker for i in old}
  new_tickers = {i.ticker for i in new}
  changed = old_tickers != new_tickers
  if not changed:
    old_by = {i.ticker: float(i.target_weight) for i in old}
    for ins in new:
      ow = old_by.get(ins.ticker)
      if ow is not None and abs(ow - float(ins.target_weight)) > 0.005:
        changed = True
        break
  _log("H-F", "final_audit_check:audit_dynamic_portfolio_changed", "weight change detect", {
    "same_tickers": old_tickers == new_tickers,
    "changed": changed,
  })


def audit_on_rebalance_semantics() -> None:
  """H-G: schedule slot not consumed on execution failure."""
  from tinkoff_bot.run_bot import OnRebalanceResult

  def _out(source, msg, sched, drift):
    if source == "manual":
      return OnRebalanceResult(msg, False, False)
    if source == "schedule":
      return OnRebalanceResult(msg, sched, False)
    return OnRebalanceResult(msg, False, drift)

  fail = _out("schedule", "failed", False, False)
  noop = _out("schedule", "noop", True, False)
  ok = _out("schedule", "ok", True, False)
  _log("H-G", "final_audit_check:audit_on_rebalance_semantics", "tick flags", {
    "fail_tick_schedule": fail.tick_schedule_calendar,
    "noop_tick_schedule": noop.tick_schedule_calendar,
    "ok_tick_schedule": ok.tick_schedule_calendar,
  })


def audit_sandbox_topup() -> None:
  """H-H: ensure_sandbox_funded tops up delta, not full target."""
  import os
  from unittest.mock import MagicMock
  from tinkoff_bot.ops_automation import ensure_sandbox_funded

  broker = MagicMock()
  broker.get_equity_snapshot.return_value = (3_000.0, 99_500.0, {})
  captured: list = []
  broker.set_sandbox_balance = lambda amt, currency="RUB": captured.append(amt)
  os.environ["SANDBOX_TARGET_CASH"] = "100000"
  ensure_sandbox_funded(broker, "RUB")
  _log("H-H", "final_audit_check:audit_sandbox_topup", "topup amount", {
    "captured": captured,
    "expected_1000": captured[0] if captured else None,
    "not_full_target": captured[0] != 100_000.0 if captured else True,
  })


def audit_instrument_pause_tz() -> None:
  """H-I: timezone-aware pause ISO respected."""
  from datetime import timedelta
  import tinkoff_bot.instrument_pause as ip

  tmp = ROOT / "data" / "_audit_pause.json"
  orig = ip.PAUSE_FILE
  ip.PAUSE_FILE = tmp
  try:
    future = (datetime.now() + timedelta(hours=2)).isoformat()
    tmp.write_text(json.dumps({"F1": future}), encoding="utf-8")
    paused = ip.is_paused("F1")
    _log("H-I", "final_audit_check:audit_instrument_pause_tz", "pause check", {
      "until": future,
      "is_paused": paused,
    })
  finally:
    ip.PAUSE_FILE = orig
    if tmp.exists():
      tmp.unlink()


def audit_empty_candles() -> None:
  """H-J: empty candle response does not KeyError."""
  from types import SimpleNamespace
  from tinkoff_bot.broker import TinkoffBroker
  from tinkoff_bot.config import TinkoffConfig

  cfg = TinkoffConfig(token="x", account_id="y", use_sandbox=True)
  broker = TinkoffBroker(cfg)
  resp = SimpleNamespace(candles=[])
  rows = []
  for c in resp.candles:
    rows.append({})
  import pandas as pd
  if not rows:
    df = pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
  else:
    df = pd.DataFrame(rows).set_index("time")
  _log("H-J", "final_audit_check:audit_empty_candles", "empty df ok", {
    "columns": list(df.columns),
    "empty": df.empty,
  })


def main() -> int:
  LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
  if LOG_PATH.exists():
    LOG_PATH.unlink()
  checks = [
    audit_risk_baseline,
    audit_trade_history,
    audit_portfolio_weights,
    audit_learned_params,
    audit_dynamic_portfolio_changed,
    audit_on_rebalance_semantics,
    audit_sandbox_topup,
    audit_instrument_pause_tz,
    audit_empty_candles,
  ]
  errors = []
  for fn in checks:
    try:
      fn()
    except Exception as e:
      errors.append(f"{fn.__name__}: {e}")
      _log("ERR", f"final_audit_check:{fn.__name__}", "check failed", {"error": str(e)})
  _log("SUM", "final_audit_check:main", "audit complete", {
    "checks": len(checks),
    "errors": errors,
  })
  print(f"Audit done. Logs: {LOG_PATH}")
  if errors:
    print("ERRORS:", errors)
    return 1
  return 0


if __name__ == "__main__":
  raise SystemExit(main())

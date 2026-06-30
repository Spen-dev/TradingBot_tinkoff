"""Final runtime audit — writes NDJSON to debug-b92523.log."""
from __future__ import annotations

import asyncio
import json
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
  sys.path.insert(0, str(ROOT))

LOG = ROOT / "debug-b92523.log"
SESSION = "b92523"


def _log(hid: str, loc: str, msg: str, data: dict) -> None:
  entry = {
    "sessionId": SESSION,
    "runId": "final-audit-v3",
    "hypothesisId": hid,
    "location": loc,
    "message": msg,
    "data": data,
    "timestamp": int(time.time() * 1000),
  }
  with open(LOG, "a", encoding="utf-8") as f:
    f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def check_sync_handlers_block_loop() -> None:
  """H-N: sync run_retrain blocks event loop."""
  import asyncio

  def slow():
    time.sleep(0.5)
    return "ok"

  async def sync_style():
    await asyncio.sleep(0.05)
    slow()
    return "done"

  async def executor_style():
    await asyncio.sleep(0.05)
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, slow)

  async def measure(coro_fn):
    ticks = []

    async def ticker():
      for _ in range(10):
        await asyncio.sleep(0.05)
        ticks.append(time.time())

    async def run():
      await asyncio.sleep(0.05)
      await coro_fn()

    await asyncio.gather(ticker(), run())
    gaps = [ticks[i] - ticks[i - 1] for i in range(1, len(ticks))]
    return max(gaps) if gaps else 0.0

  sync_gap = asyncio.run(measure(sync_style))
  exec_gap = asyncio.run(measure(executor_style))
  _log("H-N", "audit:sync_handlers", "handler blocks loop", {
    "sync_gap_s": round(sync_gap, 3),
    "executor_gap_s": round(exec_gap, 3),
    "sync_blocks": sync_gap > 0.3,
    "executor_free": exec_gap < 0.3,
  })


def check_place_order_double_retry() -> None:
  """H-O: portfolio outer retry can duplicate after broker retry."""
  from tinkoff_bot.broker import _BROKER_RETRY_ATTEMPTS

  calls = []

  class FakeBroker:
    def place_order(self, **kw):
      calls.append(1)
      if len(calls) == 1:
        raise TimeoutError("simulated timeout after broker accepted")
      return "order-2"

  from tinkoff_bot.config import PortfolioConfig, RiskConfig, InstrumentConfig
  from tinkoff_bot.portfolio import PortfolioManager, RebalanceOrder
  from tinkoff_bot.risk import RiskManager
  from t_tech.invest import OrderDirection

  pcfg = PortfolioConfig(
    base_currency="RUB", rebalance_frequency="daily", rebalance_time="10:00",
    commission_rate=0.0003, dry_run=False, limit_price_pct=0.001,
    rebalance_interval_hours=0.0,
  )
  rcfg = RiskConfig(
    max_drawdown=0.15, daily_loss_limit=0.03, default_stop_loss_pct=0.05,
    trailing_stop_pct=0.02, var_confidence=0.95, kelly_fraction_cap=0.5,
  )
  inst = [InstrumentConfig(figi="F1", ticker="A", strategy="adaptive", target_weight=1.0, strategy_params={}, lot=1)]
  broker = FakeBroker()
  broker.get_cash_balance = lambda currency="RUB": 100_000.0
  broker.get_open_orders = lambda: []
  broker.cancel_orders = lambda x: None
  broker.get_last_price = lambda f: 100.0

  pm = PortfolioManager(pcfg, inst, broker, RiskManager(rcfg))
  orders = [
    RebalanceOrder("F1", "A", 10, OrderDirection.ORDER_DIRECTION_BUY, 100.0, 1.0, "adaptive"),
  ]
  # Monkeypatch build path — call execute internals via planned orders
  pm.build_rebalance_orders = lambda x: orders  # type: ignore

  try:
    pm.execute_rebalance(100_000.0, orders)
  except Exception:
    pass

  _log("H-O", "audit:place_order_retry", "duplicate risk", {
    "broker_retry_attempts_config": _BROKER_RETRY_ATTEMPTS,
    "place_order_calls": len(calls),
    "duplicate_risk": len(calls) > 1,
    "expected_single_call": True,
  })


def check_safety_mismatch() -> None:
  """H-P: build uses SAFETY=0.75, execute uses 0.95."""
  import inspect
  import tinkoff_bot.portfolio as pmod

  src_build = inspect.getsource(pmod.PortfolioManager.build_rebalance_orders)
  src_exec = inspect.getsource(pmod.PortfolioManager.execute_rebalance)
  build_safety = "_CASH_SAFETY" in src_build or "0.75" in src_build
  exec_safety = "_CASH_SAFETY" in src_exec
  _log("H-P", "audit:safety_mismatch", "cash buffer mismatch", {
    "build_uses_cash_safety": build_safety,
    "execute_uses_cash_safety": exec_safety,
    "mismatch": build_safety and not exec_safety,
  })


def check_config_validation() -> None:
  from tinkoff_bot.config import load_config, validate_config

  cfg = load_config(str(ROOT / "config.yaml"))
  ok, errs = validate_config(cfg)
  _log("H-Q", "audit:config", "production config valid", {
    "ok": ok,
    "error_count": len(errs),
    "errors": errs[:5],
  })


def check_risk_persist() -> None:
  from tinkoff_bot.config import RiskConfig
  from tinkoff_bot.risk import RiskManager, RISK_STATE_FILE
  import tinkoff_bot.risk as rm

  tmp = ROOT / "data" / "_audit_risk.json"
  orig = RISK_STATE_FILE
  rm.RISK_STATE_FILE = tmp
  try:
    tmp.write_text(json.dumps({
      "max_equity_seen": 150000, "daily_equity_start": 150000,
      "daily_equity_date": "2020-01-01", "pause_until": None,
    }), encoding="utf-8")
    r = RiskManager(RiskConfig(
      max_drawdown=0.15, daily_loss_limit=0.03, default_stop_loss_pct=0.05,
      trailing_stop_pct=0.02, var_confidence=0.95, kelly_fraction_cap=0.5,
    ))
    stale_cleared = r._daily_equity_start is None
    st = r.update_equity(120000, 120000)
    blocked = not r.is_trading_allowed(st)
    _log("H-R", "audit:risk", "stale daily + drawdown", {
      "stale_daily_cleared": stale_cleared,
      "blocked_at_120k_vs_150k_peak": blocked,
    })
  finally:
    rm.RISK_STATE_FILE = orig
    if tmp.exists():
      tmp.unlink()


def main() -> int:
  LOG.parent.mkdir(parents=True, exist_ok=True)
  if LOG.exists():
    LOG.unlink()
  for fn in (
    check_sync_handlers_block_loop,
    check_place_order_double_retry,
    check_safety_mismatch,
    check_config_validation,
    check_risk_persist,
  ):
    try:
      fn()
    except Exception as e:
      _log("ERR", f"audit:{fn.__name__}", str(e), {})
  print(f"Audit OK -> {LOG}")
  return 0


if __name__ == "__main__":
  raise SystemExit(main())

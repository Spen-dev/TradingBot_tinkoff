import asyncio
import json
import logging
import os
import signal
import time
from datetime import datetime, date, timedelta
from pathlib import Path

from tinkoff.invest.exceptions import RequestError

logger = logging.getLogger(__name__)

from tinkoff_bot.config import load_config, validate_config
from tinkoff_bot.telegram_bot import TelegramController
from tinkoff_bot.broker import TinkoffBroker
from tinkoff_bot.risk import RiskManager
from tinkoff_bot.portfolio import PortfolioManager
from tinkoff_bot.metrics import inc_trades, inc_error, update_equity
from tinkoff_bot.alerts import send_alert, send_alert_sync, set_alert_cooldown

try:
  from tinkoff_bot.logging_config import setup_logging
except Exception as e:
  logging.getLogger(__name__).debug("setup_logging недоступен: %s", e)
  setup_logging = None


def _get_version() -> str:
  try:
    import importlib.metadata
    return importlib.metadata.version("tinkoff_bot")
  except Exception:
    return "0.1.0"


async def main() -> None:
  robot_started_at = datetime.now()
  if setup_logging:
    setup_logging(json_log=True, console=True)
  app_version = _get_version()
  logger.info("tinkoff_bot v%s", app_version)
  base_dir = Path(__file__).resolve().parent
  cfg = load_config(str(base_dir / "config.yaml"))
  # Режим sandbox/real: в реале автоматически ужесточаем риски и размеры позиций
  try:
    if getattr(cfg, "mode", "sandbox") == "real":
      cfg.risk.max_drawdown = min(cfg.risk.max_drawdown, 0.10)
      cfg.risk.daily_loss_limit = min(cfg.risk.daily_loss_limit, 0.02)
      # Ограничиваем долю одной позиции и разовой сделки
      cfg.portfolio.max_position_pct = min(getattr(cfg.portfolio, "max_position_pct", 0.2) or 0.2, 0.2)
      cfg.portfolio.single_trade_max_pct = min(getattr(cfg.portfolio, "single_trade_max_pct", 0.1) or 0.1, 0.1)
  except Exception as e:
    logger.warning("Ужесточение рисков в real: %s", e)
  set_alert_cooldown(getattr(cfg.portfolio, "alert_cooldown_minutes", 30))
  try:
    from tinkoff_bot.learned_params import load_learned_params
    load_learned_params()
  except Exception as e:
    print("Предупреждение (learned_params):", e)

  tg = TelegramController(cfg.telegram)
  ok, errs = validate_config(cfg)
  if not ok:
    await send_alert(tg, "⚠️ Ошибки конфига: " + "; ".join(errs), "config_error", force=True)

  broker = TinkoffBroker(cfg.tinkoff)
  if getattr(cfg.portfolio, "use_candle_cache", False):
    try:
      from tinkoff_bot.candle_cache import CachingBroker
      broker = CachingBroker(broker, True, getattr(cfg.portfolio, "candle_cache_days", 60))
    except Exception:
      pass
  risk = RiskManager(cfg.risk)
  pm = PortfolioManager(cfg.portfolio, cfg.instruments, broker, risk)
  broker_timeout = max(5.0, float(getattr(cfg.portfolio, "request_timeout_seconds", 30) or 30))

  async def broker_get_cash_async():
    loop = asyncio.get_running_loop()
    return await asyncio.wait_for(
      loop.run_in_executor(None, lambda: broker.get_cash_balance(currency=cfg.portfolio.base_currency)),
      timeout=broker_timeout,
    )

  day_start_equity: float | None = None
  last_trade_time: datetime | None = None
  trading_enabled = getattr(cfg.portfolio, "trading_enabled", True)
  started = False
  real_trade_confirmed = False
  awaiting_real_confirm = False
  awaiting_stop_confirm = False

  def compute_equity() -> tuple[float, float, int]:
    positions = broker.get_portfolio()
    cash = broker.get_cash_balance(currency=cfg.portfolio.base_currency)
    equity = cash + sum(p.value for p in positions.values())
    return equity, cash, len(positions)

  def maybe_reset_equity_baseline(equity: float, cash: float, npos: int) -> None:
    """Авто-сброс baseline equity в песочнице, если счёт явно обнулился."""
    nonlocal day_start_equity
    if not cfg.tinkoff.use_sandbox:
      return
    if equity == 0 and cash == 0 and npos == 0:
      day_start_equity = 0.0
      try:
        risk.reset_equity_baseline(0.0)
      except AttributeError:
        # На старых версиях RiskManager fallback к reset_daily.
        risk.reset_daily(0.0)

  async def on_start():
    nonlocal day_start_equity, real_trade_confirmed, awaiting_real_confirm

    # Каждый новый запуск требует повторного подтверждения реальной торговли.
    real_trade_confirmed = False
    awaiting_real_confirm = False

    try:
      if cfg.tinkoff.use_sandbox:
        # В песочнице нужен отдельный sandbox account_id.
        # Если в .env подставили обычный брокерский account_id, создаём sandbox-аккаунт и продолжаем.
        try:
          _ = broker.get_cash_balance(currency=cfg.portfolio.base_currency)
        except RequestError as e:
          if str(e).find("50004") != -1:
            from tinkoff.invest.sandbox.client import SandboxClient

            with SandboxClient(cfg.tinkoff.token) as client:
              sand = client.users.get_accounts()
              if sand.accounts:
                cfg.tinkoff.account_id = sand.accounts[0].id
              else:
                opened = client.sandbox.open_sandbox_account()
                cfg.tinkoff.account_id = opened.account_id
          else:
            raise

        target_cash = float(os.getenv("SANDBOX_TARGET_CASH", "100000"))
        cash = broker.get_cash_balance(currency=cfg.portfolio.base_currency)
        if cash < target_cash:
          broker.set_sandbox_balance(target_cash - cash, currency=cfg.portfolio.base_currency)

      equity, cash, npos = compute_equity()
      if day_start_equity is None:
        day_start_equity = equity
      print(f"Робот запущен. Cash={cash:.2f} Equity={equity:.2f} Positions={npos}")
      nonlocal started
      started = True
      await send_alert(tg, f"🟢 Робот запущен. Портфель: {equity:.2f} {cfg.portfolio.base_currency}, позиций: {npos}", "start", force=True)
    except Exception as e:
      inc_error()
      logger.exception("on_start: %s", e)
      raise

  async def on_stop():
    nonlocal started
    started = False
    print("Робот остановлен (торговля приостановлена). Нажмите Старт для запуска снова.")

  async def on_stop_request() -> str | None:
    """При нажатии СТОП: в режиме real запрашивает подтверждение, иначе сразу останавливает. Возвращает сообщение для чата или None если остановка выполнена."""
    nonlocal awaiting_stop_confirm
    if getattr(cfg, "mode", "sandbox") == "real":
      awaiting_stop_confirm = True
      return "Точно остановить торговлю? Ответьте Да для подтверждения."
    await on_stop()
    return None

  async def on_confirm_received(text: str) -> str | None:
    """Обработка ответа «Да»: подтверждение реальной торговли или подтверждение остановки."""
    nonlocal awaiting_real_confirm, awaiting_stop_confirm, real_trade_confirmed
    t = (text or "").strip().lower()
    if t != "да":
      return None
    if awaiting_stop_confirm:
      awaiting_stop_confirm = False
      await on_stop()
      return "🛑 Робот остановлен. Нажмите Старт для запуска снова."
    if awaiting_real_confirm:
      awaiting_real_confirm = False
      real_trade_confirmed = True
      return "Реальная торговля подтверждена. Можно выполнять ребаланс."
    return None

  async def on_status() -> str:
    nonlocal day_start_equity
    try:
      from tinkoff_bot.telegram_utils import format_money, format_pct
      equity, cash, npos = compute_equity()
      maybe_reset_equity_baseline(equity, cash, npos)
      if day_start_equity is None:
        day_start_equity = equity
      st = risk.update_equity(equity, day_start_equity)
      drawdown = (st.max_equity_seen - st.equity) / max(st.max_equity_seen, 1e-9)
      update_equity(st.equity, drawdown)
      allowed = risk.is_trading_allowed(st)
      allowed_str = "Да" if allowed else "Нет"
      sandbox_str = "Да" if cfg.tinkoff.use_sandbox else "Нет"
      mode_str = getattr(cfg, "mode", "sandbox") or "sandbox"
      dry_run_str = "Да" if getattr(cfg.portfolio, "dry_run", False) else "Нет"
      now = datetime.now()
      rt = getattr(cfg.portfolio, "rebalance_time", "10:00") or "10:00"
      try:
        rh, rm = map(int, rt.split(":"))
      except (ValueError, AttributeError):
        rh, rm = 10, 0
      digest_t = getattr(cfg.portfolio, "daily_digest_time", "18:00") or "18:00"
      try:
        dh, dm = map(int, digest_t.split(":"))
      except (ValueError, AttributeError):
        dh, dm = 18, 0
      next_reb = now.replace(hour=rh, minute=rm, second=0, microsecond=0)
      if next_reb <= now:
        next_reb += timedelta(days=1)
      next_dig = now.replace(hour=dh, minute=dm, second=0, microsecond=0)
      if next_dig <= now:
        next_dig += timedelta(days=1)
      lines = [
        f"Версия: {app_version}",
        f"Режим: {mode_str}",
        f"Dry-run: {dry_run_str}",
        f"Песочница: {sandbox_str}",
        f"Деньги на счёте: {format_money(cash, cfg.portfolio.base_currency)}",
        f"Портфель: {format_money(equity, cfg.portfolio.base_currency)}",
        f"Позиций: {npos}",
        f"Дневной результат: {format_money(st.daily_pnl, cfg.portfolio.base_currency)}",
        f"Текущая просадка: {format_pct(drawdown * 100)}",
        f"Торговля разрешена: {allowed_str}",
        f"След. ребаланс: {next_reb.strftime('%H:%M')}",
        f"След. дайджест: {next_dig.strftime('%H:%M')}",
      ]
      return "\n".join(lines)
    except Exception:
      inc_error()
      return "Ошибка при получении статуса (см. логи)"

  async def on_positions() -> str:
    try:
      from tinkoff_bot.telegram_utils import format_money
      positions = broker.get_portfolio()
      if not positions:
        return "Нет открытых позиций."
      figi_to_ticker = {i.figi: i.ticker for i in cfg.instruments}
      lines = ["Позиции:"]
      for figi, pos in positions.items():
        name = figi_to_ticker.get(figi, figi)
        lines.append(f"  {name}: кол-во {pos.quantity:.0f}, сумма {format_money(pos.value, cfg.portfolio.base_currency)}")
      return "\n".join(lines)
    except Exception:
      inc_error()
      return "Ошибка при получении позиций (см. логи)"

  async def on_portfolio() -> str:
    try:
      from tinkoff_bot.telegram_utils import format_money, format_pct
      equity, _, _ = compute_equity()
      positions = broker.get_portfolio()
      figi_to_ticker = {i.figi: i.ticker for i in cfg.instruments}
      current_by_figi = {figi: pos.value for figi, pos in positions.items()}
      total_w = sum(getattr(i, "target_weight", 0.0) for i in cfg.instruments)
      lines: list[str] = ["Портфель (цель → текущее → отклонение):"]
      for inst in cfg.instruments:
        w = getattr(inst, "target_weight", 0.0) or 0.0
        target_pct = w * 100.0
        cur_val = current_by_figi.get(inst.figi, 0.0)
        cur_pct = (cur_val / equity * 100.0) if equity and equity > 0 else 0.0
        dev = cur_pct - target_pct
        dev_str = f"{dev:+.1f}" if dev >= 0 else f"{dev:.1f}"
        lines.append(f"  {inst.ticker}: {format_pct(target_pct)} → {format_pct(cur_pct)} ({dev_str}%)")
      if cfg.instruments and abs(total_w - 1.0) > 0.01:
        lines.append(f"\n⚠️ Сумма целевых весов ≈ {total_w:.2f}, а не 1.0")
      return "\n".join(lines)
    except Exception:
      inc_error()
      return "Ошибка при получении портфеля (см. логи)"

  async def on_rebalance() -> str:
    nonlocal day_start_equity, last_trade_time, awaiting_real_confirm, real_trade_confirmed
    try:
      mode = getattr(cfg, "mode", "sandbox") or "sandbox"
      dry_run = getattr(cfg.portfolio, "dry_run", True)
      if mode == "real" and not dry_run and not real_trade_confirmed:
        awaiting_real_confirm = True
        await send_alert(tg, "Подтвердите включение реальной торговли? Ответьте Да в чат для подтверждения.", "real_confirm", force=True)
        return "Ожидание подтверждения. Ответьте Да в чат для включения реальной торговли."
      equity, cash, npos = compute_equity()
      maybe_reset_equity_baseline(equity, cash, npos)
      if day_start_equity is None:
        day_start_equity = equity
      st = risk.update_equity(equity, day_start_equity or 0)
      if not risk.is_trading_allowed(st):
        reason = risk.get_block_reason(st)
        msg = f"⚠️ Торговля запрещена: {reason or 'риск-лимиты'}. Ребаланс не выполнен."
        if equity == 0 and (day_start_equity or 0) > 0:
          msg += " (equity=0 — проверьте доступ к брокеру.)"
        if reason and "пауза" in reason:
          msg += " Сброс: /pause 0"
        await send_alert(tg, msg, "trading_blocked")
        return f"Торговля запрещена: {reason or 'лимит'}"
      now = datetime.now()
      rt = getattr(cfg.portfolio, "rebalance_time", "10:00") or "10:00"
      try:
        rh, rm = map(int, rt.split(":"))
      except (ValueError, AttributeError):
        rh, rm = 10, 0
      w_start = getattr(cfg.portfolio, "rebalance_window_start_minutes", 0) or 0
      w_end = getattr(cfg.portfolio, "rebalance_window_end_minutes", 24 * 60) or (24 * 60)
      rt_mins = rh * 60 + rm
      now_mins = now.hour * 60 + now.minute
      in_window = (w_start == 0 and w_end >= 24 * 60) or (rt_mins + w_start <= now_mins <= w_end)
      prefix = ""
      if not in_window:
        prefix = "⚠️ Сейчас вне торгового окна. "
      if not trading_enabled:
        orders = pm.build_rebalance_orders(day_start_equity or 0)
        await send_alert(tg, f"📋 Режим мониторинга: было бы заявок {len(orders)} (заявки не выставлены)", "monitoring")
        return prefix + f"Мониторинг: заявок не выставлено (было бы {len(orders)})"
      try:
        from tinkoff_bot.trade_history import get_consecutive_losses
        min_pnl = getattr(cfg.risk, "min_pnl_to_count_loss_rub", 0.0) or 0.0
        consecutive = get_consecutive_losses(broker.get_last_price, horizon_days=5, min_pnl_rub=min_pnl)
        pause_set = pm.risk.update_consecutive_losses(consecutive)
        if pause_set:
          ph = getattr(cfg.risk, "pause_hours", 24) or 24
          await send_alert(tg, f"⏸ Торговля приостановлена на {ph:.0f} ч из-за серии убытков ({consecutive} подряд).", "pause")
      except Exception:
        pass
      # Исполнение ребаланса выносим в отдельный поток, чтобы не блокировать event loop.
      loop = asyncio.get_running_loop()
      trades = await loop.run_in_executor(None, lambda: pm.execute_rebalance(day_start_equity or 0))
      if trades:
        dry_run = getattr(cfg.portfolio, "dry_run", False)
        last_trade_time = datetime.now()
        inc_trades(len(trades))
        for t in trades:
          await tg.send_trade_notification(
            ticker=t["ticker"],
            direction=t["direction"],
            quantity=t["quantity"],
            price=t["price"],
            amount=t["amount"],
            commission=t["commission"],
            simulation=dry_run,
          )
        msg = f"Выставлено заявок: {len(trades)}"
        if dry_run:
          msg += " (симуляция, dry-run)"
        return prefix + msg
      return prefix + "Заявки не нужны (нет инструментов/нет отклонений/риск-лимиты)"
    except Exception as e:
      inc_error()
      logger.exception("on_rebalance: %s", e)
      return f"Ошибка ребаланса: {e}"

  async def on_select_strategy() -> str:
    try:
      from tinkoff_bot.self_learn import run_strategy_selection
      days = getattr(cfg.portfolio, "strategy_selection_days", 90) or 90
      comm = getattr(cfg.portfolio, "commission_rate", 0.0003) or 0.0003
      msg, changes = run_strategy_selection(
        broker, cfg.instruments, days=days,
        commission_rate=comm,
        train_ratio=getattr(cfg.portfolio, "self_learn_train_ratio", 0.7) or 0.7,
        use_sharpe=getattr(cfg.portfolio, "self_learn_use_sharpe", True),
        min_trades=getattr(cfg.portfolio, "self_learn_min_trades", 5) or 5,
        risk_penalty=getattr(cfg.portfolio, "self_learn_risk_penalty", 0.5) or 0.5,
        allow_deepseek=getattr(cfg.portfolio, "use_deepseek_advisor", False),
        deepseek_model=getattr(cfg.portfolio, "deepseek_model", "deepseek-chat"),
        strategy_change_min_delta=getattr(cfg.portfolio, "strategy_change_min_delta", 0.05) or 0,
        strategy_diversity_max_share=getattr(cfg.portfolio, "strategy_diversity_max_share", 0) or 0,
      )
      if changes:
        await send_alert(tg, "📊 Смена стратегий: " + ", ".join(f"{t} {o}→{n}" for t, o, n in changes), "strategy_changes", force=True)
      return msg
    except Exception as e:
      inc_error()
      logger.exception("on_select_strategy: %s", e)
      return f"Ошибка выбора стратегии: {e}"

  async def on_retrain() -> str:
    try:
      from tinkoff_bot.self_learn import run_retrain
      from tinkoff_bot.trade_history import get_consecutive_losses
      days = getattr(cfg.portfolio, "retrain_days", 60) or 60
      consecutive = 0
      try:
        min_pnl = getattr(cfg.risk, "min_pnl_to_count_loss_rub", 0.0) or 0.0
        consecutive = get_consecutive_losses(broker.get_last_price, horizon_days=10, min_pnl_rub=min_pnl)
      except Exception:
        pass
      risk_penalty_mult = 1.0 + (0.5 * min(consecutive, 5) / 5.0)  # до 1.5 при серии убытков
      return run_retrain(
        broker, cfg.instruments, days=days,
        commission_rate=getattr(cfg.portfolio, "commission_rate", 0.0003) or 0.0003,
        train_ratio=getattr(cfg.portfolio, "self_learn_train_ratio", 0.7) or 0.7,
        use_sharpe=getattr(cfg.portfolio, "self_learn_use_sharpe", True),
        min_trades=getattr(cfg.portfolio, "self_learn_min_trades", 5) or 5,
        risk_penalty=getattr(cfg.portfolio, "self_learn_risk_penalty", 0.5) or 0.5,
        risk_penalty_mult=risk_penalty_mult,
        optuna_trials=getattr(cfg.portfolio, "self_learn_optuna_trials", 0) or 0,
        optimize_weights=getattr(cfg.portfolio, "self_learn_optimize_weights", False),
        weight_cap=getattr(cfg.portfolio, "self_learn_weight_cap", 0.4) or 0.4,
        atr_period=getattr(cfg.portfolio, "volatility_atr_period", 14) or 14,
        tune_by_regime=getattr(cfg.portfolio, "self_learn_tune_by_regime", False),
      )
    except Exception as e:
      inc_error()
      logger.exception("on_retrain: %s", e)
      return f"Ошибка самообучения: {e}"

  async def on_pause(hours: float) -> None:
    risk.set_pause_until(hours)
    await send_alert(tg, f"⏸ Пауза торговли на {hours:.0f} ч установлена вручную.", "pause", force=True)

  async def on_unpause(ticker: str) -> str:
    from tinkoff_bot.instrument_pause import clear_pause
    ticker = ticker.upper().strip()
    for i in cfg.instruments:
      if getattr(i, "ticker", "").upper() == ticker:
        clear_pause(i.figi)
        return f"Пауза снята для {ticker}."
    return f"Тикер {ticker} не найден в конфиге."

  async def on_help_extra() -> str:
    """Дополнение к /help: сколько времени работает робот (uptime)."""
    try:
      delta = datetime.now() - robot_started_at
      total_sec = int(delta.total_seconds())
      if total_sec < 0:
        return ""
      days = total_sec // 86400
      rest = total_sec % 86400
      hours = rest // 3600
      minutes = (rest % 3600) // 60
      parts = []
      if days > 0:
        parts.append(f"{days} дн.")
      if hours > 0 or days > 0:
        parts.append(f"{hours} ч")
      parts.append(f"{minutes} мин")
      return "⏱ Робот работает: " + " ".join(parts)
    except Exception:
      return ""

  async def on_last_errors() -> str:
    """Последние строки из лога с ошибками (или последние 15 строк)."""
    try:
      log_path = base_dir / "data" / "logs" / "bot.log"
      if not log_path.exists():
        return "Лог-файл не найден."
      lines = log_path.read_text(encoding="utf-8", errors="replace").strip().split("\n")
      err_lines = [l for l in lines[-200:] if "ERROR" in l or "error" in l.lower()]
      last = err_lines[-15:] if err_lines else lines[-15:]
      if not last:
        return "Последних ошибок в логе нет."
      return "Последние записи из лога:\n" + "\n".join(last)
    except Exception as e:
      return f"Ошибка чтения лога: {e}"

  tg.set_callbacks(
    on_start=on_start,
    on_stop=on_stop,
    on_stop_request=on_stop_request,
    on_status=on_status,
    on_rebalance=on_rebalance,
    on_positions=on_positions,
    on_portfolio=on_portfolio,
    on_retrain=on_retrain,
    on_select_strategy=on_select_strategy,
    on_pause=on_pause,
    on_unpause=on_unpause,
    on_help_extra=on_help_extra,
    is_started=lambda: started,
    on_confirm=on_confirm_received,
    get_mode=lambda: getattr(cfg, "mode", "sandbox") or "sandbox",
    on_last_errors=on_last_errors,
  )

  last_live_ping: datetime | None = None

  try:
    from tinkoff_bot.health_server import run_health_server
    health_server = await run_health_server(cfg.web.host, cfg.web.port, broker, cfg, lambda: started)
  except Exception:
    health_server = None

  async def auto_rebalance_scheduler():
    """Ребаланс по расписанию, по дрейфу, дайджест, алерт «нет сделок», сброс дня, блокировка инструментов, недельный отчёт."""
    nonlocal last_trade_time, day_start_equity, last_live_ping
    rebalance_time = getattr(cfg.portfolio, "rebalance_time", "10:00")
    try:
      hour, minute = map(int, rebalance_time.split(":"))
    except (ValueError, AttributeError):
      hour, minute = 10, 0
    digest_time = getattr(cfg.portfolio, "daily_digest_time", "18:00")
    try:
      digest_h, digest_m = map(int, digest_time.split(":"))
    except (ValueError, AttributeError):
      digest_h, digest_m = 18, 0
    no_trades_hours = getattr(cfg.portfolio, "no_trades_alert_hours", 0) or 0
    last_rebalance_date: date | None = None
    last_drift_rebalance: datetime | None = None
    last_retrain_date: date | None = None
    last_digest_date: date | None = None
    last_rl_train_date: date | None = None
    rl_train_start_done = False
    strategy_selection_start_done = False
    auto_strategy_selection_on_start = getattr(cfg.portfolio, "auto_strategy_selection_on_start", False)
    strategy_selection_interval_days = getattr(cfg.portfolio, "strategy_selection_interval_days", 0) or 0
    strategy_selection_state_file = base_dir / "data" / "strategy_selection_state.json"
    last_day_reset_date: date | None = None
    last_weekly_report_date: date | None = None
    last_alert_drawdown_date: date | None = None
    last_alert_daily_loss_date: date | None = None
    alert_live_ping_hours = getattr(cfg.portfolio, "alert_live_ping_hours", 0.0) or 0.0
    weekly_weekday = getattr(cfg.portfolio, "weekly_report_weekday", 6) or 6
    weekly_time = getattr(cfg.portfolio, "weekly_report_time", "18:00") or "18:00"
    try:
      wh, wm = map(int, weekly_time.split(":"))
    except (ValueError, AttributeError):
      wh, wm = 18, 0
    inst_pause_after = getattr(cfg.portfolio, "instrument_pause_after_losses", 0) or 0
    inst_pause_hours = getattr(cfg.portfolio, "instrument_pause_hours", 24.0) or 24.0
    check_interval = max(1, getattr(cfg.portfolio, "rebalance_check_interval_minutes", 30))
    cooldown_min = getattr(cfg.portfolio, "rebalance_cooldown_minutes", 60)
    drift_pct = getattr(cfg.portfolio, "rebalance_drift_pct", 0.05)
    on_drift = getattr(cfg.portfolio, "rebalance_on_drift", True)
    auto_retrain_days = getattr(cfg.portfolio, "auto_retrain_interval_days", 0) or 0
    rl_train_on_start = getattr(cfg.portfolio, "rl_train_on_start", False)
    rl_train_interval_days = getattr(cfg.portfolio, "rl_train_interval_days", 0) or 0
    rl_instruments = [i for i in cfg.instruments if getattr(i, "strategy", None) == "rl"]
    window_start = getattr(cfg.portfolio, "rebalance_window_start_minutes", 0) or 0
    window_end = getattr(cfg.portfolio, "rebalance_window_end_minutes", 24 * 60) or (24 * 60)
    rt_mins = hour * 60 + minute
    market_index_figi = getattr(cfg.portfolio, "market_index_figi", "") or ""
    market_panic_drop = getattr(cfg.portfolio, "market_panic_drop_pct", 0.05) or 0.0
    vol_low = getattr(cfg.portfolio, "market_vol_low_threshold_pct", 0.01) or 0.01
    vol_high = getattr(cfg.portfolio, "market_vol_high_threshold_pct", 0.03) or 0.03
    last_market_check_date: date | None = None
    market_vol_level: str = "normal"  # low / normal / high
    panic_today: bool = False

    def _in_rebalance_window() -> bool:
      now_mins = now.hour * 60 + now.minute
      if window_start == 0 and window_end >= 24 * 60:
        return True
      return (now_mins >= rt_mins + window_start) and (now_mins <= window_end)

    while True:
      await asyncio.sleep(60)
      now = datetime.now()
      if not started:
        continue
      if auto_strategy_selection_on_start and not strategy_selection_start_done:
        strategy_selection_start_done = True
        try:
          from tinkoff_bot.self_learn import run_strategy_selection
          loop = asyncio.get_event_loop()
          sel_days = getattr(cfg.portfolio, "strategy_selection_days", 90) or 90
          msg, changes = await loop.run_in_executor(
            None,
            lambda: run_strategy_selection(
              broker, cfg.instruments, days=sel_days,
              commission_rate=getattr(cfg.portfolio, "commission_rate", 0.0003) or 0.0003,
              train_ratio=getattr(cfg.portfolio, "self_learn_train_ratio", 0.7) or 0.7,
              use_sharpe=getattr(cfg.portfolio, "self_learn_use_sharpe", True),
              min_trades=getattr(cfg.portfolio, "self_learn_min_trades", 5) or 5,
              risk_penalty=getattr(cfg.portfolio, "self_learn_risk_penalty", 0.5) or 0.5,
              allow_deepseek=getattr(cfg.portfolio, "use_deepseek_advisor", False),
              deepseek_model=getattr(cfg.portfolio, "deepseek_model", "deepseek-chat"),
              strategy_change_min_delta=getattr(cfg.portfolio, "strategy_change_min_delta", 0.05) or 0,
              strategy_diversity_max_share=getattr(cfg.portfolio, "strategy_diversity_max_share", 0) or 0,
            ),
          )
          await send_alert(tg, "📊 Выбор стратегий при старте:\n" + msg, "strategy_selection", force=True)
          if changes:
            await send_alert(tg, "📊 Смена стратегий: " + ", ".join(f"{t} {o}→{n}" for t, o, n in changes), "strategy_changes", force=True)
        except Exception as e:
          logger.exception("Strategy selection on start: %s", e)
      if strategy_selection_interval_days > 0:
        last_sel_date: date | None = None
        if strategy_selection_state_file.exists():
          try:
            data = json.loads(strategy_selection_state_file.read_text(encoding="utf-8"))
            s = data.get("last_date", "")[:10]
            if s:
              last_sel_date = datetime.strptime(s, "%Y-%m-%d").date()
          except Exception:
            pass
        if last_sel_date is None or (today - last_sel_date).days >= strategy_selection_interval_days:
          try:
            from tinkoff_bot.self_learn import run_strategy_selection
            loop = asyncio.get_event_loop()
            sel_days = getattr(cfg.portfolio, "strategy_selection_days", 90) or 90
            msg, changes = await loop.run_in_executor(
              None,
              lambda: run_strategy_selection(
                broker, cfg.instruments, days=sel_days,
                commission_rate=getattr(cfg.portfolio, "commission_rate", 0.0003) or 0.0003,
                train_ratio=getattr(cfg.portfolio, "self_learn_train_ratio", 0.7) or 0.7,
                use_sharpe=getattr(cfg.portfolio, "self_learn_use_sharpe", True),
                min_trades=getattr(cfg.portfolio, "self_learn_min_trades", 5) or 5,
                risk_penalty=getattr(cfg.portfolio, "self_learn_risk_penalty", 0.5) or 0.5,
                allow_deepseek=getattr(cfg.portfolio, "use_deepseek_advisor", False),
                deepseek_model=getattr(cfg.portfolio, "deepseek_model", "deepseek-chat"),
                strategy_change_min_delta=getattr(cfg.portfolio, "strategy_change_min_delta", 0.05) or 0,
                strategy_diversity_max_share=getattr(cfg.portfolio, "strategy_diversity_max_share", 0) or 0,
              ),
            )
            strategy_selection_state_file.parent.mkdir(parents=True, exist_ok=True)
            strategy_selection_state_file.write_text(json.dumps({"last_date": today.isoformat()}, ensure_ascii=False), encoding="utf-8")
            await send_alert(tg, "📊 Периодический выбор стратегий:\n" + msg, "strategy_selection", force=True)
            if changes:
              await send_alert(tg, "📊 Смена стратегий: " + ", ".join(f"{t} {o}→{n}" for t, o, n in changes), "strategy_changes", force=True)
          except Exception as e:
            logger.exception("Periodic strategy selection: %s", e)
      if alert_live_ping_hours > 0:
        if last_live_ping is None:
          last_live_ping = now
        elif (now - last_live_ping).total_seconds() >= alert_live_ping_hours * 3600:
          last_live_ping = now
          await send_alert(tg, "🤖 Робот работает.", "live_ping")
      day_start = day_start_equity or 0.0
      today = now.date()
      # Ежедневная оценка состояния рынка по индексу
      if market_index_figi and last_market_check_date != today:
        last_market_check_date = today
        panic_today = False
        try:
          from_dt = today - timedelta(days=3)
          df_idx = broker.get_historical_candles(market_index_figi, from_dt, now)
          if df_idx is not None and len(df_idx) >= 2:
            close = df_idx["close"]
            c0, c1 = float(close.iloc[-2]), float(close.iloc[-1])
            if c0 > 0:
              ret = (c1 / c0) - 1
              abs_ret = abs(ret)
              if ret <= -market_panic_drop:
                panic_today = True
                # Глобальная пауза до конца дня
                hours_left = max(1.0, 24 - now.hour)
                risk.set_pause_until(hours_left)
                await send_alert(tg, f"⏸ Kill-switch: индекс {market_index_figi} упал на {ret*100:.1f}%. Торговля приостановлена до конца дня.", "market_panic", force=True)
              if abs_ret <= vol_low:
                market_vol_level = "low"
              elif abs_ret >= vol_high:
                market_vol_level = "high"
              else:
                market_vol_level = "normal"
        except Exception:
          market_vol_level = "normal"
      # Единственное место сброса дня: при смене даты обновляем day_start_equity и риск.
      if day_start_equity is not None and last_day_reset_date is not None and today != last_day_reset_date:
        try:
          equity, _, _ = compute_equity()
          day_start_equity = equity
          risk.reset_daily(equity)
          last_day_reset_date = today
        except Exception:
          pass
      if last_day_reset_date is None and day_start_equity is not None:
        last_day_reset_date = today
      if last_rebalance_date != today and _in_rebalance_window() and not panic_today:
        last_rebalance_date = today
        last_drift_rebalance = now
        try:
          await broker_get_cash_async()
        except Exception as e:
          inc_error()
          await send_alert(tg, f"⚠️ Ребаланс пропущен: брокер не отвечает ({e})", "rebalance_skip", force=True)
          continue
        try:
          res = await on_rebalance()
          await send_alert(tg, f"🤖 Авторебаланс (по расписанию): {res}", "rebalance")
        except Exception as e:
          inc_error()
          await send_alert(tg, f"❌ Ошибка авторебаланса: {e}", "rebalance_error")
        continue

      # Адаптация частоты проверки дрейфа по волатильности рынка
      effective_check_interval = check_interval
      if market_vol_level == "low":
        effective_check_interval = max(check_interval, 60)
      elif market_vol_level == "high":
        effective_check_interval = min(check_interval, 15)

      if on_drift and (now.minute % effective_check_interval == 0) and _in_rebalance_window() and not panic_today:
        if last_drift_rebalance and (now - last_drift_rebalance).total_seconds() < cooldown_min * 60:
          pass
        else:
          try:
            if pm.rebalance_needed(day_start, drift_pct):
              try:
                await broker_get_cash_async()
              except Exception as e:
                inc_error()
                await send_alert(tg, f"⚠️ Ребаланс пропущен: брокер не отвечает ({e})", "rebalance_skip", force=True)
              else:
                last_drift_rebalance = now
                res = await on_rebalance()
                await send_alert(tg, f"📈 Ребаланс по ситуации (дрейф >{drift_pct:.0%}): {res}", "rebalance")
          except Exception as e:
            inc_error()
            await send_alert(tg, f"❌ Ошибка ребаланса по дрейфу: {e}", "rebalance_error")

      if now.hour == digest_h and now.minute == digest_m and last_digest_date != now.date():
        last_digest_date = now.date()
        try:
          equity, cash, npos = compute_equity()
          st = risk.update_equity(equity, day_start)
          dd = (st.max_equity_seen - st.equity) / max(st.max_equity_seen, 1e-9)
          pause = risk.get_pause_until()
          pause_str = f", пауза до {pause}" if pause else ""
          await send_alert(tg, f"📊 Дневной дайджест: портфель {equity:.2f} {cfg.portfolio.base_currency}, дневной PnL {st.daily_pnl:.2f}, просадка {dd:.1%}{pause_str}", "daily_digest")
          # Алерты по порогам (раз в день)
          alert_dd = getattr(cfg.portfolio, "alert_drawdown_pct", 0.0) or 0.0
          alert_daily = getattr(cfg.portfolio, "alert_daily_loss_pct", 0.0) or 0.0
          if alert_dd > 0 and dd >= alert_dd and last_alert_drawdown_date != today:
            last_alert_drawdown_date = today
            await send_alert(tg, f"⚠️ Просадка портфеля {dd:.1%} превысила порог {alert_dd:.1%}.", "alert_drawdown", force=True)
          day_start_val = max(day_start, 1e-9)
          if alert_daily > 0 and st.daily_pnl < 0 and (-st.daily_pnl / day_start_val) >= alert_daily and last_alert_daily_loss_date != today:
            last_alert_daily_loss_date = today
            await send_alert(tg, f"⚠️ Дневной убыток {st.daily_pnl:.2f} ({-st.daily_pnl/day_start_val:.1%}) превысил порог {alert_daily:.1%}.", "alert_daily_loss", force=True)
        except Exception as e:
          logger.warning("Дневной дайджест: %s", e)

      if no_trades_hours > 0 and trading_enabled and last_trade_time is not None:
        if (now - last_trade_time).total_seconds() >= no_trades_hours * 3600:
          await send_alert(tg, f"⚠️ Нет сделок более {no_trades_hours} ч. Проверьте логи и доступ к брокеру.", "no_trades")

      if inst_pause_after > 0:
        try:
          from tinkoff_bot.trade_history import get_consecutive_losses_per_figi
          from tinkoff_bot.instrument_pause import update_pauses
          min_pnl = getattr(cfg.risk, "min_pnl_to_count_loss_rub", 0.0) or 0.0
          consec = get_consecutive_losses_per_figi(broker.get_last_price, horizon_days=10, min_pnl_rub=min_pnl)
          paused_figi = update_pauses(consec, inst_pause_after, inst_pause_hours)
          if paused_figi:
            figi_to_ticker = {i.figi: i.ticker for i in cfg.instruments}
            tickers = [figi_to_ticker.get(f, f) for f in paused_figi]
            await send_alert(tg, f"⏸ Пауза по инструментам (серия убытков ≥{inst_pause_after}): {', '.join(tickers)}", "instrument_pause", force=True)
        except Exception:
          pass

      if now.weekday() == weekly_weekday and now.hour == wh and now.minute == wm and last_weekly_report_date != today:
        last_weekly_report_date = today
        try:
          from tinkoff_bot.trade_history import get_trades, get_per_instrument_stats, get_strategy_stats
          from tinkoff_bot.self_learn import _get_signals_for_df, _simulate_pnl_and_dd, _compute_sharpe
          from tinkoff_bot.instrument_pause import is_paused as instrument_is_paused, set_pause_hours

          equity, cash, npos = compute_equity()
          week_ago_dt = now - timedelta(days=7)
          week_ago = week_ago_dt.isoformat()
          trades_week = [t for t in get_trades(limit=100) if t.ts >= week_ago]

          # Реальный PnL по инструментам за последние 30 дней (по оценке trade_history)
          stats = get_per_instrument_stats(broker.get_last_price, horizon_days=30, max_trades=300)
          per_inst_lines: list[str] = []
          winners = sorted(stats.items(), key=lambda kv: kv[1].get("pnl", 0.0), reverse=True)
          losers = sorted(stats.items(), key=lambda kv: kv[1].get("pnl", 0.0))[:3]
          for figi, s in winners[:3]:
            per_inst_lines.append(
              f"↑ {s.get('ticker', figi)}: результат {s['pnl']:.2f} RUB, сделок {s['trades']}, винрейт {s.get('win_rate', 0.0)*100:.0f}%"
            )
          for figi, s in losers:
            if s.get("pnl", 0.0) >= 0:
              continue
            per_inst_lines.append(
              f"↓ {s.get('ticker', figi)}: результат {s['pnl']:.2f} RUB, сделок {s['trades']}, винрейт {s.get('win_rate', 0.0)*100:.0f}%"
            )
          per_inst_text = "\n".join(per_inst_lines) if per_inst_lines else "нет достаточно сделок для оценки"

          # Статистика по стратегиям
          strat_stats = get_strategy_stats(broker.get_last_price, horizon_days=30)
          strat_lines: list[str] = []
          for name, s in sorted(strat_stats.items(), key=lambda kv: kv[1].get("pnl", 0.0), reverse=True)[:3]:
            strat_lines.append(
              f"↑ {name}: средний результат {s.get('avg_pnl', 0.0):.2f} RUB, сделок {s['trades']}, винрейт {s.get('win_rate', 0.0)*100:.0f}%"
            )
          for name, s in sorted(strat_stats.items(), key=lambda kv: kv[1].get("pnl", 0.0))[:3]:
            if s.get("pnl", 0.0) >= 0:
              continue
            strat_lines.append(
              f"↓ {name}: средний результат {s.get('avg_pnl', 0.0):.2f} RUB, сделок {s['trades']}, винрейт {s.get('win_rate', 0.0)*100:.0f}%"
            )
          strat_text = "\n".join(strat_lines) if strat_lines else "нет достаточно сделок для оценки стратегий"

          # Авто-пауза для сильно убыточных инструментов (самоотключение)
          bad_paused: list[str] = []
          for figi, s in stats.items():
            trades_n = s.get("trades", 0)
            pnl_val = s.get("pnl", 0.0)
            win_rate = s.get("win_rate", 0.0)
            if trades_n >= 10 and pnl_val < 0 and win_rate < 0.45:
              set_pause_hours(figi, 24 * 7)  # пауза на неделю
              bad_paused.append(s.get("ticker", figi))

          # Текущие паузы по инструментам и по риску
          paused_now = [i.ticker for i in cfg.instruments if instrument_is_paused(i.figi)]
          pause_text = ", ".join(sorted(set(paused_now))) if paused_now else "нет"
          risk_pause = risk.get_pause_until()
          risk_text = risk_pause.strftime("%Y-%m-%d %H:%M") if risk_pause else "нет"

          # Автобэктест стратегий по истории (окно 90 дней)
          bt_days = 90
          bt_to = now
          bt_from = bt_to - timedelta(days=bt_days)
          commission = getattr(cfg.portfolio, "commission_rate", 0.0003) or 0.0003
          rows = []
          for inst in cfg.instruments:
            try:
              df = broker.get_historical_candles(inst.figi, bt_from, bt_to)
            except Exception:
              continue
            if df is None or len(df) < 40:
              continue
            try:
              signals = _get_signals_for_df(broker, inst, df, params_override={})
              pnl_bt, max_dd, n_trades_bt, daily_returns = _simulate_pnl_and_dd(df, signals, commission_rate=commission)
              sharpe = _compute_sharpe(daily_returns)
              rows.append((inst.ticker, pnl_bt, max_dd, sharpe, n_trades_bt))
            except Exception:
              continue
          rows.sort(key=lambda x: x[1], reverse=True)
          bt_lines = []
          for ticker, pnl_bt, max_dd, sharpe, n_trades_bt in rows[:4]:
            bt_lines.append(
              f"{ticker}: доходность {pnl_bt*100:.1f}%, макс. просадка {max_dd*100:.1f}%, коэфф. Шарпа {sharpe:.2f}, сделок {n_trades_bt}"
            )
          bt_text = "\n".join(bt_lines) if bt_lines else "нет достаточно данных для бэктеста"

          # Версионирование RL-моделей: из JSON рядом с .zip
          rl_lines = []
          for inst in rl_instruments:
            try:
              params = getattr(inst, "strategy_params", None) or {}
              model_path = params.get("rl_model_path", f"data/rl_model_{inst.ticker}.zip")
              meta_path = base_dir / Path(model_path).with_suffix(".json")
              if meta_path.exists():
                import json
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                dt_str = meta.get("date", "")[:10]
                if len(dt_str) >= 10:
                  from datetime import datetime as _dt
                  d = _dt.fromisoformat(dt_str)
                  dt_str = d.strftime("%d.%m.%Y")
                days = meta.get("days", 0)
                rl_lines.append(f"{inst.ticker}: {dt_str}, окно {days} дн.")
            except Exception:
              pass
          rl_text = "\n".join(rl_lines) if rl_lines else "нет данных"

          msg = (
            f"📈 Недельный отчёт: портфель {equity:.2f} {cfg.portfolio.base_currency}, "
            f"сделок за неделю: {len(trades_week)}, позиций: {npos}"
            f"\n\n📊 Инструменты (оценка 30 дн.):\n{per_inst_text}"
            f"\n\n📚 Стратегии (оценка 30 дн.):\n{strat_text}"
            f"\n\n🤖 RL-модели:\n{rl_text}"
            f"\n\n⏸ Пауза по инструментам: {pause_text}\n⏱ Пауза по риску до: {risk_text}"
            f"\n\n🧪 Бэктест стратегий за {bt_days} дн. (оценка):\n{bt_text}"
          )
          if bad_paused:
            msg += "\n\n⚠️ Автопауза включена для: " + ", ".join(sorted(set(bad_paused)))

          await send_alert(tg, msg, "weekly_digest")
        except Exception:
          pass

      if auto_retrain_days > 0 and last_retrain_date is not None:
        if (now.date() - last_retrain_date).days >= auto_retrain_days:
          last_retrain_date = now.date()
          try:
            from tinkoff_bot.self_learn import run_retrain
            from tinkoff_bot.trade_history import get_consecutive_losses
            days = getattr(cfg.portfolio, "retrain_days", 60) or 60
            consecutive = 0
            try:
              min_pnl = getattr(cfg.risk, "min_pnl_to_count_loss_rub", 0.0) or 0.0
              consecutive = get_consecutive_losses(broker.get_last_price, horizon_days=10, min_pnl_rub=min_pnl)
            except Exception:
              pass
            risk_penalty_mult = 1.0 + (0.5 * min(consecutive, 5) / 5.0)
            loop = asyncio.get_event_loop()
            res = await loop.run_in_executor(None, lambda: run_retrain(
              broker, cfg.instruments, days=days,
              commission_rate=getattr(cfg.portfolio, "commission_rate", 0.0003) or 0.0003,
              train_ratio=getattr(cfg.portfolio, "self_learn_train_ratio", 0.7) or 0.7,
              use_sharpe=getattr(cfg.portfolio, "self_learn_use_sharpe", True),
              min_trades=getattr(cfg.portfolio, "self_learn_min_trades", 5) or 5,
              risk_penalty=getattr(cfg.portfolio, "self_learn_risk_penalty", 0.5) or 0.5,
              risk_penalty_mult=risk_penalty_mult,
              optuna_trials=getattr(cfg.portfolio, "self_learn_optuna_trials", 0) or 0,
              optimize_weights=getattr(cfg.portfolio, "self_learn_optimize_weights", False),
              weight_cap=getattr(cfg.portfolio, "self_learn_weight_cap", 0.4) or 0.4,
              atr_period=getattr(cfg.portfolio, "volatility_atr_period", 14) or 14,
              tune_by_regime=getattr(cfg.portfolio, "self_learn_tune_by_regime", False),
            ))
            await send_alert(tg, f"📚 Самообучение: {res}", "self_learn")
          except Exception as e:
            inc_error()
            await send_alert(tg, f"❌ Ошибка самообучения: {e}", "self_learn_error")
      elif auto_retrain_days > 0 and last_retrain_date is None:
        last_retrain_date = now.date()

      # RL: обучение при старте (один раз) или по интервалу
      if rl_instruments:
        if rl_train_on_start and not rl_train_start_done:
          rl_train_start_done = True
          last_rl_train_date = now.date()
          rl_days = getattr(cfg.portfolio, "rl_train_days", 365) or 365
          rl_steps = getattr(cfg.portfolio, "rl_train_timesteps", 50_000) or 50_000
          base_dir = Path(__file__).resolve().parent
          results = []
          try:
            from tinkoff_bot.train_rl import run_rl_train
            loop = asyncio.get_event_loop()
            for inv in rl_instruments:
              out_path = base_dir / "data" / f"rl_model_{getattr(inv, 'ticker', inv.figi)}.zip"
              comm = getattr(cfg.portfolio, "commission_rate", 0.0003) or 0.0003
              wf = getattr(cfg.portfolio, "rl_train_walk_forward_ratio", 0.7) or 0.7
              res = await loop.run_in_executor(
                None,
                lambda i=inv, p=str(out_path): run_rl_train(
                  broker, i.figi, days=rl_days, out_path=p, timesteps=rl_steps, verbose=0,
                  commission_rate=comm, walk_forward_ratio=wf,
                ),
              )
              results.append(res)
            await send_alert(tg, "🧠 RL обучение (при старте): " + "; ".join(results), "rl_train")
          except Exception as e:
            inc_error()
            await send_alert(tg, f"❌ Ошибка RL обучения: {e}", "rl_train_error")
        elif rl_train_interval_days > 0:
          if last_rl_train_date is None:
            last_rl_train_date = now.date()
          elif (now.date() - last_rl_train_date).days >= rl_train_interval_days:
            last_rl_train_date = now.date()
            rl_days = getattr(cfg.portfolio, "rl_train_days", 365) or 365
            rl_steps = getattr(cfg.portfolio, "rl_train_timesteps", 50_000) or 50_000
            base_dir = Path(__file__).resolve().parent
            results = []
            try:
              from tinkoff_bot.train_rl import run_rl_train
              loop = asyncio.get_event_loop()
              for inv in rl_instruments:
                out_path = base_dir / "data" / f"rl_model_{getattr(inv, 'ticker', inv.figi)}.zip"
                comm = getattr(cfg.portfolio, "commission_rate", 0.0003) or 0.0003
                wf = getattr(cfg.portfolio, "rl_train_walk_forward_ratio", 0.7) or 0.7
                res = await loop.run_in_executor(
                  None,
                  lambda i=inv, p=str(out_path): run_rl_train(
                    broker, i.figi, days=rl_days, out_path=p, timesteps=rl_steps, verbose=0,
                    commission_rate=comm, walk_forward_ratio=wf,
                  ),
                )
                results.append(res)
              await send_alert(tg, f"🧠 RL обучение (раз в {rl_train_interval_days} дн.): " + "; ".join(results), "rl_train")
            except Exception as e:
              inc_error()
              await send_alert(tg, f"❌ Ошибка RL обучения: {e}", "rl_train_error")

  scheduler_task = asyncio.create_task(auto_rebalance_scheduler())

  async def watchdog():
    failures = 0
    interval = max(60, getattr(cfg.portfolio, "watchdog_interval_seconds", 90))
    while True:
      await asyncio.sleep(interval)
      if not started:
        continue
      try:
        await broker_get_cash_async()
        failures = 0
      except Exception as e:
        logger.warning("watchdog get_cash_balance: %s", e)
        failures += 1
        if failures >= 3:
          try:
            await send_alert(tg, "⚠️ Робот: брокер не отвечает после нескольких попыток.", "watchdog")
          except Exception as alert_err:
            logger.warning("watchdog send_alert: %s", alert_err)
          failures = 0

  watchdog_task = asyncio.create_task(watchdog())

  try:
    loop = asyncio.get_running_loop()
    def _on_signal():
      global _graceful_shutdown
      _graceful_shutdown = True
      tg.request_stop()
    for sig in (signal.SIGTERM, signal.SIGINT):
      try:
        loop.add_signal_handler(sig, _on_signal)
      except (NotImplementedError, OSError):
        break
  except Exception:
    pass
  try:
    await tg.run()
  finally:
    scheduler_task.cancel()
    watchdog_task.cancel()
    if health_server:
      health_server.close()
      await health_server.wait_closed()


_graceful_shutdown = False


if __name__ == "__main__":
  while True:
    try:
      asyncio.run(main())
      break
    except Exception as e:
      if _graceful_shutdown:
        break
      logger.exception("main: %s", e)
      send_alert_sync(f"Робот упал, перезапуск через 60 сек: {e}")
      time.sleep(60)
    if _graceful_shutdown:
      break


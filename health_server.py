"""HTTP health-check и метрики: /health и /metrics для мониторинга."""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from typing import TYPE_CHECKING, Callable, Dict, Any

if TYPE_CHECKING:
  from .broker import TinkoffBroker, Position
  from .config import AppConfig

logger = logging.getLogger(__name__)


DASHBOARD_HTML = """
<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="UTF-8" />
  <title>tinkoff_bot dashboard</title>
  <style>
    body { font-family: system-ui, -apple-system, BlinkMacSystemFont, sans-serif; margin: 0; padding: 16px; background: #0b1020; color: #e5e9f0; }
    h1 { margin-top: 0; }
    .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 16px; }
    .card { background: #151a2c; border-radius: 8px; padding: 12px 16px; box-shadow: 0 0 0 1px rgba(255,255,255,0.03); }
    .card h2 { margin: 0 0 8px 0; font-size: 16px; }
    table { width: 100%; border-collapse: collapse; font-size: 13px; }
    th, td { padding: 4px 6px; text-align: right; border-bottom: 1px solid rgba(255,255,255,0.05); }
    th { text-align: left; font-weight: 500; color: #a0a7c0; }
    tr:nth-child(even) { background: rgba(255,255,255,0.01); }
    .status-ok { color: #8fda7f; }
    .status-bad { color: #ff6b6b; }
    .status-warn { color: #ffd166; }
    .pill { display: inline-block; padding: 2px 6px; border-radius: 10px; font-size: 11px; }
    .pill-ok { background: rgba(143,218,127,0.12); color: #8fda7f; }
    .pill-bad { background: rgba(255,107,107,0.12); color: #ff6b6b; }
    .pill-warn { background: rgba(255,209,102,0.12); color: #ffd166; }
    .small { font-size: 12px; color: #a0a7c0; }
  </style>
</head>
<body>
  <h1>tinkoff_bot — dashboard</h1>
  <div class="grid">
    <div class="card" id="status-card">
      <h2>Статус робота</h2>
      <div id="status-body" class="small">Загрузка…</div>
    </div>
    <div class="card">
      <h2>Портфель</h2>
      <table id="portfolio-table">
        <thead>
          <tr>
            <th>Тикер</th>
            <th>Кол-во</th>
            <th>Цена</th>
            <th>Сумма</th>
            <th>Целевой вес</th>
          </tr>
        </thead>
        <tbody></tbody>
      </table>
    </div>
  </div>
  <script>
    async function fetchJson(url) {
      const r = await fetch(url, { cache: 'no-store' });
      if (!r.ok) throw new Error('HTTP ' + r.status);
      return await r.json();
    }

    function fmtMoney(v) {
      return (v || 0).toLocaleString('ru-RU', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    }

    function fmtPct(v) {
      return (v || 0).toFixed(2) + '%';
    }

    async function refresh() {
      try {
        const [status, portfolio] = await Promise.all([
          fetchJson('/api/status'),
          fetchJson('/api/portfolio'),
        ]);

        const sEl = document.getElementById('status-body');
        const allowed = status.trading_allowed;
        const riskText = allowed ? '<span class="pill pill-ok">торговля разрешена</span>'
                                 : '<span class="pill pill-bad">торговля остановлена</span>';
        sEl.innerHTML = `
          <div>Версия: <b>${status.version || '?'}</b></div>
          <div>Режим: <b>${status.mode}</b>, песочница: <b>${status.sandbox ? 'Да' : 'Нет'}</b></div>
          <div>Equity: <b>${fmtMoney(status.equity)} RUB</b></div>
          <div>Кэш: <b>${fmtMoney(status.cash)} RUB</b></div>
          <div>Позиции: <b>${status.positions_count}</b></div>
          <div>Дневной результат: <b>${fmtMoney(status.daily_pnl)} RUB</b></div>
          <div>Просадка: <b>${fmtPct(status.drawdown_pct)}</b></div>
          <div style="margin-top:6px;">${riskText}</div>
          <div class="small" style="margin-top:6px;">След. ребаланс: ${status.next_rebalance || '-'}, дайджест: ${status.next_digest || '-'}</div>
        `;

        const tbody = document.querySelector('#portfolio-table tbody');
        tbody.innerHTML = '';
        (portfolio.instruments || []).forEach(it => {
          const tr = document.createElement('tr');
          tr.innerHTML = `
            <td style="text-align:left;">${it.ticker || it.figi}</td>
            <td>${it.quantity}</td>
            <td>${fmtMoney(it.price)}</td>
            <td>${fmtMoney(it.value)}</td>
            <td>${fmtPct(it.target_weight * 100)}</td>
          `;
          tbody.appendChild(tr);
        });
      } catch (e) {
        document.getElementById('status-body').innerHTML = '<span class="status-bad">Ошибка загрузки: ' + e.message + '</span>';
      }
    }

    refresh();
    setInterval(refresh, 5000);
  </script>
</body>
</html>
""".strip()


async def _write_response(writer: asyncio.StreamWriter, status: int, body: bytes, content_type: str = "text/plain; charset=utf-8") -> None:
  writer.write(
    f"HTTP/1.0 {status} {'OK' if status == 200 else 'Error'}\r\n"
    f"Content-Type: {content_type}\r\n"
    "Connection: close\r\n"
    f"Content-Length: {len(body)}\r\n\r\n".encode("utf-8")
  )
  writer.write(body)
  await writer.drain()
  try:
    writer.close()
    await writer.wait_closed()
  except Exception:
    pass


async def _handle_api_status(broker: "TinkoffBroker | None", cfg: "AppConfig | None") -> Dict[str, Any]:
  from .risk import RiskManager
  from .metrics import get_trades  # type: ignore[import]  # not used, but left as placeholder
  from .trade_history import get_trades as load_trades
  cash = 0.0
  equity = 0.0
  positions_count = 0
  daily_pnl = 0.0
  drawdown_pct = 0.0
  trading_allowed = True
  if broker and cfg:
    try:
      cash = broker.get_cash_balance(cfg.portfolio.base_currency)
      positions = broker.get_portfolio()
      positions_count = len(positions)
      equity = cash + sum(p.value for p in positions.values())
      # Приближённая оценка состояния риска (без сохранённой истории)
      rm = RiskManager(cfg.risk)
      state = rm.update_equity(equity, equity)
      trading_allowed = cfg.portfolio.trading_enabled and rm.is_trading_allowed(state)
    except Exception:
      pass
  # Оценка next_rebalance / next_digest по cfg (локально, как в /status)
  next_reb = ""
  next_dig = ""
  try:
    now = datetime.now()
    rt = getattr(cfg.portfolio, "rebalance_time", "10:00") if cfg else "10:00"
    dh = getattr(cfg.portfolio, "daily_digest_time", "18:00") if cfg else "18:00"
    rh, rm = map(int, str(rt).split(":"))
    d_h, d_m = map(int, str(dh).split(":"))
    nr = now.replace(hour=rh, minute=rm, second=0, microsecond=0)
    if nr <= now:
      from datetime import timedelta
      nr += timedelta(days=1)
    nd = now.replace(hour=d_h, minute=d_m, second=0, microsecond=0)
    if nd <= now:
      from datetime import timedelta
      nd += timedelta(days=1)
    next_reb = nr.strftime("%H:%M")
    next_dig = nd.strftime("%H:%M")
  except Exception:
    pass
  mode = "sandbox"
  sandbox = True
  if cfg:
    mode = getattr(cfg, "mode", "sandbox")
    sandbox = bool(getattr(cfg.tinkoff, "use_sandbox", True))
  try:
    from importlib import metadata
    version = metadata.version("tinkoff_bot")
  except Exception:
    version = "0.1.0"
  # Берём последний ежедневный PnL и просадку из Telegram-логики не можем, оставляем 0
  return {
    "version": version,
    "mode": mode,
    "sandbox": sandbox,
    "equity": equity,
    "cash": cash,
    "positions_count": positions_count,
    "daily_pnl": daily_pnl,
    "drawdown_pct": drawdown_pct,
    "trading_allowed": trading_allowed,
    "next_rebalance": next_reb,
    "next_digest": next_dig,
  }


async def _handle_api_portfolio(broker: "TinkoffBroker | None", cfg: "AppConfig | None") -> Dict[str, Any]:
  from .learned_params import load_learned_params, get_effective_strategy, get_effective_target_weight
  instruments: list[Dict[str, Any]] = []
  if not broker or not cfg:
    return {"instruments": instruments}
  try:
    positions: Dict[str, Position] = broker.get_portfolio()
    cash = broker.get_cash_balance(cfg.portfolio.base_currency)
    equity = cash + sum(p.value for p in positions.values())
    by_figi = {i.figi: i for i in cfg.instruments}
    learned = load_learned_params()
    for figi, pos in positions.items():
      ins = by_figi.get(figi)
      ticker = getattr(ins, "ticker", figi) if ins else figi
      target_weight = 0.0
      strategy = ""
      if ins:
        target_weight = get_effective_target_weight(ins, learned)
        strategy = str(get_effective_strategy(ins, learned, None))
      instruments.append({
        "figi": figi,
        "ticker": ticker,
        "quantity": pos.quantity,
        "price": pos.current_price,
        "value": pos.value,
        "target_weight": float(target_weight),
        "strategy": strategy,
      })
  except Exception:
    pass
  return {"instruments": instruments}


async def handle_health(
  reader: asyncio.StreamReader,
  writer: asyncio.StreamWriter,
  broker: "TinkoffBroker | None",
  cfg: "AppConfig | None",
  is_ready: Callable[[], bool],
) -> None:
  """Обработчик запросов: GET /health или GET / -> JSON; GET /metrics -> Prometheus."""
  try:
    data = await asyncio.wait_for(reader.read(1024), timeout=2.0)
    line = data.decode("utf-8", errors="ignore").split("\r\n")[0]
    # Маршрутизация по простому HTTP-line
    if "GET /metrics" in line:
      try:
        from prometheus_client import generate_latest
        body = generate_latest()
        if not isinstance(body, bytes):
          body = body.encode("utf-8")
        await _write_response(writer, 200, body, "text/plain; charset=utf-8")
      except Exception as e:
        logger.debug("Metrics generation error: %s", e)
        await _write_response(writer, 500, b"")
      return
    if "GET /dashboard" in line or "GET / " in line and "/api/" not in line and "/health" not in line:
      await _write_response(writer, 200, DASHBOARD_HTML.encode("utf-8"), "text/html; charset=utf-8")
      return
    if "GET /api/status" in line:
      try:
        body_obj = await _handle_api_status(broker, cfg)
        body = json.dumps(body_obj, ensure_ascii=False).encode("utf-8")
        await _write_response(writer, 200, body, "application/json; charset=utf-8")
      except Exception as e:
        logger.debug("api/status error: %s", e)
        await _write_response(writer, 500, b"{}", "application/json; charset=utf-8")
      return
    if "GET /api/portfolio" in line:
      try:
        body_obj = await _handle_api_portfolio(broker, cfg)
        body = json.dumps(body_obj, ensure_ascii=False).encode("utf-8")
        await _write_response(writer, 200, body, "application/json; charset=utf-8")
      except Exception as e:
        logger.debug("api/portfolio error: %s", e)
        await _write_response(writer, 500, b"{}", "application/json; charset=utf-8")
      return
    if "GET /health" in line:
      broker_ok = False
      if broker:
        try:
          broker.get_cash_balance(currency=(cfg.portfolio.base_currency if cfg else "RUB"))
          broker_ok = True
        except Exception:
          pass
      config_ok = cfg is not None
      ready = is_ready() if callable(is_ready) else True
      status = 200 if (broker_ok and config_ok) else 503
      body = json.dumps({"broker_ok": broker_ok, "config_ok": config_ok, "ready": ready}, ensure_ascii=False).encode("utf-8")
      await _write_response(writer, status, body, "application/json; charset=utf-8")
      return
    # Всё остальное — 404
    await _write_response(writer, 404, b"Not found")
  except Exception as e:
    logger.debug("Health check error: %s", e)
    try:
      await _write_response(writer, 500, b"")
    except Exception:
      pass


async def run_health_server(
  host: str,
  port: int,
  broker: "TinkoffBroker | None",
  cfg: "AppConfig | None",
  is_ready: Callable[[], bool] = lambda: True,
) -> asyncio.Server:
  """Запустить TCP-сервер для /health."""
  server = await asyncio.start_server(
    lambda r, w: handle_health(r, w, broker, cfg, is_ready),
    host=host,
    port=port,
  )
  return server

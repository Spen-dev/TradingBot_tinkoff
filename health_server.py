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
  <title>tinkoff_bot — арена стратегий</title>
  <style>
    body { font-family: system-ui, -apple-system, BlinkMacSystemFont, sans-serif; margin: 0; padding: 16px 24px 24px; background: #050816; color: #e5e9f0; }
    .topbar { display: flex; align-items: center; justify-content: space-between; margin-bottom: 16px; }
    .brand { display: flex; align-items: center; gap: 10px; }
    .brand-logo { width: 28px; height: 28px; border-radius: 8px; background: radial-gradient(circle at 30% 20%, #ffe27a, #ff4d67); display: flex; align-items: center; justify-content: center; font-size: 16px; }
    .brand-title { font-weight: 600; font-size: 18px; }
    .brand-subtitle { font-size: 12px; color: #a0a7c0; }
    .pill-switch { display: inline-flex; padding: 2px; border-radius: 999px; background: #111827; box-shadow: 0 0 0 1px rgba(255,255,255,0.06); }
    .pill-option { border: none; background: transparent; color: #a0a7c0; font-size: 11px; padding: 4px 10px; border-radius: 999px; cursor: pointer; }
    .pill-option-active { background: linear-gradient(90deg, #f97316, #facc15); color: #111827; font-weight: 600; }
    .tabs { display: flex; gap: 24px; border-bottom: 1px solid rgba(148,163,184,0.3); margin-bottom: 12px; }
    .tab { padding: 8px 0; font-size: 13px; color: #94a3b8; border: none; background: none; cursor: pointer; position: relative; }
    .tab-active { color: #f9fafb; font-weight: 600; }
    .tab-active::after { content: ''; position: absolute; left: 0; right: 0; bottom: -1px; height: 2px; background: linear-gradient(90deg, #22c55e, #3b82f6); border-radius: 999px; }
    .layout { display: flex; gap: 16px; margin-top: 12px; }
    .layout-left { flex: 0 0 320px; }
    .layout-right { flex: 1; display: flex; flex-direction: column; gap: 16px; }
    .card { background: #0b1120; border-radius: 12px; padding: 12px 16px; box-shadow: 0 0 0 1px rgba(15,23,42,0.9), 0 18px 45px rgba(15,23,42,0.8); }
    .card h2 { margin: 0 0 8px 0; font-size: 15px; }
    .metric-row { display: flex; flex-wrap: wrap; gap: 8px 12px; font-size: 12px; }
    .metric-label { color: #9ca3af; }
    .metric-value { font-weight: 500; }
    table { width: 100%; border-collapse: collapse; font-size: 12px; }
    th, td { padding: 4px 6px; text-align: right; border-bottom: 1px solid rgba(15,23,42,0.9); }
    th { text-align: left; font-weight: 500; color: #9ca3af; font-size: 11px; text-transform: uppercase; letter-spacing: 0.04em; }
    tr:nth-child(even) { background: rgba(15,23,42,0.8); }
    .status-ok { color: #4ade80; }
    .status-bad { color: #fb7185; }
    .status-warn { color: #facc15; }
    .pill { display: inline-block; padding: 2px 6px; border-radius: 999px; font-size: 11px; }
    .pill-ok { background: rgba(34,197,94,0.14); color: #4ade80; }
    .pill-bad { background: rgba(248,113,113,0.12); color: #fb7185; }
    .pill-warn { background: rgba(250,204,21,0.14); color: #facc15; }
    .small { font-size: 12px; color: #9ca3af; }
    .tab-content { display: none; }
    .tab-content-active { display: block; }
    .chart-wrapper { height: 260px; }
  </style>
</head>
<body>
  <div class="topbar">
    <div class="brand">
      <div class="brand-logo">AI</div>
      <div>
        <div class="brand-title">tinkoff_bot</div>
        <div class="brand-subtitle">Автономная арена стратегий</div>
      </div>
    </div>
    <div class="pill-switch">
      <button class="pill-option pill-option-active" id="market-ru" type="button">RU рынок</button>
      <button class="pill-option" id="market-us" type="button">US рынок</button>
    </div>
  </div>

  <div class="tabs">
    <button class="tab tab-active" data-tab="evolution" type="button">Эволюция портфеля</button>
    <button class="tab" data-tab="analysis" type="button">Анализ портфеля</button>
  </div>

  <div class="layout">
    <div class="layout-left">
      <div class="card" id="status-card">
        <h2>Статус робота</h2>
        <div id="status-body" class="small">Загрузка…</div>
      </div>
    </div>
    <div class="layout-right">
      <div id="tab-evolution" class="tab-content tab-content-active">
        <div class="card">
          <h2>Общая стоимость портфеля</h2>
          <div class="small" id="equity-subtitle">Equity по дням</div>
          <div class="chart-wrapper">
            <canvas id="equity-chart"></canvas>
          </div>
        </div>
      </div>
      <div id="tab-analysis" class="tab-content">
        <div class="card">
          <h2>Анализ портфеля</h2>
          <table id="portfolio-table">
            <thead>
              <tr>
                <th>Тикер</th>
                <th>Кол-во</th>
                <th>Цена</th>
                <th>Сумма</th>
                <th>Целевой вес</th>
                <th>Стратегия</th>
              </tr>
            </thead>
            <tbody></tbody>
          </table>
        </div>
      </div>
    </div>
  </div>

  <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
  <script src="https://cdn.jsdelivr.net/npm/chartjs-adapter-date-fns@3"></script>
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

    function initTabs() {
      const tabs = document.querySelectorAll('.tab');
      const contents = document.querySelectorAll('.tab-content');
      tabs.forEach(btn => {
        btn.addEventListener('click', () => {
          const tab = btn.dataset.tab;
          tabs.forEach(t => t.classList.toggle('tab-active', t === btn));
          contents.forEach(c => c.classList.toggle('tab-content-active', c.id === 'tab-' + tab));
        });
      });
    }

    async function refresh() {
      try {
        const [status, portfolio, equityHist] = await Promise.all([
          fetchJson('/api/status'),
          fetchJson('/api/portfolio'),
          fetchJson('/api/equity'),
        ]);

        const sEl = document.getElementById('status-body');
        const allowed = status.trading_allowed;
        const riskText = allowed ? '<span class="pill pill-ok">торговля разрешена</span>'
                                 : '<span class="pill pill-bad">торговля остановлена</span>';
        sEl.innerHTML = `
          <div class="metric-row">
            <div><span class="metric-label">Версия</span> <span class="metric-value">${status.version || '?'}</span></div>
            <div><span class="metric-label">Режим</span> <span class="metric-value">${status.mode}</span></div>
            <div><span class="metric-label">Песочница</span> <span class="metric-value">${status.sandbox ? 'Да' : 'Нет'}</span></div>
          </div>
          <div class="metric-row" style="margin-top:6px;">
            <div><span class="metric-label">Equity</span> <span class="metric-value">${fmtMoney(status.equity)} RUB</span></div>
            <div><span class="metric-label">Кэш</span> <span class="metric-value">${fmtMoney(status.cash)} RUB</span></div>
            <div><span class="metric-label">Позиции</span> <span class="metric-value">${status.positions_count}</span></div>
          </div>
          <div class="metric-row" style="margin-top:6px;">
            <div><span class="metric-label">Дневной результат</span> <span class="metric-value">${fmtMoney(status.daily_pnl)} RUB</span></div>
            <div><span class="metric-label">Просадка</span> <span class="metric-value">${fmtPct(status.drawdown_pct)}</span></div>
          </div>
          <div class="small" style="margin-top:6px;">${riskText}</div>
          <div class="small" style="margin-top:6px;">След. ребаланс: ${status.next_rebalance || '-'}, дайджест: ${status.next_digest || '-'}</div>
          <div class="small" style="margin-top:4px; color:#6b7280;">Обновлено (МСК): ${status.updated_at ? new Date(status.updated_at).toLocaleTimeString('ru-RU', { timeZone: 'Europe/Moscow' }) : '—'}</div>
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
            <td>${fmtPct((it.target_weight || 0) * 100)}</td>
            <td style="text-align:left;">${it.strategy || '-'}</td>
          `;
          tbody.appendChild(tr);
        });

        // Эволюция стоимости портфеля: X — дата, Y — equity. Если истории нет — подставляем две точки (вчера + сейчас)
        let pts = equityHist.points || [];
        let usedSynthetic = false;
        if (pts.length === 0 && status.equity != null && status.equity !== undefined) {
          const now = new Date();
          const yesterday = new Date(now);
          yesterday.setDate(yesterday.getDate() - 1);
          pts = [
            { ts: yesterday.toISOString(), equity: status.equity },
            { ts: now.toISOString(), equity: status.equity },
          ];
          usedSynthetic = true;
        }
        const labels = pts.map(p => new Date(p.ts));
        const data = pts.map(p => p.equity);
        const subEl = document.getElementById('equity-subtitle');
        if (subEl) subEl.textContent = usedSynthetic
          ? 'Показано текущее значение (история накапливается каждую минуту)'
          : 'Equity по дням';
        if (!window.equityChart) {
          const ctx = document.getElementById('equity-chart').getContext('2d');
          window.equityChart = new Chart(ctx, {
            type: 'line',
            data: {
              labels,
              datasets: [{
                label: 'Equity, RUB',
                data,
                borderColor: '#38bdf8',
                backgroundColor: 'rgba(56,189,248,0.12)',
                tension: 0.3,
                pointRadius: 0,
              }],
            },
            options: {
              responsive: true,
              maintainAspectRatio: false,
              plugins: { legend: { display: false } },
              scales: {
                x: {
                  type: 'time',
                  time: { unit: 'day', displayFormats: { day: 'dd.MM' } },
                  ticks: { color: '#9ca3af', maxTicksLimit: 10 },
                  grid: { color: 'rgba(15,23,42,0.7)' },
                },
                y: {
                  ticks: { color: '#9ca3af' },
                  grid: { color: 'rgba(15,23,42,0.7)' },
                },
              },
            },
          });
        } else {
          window.equityChart.data.labels = labels;
          window.equityChart.data.datasets[0].data = data;
          window.equityChart.update('none');
        }
      } catch (e) {
        document.getElementById('status-body').innerHTML = '<span class="status-bad">Ошибка загрузки: ' + e.message + '</span>';
      }
    }

    initTabs();
    refresh();
    setInterval(refresh, 5000);
  </script>
</body>
</html>
""".strip()


async def _write_response(
  writer: asyncio.StreamWriter,
  status: int,
  body: bytes,
  content_type: str = "text/plain; charset=utf-8",
  extra_headers: Dict[str, str] | None = None,
) -> None:
  headers = [
    f"HTTP/1.0 {status} {'OK' if status == 200 else 'Error'}\r\n",
    f"Content-Type: {content_type}\r\n",
    "Connection: close\r\n",
    f"Content-Length: {len(body)}\r\n",
  ]
  if extra_headers:
    for k, v in extra_headers.items():
      headers.append(f"{k}: {v}\r\n")
  headers.append("\r\n")
  writer.write("".join(headers).encode("utf-8"))
  writer.write(body)
  await writer.drain()
  try:
    writer.close()
    await writer.wait_closed()
  except Exception:
    pass


def _load_status_snapshot() -> Dict[str, Any] | None:
  """Снимок статуса из основного цикла (актуальные PnL и просадка)."""
  try:
    from pathlib import Path
    snap_file = Path(__file__).resolve().parent / "data" / "status_snapshot.json"
    if not snap_file.exists():
      return None
    data = json.loads(snap_file.read_text(encoding="utf-8"))
    if isinstance(data, dict):
      return data
  except Exception:
    pass
  return None


async def _handle_api_status(broker: "TinkoffBroker | None", cfg: "AppConfig | None") -> Dict[str, Any]:
  """Безопасный статус для дашборда: при любой ошибке возвращает заглушку, а не 500."""
  try:
    from .risk import RiskManager
    cash = 0.0
    equity = 0.0
    positions_count = 0
    daily_pnl = 0.0
    drawdown_pct = 0.0
    trading_allowed = True
    updated_at = datetime.now().isoformat()
    snap = _load_status_snapshot()
    if snap:
      equity = float(snap.get("equity", 0))
      cash = float(snap.get("cash", 0))
      positions_count = int(snap.get("positions_count", 0))
      daily_pnl = float(snap.get("daily_pnl", 0))
      drawdown_pct = float(snap.get("drawdown_pct", 0))
      trading_allowed = bool(snap.get("trading_allowed", True))
      updated_at = str(snap.get("updated_at", updated_at))
    elif broker and cfg:
      try:
        cash = broker.get_cash_balance(cfg.portfolio.base_currency)
        positions = broker.get_portfolio()
        positions_count = len(positions)
        equity = cash + sum(p.value for p in positions.values())
        rm = RiskManager(cfg.risk)
        state = rm.update_equity(equity, equity)
        trading_allowed = cfg.portfolio.trading_enabled and rm.is_trading_allowed(state)
      except Exception as e:
        logger.debug("api_status: broker/risk error: %s", e)
    next_reb = ""
    next_dig = ""
    try:
      now = datetime.now()
      rt = getattr(cfg.portfolio, "rebalance_time", "10:00") if cfg else "10:00"
      dh = getattr(cfg.portfolio, "daily_digest_time", "18:00") if cfg else "18:00"
      rh, rm = map(int, str(rt).split(":"))
      d_h, d_m = map(int, str(dh).split(":"))
      from datetime import timedelta
      nr = now.replace(hour=rh, minute=rm, second=0, microsecond=0)
      if nr <= now:
        nr += timedelta(days=1)
      nd = now.replace(hour=d_h, minute=d_m, second=0, microsecond=0)
      if nd <= now:
        nd += timedelta(days=1)
      next_reb = nr.strftime("%H:%M")
      next_dig = nd.strftime("%H:%M")
    except Exception as e:
      logger.debug("api_status: schedule error: %s", e)
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
      "updated_at": updated_at,
    }
  except Exception as e:
    logger.debug("api_status: fatal error: %s", e)
    return {
      "version": "0.1.0",
      "mode": "sandbox",
      "sandbox": True,
      "equity": 0.0,
      "cash": 0.0,
      "positions_count": 0,
      "daily_pnl": 0.0,
      "drawdown_pct": 0.0,
      "trading_allowed": False,
      "next_rebalance": "",
      "next_digest": "",
      "updated_at": datetime.now().isoformat(),
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


async def _handle_api_equity() -> Dict[str, Any]:
  from .equity_history import load_equity_history
  points = load_equity_history(limit=500)
  return {
    "points": [
      {"ts": p.ts, "equity": p.equity, "cash": p.cash, "positions": p.positions}
      for p in points
    ]
  }


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
      await _write_response(
        writer, 200, DASHBOARD_HTML.encode("utf-8"),
        "text/html; charset=utf-8",
        extra_headers={"Cache-Control": "no-store, no-cache"},
      )
      return
    if "GET /api/status" in line:
      body_obj = await _handle_api_status(broker, cfg)
      body = json.dumps(body_obj, ensure_ascii=False).encode("utf-8")
      await _write_response(writer, 200, body, "application/json; charset=utf-8", extra_headers={"Cache-Control": "no-store, no-cache"})
      return
    if "GET /api/portfolio" in line:
      try:
        body_obj = await _handle_api_portfolio(broker, cfg)
      except Exception as e:
        logger.debug("api/portfolio error: %s", e)
        body_obj = {"instruments": []}
      body = json.dumps(body_obj, ensure_ascii=False).encode("utf-8")
      await _write_response(writer, 200, body, "application/json; charset=utf-8", extra_headers={"Cache-Control": "no-store, no-cache"})
      return
    if "GET /api/equity" in line:
      try:
        body_obj = await _handle_api_equity()
      except Exception as e:
        logger.debug("api/equity error: %s", e)
        body_obj = {"points": []}
      body = json.dumps(body_obj, ensure_ascii=False).encode("utf-8")
      await _write_response(writer, 200, body, "application/json; charset=utf-8", extra_headers={"Cache-Control": "no-store, no-cache"})
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

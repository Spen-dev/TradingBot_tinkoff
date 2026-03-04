"""HTTP health-check и метрики: /health и /metrics для мониторинга."""
from __future__ import annotations

import asyncio
import json
import logging
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
  from .broker import TinkoffBroker
  from .config import AppConfig

logger = logging.getLogger(__name__)


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
    if "GET /metrics" in line:
      try:
        from prometheus_client import generate_latest
        body = generate_latest()
        if not isinstance(body, bytes):
          body = body.encode("utf-8")
        writer.write(
          b"HTTP/1.0 200 OK\r\n"
          b"Content-Type: text/plain; charset=utf-8\r\n"
          b"Connection: close\r\n"
          b"Content-Length: " + str(len(body)).encode() + b"\r\n\r\n"
        )
        writer.write(body)
      except Exception as e:
        logger.debug("Metrics generation error: %s", e)
        writer.write(b"HTTP/1.0 500 Internal Server Error\r\nConnection: close\r\n\r\n")
      await writer.drain()
      try:
        writer.close()
        await writer.wait_closed()
      except Exception:
        pass
      return
    if "GET /health" not in line and "GET / " not in line:
      writer.write(b"HTTP/1.0 404 Not Found\r\nConnection: close\r\n\r\n")
      await writer.drain()
      writer.close()
      return
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
    body = json.dumps({"broker_ok": broker_ok, "config_ok": config_ok, "ready": ready}, ensure_ascii=False)
    writer.write(
      f"HTTP/1.0 {status} {'OK' if status == 200 else 'Service Unavailable'}\r\n"
      "Content-Type: application/json\r\n"
      "Connection: close\r\n"
      f"Content-Length: {len(body.encode('utf-8'))}\r\n\r\n{body}".encode("utf-8")
    )
    await writer.drain()
  except Exception as e:
    logger.debug("Health check error: %s", e)
  finally:
    try:
      writer.close()
      await writer.wait_closed()
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

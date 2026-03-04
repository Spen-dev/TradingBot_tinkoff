"""Уведомления с ограничением частоты и резервной записью в файл."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
  from .telegram_bot import TelegramController

logger = logging.getLogger(__name__)
ALERTS_LOG = Path(__file__).resolve().parent / "data" / "alerts.log"
_cooldown: dict[str, datetime] = {}
_cooldown_minutes = 30


def set_alert_cooldown(minutes: int) -> None:
  global _cooldown_minutes
  _cooldown_minutes = max(1, minutes)


def _should_send(alert_type: str) -> bool:
  now = datetime.now()
  last = _cooldown.get(alert_type)
  if last is None:
    return True
  if (now - last).total_seconds() >= _cooldown_minutes * 60:
    return True
  return False


def _mark_sent(alert_type: str) -> None:
  _cooldown[alert_type] = datetime.now()


def _fallback_write(message: str) -> None:
  ALERTS_LOG.parent.mkdir(parents=True, exist_ok=True)
  with open(ALERTS_LOG, "a", encoding="utf-8") as f:
    f.write(f"{datetime.now().isoformat()} {message}\n")


async def send_alert(
  tg: "TelegramController | None",
  message: str,
  alert_type: str = "default",
  force: bool = False,
) -> bool:
  """Отправить уведомление в Telegram с ограничением частоты. При ошибке — 1–2 повтора с задержкой, затем запись в data/alerts.log."""
  if not force and not _should_send(alert_type):
    return False
  if tg:
    import asyncio
    for attempt in range(3):
      try:
        await tg.send_daily_report(message)
        _mark_sent(alert_type)
        return True
      except Exception as e:
        logger.warning("send_alert attempt %d: %s", attempt + 1, e)
        if attempt < 2:
          await asyncio.sleep(2.0 * (attempt + 1))
  logger.error("Telegram недоступен после 3 попыток, запись в %s: %s", ALERTS_LOG, message)
  _fallback_write(message)
  _mark_sent(alert_type)
  return True


def send_alert_sync(message: str) -> None:
  """Синхронная запись в alerts.log (для использования при падении процесса)."""
  _fallback_write(message)

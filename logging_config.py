"""Структурированное логирование: ротация по дням, хранение 3 месяца."""
from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timedelta
from pathlib import Path

LOG_DIR = Path(__file__).resolve().parent / "data" / "logs"
LOG_FILE = LOG_DIR / "bot.log"
LOG_RETENTION_DAYS = 90  # хранить только последние 3 месяца


class JsonFormatter(logging.Formatter):
  """Формат одной записи в одну строку JSON."""
  def format(self, record: logging.LogRecord) -> str:
    obj = {
      "ts": datetime.utcnow().isoformat() + "Z",
      "level": record.levelname,
      "logger": record.name,
      "msg": record.getMessage(),
    }
    if record.exc_info:
      obj["exc"] = self.formatException(record.exc_info)
    return json.dumps(obj, ensure_ascii=False)


def _cleanup_old_logs() -> None:
  """Удалить файлы логов старше LOG_RETENTION_DAYS."""
  if not LOG_DIR.exists():
    return
  cutoff = datetime.now() - timedelta(days=LOG_RETENTION_DAYS)
  for p in LOG_DIR.glob("bot.log*"):
    if p.name == "bot.log":
      continue
    try:
      if p.stat().st_mtime < cutoff.timestamp():
        p.unlink()
    except Exception:
      pass


def setup_logging(
  json_log: bool = True,
  console: bool = True,
  log_level: str = "INFO",
) -> None:
  """Настроить корневой логгер: ротация по дням, хранить 3 месяца."""
  LOG_DIR.mkdir(parents=True, exist_ok=True)
  _cleanup_old_logs()
  root = logging.getLogger()
  root.setLevel(getattr(logging, log_level.upper(), logging.INFO))
  if root.handlers:
    return
  try:
    from logging.handlers import TimedRotatingFileHandler
    fh = TimedRotatingFileHandler(
      LOG_FILE, when="midnight", interval=1, backupCount=LOG_RETENTION_DAYS, encoding="utf-8",
    )
    fh.suffix = "%Y-%m-%d"
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(JsonFormatter() if json_log else logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
    root.addHandler(fh)
  except Exception:
    pass
  if console:
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    ch.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    root.addHandler(ch)

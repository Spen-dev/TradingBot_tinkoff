"""Структурированное логирование: ротация по дням, автоочистка старых файлов."""
from __future__ import annotations

import json
import logging
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

LOG_DIR = Path(__file__).resolve().parent / "data" / "logs"
LOG_FILE = LOG_DIR / "bot.log"
DEFAULT_LOG_RETENTION_DAYS = 14
_BOT_LOG_DATE_RE = re.compile(r"^bot\.log\.(\d{4}-\d{2}-\d{2})$")


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


def _trim_large_log(path: Path, max_bytes: int, keep_lines: int) -> bool:
  """Обрезать большой лог, оставив последние keep_lines строк. Возвращает True если файл изменён."""
  if not path.exists() or keep_lines <= 0:
    return False
  try:
    if path.stat().st_size <= max_bytes:
      return False
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    if len(lines) <= keep_lines:
      return False
    path.write_text("\n".join(lines[-keep_lines:]) + "\n", encoding="utf-8")
    return True
  except Exception:
    return False


def cleanup_old_logs(retention_days: int | None = None) -> int:
  """Удалить ротированные bot.log.* старше retention_days; обрезать слишком большие служебные логи.

  Вызывается при старте и раз в сутки из планировщика. Возвращает число удалённых файлов.
  """
  days = max(1, int(retention_days or DEFAULT_LOG_RETENTION_DAYS))
  if not LOG_DIR.exists():
    return 0
  cutoff_date = (datetime.now() - timedelta(days=days)).date()
  removed = 0
  for p in list(LOG_DIR.iterdir()):
    if not p.is_file():
      continue
    name = p.name
    if name == "bot.log":
      continue
    m = _BOT_LOG_DATE_RE.match(name)
    if m:
      try:
        file_date = datetime.strptime(m.group(1), "%Y-%m-%d").date()
        if file_date < cutoff_date:
          p.unlink(missing_ok=True)
          removed += 1
        continue
      except ValueError:
        pass
    if name.startswith("bot.log."):
      try:
        if datetime.fromtimestamp(p.stat().st_mtime).date() < cutoff_date:
          p.unlink(missing_ok=True)
          removed += 1
      except Exception:
        pass
  _trim_large_log(LOG_DIR / "rebalance_decisions.log", max_bytes=5 * 1024 * 1024, keep_lines=3000)
  data_dir = LOG_DIR.parent
  _trim_large_log(data_dir / "audit_orders.log", max_bytes=5 * 1024 * 1024, keep_lines=3000)
  return removed


def setup_logging(
  json_log: bool = True,
  console: bool = True,
  log_level: str = "INFO",
  log_retention_days: int | None = None,
) -> None:
  """Настроить корневой логгер: ротация по дням и очистка старых файлов."""
  retention = max(1, int(log_retention_days or DEFAULT_LOG_RETENTION_DAYS))
  LOG_DIR.mkdir(parents=True, exist_ok=True)
  cleanup_old_logs(retention)
  root = logging.getLogger()
  root.setLevel(getattr(logging, log_level.upper(), logging.INFO))
  if root.handlers:
    return
  try:
    from logging.handlers import TimedRotatingFileHandler
    fh = TimedRotatingFileHandler(
      LOG_FILE, when="midnight", interval=1, backupCount=retention, encoding="utf-8",
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

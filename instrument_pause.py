"""Блокировка инструмента по серии убытков: временно не торговать бумагу."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

PAUSE_FILE = Path(__file__).resolve().parent / "data" / "instrument_pause.json"


def _load() -> dict:
  if not PAUSE_FILE.exists():
    return {}
  try:
    data = json.loads(PAUSE_FILE.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}
  except Exception:
    return {}


def _save(data: dict) -> None:
  PAUSE_FILE.parent.mkdir(parents=True, exist_ok=True)
  PAUSE_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def is_paused(figi: str) -> bool:
  until = _load().get(figi)
  if not until:
    return False
  try:
    return datetime.now() < datetime.fromisoformat(until)
  except Exception:
    return False


def set_pause(figi: str, until_iso: str) -> None:
  data = _load()
  data[figi] = until_iso
  _save(data)


def set_pause_hours(figi: str, hours: float) -> None:
  from datetime import timedelta
  until = datetime.now() + timedelta(hours=hours)
  set_pause(figi, until.isoformat())


def clear_pause(figi: str) -> None:
  """Снять паузу по инструменту (для ручной разморозки)."""
  data = _load()
  if figi in data:
    del data[figi]
    _save(data)


def update_pauses(consecutive_per_figi: dict, threshold: int, pause_hours: float) -> list[str]:
  """Установить паузу по figi, где consecutive >= threshold. Возвращает список figi, по которым пауза установлена в этом вызове."""
  from datetime import timedelta
  now = datetime.now()
  until = (now + timedelta(hours=pause_hours)).isoformat()
  data = _load()
  paused: list[str] = []
  for figi, c in consecutive_per_figi.items():
    if c >= threshold:
      current_until = data.get(figi)
      if current_until:
        try:
          if datetime.fromisoformat(current_until) > now:
            # Already paused: keep current value and skip duplicate alert.
            continue
        except Exception:
          pass
      data[figi] = until
      paused.append(figi)
  if paused:
    _save(data)
  return paused

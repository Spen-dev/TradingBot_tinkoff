from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List

_BASE_DIR = Path(__file__).resolve().parent
_DATA_DIR = _BASE_DIR / "data"
_HIST_FILE = _DATA_DIR / "equity_history.jsonl"
_MAX_POINTS = 2000


@dataclass
class EquityPoint:
  ts: str
  equity: float
  cash: float
  positions: int


def _ensure_dir() -> None:
  _DATA_DIR.mkdir(parents=True, exist_ok=True)


def append_equity_point(ts: datetime, equity: float, cash: float, positions: int) -> None:
  """Добавить точку на график equity. Хранит историю в jsonl, максимум _MAX_POINTS последних точек."""
  try:
    _ensure_dir()
    line = json.dumps(
      {
        "ts": ts.isoformat(),
        "equity": float(equity),
        "cash": float(cash),
        "positions": int(positions),
      },
      ensure_ascii=False,
    )
    with open(_HIST_FILE, "a", encoding="utf-8") as f:
      f.write(line + "\n")
  except Exception:
    return
  # Простая обрезка файла: если слишком большой, оставляем последние _MAX_POINTS строк.
  try:
    lines = _HIST_FILE.read_text(encoding="utf-8").splitlines()
    if len(lines) > _MAX_POINTS * 2:
      lines = lines[-_MAX_POINTS:]
      _HIST_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
  except Exception:
    pass


def load_equity_history(limit: int = 500) -> List[EquityPoint]:
  """Загрузить последние limit точек истории equity."""
  if not _HIST_FILE.exists():
    return []
  try:
    lines = _HIST_FILE.read_text(encoding="utf-8").splitlines()
  except Exception:
    return []
  points: List[EquityPoint] = []
  for line in lines[-limit:]:
    try:
      data = json.loads(line)
      points.append(
        EquityPoint(
          ts=str(data.get("ts", "")),
          equity=float(data.get("equity", 0.0)),
          cash=float(data.get("cash", 0.0)),
          positions=int(data.get("positions", 0)),
        )
      )
    except Exception:
      continue
  return points


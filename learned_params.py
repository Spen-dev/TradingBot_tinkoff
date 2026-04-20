"""Хранение параметров стратегий, полученных при самообучении."""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict

from .config import InstrumentConfig

logger = logging.getLogger(__name__)

LEARNED_DIR = Path(__file__).resolve().parent / "learned_params"
LEARNED_FILE = LEARNED_DIR / "params.json"


def _ensure_dir() -> None:
  LEARNED_DIR.mkdir(parents=True, exist_ok=True)


def load_learned_params() -> Dict[str, Dict[str, Any]]:
  """Загрузить сохранённые обученные параметры по figi."""
  if not LEARNED_FILE.exists():
    return {}
  try:
    with open(LEARNED_FILE, "r", encoding="utf-8") as f:
      data = json.load(f)
    return data if isinstance(data, dict) else {}
  except Exception as e:
    logger.warning("Не удалось загрузить learned_params: %s", e)
    return {}


def save_learned_params(all_params: Dict[str, Dict[str, Any]]) -> None:
  """Сохранить обученные параметры по всем figi."""
  _ensure_dir()
  with open(LEARNED_FILE, "w", encoding="utf-8") as f:
    json.dump(all_params, f, ensure_ascii=False, indent=2)


def update_learned_params(figi: str, params: Dict[str, Any]) -> None:
  """Обновить параметры для одного инструмента."""
  current = load_learned_params()
  current[figi] = {**(current.get(figi, {})), **params}
  save_learned_params(current)


def get_effective_params(instrument: InstrumentConfig, learned: Dict[str, Dict[str, Any]], regime: str | None = None) -> Dict[str, Any]:
  """Слить параметры из конфига и обученные. Если regime задан — использовать params_trend/params_range/params_weak_trend при наличии."""
  base = dict(instrument.strategy_params or {})
  override = learned.get(instrument.figi) or {}
  if regime in ("trend", "range", "weak_trend"):
    key = f"params_{regime}"
    if override.get(key):
      return {**base, **override[key]}
    if regime == "weak_trend" and override.get("params_trend"):
      return {**base, **override["params_trend"]}
  return {**base, **override}


def get_effective_strategy(instrument: InstrumentConfig, learned: Dict[str, Dict[str, Any]], regime: str | None = None):
  """Стратегия для инструмента: при regime — strategy_trend/strategy_range/strategy_weak_trend, иначе из learned или конфига."""
  override = learned.get(instrument.figi) or {}
  if regime in ("trend", "range", "weak_trend"):
    key = f"strategy_{regime}"
    if override.get(key):
      return override[key]
    if regime == "weak_trend" and override.get("strategy_trend"):
      return override["strategy_trend"]
  if "strategy" in override:
    return override["strategy"]
  return instrument.strategy


def get_effective_target_weight(instrument: InstrumentConfig, learned: Dict[str, Dict[str, Any]]) -> float:
  """Целевой вес инструмента: из learned (после optimize_weights) или из конфига."""
  override = learned.get(instrument.figi) or {}
  if "target_weight" in override:
    return float(override["target_weight"])
  return instrument.target_weight

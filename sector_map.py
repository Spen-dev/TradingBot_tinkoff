"""Сектора MOEX-кандидатов для лимитов диверсификации."""

from __future__ import annotations

from typing import Dict, List

TICKER_SECTOR: Dict[str, str] = {
  "SBER": "banks",
  "VTBR": "banks",
  "LKOH": "oil",
  "ROSN": "oil",
  "TATN": "oil",
  "TATNP": "oil",
  "NVTK": "oil",
  "GMKN": "metals",
  "NLMK": "metals",
  "CHMF": "metals",
  "PLZL": "metals",
  "MGNT": "consumer",
  "MTSS": "telecom",
  "AFLT": "transport",
  "YNDX": "tech",
  "OZON": "tech",
}


def sector_of(ticker: str) -> str:
  return TICKER_SECTOR.get((ticker or "").upper(), "other")


def _sector_weights(rows: List[dict]) -> Dict[str, float]:
  out: Dict[str, float] = {}
  for row in rows:
    sec = sector_of(row["ticker"])
    out[sec] = out.get(sec, 0.0) + float(row["target_weight"])
  return out


def enforce_sector_caps(
  selections: List[dict],
  max_sector_weight: float,
) -> List[dict]:
  """Ограничивает суммарный вес сектора; излишек — только в сектора с headroom."""
  if max_sector_weight <= 0 or not selections:
    return selections
  cap = max(0.1, min(1.0, max_sector_weight))
  rows = [dict(s) for s in selections]
  for _ in range(20):
    by_sector = _sector_weights(rows)
    worst_sec, worst_w = max(by_sector.items(), key=lambda kv: kv[1])
    if worst_w <= cap + 1e-9:
      break
    scale = cap / worst_w
    for row in rows:
      if sector_of(row["ticker"]) == worst_sec:
        row["target_weight"] = float(row["target_weight"]) * scale
    deficit = 1.0 - sum(float(r["target_weight"]) for r in rows)
    if deficit <= 1e-9:
      continue
    by_sector = _sector_weights(rows)
    headroom = {sec: max(0.0, cap - w) for sec, w in by_sector.items()}
    room_total = sum(headroom.values())
    if room_total <= 1e-9:
      break
    for row in rows:
      sec = sector_of(row["ticker"])
      sec_room = headroom.get(sec, 0.0)
      if sec_room <= 0:
        continue
      sec_w = by_sector.get(sec, 0.0) or 1e-9
      row["target_weight"] = float(row["target_weight"]) + deficit * (sec_room / room_total) * (float(row["target_weight"]) / sec_w)
  total = sum(float(r["target_weight"]) for r in rows) or 1.0
  if total > 1.0 + 1e-6:
    for row in rows:
      row["target_weight"] = float(row["target_weight"]) / total
  return rows

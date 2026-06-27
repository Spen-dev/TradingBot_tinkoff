"""Календарь торгов MOEX (акции, T+): выходные и праздники."""

from __future__ import annotations

from datetime import date

# Официальные нерабочие дни MOEX (акции), 2025–2026. Обновлять при публикации календаря биржи.
_MOEX_HOLIDAYS: frozenset[date] = frozenset({
  # 2025
  date(2025, 1, 1), date(2025, 1, 2), date(2025, 1, 3), date(2025, 1, 6), date(2025, 1, 7), date(2025, 1, 8),
  date(2025, 2, 24), date(2025, 3, 10), date(2025, 5, 1), date(2025, 5, 2), date(2025, 5, 9),
  date(2025, 6, 12), date(2025, 6, 13), date(2025, 11, 3), date(2025, 11, 4), date(2025, 12, 31),
  # 2026
  date(2026, 1, 1), date(2026, 1, 2), date(2026, 1, 7), date(2026, 2, 23), date(2026, 3, 9),
  date(2026, 5, 1), date(2026, 5, 11), date(2026, 6, 12), date(2026, 11, 4), date(2026, 12, 31),
})


def is_moex_equity_trading_day(day: date) -> bool:
  """True — биржа открыта (пн–пт и не праздник MOEX)."""
  if day.weekday() >= 5:
    return False
  return day not in _MOEX_HOLIDAYS

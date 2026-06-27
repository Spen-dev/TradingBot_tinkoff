from datetime import date

from tinkoff_bot.moex_calendar import is_moex_equity_trading_day


def test_weekend_not_trading():
  assert is_moex_equity_trading_day(date(2026, 6, 28)) is False  # Sun


def test_weekday_trading():
  assert is_moex_equity_trading_day(date(2026, 6, 29)) is True  # Mon


def test_holiday_not_trading():
  assert is_moex_equity_trading_day(date(2026, 1, 1)) is False

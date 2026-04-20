"""Вспомогательные функции для Telegram-бота: форматирование чисел, разбивка длинных сообщений."""
from __future__ import annotations

TELEGRAM_MAX_MESSAGE_LENGTH = 4096


def format_money(value: float, currency: str = "₽") -> str:
  """Формат числа: пробелы как разделитель тысяч, запятая для копеек. Например: 1 234,56 ₽."""
  if value != value:  # NaN
    return "—"
  try:
    int_part = int(value)
    dec_part = round((value - int_part) * 100)
    if dec_part >= 100:
      dec_part = 0
      int_part += 1
    elif dec_part < 0:
      dec_part = 0
    s_int = f"{int_part:,}".replace(",", " ")
    return f"{s_int},{dec_part:02d} {currency}".strip()
  except (ValueError, TypeError):
    return f"{value:.2f} {currency}".strip()


def format_pct(value: float) -> str:
  """Проценты с запятой: 12,5%."""
  try:
    return f"{value:.1f}%".replace(".", ",")
  except (ValueError, TypeError):
    return f"{value}%"


def split_message(text: str, max_len: int = TELEGRAM_MAX_MESSAGE_LENGTH) -> list[str]:
  """Разбить длинное сообщение на части не длиннее max_len (по границам строк где возможно)."""
  if len(text) <= max_len:
    return [text] if text else []
  chunks = []
  rest = text
  while rest:
    if len(rest) <= max_len:
      chunks.append(rest)
      break
    chunk = rest[:max_len]
    last_newline = chunk.rfind("\n")
    if last_newline > max_len // 2:
      chunk = chunk[: last_newline + 1]
      rest = rest[last_newline + 1 :]
    else:
      rest = rest[max_len:]
    chunks.append(chunk)
  return chunks

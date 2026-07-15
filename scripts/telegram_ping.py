"""Проверка Telegram: getMe + отправка тестового сообщения admin."""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
  sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")


async def main() -> int:
  from aiogram import Bot

  token = os.getenv("TELEGRAM_TOKEN", "").strip()
  chat_id = int(os.getenv("TELEGRAM_ADMIN_CHAT_ID", "0") or 0)
  if not token or not chat_id:
    print("TELEGRAM_TOKEN или TELEGRAM_ADMIN_CHAT_ID не заданы")
    return 1
  bot = Bot(token=token)
  me = await bot.get_me()
  print(f"bot=@{me.username} id={me.id} admin_chat_id={chat_id}")
  await bot.send_message(chat_id, "🔧 Тест связи: бот на VPS отвечает. Попробуйте /status")
  await bot.session.close()
  print("send_message: ok")
  return 0


if __name__ == "__main__":
  raise SystemExit(asyncio.run(main()))

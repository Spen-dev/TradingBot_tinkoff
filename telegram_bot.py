import asyncio
import logging
from typing import Callable, Awaitable

from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command

from .config import TelegramConfig
from .telegram_utils import split_message

_log = logging.getLogger(__name__)

START_BUTTON_TEXT = "🟢 Старт"
STOP_BUTTON_TEXT = "🛑 СТОП"
POSITIONS_BUTTON_TEXT = "📋 Позиции"
PORTFOLIO_BUTTON_TEXT = "📂 Портфель"
PAUSE_1H_TEXT = "⏸ Пауза 1 ч"
PAUSE_24H_TEXT = "⏸ Пауза 24 ч"


def get_main_keyboard() -> types.ReplyKeyboardMarkup:
  return types.ReplyKeyboardMarkup(
    keyboard=[
      [types.KeyboardButton(text=START_BUTTON_TEXT)],
      [types.KeyboardButton(text="📊 Статус"), types.KeyboardButton(text=POSITIONS_BUTTON_TEXT)],
      [types.KeyboardButton(text=PORTFOLIO_BUTTON_TEXT)],
      [types.KeyboardButton(text=STOP_BUTTON_TEXT)],
    ],
    resize_keyboard=True,
    input_field_placeholder="Команда или кнопка",
  )


class TelegramController:
  def __init__(self, cfg: TelegramConfig):
    self.bot = Bot(token=cfg.token)
    self.dp = Dispatcher()
    self.admin_chat_id = cfg.admin_chat_id
    self._stop_event = asyncio.Event()

    self._on_start: Callable[[], Awaitable[None]] | None = None
    self._on_stop: Callable[[], Awaitable[None]] | None = None
    self._on_status: Callable[[], Awaitable[str]] | None = None
    self._on_rebalance: Callable[[], Awaitable[str]] | None = None
    self._on_positions: Callable[[], Awaitable[str]] | None = None
    self._on_portfolio: Callable[[], Awaitable[str]] | None = None
    self._on_retrain: Callable[[], Awaitable[str]] | None = None
    self._on_select_strategy: Callable[[], Awaitable[str]] | None = None
    self._on_pause: Callable[[float], Awaitable[None]] | None = None
    self._on_unpause: Callable[[str], Awaitable[str]] | None = None
    self._on_help_extra: Callable[[], Awaitable[str]] | None = None
    self._is_started: Callable[[], bool] | None = None
    self._on_confirm: Callable[[str], Awaitable[str | None]] | None = None
    self._get_mode: Callable[[], str] | None = None
    self._on_stop_request: Callable[[], Awaitable[str | None]] | None = None
    self._on_last_errors: Callable[[], Awaitable[str]] | None = None

    self._register_handlers()

  def set_callbacks(
    self,
    on_start: Callable[[], Awaitable[None]],
    on_stop: Callable[[], Awaitable[None]],
    on_status: Callable[[], Awaitable[str]],
    on_rebalance: Callable[[], Awaitable[str]],
    on_positions: Callable[[], Awaitable[str]] | None = None,
    on_portfolio: Callable[[], Awaitable[str]] | None = None,
    on_retrain: Callable[[], Awaitable[str]] | None = None,
    on_select_strategy: Callable[[], Awaitable[str]] | None = None,
    on_pause: Callable[[float], Awaitable[None]] | None = None,
    on_unpause: Callable[[str], Awaitable[str]] | None = None,
    on_help_extra: Callable[[], Awaitable[str]] | None = None,
    is_started: Callable[[], bool] | None = None,
    on_confirm: Callable[[str], Awaitable[str | None]] | None = None,
    get_mode: Callable[[], str] | None = None,
    on_stop_request: Callable[[], Awaitable[str | None]] | None = None,
    on_last_errors: Callable[[], Awaitable[str]] | None = None,
  ) -> None:
    self._on_start = on_start
    self._on_stop = on_stop
    self._on_stop_request = on_stop_request
    self._on_last_errors = on_last_errors
    self._on_status = on_status
    self._on_rebalance = on_rebalance
    self._on_positions = on_positions
    self._on_portfolio = on_portfolio
    self._on_retrain = on_retrain
    self._on_select_strategy = on_select_strategy
    self._on_pause = on_pause
    self._on_unpause = on_unpause
    self._on_help_extra = on_help_extra
    self._is_started = is_started
    self._on_confirm = on_confirm
    self._get_mode = get_mode

  def _register_handlers(self) -> None:
    HELP_TEXT = (
      "📌 Команды бота:\n\n"
      "/start — запуск робота, показ кнопок\n"
      "/stop — приостановка торговли (робот остаётся запущен)\n"
      "/status — текущий статус (портфель, риск, разрешена ли торговля)\n"
      "/rebalance — ручной ребаланс (выставить заявки по текущим сигналам)\n"
      "/retrain — запуск самообучения (пересчёт параметров стратегий)\n"
      "/select_strategy — выбор лучшей стратегии по бэктесту для каждого инструмента\n"
      "/pause [часы] — пауза торговли на N часов (по умолчанию 24)\n"
      "/unpause <тикер> — снять паузу по инструменту, например /unpause VTBR\n"
      "/last_errors — последние строки из лога (ошибки)\n"
      "/help — этот список команд\n\n"
      "Кнопки:\n"
      "🟢 Старт — запуск робота, то же что /start\n"
      "📊 Статус — то же, что /status\n"
      "📋 Позиции — открытые позиции (тикер, количество, сумма)\n"
      "📂 Портфель — целевые веса и текущие веса\n"
      "⏸ Пауза 1 ч / 24 ч — быстрая пауза торговли\n"
      "🛑 СТОП — приостановка торговли (процесс не завершается)\n\n"
      "Полный выход из бота — только через Ctrl+C в терминале."
    )

    @self.dp.message(Command("start"))
    async def cmd_start(msg: types.Message):
      if msg.chat.id != self.admin_chat_id:
        return
      if self._is_started and self._is_started():
        await msg.answer("Робот уже запущен.", reply_markup=get_main_keyboard())
        return
      if self._on_start:
        await self._on_start()
      await msg.answer("Готово. Используйте кнопки ниже.", reply_markup=get_main_keyboard())

    @self.dp.message(lambda m: m.text and m.text.strip() == START_BUTTON_TEXT)
    async def btn_start(msg: types.Message):
      if msg.chat.id != self.admin_chat_id:
        return
      if self._is_started and self._is_started():
        await msg.answer("Робот уже запущен.", reply_markup=get_main_keyboard())
        return
      if self._on_start:
        await self._on_start()
      await msg.answer("Готово. Используйте кнопки ниже.", reply_markup=get_main_keyboard())

    @self.dp.message(Command("help"))
    async def cmd_help(msg: types.Message):
      if msg.chat.id != self.admin_chat_id:
        return
      text = HELP_TEXT
      if self._on_help_extra:
        try:
          extra = await self._on_help_extra()
          if extra:
            text += "\n\n" + extra
        except Exception:
          pass
      await self.answer_chunked(msg, text)

    @self.dp.message(Command("stop"))
    async def cmd_stop(msg: types.Message):
      if msg.chat.id != self.admin_chat_id:
        return
      if self._is_started and not self._is_started():
        await msg.answer("Робот не запущен. Нажмите Старт.")
        return
      if self._on_stop_request:
        reply = await self._on_stop_request()
        if reply is not None:
          await msg.answer(reply)
          return
      await msg.answer("Робот остановлен. Нажмите Старт для запуска снова.")

    @self.dp.message(lambda m: m.text and m.text.strip() == STOP_BUTTON_TEXT)
    async def cmd_stop_button(msg: types.Message):
      if msg.chat.id != self.admin_chat_id:
        return
      if self._is_started and not self._is_started():
        await msg.answer("Робот не запущен. Нажмите Старт.")
        return
      if self._on_stop_request:
        reply = await self._on_stop_request()
        if reply is not None:
          await msg.answer(reply)
          return
      await msg.answer("🛑 Робот остановлен. Нажмите Старт для запуска снова.")

    @self.dp.message(lambda m: m.text and m.text.strip().lower() == "да")
    async def cmd_confirm(msg: types.Message):
      if msg.chat.id != self.admin_chat_id:
        return
      if self._on_confirm:
        reply = await self._on_confirm(msg.text or "")
        if reply:
          await msg.answer(reply)

    @self.dp.message(Command("status"))
    async def cmd_status(msg: types.Message):
      if msg.chat.id != self.admin_chat_id:
        return
      if self._on_status:
        text = await self._on_status()
      else:
        text = "Статус недоступен"
      await self.answer_chunked(msg, text)

    @self.dp.message(lambda m: m.text and m.text.strip() == "📊 Статус")
    async def btn_status(msg: types.Message):
      if msg.chat.id != self.admin_chat_id:
        return
      if self._on_status:
        text = await self._on_status()
      else:
        text = "Статус недоступен"
      await self.answer_chunked(msg, text)

    @self.dp.message(lambda m: m.text and m.text.strip() == POSITIONS_BUTTON_TEXT)
    async def btn_positions(msg: types.Message):
      if msg.chat.id != self.admin_chat_id:
        return
      if self._on_positions:
        text = await self._on_positions()
      else:
        text = "Позиции недоступны"
      await self.answer_chunked(msg, text)

    @self.dp.message(lambda m: m.text and m.text.strip() == PORTFOLIO_BUTTON_TEXT)
    async def btn_portfolio(msg: types.Message):
      if msg.chat.id != self.admin_chat_id:
        return
      if self._on_portfolio:
        text = await self._on_portfolio()
      else:
        text = "Портфель недоступен"
      await self.answer_chunked(msg, text)

    @self.dp.message(Command("rebalance"))
    async def cmd_rebalance(msg: types.Message):
      if msg.chat.id != self.admin_chat_id:
        return
      if self._on_rebalance:
        res = await self._on_rebalance()
      else:
        res = "Ребаланс не настроен"
      await self.answer_chunked(msg, res)

    @self.dp.message(Command("retrain"))
    async def cmd_retrain(msg: types.Message):
      if msg.chat.id != self.admin_chat_id:
        return
      if self._on_retrain:
        await msg.answer("Запуск самообучения…")
        res = await self._on_retrain()
        await self.answer_chunked(msg, res)
      else:
        await msg.answer("Самообучение не настроено")

    @self.dp.message(Command("select_strategy"))
    async def cmd_select_strategy(msg: types.Message):
      if msg.chat.id != self.admin_chat_id:
        return
      if self._on_select_strategy:
        await msg.answer("Выбор лучшей стратегии…")
        res = await self._on_select_strategy()
        await self.answer_chunked(msg, res)
      else:
        await msg.answer("Не настроено.")

    @self.dp.message(Command("pause"))
    async def cmd_pause(msg: types.Message):
      if msg.chat.id != self.admin_chat_id:
        return
      text = (msg.text or "").strip().split()
      hours = 24.0
      if len(text) >= 2:
        try:
          hours = float(text[1])
          hours = max(0.5, min(720, hours))
        except ValueError:
          pass
      if self._on_pause:
        await self._on_pause(hours)
        await msg.answer(f"Пауза на {hours:.0f} ч установлена.")
      else:
        await msg.answer("Команда паузы не настроена.")

    @self.dp.message(Command("unpause"))
    async def cmd_unpause(msg: types.Message):
      if msg.chat.id != self.admin_chat_id:
        return
      text = (msg.text or "").strip().split()
      ticker = (text[1].upper() if len(text) >= 2 else "").strip()
      if not ticker:
        await msg.answer("Укажите тикер: /unpause VTBR")
        return
      if self._on_unpause:
        res = await self._on_unpause(ticker)
        await msg.answer(res)
      else:
        await msg.answer("Команда разморозки не настроена.")

    @self.dp.message(Command("last_errors"))
    async def cmd_last_errors(msg: types.Message):
      if msg.chat.id != self.admin_chat_id:
        return
      if self._on_last_errors:
        text = await self._on_last_errors()
        await self.answer_chunked(msg, text)
      else:
        await msg.answer("Команда недоступна.")

    @self.dp.message(lambda m: m.text and m.text.strip() == PAUSE_1H_TEXT)
    async def btn_pause_1h(msg: types.Message):
      if msg.chat.id != self.admin_chat_id:
        return
      if self._on_pause:
        await self._on_pause(1.0)
        await msg.answer("Пауза на 1 ч установлена.")

    @self.dp.message(lambda m: m.text and m.text.strip() == PAUSE_24H_TEXT)
    async def btn_pause_24h(msg: types.Message):
      if msg.chat.id != self.admin_chat_id:
        return
      if self._on_pause:
        await self._on_pause(24.0)
        await msg.answer("Пауза на 24 ч установлена.")

  async def send_daily_report(self, text: str) -> None:
    """Отправка отчёта; длинные сообщения разбиваются на части до 4096 символов."""
    for chunk in split_message(text):
      await self.bot.send_message(self.admin_chat_id, chunk)

  async def answer_chunked(self, msg: types.Message, text: str) -> None:
    """Ответ в чат с разбивкой длинного текста на несколько сообщений."""
    for chunk in split_message(text):
      await msg.answer(chunk)

  def format_trade_message(
    self,
    ticker: str,
    direction: str,
    quantity: float,
    price: float,
    amount: float,
    commission: float,
    simulation: bool = False,
  ) -> str:
    from datetime import datetime
    now = datetime.now()
    time_str = now.strftime("%H:%M:%S")
    emoji = "🟢" if direction == "ПОКУПКА" else "🔴"
    # Важно: на этом этапе мы знаем только, что ордер успешно принят брокером.
    # Фактическое исполнение (полное/частичное) не проверяется.
    header = "Заявка отправлена"
    if simulation:
      header = "Заявка (симуляция, dry-run)"
    from .telegram_utils import format_money
    return (
      f"{emoji} {header} [{time_str}]\n"
      "───────────────\n"
      f"Тикер: {ticker}\n"
      f"Направление: {direction}\n"
      f"Количество: {quantity}\n"
      f"Цена: {format_money(price)}\n"
      f"Сумма: {format_money(amount)}\n"
      f"Комиссия: {format_money(commission)}\n"
      "───────────────"
    )

  async def send_trade_notification(
    self,
    ticker: str,
    direction: str,
    quantity: float,
    price: float,
    amount: float,
    commission: float,
    simulation: bool = False,
  ) -> None:
    text = self.format_trade_message(ticker, direction, quantity, price, amount, commission, simulation=simulation)
    await self.bot.send_message(self.admin_chat_id, text)

  def request_stop(self) -> None:
    """Вызвать извне для запроса остановки (устанавливает событие)."""
    self._stop_event.set()

  async def run(self) -> None:
    """Запуск бота. Завершится, когда будет нажата кнопка СТОП или вызван /stop."""
    _log.info("Telegram polling запущен; ответы только в чате admin_chat_id=%s", self.admin_chat_id)
    poll_task = asyncio.create_task(self.dp.start_polling(self.bot))
    await self._stop_event.wait()
    poll_task.cancel()
    try:
      await poll_task
    except asyncio.CancelledError:
      pass


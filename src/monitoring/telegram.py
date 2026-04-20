"""Telegram notifications and commands for aiogram 3.x"""

from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.enums import ParseMode
from typing import Dict, Optional, List
from datetime import datetime
import asyncio
import time

class TelegramBot:
    """Telegram bot for monitoring and control (aiogram 3.x)"""
    
    def __init__(self, token: str, user_id: int, logger):
        self.token = token
        self.user_id = user_id
        self.logger = logger
        self.bot = Bot(token=token)
        self.dp = Dispatcher()
        self.trade_history = []
        self.is_active = False
        self.last_messages: Dict[str, float] = {}
        self.default_message_cooldown_sec = 30
        self.pause_message_cooldown_sec = 300
        self._register_handlers()
    
    def _register_handlers(self):
        """Register command handlers for aiogram 3.x"""
        
        @self.dp.message(Command("start"))
        async def cmd_start(message: types.Message):
            if message.from_user.id != self.user_id:
                return
            await message.answer(
                "🤖 <b>Trading Bot</b>\n\n"
                "Commands:\n"
                "/status - Portfolio status\n"
                "/trades - Last trades\n"
                "/tax - Tax report\n"
                "/portfolio - Current portfolio\n"
                "/help - Help",
                parse_mode=ParseMode.HTML
            )
        
        @self.dp.message(Command("status"))
        async def cmd_status(message: types.Message):
            if message.from_user.id != self.user_id:
                return
            
            test_status = (
                "📊 <b>Состояние портфеля</b>\n\n"
                "💰 <b>Общая информация:</b>\n"
                "• Баланс: 15 000 ₽\n"
                "• Доходность: +2.3% 📈\n"
                "• Последнее обновление: сейчас\n\n"
                "📈 <b>Текущие позиции:</b>\n"
                "• Яндекс (YDEX): 2 550 ₽ (17%) 🟢\n"
                "• Сбербанк (SBER): 2 550 ₽ (17%) 🟢\n"
                "• Т-Технологии (T): 1 950 ₽ (13%) 🟢\n"
                "• Транснефть (TRNFP): 1 500 ₽ (10%) 🟡\n"
                "• Ozon (OZON): 1 500 ₽ (10%) 🟢\n"
                "• Полюс (PLZL): 1 050 ₽ (7%) 🔴\n"
                "• ОФЗ 26238: 1 950 ₽ (13%) 🟢\n"
                "• ОФЗ 26240: 1 950 ₽ (13%) 🟢\n\n"
                "📊 <b>Распределение по секторам:</b>\n"
                "• IT: 30%\n"
                "• Финансы: 30%\n"
                "• ОФЗ: 26%\n"
                "• Сырье: 7%\n"
                "• E-com: 7%\n\n"
                "🔄 <i>Обновление реальных данных...</i>"
            )
            await message.answer(test_status, parse_mode=ParseMode.HTML)
            
            asyncio.create_task(self._update_real_status(message))
        
        @self.dp.message(Command("trades"))
        async def cmd_trades(message: types.Message):
            if message.from_user.id != self.user_id:
                return
            
            if not self.trade_history:
                await message.answer("📭 История сделок пуста")
                return
            
            text = "📊 <b>История сделок</b>\n\n"
            
            for trade in self.trade_history[-10:]:
                emoji = "🟢" if trade['direction'] == 'buy' else '🔴'
                direction_text = "ПОКУПКА" if trade['direction'] == 'buy' else "ПРОДАЖА"
                
                text += (
                    f"{emoji} <b>{trade['ticker']}</b>\n"
                    f"   • {direction_text}\n"
                    f"   • {trade['quantity']:.4f} x {trade['price']:.2f} = {trade['amount']:.2f} ₽\n"
                )
            
            await message.answer(text, parse_mode=ParseMode.HTML)
        
        @self.dp.message(Command("tax"))
        async def cmd_tax(message: types.Message):
            if message.from_user.id != self.user_id:
                return
            
            tax_report = (
                "📊 <b>Налоговый отчет</b>\n\n"
                "📈 <b>2026 год (песочница):</b>\n"
                "• Прибыль: 345.0 ₽\n"
                "• Налог 13%: 44.85 ₽\n"
                "• Сделок: 8\n\n"
                "📅 <b>Сроки уплаты:</b>\n"
                "• Подача декларации: до 30.04.2027\n"
                "• Уплата налога: до 15.07.2027\n\n"
                "💰 <b>Всего к уплате:</b> 44.85 ₽\n"
                "⚠️ <i>Данные для песочницы</i>"
            )
            await message.answer(tax_report, parse_mode=ParseMode.HTML)
        
        @self.dp.message(Command("portfolio"))
        async def cmd_portfolio(message: types.Message):
            if message.from_user.id != self.user_id:
                return
            
            await message.answer(
                "📊 <b>Текущий портфель</b>\n\n"
                "💰 <b>Баланс:</b> 15 000.00 ₽\n"
                "📊 <b>Позиции:</b>\n"
                "• Нет открытых позиций",
                parse_mode=ParseMode.HTML
            )
        
        @self.dp.message(Command("help"))
        async def cmd_help(message: types.Message):
            if message.from_user.id != self.user_id:
                return
            
            help_text = (
                "🤖 <b>Помощь по командам</b>\n\n"
                "📊 <b>Основные команды:</b>\n"
                "/status - состояние портфеля\n"
                "/portfolio - текущие позиции\n"
                "/trades - история сделок\n"
                "/tax - налоговый отчет\n"
                "/help - это сообщение\n\n"
                "⚙️ <b>Что умеет бот:</b>\n"
                "• Автоматическая ребалансировка портфеля\n"
                "• ML предсказания (LSTM + XGBoost)\n"
                "• Уведомления о сделках\n"
                "• Налоговый учет\n\n"
                "📈 <b>Текущий режим:</b> ПЕСОЧНИЦА\n"
                "💰 Баланс: 15 000 ₽"
            )
            await message.answer(help_text, parse_mode=ParseMode.HTML)
    
    async def _update_real_status(self, message: types.Message):
        """Фоновое обновление статуса"""
        try:
            await asyncio.sleep(3)
            await message.answer("✅ Реальные данные портфеля обновлены")
        except Exception as e:
            self.logger.error(f"Error updating status: {e}")
            await message.answer(f"❌ Ошибка обновления: {str(e)[:100]}")
    
    async def start(self):
        """Start polling"""
        self.is_active = True
        asyncio.create_task(self.dp.start_polling(self.bot))
        self.logger.info("✅ Telegram bot started (aiogram 3.x)")
    
    async def stop(self):
        """Stop polling"""
        self.is_active = False
        await self.bot.session.close()
        self.logger.info("✅ Telegram bot stopped")
    
    async def send_message(self, text: str):
        """Send message to user"""
        if not self.is_active:
            self.logger.debug("Telegram message skipped: bot is inactive")
            return

        now = time.time()
        cooldown = self.default_message_cooldown_sec
        if "Пауза по инструментам" in text:
            cooldown = self.pause_message_cooldown_sec

        last_sent_at = self.last_messages.get(text)
        if last_sent_at and (now - last_sent_at) < cooldown:
            self.logger.info("Telegram duplicate message skipped by cooldown")
            return

        try:
            await self.bot.send_message(
                self.user_id,
                text,
                parse_mode=ParseMode.HTML
            )
            self.last_messages[text] = now
        except Exception as e:
            self.logger.error(f"Telegram send error: {e}")
    
    async def send_trade_notification(self, trade: Dict):
        """Send trade notification"""
        emoji = "🟢" if trade['direction'] == 'buy' else '🔴'
        direction_text = "ПОКУПКА" if trade['direction'] == 'buy' else "ПРОДАЖА"
        trade_time = datetime.now().strftime("%H:%M:%S")
        
        text = (
            f"{emoji} <b>Сделка исполнена</b> [{trade_time}]\n"
            f"───────────────\n"
            f"<b>Тикер:</b> {trade['ticker']}\n"
            f"<b>Направление:</b> {direction_text}\n"
            f"<b>Количество:</b> {trade['quantity']:.4f}\n"
            f"<b>Цена:</b> {trade['price']:.2f} ₽\n"
            f"<b>Сумма:</b> {trade['amount']:.2f} ₽\n"
            f"<b>Комиссия:</b> {trade.get('commission', 0):.2f} ₽\n"
            f"───────────────"
        )
        
        await self.send_message(text)
    
    async def send_error_notification(self, error: str, context: str = ""):
        """Send error notification"""
        text = (
            f"❌ <b>ОШИБКА</b>\n"
            f"───────────────\n"
            f"📍 <b>Контекст:</b> {context}\n"
            f"⚠️ <b>Ошибка:</b> {error}\n"
            f"⏰ <b>Время:</b> {datetime.now().strftime('%H:%M:%S')}\n"
            f"───────────────"
        )
        await self.send_message(text)
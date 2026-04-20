#!/usr/bin/env python3
import asyncio
import sys
import logging
from datetime import datetime
from typing import Optional

from src.config import Config
from src.utils.logger import SecureLogger
from src.utils.cache import SecureCache
from src.utils.database import SecureDatabase
from src.utils.rate_limiter import RateLimiter
from src.data_sources.tinkoff_client import TinkoffClient
from src.trading.executor import OrderExecutor
from src.trading.portfolio import PortfolioManager
from src.monitoring.telegram import TelegramBot
from src.monitoring.taxes import TaxCalculator
from src.ml.learner import MLLearner

class TradingBot:
    def __init__(self):
        self.config = Config()
        self.logger = SecureLogger("trading_bot", self.config.LOG_PATH)
        self.cache = SecureCache(f"{self.config.DATA_PATH}/cache.pkl")
        self.db = SecureDatabase(self.config.DB_PATH)
        self.db.set_logger(self.logger)
        self.rate_limiter = RateLimiter(max_requests=80)
        
        self.tinkoff: Optional[TinkoffClient] = None
        self.telegram: Optional[TelegramBot] = None
        self.portfolio: Optional[PortfolioManager] = None
        self.executor: Optional[OrderExecutor] = None
        self.tax: Optional[TaxCalculator] = None
        self.ml: Optional[MLLearner] = None
        
        self.running = False
        self.start_time = datetime.now()
        self.trade_count = 0
        self.error_count = 0
    
    async def start(self):
        """Запуск бота"""
        self.logger.info(f"🚀 Запуск AI Trading Bot...")
        
        try:
            # Tinkoff клиент - TinvestPy сам определит режим!
            self.logger.info("📡 Создание Tinkoff клиента...")
            self.tinkoff = await TinkoffClient.create(
                token=self.config.tinkoff_token,
                account_id=None,
                logger=self.logger,
                rate_limiter=self.rate_limiter,
                cache=self.cache
            )
            
            # Определяем режим работы
            mode = self.tinkoff.get_mode()
            mode_text = "🧪 ПЕСОЧНИЦА" if mode == "sandbox" else "💰 РЕАЛЬНЫЙ СЧЕТ"
            
            # Telegram
            self.logger.info("📱 Запуск Telegram бота...")
            self.telegram = TelegramBot(
                token=self.config.TELEGRAM_TOKEN,
                user_id=self.config.TELEGRAM_USER_ID,
                logger=self.logger
            )
            await self.telegram.start()
            
            # Portfolio manager
            self.logger.info("📊 Инициализация Portfolio Manager...")
            self.portfolio = PortfolioManager(self.config, self.logger, self.db)
            self.portfolio.set_telegram(self.telegram)
            
            # Order executor
            self.logger.info("💹 Инициализация Order Executor...")
            self.executor = OrderExecutor(self.tinkoff, self.config, self.logger, self.db)
            
            # Tax calculator
            self.tax = TaxCalculator()
            
            # ML models
            self.logger.info("🧠 Загрузка ML моделей...")
            self.ml = MLLearner(self.config, self.logger)
            try:
                self.ml.load_models(self.config.MODELS_PATH)
                self.logger.info("✅ ML модели загружены")
            except Exception as e:
                self.logger.error(f"❌ Ошибка загрузки ML моделей: {e}")
                raise
            
            self.running = True
            
            # Отправляем приветствие в Telegram
            if self.telegram:
                await self.telegram.send_message(
                    f"🤖 <b>AI Trading Bot запущен</b>\n"
                    f"━━━━━━━━━━━━━━━━━━━\n"
                    f"📊 <b>Параметры:</b>\n"
                    f"• Режим: {mode_text}\n"
                    f"• Целевой портфель: {self.config.PORTFOLIO_SIZE} ₽\n"
                    f"• Ребалансировка: {self.config.REBALANCE_THRESHOLD}%\n"
                    f"• ML модели: активны\n"
                    f"━━━━━━━━━━━━━━━━━━━\n"
                    f"⏱️ Время запуска: {self.start_time.strftime('%H:%M:%S')}"
                )
            
            self.logger.info("✅ Бот успешно запущен")
            
        except Exception as e:
            self.logger.error(f"❌ Критическая ошибка запуска: {e}")
            await self.stop()
            raise
    
    async def trading_cycle(self):
        """Торговый цикл"""
        self.logger.info("📊 Торговый цикл начат")
        
        try:
            # ML предсказание
            prediction = await self.ml.predict_market()
            if prediction['confidence'] > 0.7 and self.telegram:
                await self.telegram.send_message(
                    f"🎯 <b>ML сигнал</b>\n"
                    f"━━━━━━━━━━━━━━━━━━━\n"
                    f"Действие: {prediction['action']}\n"
                    f"Уверенность: {prediction['confidence']:.1%}\n"
                    f"Прогноз: {prediction.get('price_change_pred', 0):.2f}%\n"
                    f"Режим: {prediction.get('regime', 'unknown')}\n"
                    f"━━━━━━━━━━━━━━━━━━━"
                )
            
            # Проверка портфеля и ребалансировка
            trades = await self.portfolio.check_rebalance(self.executor)
            
            if trades:
                self.trade_count += len(trades)
                self.logger.info(f"✅ Выполнено сделок: {len(trades)}")
            
            # Напоминание о налогах
            reminder = self.tax.get_payment_reminder()
            if reminder and self.telegram:
                await self.telegram.send_message(reminder)
            
            self.logger.info(f"✅ Торговый цикл завершен. Всего сделок: {self.trade_count}")
            
        except Exception as e:
            self.error_count += 1
            self.logger.error(f"❌ Ошибка в торговом цикле: {e}")
            if self.telegram:
                await self.telegram.send_error_notification(str(e), "Trading Cycle")
    
    async def run(self):
        """Основной цикл"""
        try:
            await self.start()
            
            while self.running:
                try:
                    await self.trading_cycle()
                    
                    if datetime.now().minute == 0:
                        await self.send_status_report()
                    
                    for _ in range(60):
                        if not self.running:
                            break
                        await asyncio.sleep(1)
                    
                except asyncio.CancelledError:
                    self.logger.info("⚠️ Торговый цикл отменен")
                    break
                except Exception as e:
                    self.error_count += 1
                    self.logger.error(f"❌ Ошибка в основном цикле: {e}")
                    if self.telegram:
                        await self.telegram.send_error_notification(str(e), "Main Loop")
                    
                    if self.error_count > 10:
                        self.logger.error("❌ Слишком много ошибок, остановка")
                        break
                    
                    await asyncio.sleep(60)
                    
        except KeyboardInterrupt:
            self.logger.info("🛑 Получен сигнал остановки (Ctrl+C)")
        except Exception as e:
            self.logger.error(f"❌ Критическая ошибка: {e}")
        finally:
            await self.stop()
    
    async def send_status_report(self):
        """Отправка статусного отчета"""
        try:
            uptime = datetime.now() - self.start_time
            hours = uptime.total_seconds() / 3600
            minutes = (uptime.total_seconds() % 3600) / 60
            
            # Получаем текущий баланс из API
            balance = await self.tinkoff.get_account_balance() if self.tinkoff else 0
            
            mode = self.tinkoff.get_mode() if self.tinkoff else "unknown"
            mode_text = "🧪 ПЕСОЧНИЦА" if mode == "sandbox" else "💰 РЕАЛЬНЫЙ"
            
            status = (
                f"📊 <b>Статус бота</b>\n"
                f"━━━━━━━━━━━━━━━━━━━\n"
                f"🔄 <b>Режим:</b> {mode_text}\n"
                f"⏱️ <b>Время работы:</b> {int(hours)} ч {int(minutes)} мин\n"
                f"💰 <b>Баланс:</b> {balance:.2f} ₽\n"
                f"📈 <b>Сделок:</b> {self.trade_count}\n"
                f"❌ <b>Ошибок:</b> {self.error_count}\n"
                f"⚙️ <b>Ребалансировка:</b> {self.config.REBALANCE_THRESHOLD}%\n"
                f"━━━━━━━━━━━━━━━━━━━"
            )
            
            if self.telegram:
                await self.telegram.send_message(status)
            
        except Exception as e:
            self.logger.error(f"❌ Ошибка отправки статуса: {e}")
    
    async def stop(self):
        """Остановка бота"""
        self.logger.info("🛑 Остановка бота...")
        self.running = False
        
        try:
            if self.telegram:
                await self.telegram.send_message(
                    f"🛑 <b>Бот остановлен</b>\n"
                    f"━━━━━━━━━━━━━━━━━━━\n"
                    f"📊 Статистика сессии:\n"
                    f"• Сделок: {self.trade_count}\n"
                    f"• Ошибок: {self.error_count}\n"
                    f"• Время работы: {self._get_uptime_string()}\n"
                    f"━━━━━━━━━━━━━━━━━━━"
                )
                await self.telegram.stop()
                self.logger.info("✅ Telegram остановлен")
            
            if self.tinkoff:
                await self.tinkoff.close()
                self.logger.info("✅ Tinkoff клиент закрыт")
            
            if self.db:
                self.db.close()
                self.logger.info("✅ База данных закрыта")
            
            if self.ml:
                self.ml.save_models(self.config.MODELS_PATH)
                self.logger.info("✅ ML модели сохранены")
            
            self.logger.info("✅ Бот успешно остановлен")
            
        except Exception as e:
            self.logger.error(f"❌ Ошибка при остановке: {e}")
    
    def _get_uptime_string(self) -> str:
        uptime = datetime.now() - self.start_time
        hours = int(uptime.total_seconds() / 3600)
        minutes = int((uptime.total_seconds() % 3600) / 60)
        
        if hours > 0:
            return f"{hours} ч {minutes} мин"
        else:
            return f"{minutes} мин"

async def main():
    bot = None
    try:
        bot = TradingBot()
        await bot.run()
    except KeyboardInterrupt:
        logging.info("🛑 Получен сигнал остановки")
        if bot:
            await bot.stop()
    except Exception as e:
        logging.error(f"❌ Критическая ошибка: {e}")
        if bot:
            await bot.stop()

if __name__ == "__main__":
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
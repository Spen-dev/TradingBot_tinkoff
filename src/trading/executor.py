"""Исполнение сделок через tinvest"""

from typing import Optional, Dict, List
from datetime import datetime

class OrderExecutor:
    """Исполнитель ордеров через tinvest"""
    
    def __init__(self, tinkoff, config, logger, db):
        self.tinkoff = tinkoff
        self.config = config
        self.logger = logger
        self.db = db
        self.trade_history: List[Dict] = []
    
    async def get_portfolio(self) -> Dict:
        """Получить портфель"""
        self.logger.info("📊 Запрос портфеля...")
        portfolio = await self.tinkoff.get_portfolio()
        self.logger.info(f"💰 Баланс: {portfolio['cash']:.2f} ₽")
        return portfolio
    
    async def get_price(self, ticker: str) -> Optional[float]:
        """Получить цену"""
        price = await self.tinkoff.get_current_price(ticker)
        if price:
            self.logger.info(f"💰 {ticker}: {price:.2f} ₽")
        return price
    
    async def execute_trade(self, ticker: str, quantity: float, direction: str) -> Optional[Dict]:
        """Исполнить сделку"""
        self.logger.info(f"💹 Исполнение: {direction} {quantity:.4f} {ticker}")
        
        if quantity <= 0:
            self.logger.error(f"❌ Неверное количество: {quantity}")
            return None
        
        if direction not in ['buy', 'sell']:
            self.logger.error(f"❌ Неверное направление: {direction}")
            return None
        
        try:
            price = await self.get_price(ticker)
            if not price:
                self.logger.error(f"❌ Нет цены для {ticker}")
                return None
            
            amount = quantity * price
            min_amount = getattr(self.config, 'MIN_TRADE_AMOUNT', 500)
            
            if amount < min_amount:
                self.logger.warning(f"⚠️ Сумма {amount:.2f} меньше минимума {min_amount}")
                return None
            
            result = await self.tinkoff.place_order(ticker, quantity, direction)
            
            if result:
                self.trade_history.append(result)
                self.db.save_trade(result)
                self.logger.info(f"✅ Сделка исполнена: {direction} {quantity:.4f} {ticker}")
                return result
            else:
                self.logger.error(f"❌ Ошибка исполнения: {ticker}")
                return None
            
        except Exception as e:
            self.logger.error(f"❌ Ошибка сделки: {e}")
            return None
    
    async def execute_buy(self, ticker: str, quantity: float) -> Optional[Dict]:
        """Купить"""
        return await self.execute_trade(ticker, quantity, 'buy')
    
    async def execute_sell(self, ticker: str, quantity: float) -> Optional[Dict]:
        """Продать"""
        return await self.execute_trade(ticker, quantity, 'sell')
    
    async def get_trade_history(self, limit: int = 10) -> List[Dict]:
        """История сделок"""
        return self.trade_history[-limit:]
    
    async def get_trades_count(self) -> int:
        """Количество сделок"""
        return len(self.trade_history)
    
    async def get_total_volume(self) -> float:
        """Общий объем"""
        return sum(trade.get('amount', 0) for trade in self.trade_history)
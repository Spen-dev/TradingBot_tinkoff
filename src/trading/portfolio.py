"""Portfolio management and rebalancing"""

from typing import Dict, List, Optional
from datetime import datetime

class PortfolioManager:
    """Manages portfolio composition and rebalancing"""
    
    def __init__(self, config, logger, db):
        self.config = config
        self.logger = logger
        self.db = db
        self.positions = {}
        self.cash = 0
        self.total_value = 0
        self.telegram = None
        self.last_rebalance = None
        self.rebalance_count = 0
    
    def set_telegram(self, telegram_bot):
        """Устанавливает ссылку на Telegram бота"""
        self.telegram = telegram_bot
        self.logger.info("✅ Telegram bot connected to PortfolioManager")
    
    async def check_rebalance(self, executor) -> List[Dict]:
        """Проверяет необходимость ребалансировки и исполняет сделки"""
        self.logger.info("🔄 Checking portfolio rebalance...")
        
        # Получаем текущий портфель
        portfolio = await executor.get_portfolio()
        self.cash = portfolio['cash']
        self.total_value = portfolio['total_value']
        self.positions = portfolio['positions']
        
        self.logger.info(f"📊 Current portfolio: cash={self.cash:.2f} ₽, total={self.total_value:.2f} ₽")
        
        if not self.positions:
            self.logger.info("📈 No open positions")
        
        # Рассчитываем целевые распределения
        trades_needed = []
        executed_trades = []
        
        for ticker, info in self.config.PORTFOLIO.items():
            target_share = info['target']
            current_value = self.positions.get(ticker, {}).get('value', 0)
            target_value = self.total_value * target_share
            
            diff = target_value - current_value
            threshold = self.config.REBALANCE_THRESHOLD
            deviation_percent = (abs(diff) / target_value * 100) if target_value > 0 else 0
            
            if deviation_percent > threshold:
                direction = 'buy' if diff > 0 else 'sell'
                amount = abs(diff)
                
                price = await executor.get_price(ticker)
                quantity = amount / price
                
                self.logger.info(
                    f"📊 {ticker}: target={target_value:.2f} ({target_share*100:.0f}%), "
                    f"current={current_value:.2f}, diff={diff:.2f} ({direction}), "
                    f"deviation={deviation_percent:.1f}%"
                )
                
                trades_needed.append({
                    'ticker': ticker,
                    'direction': direction,
                    'quantity': quantity,
                    'amount': amount,
                    'price': price,
                    'deviation': deviation_percent
                })
        
        # Исполняем сделки
        for trade in trades_needed:
            try:
                self.logger.info(f"💹 Executing {trade['direction']} {trade['quantity']:.4f} {trade['ticker']} at {trade['price']:.2f} ₽")
                
                result = await executor.execute_trade(
                    ticker=trade['ticker'],
                    quantity=trade['quantity'],
                    direction=trade['direction']
                )
                
                if result:
                    executed_trades.append(result)
                    self.db.save_trade(result)
                    
                    if self.telegram:
                        await self.telegram.send_trade_notification(result)
                    
                    self.rebalance_count += 1
                    self.logger.info(f"✅ Trade executed: {trade['direction']} {trade['quantity']:.4f} {trade['ticker']}")
                else:
                    self.logger.error(f"❌ Trade failed: {trade['direction']} {trade['quantity']:.4f} {trade['ticker']}")
                
            except Exception as e:
                self.logger.error(f"❌ Error executing trade for {trade['ticker']}: {e}")
        
        # Сохраняем снимок портфеля
        if self.total_value > 0:
            self.db.save_snapshot(self.total_value, self.cash, self.positions)
        
        self.last_rebalance = datetime.now()
        self.logger.info(f"✅ Rebalance complete. {len(executed_trades)} trades executed.")
        
        return executed_trades
    
    # ... остальные методы остаются без изменений, но без заглушек
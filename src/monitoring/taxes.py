"""Tax calculation and reporting

Модуль для автоматического расчета налогов от торговли на бирже.
Ставка налога: 13% (для резидентов РФ)
Сроки: подача декларации до 30 апреля, уплата до 15 июля
"""

from datetime import datetime
from typing import Dict, List, Optional

class TaxCalculator:
    """Calculate taxes for trading
    
    Автоматически отслеживает все сделки и рассчитывает налог к уплате.
    Напоминает о приближении сроков уплаты.
    """
    
    def __init__(self, tax_rate: float = 0.13):
        """
        Args:
            tax_rate: Ставка налога (13% по умолчанию)
        """
        self.tax_rate = tax_rate
        self.trades: List[Dict] = []
    
    def add_trade(self, trade: Dict):
        """Add trade to tax calculation
        
        Args:
            trade: Словарь с информацией о сделке
        """
        self.trades.append({
            'date': trade.get('timestamp', datetime.now()),
            'ticker': trade['ticker'],
            'buy': trade.get('buy_amount', 0),
            'sell': trade.get('sell_amount', 0),
            'commission': trade.get('commission', 0),
            'direction': trade.get('direction')
        })
    
    def calculate_profit(self, year: Optional[int] = None) -> Dict:
        """Calculate profit for a given year
        
        Args:
            year: Год для расчета (если None - текущий год)
            
        Returns:
            Dict с информацией о прибыли и налоге
        """
        year = year or datetime.now().year
        
        buy_total = 0.0
        sell_total = 0.0
        commission_total = 0.0
        
        for trade in self.trades:
            if trade['date'].year == year:
                if trade['direction'] == 'buy':
                    buy_total += trade.get('amount', 0)
                else:
                    sell_total += trade.get('amount', 0)
                commission_total += trade.get('commission', 0)
        
        profit = sell_total - buy_total - commission_total
        
        return {
            'year': year,
            'profit': round(profit, 2),
            'tax': round(profit * self.tax_rate if profit > 0 else 0, 2),
            'trades_count': len([t for t in self.trades if t['date'].year == year])
        }
    
    def get_payment_reminder(self) -> Optional[str]:
        """Get tax payment reminder if needed
        
        Проверяет, не приближается ли срок уплаты налогов.
        Возвращает напоминание за 30, 14, 7, 3, 1 день до дедлайна.
        
        Returns:
            str: Текст напоминания или None если еще рано
        """
        now = datetime.now()
        
        # Check if we're in tax season (January-July)
        if now.month > 7:
            return None
        
        data = self.calculate_profit(now.year - 1)
        
        if data['tax'] <= 0:
            return None
        
        deadline = datetime(now.year, 7, 15)
        days_left = (deadline - now).days
        
        # Напоминаем только когда осталось мало времени
        if days_left in [30, 14, 7, 3, 1] or days_left < 0:
            urgency = "⚠️" if days_left < 7 else "📅"
            return (
                f"{urgency} <b>Tax Reminder</b>\n\n"
                f"Year {now.year - 1}:\n"
                f"Profit: {data['profit']:,.2f} ₽\n"
                f"Tax due: {data['tax']:,.2f} ₽\n\n"
                f"Days left: {days_left}\n"
                f"Deadline: July 15, {now.year}"
            )
        
        return None
"""Вспомогательные функции для работы с песочницей Tinkoff"""

from tinkoff.invest import SandboxClient
from tinkoff.invest.utils import decimal_to_quotation, quotation_to_decimal
import asyncio
import logging

class SandboxHelper:
    """Класс для управления песочницей"""
    
    def __init__(self, token: str, logger: logging.Logger):
        self.token = token
        self.logger = logger
        self.client = None
        self.account_id = None
    
    async def __aenter__(self):
        self.client = SandboxClient(token=self.token)
        await self.client.__aenter__()
        return self
    
    async def __aexit__(self, *args):
        await self.client.__aexit__(*args)
    
    async def create_account(self, initial_balance: float = 15000) -> str:
        """Создает счет в песочнице с начальным балансом"""
        
        self.logger.info("🏦 Создание счета в песочнице...")
        
        # Открываем счет
        account = await self.client.sandbox.open_sandbox_account()
        self.account_id = account.account_id
        self.logger.info(f"✅ Счет создан: {self.account_id}")
        
        # Пополняем счет
        await self.client.sandbox.sandbox_pay_in(
            account_id=self.account_id,
            amount=initial_balance,
            currency='rub'
        )
        self.logger.info(f"💰 Пополнен на {initial_balance} ₽")
        
        return self.account_id
    
    async def get_accounts(self):
        """Получает список счетов в песочнице"""
        accounts = await self.client.sandbox.get_sandbox_accounts()
        return accounts.accounts
    
    async def close_account(self, account_id: str = None):
        """Закрывает счет в песочнице"""
        acc_id = account_id or self.account_id
        if acc_id:
            await self.client.sandbox.close_sandbox_account(account_id=acc_id)
            self.logger.info(f"🗑️ Счет {acc_id} закрыт")
    
    async def get_portfolio(self, account_id: str = None):
        """Получает состояние портфеля в песочнице"""
        acc_id = account_id or self.account_id
        portfolio = await self.client.sandbox.get_sandbox_portfolio(
            account_id=acc_id
        )
        return portfolio
    
    async def pay_in(self, amount: float, account_id: str = None):
        """Пополняет счет в песочнице"""
        acc_id = account_id or self.account_id
        await self.client.sandbox.sandbox_pay_in(
            account_id=acc_id,
            amount=amount,
            currency='rub'
        )
        self.logger.info(f"💰 Пополнено на {amount} ₽")

# Функция для быстрого создания счета
async def setup_sandbox(token: str, initial_balance: float = 15000) -> str:
    """Быстрая настройка песочницы"""
    async with SandboxHelper(token, logging.getLogger()) as helper:
        account_id = await helper.create_account(initial_balance)
        return account_id
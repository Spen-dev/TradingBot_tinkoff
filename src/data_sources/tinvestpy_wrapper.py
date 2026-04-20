"""Обёртка для TinvestPy с прямым использованием токена (без хранилища)"""

import json
import requests
from typing import Optional, Dict

class TinvestPyDirect:
    """Прямой клиент TinvestPy без системного хранилища"""
    
    def __init__(self, token: str):
        self.token = token
        self.base_url = "https://invest-public-api.tinkoff.ru/rest"
        self.sandbox_url = "https://sandbox-invest-public-api.tinkoff.ru/rest"
        self.use_sandbox = "sandbox" in token.lower()  # Простое определение
        
    def _get_url(self, method: str) -> str:
        """Получает правильный URL для метода"""
        base = self.sandbox_url if self.use_sandbox else self.base_url
        return f"{base}/tinkoff.public.invest.api.contract.v1.{method}"
    
    def _make_request(self, method: str, data: dict = None) -> dict:
        """Делает запрос к API"""
        url = self._get_url(method)
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
            "Accept": "application/json"
        }
        
        response = requests.post(url, headers=headers, json=data or {})
        
        if response.status_code != 200:
            raise Exception(f"Ошибка {response.status_code}: {response.text}")
        
        return response.json()
    
    def get_info(self) -> dict:
        """Получает информацию о счетах"""
        return self._make_request("UsersService/GetAccounts")
    
    def get_portfolio(self, account_id: str = "") -> dict:
        """Получает портфель"""
        return self._make_request("OperationsService/GetPortfolio", {
            "accountId": account_id
        })
    
    def get_last_price(self, ticker: str) -> Optional[float]:
        """Получает последнюю цену по тикеру"""
        # Здесь нужно получить FIGI по тикеру
        # Упрощённо для теста
        return 100.0
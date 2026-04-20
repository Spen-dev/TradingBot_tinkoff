"""Упрощенная версия TinvestPy для песочницы"""

import requests
from datetime import datetime

class SimpleTinvestPy:
    """Упрощенный клиент TinvestPy"""
    
    def __init__(self, token, account_id=None):
        self.token = token
        self.account_id = account_id or 'sandbox_default'
        self.base_url = "https://sandbox-invest-public-api.tinkoff.ru/rest"
        
    def _request(self, method, data=None):
        """Отправляет запрос к API"""
        url = f"{self.base_url}/tinkoff.public.invest.api.contract.v1.{method}"
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json"
        }
        
        response = requests.post(url, headers=headers, json=data or {})
        
        if response.status_code != 200:
            return None
            
        return response.json()
    
    def get_portfolio(self):
        """Получает портфель"""
        return self._request("OperationsService/GetPortfolio", {
            "accountId": self.account_id
        })
    
    def get_last_price(self, ticker):
        """Получает последнюю цену"""
        # Для теста возвращаем заглушку
        prices = {
            "SBER": 313.61,
            "YDEX": 4730.00,
            "T": 3431.20,
            "OZON": 4664.50,
            "PLZL": 2510.00,
            "TRNFP": 1414.80
        }
        return prices.get(ticker, 100.0)
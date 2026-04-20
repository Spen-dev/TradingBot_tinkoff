import os
from typing import Dict, Any, Optional
from pydantic import validator
from pydantic_settings import BaseSettings

class Config(BaseSettings):
    # ========== РЕЖИМ РАБОТЫ ==========
    MODE: str = "sandbox"  # "sandbox", "prod"
    
    # ========== API KEYS ==========
    # Токен для песочницы
    TINKOFF_TOKEN_SANDBOX: Optional[str] = None
    
    # ========== TELEGRAM ==========
    TELEGRAM_TOKEN: str
    TELEGRAM_USER_ID: int
    
    # ========== ПАРАМЕТРЫ ПОРТФЕЛЯ ==========
    INITIAL_BALANCE: float = 15000
    PORTFOLIO_SIZE: float = 15000
    REBALANCE_THRESHOLD: float = 10
    
    # ========== ПОРТФЕЛЬ ==========
    PORTFOLIO: Dict[str, Dict[str, Any]] = {
        "YDEX": {"name": "Яндекс", "target": 0.17, "sector": "IT"},
        "SBER": {"name": "Сбербанк", "target": 0.17, "sector": "Finance"},
        "T": {"name": "Т-Технологии", "target": 0.13, "sector": "Fintech"},
        "TRNFP": {"name": "Транснефть ап", "target": 0.10, "sector": "Infra"},
        "OZON": {"name": "Ozon", "target": 0.10, "sector": "E-com"},
        "PLZL": {"name": "Полюс", "target": 0.07, "sector": "Gold"},
        "SU26238RMFS4": {"name": "ОФЗ 26238", "target": 0.13, "type": "bond"},
        "SU26240RMFS0": {"name": "ОФЗ 26240", "target": 0.13, "type": "bond"},
    }
    
    # ========== ПУТИ ==========
    DATA_PATH: str = "/data"
    LOG_PATH: str = "/logs"
    MODELS_PATH: str = "/models"
    DB_PATH: str = "/data/trading_bot.db"
    
    @property
    def tinkoff_token(self) -> str:
        """Возвращает токен для Tinkoff API"""
        if not self.TINKOFF_TOKEN_SANDBOX:
            raise ValueError("❌ TINKOFF_TOKEN_SANDBOX не задан в .env")
        return self.TINKOFF_TOKEN_SANDBOX
    
    @property
    def account_id(self) -> Optional[str]:
        """ID счета (для совместимости)"""
        return None  # TinvestPy не требует account_id
    
    @property
    def is_sandbox(self) -> bool:
        """Проверка режима"""
        return self.MODE == "sandbox"
    
    @validator('MODE')
    def validate_mode(cls, v):
        """Проверка режима работы"""
        if v not in ["sandbox"]:
            raise ValueError('MODE должен быть "sandbox"')
        return v
    
    @validator('INITIAL_BALANCE')
    def validate_initial_balance(cls, v):
        """Проверка начального баланса"""
        if v < 1000:
            raise ValueError("Начальный баланс должен быть не менее 1000 ₽")
        return v
    
    @validator('PORTFOLIO_SIZE')
    def validate_portfolio_size(cls, v):
        """Проверка размера портфеля"""
        if v < 1000:
            raise ValueError("Размер портфеля должен быть не менее 1000 ₽")
        return v
    
    @validator('REBALANCE_THRESHOLD')
    def validate_threshold(cls, v):
        """Проверка порога ребалансировки"""
        if v < 1 or v > 50:
            raise ValueError("Порог ребалансировки должен быть от 1% до 50%")
        return v
    
    class Config:
        env_file = '.env'
        env_file_encoding = 'utf-8'
        case_sensitive = True
        extra = 'ignore'
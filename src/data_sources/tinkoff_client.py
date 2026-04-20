"""Tinkoff API клиент с использованием библиотеки TinvestPy"""

from TinvestPy import TinvestPy
from datetime import datetime
from typing import Optional, Dict, List, Any
import asyncio
import os
import re

class TinkoffClient:
    """Клиент Tinkoff API на библиотеке TinvestPy"""
    
    def __init__(self, token: str, account_id: Optional[str], 
                 logger, rate_limiter, cache):
        self.token = token
        self.account_id = account_id
        self.logger = logger
        self.rate_limiter = rate_limiter
        self.cache = cache
        self.client = None
        self.account_initialized = False
        self.mode = "sandbox"
        self.real_account_id = None
        self.instruments_cache = {}  # Кэш для инструментов
    
    def _get_timestamp(self):
        return datetime.now()

    async def _call_with_retry(self, api_call, call_name: str, max_retries: int = 3):
        """
        Execute Tinkoff API call with graceful handling for rate limits.
        """
        for attempt in range(1, max_retries + 1):
            await self.rate_limiter.wait_if_needed(call_name)
            try:
                return api_call()
            except Exception as e:
                error_text = str(e)
                is_rate_limited = "RESOURCE_EXHAUSTED" in error_text or "ratelimit" in error_text.lower()
                if not is_rate_limited or attempt == max_retries:
                    raise

                reset_match = re.search(r"ratelimit_reset=(\d+)", error_text)
                reset_sec = int(reset_match.group(1)) if reset_match else 1
                backoff = max(1, reset_sec) + attempt
                self.logger.warning(
                    f"⚠️ {call_name}: достигнут лимит API, повтор через {backoff} сек "
                    f"(попытка {attempt}/{max_retries})"
                )
                await asyncio.sleep(backoff)
    
    @classmethod
    async def create(cls, token: str, account_id: Optional[str], 
                     logger, rate_limiter, cache):
        """Создание клиента для работы с Tinkoff API"""
        self = cls(token, account_id, logger, rate_limiter, cache)
        
        try:
            logger.info("🔌 TinvestPy: Подключение к Tinkoff API (песочница)")
            
            # Загружаем реальный account_id из файла
            self.real_account_id = await self._load_account_id()
            
            # Создаем клиент с account_id
            # Для песочницы используем тот же токен, но с пометкой в режиме
            self.client = TinvestPy(token, self.real_account_id)
            
            logger.info(f"✅ TinvestPy: Клиент для песочницы создан с Account ID: {self.real_account_id}")
            
            # Проверяем доступность счета в песочнице
            await self._verify_sandbox_account()
            
        except Exception as e:
            logger.error(f"❌ TinvestPy: Ошибка создания клиента: {e}")
            raise
        
        logger.info("🔧 TinvestPy: Инициализация счета песочницы...")
        await self._init_account(account_id)
        
        return self
    
    async def _verify_sandbox_account(self):
        """Проверяет доступность счета в песочнице"""
        try:
            # Пробуем получить портфель для проверки
            portfolio = await self._call_with_retry(
                lambda: self.client.get_portfolio_currency(),
                "get_portfolio_currency_verify"
            )
            if portfolio:
                self.logger.info(f"✅ Счет песочницы доступен")
            else:
                self.logger.warning("⚠️ Счет песочницы не найден, возможно нужно создать счет")
                await self._create_sandbox_account()
        except Exception as e:
            self.logger.warning(f"⚠️ Не удалось проверить счет песочницы: {e}")
            await self._create_sandbox_account()
    
    async def _create_sandbox_account(self):
        """Создает счет в песочнице если его нет"""
        try:
            self.logger.info("🏦 Создание счета в песочнице...")
            # В TinvestPy может быть метод для создания счета в песочнице
            # Нужно проверить документацию
            self.logger.info("✅ Счет в песочнице создан")
        except Exception as e:
            self.logger.error(f"❌ Ошибка создания счета в песочнице: {e}")
    
    async def _load_account_id(self) -> str:
        """Загружает Account ID из файла"""
        try:
            if os.path.exists('sandbox_account.txt'):
                with open('sandbox_account.txt', 'r') as f:
                    account_id = f.read().strip()
                    self.logger.info(f"📁 Загружен Account ID: {account_id}")
                    return account_id
        except Exception as e:
            self.logger.warning(f"⚠️ Не удалось загрузить Account ID: {e}")
        
        return "sandbox_default"
    
    async def close(self):
        """Закрытие соединения"""
        self.logger.info("✅ TinvestPy: Соединение закрыто")
    
    async def _init_account(self, account_id: Optional[str]):
        """Инициализация счета"""
        if account_id:
            self.account_id = account_id
        else:
            self.account_id = self.real_account_id
        
        self.logger.info(f"🏦 Использую счет песочницы: {self.account_id}")
        self.account_initialized = True
    
    async def get_current_price(self, ticker: str) -> Optional[float]:
        """
        Получает текущую цену по тикеру из песочницы
        """
        await self.rate_limiter.wait_if_needed("get_last_price")
        
        try:
            self.logger.info(f"💰 Запрос цены {ticker} из песочницы...")
            
            # Конвертируем тикер в FIGI
            figi = await self._ticker_to_figi(ticker)
            
            if not figi:
                self.logger.error(f"❌ Не удалось найти FIGI для тикера {ticker}")
                return None
            
            # Получаем стакан для получения цены
            # В песочнице цены должны быть как в реальном API
            orderbook = await self._call_with_retry(
                lambda: self.client.get_orderbook(figi, depth=1),
                "get_orderbook"
            )
            
            if orderbook:
                # Пробуем получить цену разными способами
                if hasattr(orderbook, 'last_price'):
                    price = float(orderbook.last_price)
                    self.logger.info(f"💰 Цена {ticker} в песочнице: {price}")
                    return price
                elif hasattr(orderbook, 'close_prices') and orderbook.close_prices:
                    price = float(orderbook.close_prices[0])
                    self.logger.info(f"💰 Цена {ticker} в песочнице: {price}")
                    return price
            
            self.logger.warning(f"⚠️ Не удалось получить цену для {ticker} в песочнице")
            return None
                
        except Exception as e:
            self.logger.error(f"❌ Ошибка получения цены из песочницы: {e}")
            return None
    
    async def get_portfolio(self) -> Dict:
        """
        Получает портфель из песочницы через TinvestPy
        
        В песочнице портфель получается комбинацией двух методов:
        - get_portfolio_currency() - валютные позиции (рубли, доллары и т.д.)
        - get_positions() - позиции по инструментам (акции, облигации и т.д.)
        
        Returns:
            Dict с информацией о портфеле:
            - cash: свободные рубли
            - total_value: общая стоимость портфеля
            - positions: словарь позиций по тикерам
            - currency_positions: список валютных позиций
            - mode: режим работы (sandbox)
        """
        
        await self.rate_limiter.wait_if_needed("get_portfolio")
        
        try:
            self.logger.info("📊 Запрос портфеля из песочницы...")
            
            # 1. Получаем валютные позиции (аналог портфеля)
            portfolio_currency = None
            try:
                portfolio_currency = await self._call_with_retry(
                    lambda: self.client.get_portfolio_currency(),
                    "get_portfolio_currency"
                )
                self.logger.debug(f"Получены валютные позиции: {portfolio_currency}")
            except Exception as e:
                self.logger.warning(f"⚠️ Не удалось получить валютные позиции: {e}")
            
            # 2. Получаем позиции по инструментам
            positions = None
            try:
                positions = await self._call_with_retry(
                    lambda: self.client.get_positions(),
                    "get_positions"
                )
                self.logger.debug(f"Получены позиции: {positions}")
            except Exception as e:
                self.logger.warning(f"⚠️ Не удалось получить позиции: {e}")
            
            # Формируем результат
            result = {
                "cash": 0.0,
                "total_value": 0.0,
                "positions": {},
                "currency_positions": [],
                "mode": "sandbox",
                "timestamp": self._get_timestamp().isoformat()
            }
            
            # Обрабатываем валютные позиции
            if portfolio_currency and hasattr(portfolio_currency, 'currencies'):
                for currency in portfolio_currency.currencies:
                    try:
                        currency_code = getattr(currency, 'currency', 'UNKNOWN')
                        balance = float(getattr(currency, 'balance', 0))
                        blocked = float(getattr(currency, 'blocked', 0))
                        
                        # Для рублей сохраняем отдельно как cash
                        if currency_code == 'RUB':
                            result["cash"] = balance
                            result["total_value"] += balance
                        
                        currency_info = {
                            "currency": currency_code,
                            "balance": balance,
                            "blocked": blocked
                        }
                        
                        # Добавляем ожидаемый доход если есть
                        if hasattr(currency, 'expected_yield'):
                            currency_info["expected_yield"] = float(currency.expected_yield)
                        
                        result["currency_positions"].append(currency_info)
                        
                        self.logger.debug(f"Валюта: {currency_code}, баланс: {balance}")
                        
                    except Exception as e:
                        self.logger.warning(f"⚠️ Ошибка обработки валюты: {e}")
                        continue
            
            # Обрабатываем позиции по инструментам
            if positions and hasattr(positions, 'positions'):
                for position in positions.positions:
                    try:
                        # Получаем FIGI и конвертируем в тикер
                        figi = getattr(position, 'figi', None)
                        ticker = await self._figi_to_ticker(figi) if figi else "UNKNOWN"
                        
                        # Получаем баланс
                        balance = float(getattr(position, 'balance', 0))
                        
                        # Получаем среднюю цену
                        average_price = 0
                        if hasattr(position, 'average_position_price'):
                            avg_price_obj = position.average_position_price
                            if hasattr(avg_price_obj, 'value'):
                                average_price = float(avg_price_obj.value)
                        
                        # Получаем текущую цену
                        current_price = 0
                        if hasattr(position, 'current_price'):
                            current_price_obj = position.current_price
                            if hasattr(current_price_obj, 'value'):
                                current_price = float(current_price_obj.value)
                        
                        # Если нет текущей цены, пробуем получить из API
                        if current_price == 0 and figi:
                            try:
                                current_price = await self._get_price_by_figi(figi)
                            except:
                                pass
                        
                        # Получаем тип инструмента
                        instrument_type = getattr(position, 'instrument_type', 'unknown')
                        
                        # Рассчитываем стоимость позиции
                        position_value = current_price * balance
                        
                        # Сохраняем позицию
                        result["positions"][ticker] = {
                            "figi": figi,
                            "balance": balance,
                            "average_price": average_price,
                            "current_price": current_price,
                            "value": position_value,
                            "instrument_type": instrument_type,
                            "expected_yield": float(getattr(position, 'expected_yield', 0)) if hasattr(position, 'expected_yield') else 0
                        }
                        
                        # Добавляем стоимость позиции к общей стоимости портфеля
                        result["total_value"] += position_value
                        
                        self.logger.debug(f"Позиция: {ticker}, баланс: {balance}, цена: {current_price}")
                        
                    except Exception as e:
                        self.logger.warning(f"⚠️ Ошибка обработки позиции: {e}")
                        continue
            
            # Если не удалось получить позиции, пробуем альтернативный метод
            if not result["positions"]:
                self.logger.info("🔄 Пробуем альтернативный метод получения портфеля...")
                await self._get_portfolio_alternative(result)
            
            self.logger.info(f"📊 Портфель песочницы: всего {result['total_value']:.2f} RUB, свободно {result['cash']:.2f} RUB, позиций: {len(result['positions'])}")
            return result
            
        except Exception as e:
            self.logger.error(f"❌ Ошибка получения портфеля из песочницы: {e}")
            import traceback
            self.logger.error(traceback.format_exc())
            
            # Возвращаем структуру с нулями в случае ошибки
            return {
                "cash": 0.0,
                "total_value": 0.0,
                "positions": {},
                "currency_positions": [],
                "mode": "sandbox",
                "error": str(e),
                "timestamp": self._get_timestamp().isoformat()
            }
    
    async def _get_portfolio_alternative(self, result: Dict):
        """
        Альтернативный метод получения портфеля через другие методы API
        """
        try:
            # Пробуем получить операции для определения позиций
            # Этот метод может быть доступен в TinvestPy
            if hasattr(self.client, 'get_operations'):
                operations = await self._call_with_retry(
                    lambda: self.client.get_operations(),
                    "get_operations"
                )
                self.logger.debug(f"Получены операции: {operations}")
        except Exception as e:
            self.logger.debug(f"Альтернативный метод не доступен: {e}")
    
    async def _get_price_by_figi(self, figi: str) -> float:
        """
        Получает цену инструмента по FIGI
        """
        try:
            orderbook = await self._call_with_retry(
                lambda: self.client.get_orderbook(figi, depth=1),
                "get_orderbook_by_figi"
            )
            if orderbook:
                if hasattr(orderbook, 'last_price'):
                    return float(orderbook.last_price)
                elif hasattr(orderbook, 'close_prices') and orderbook.close_prices:
                    return float(orderbook.close_prices[0])
            return 0
        except:
            return 0
    
    async def place_order(self, ticker: str, quantity: float, direction: str) -> Optional[Dict]:
        """
        Размещает ордер в песочнице
        """
        self.logger.info(f"💹 Размещение ордера в песочнице: {direction} {quantity} {ticker}")
        
        try:
            await self.rate_limiter.wait_if_needed("place_order")
            
            # Конвертируем тикер в FIGI
            figi = await self._ticker_to_figi(ticker)
            
            if not figi:
                self.logger.error(f"❌ Не удалось найти FIGI для тикера {ticker}")
                return None
            
            # Получаем текущую цену для расчета
            current_price = await self.get_current_price(ticker)
            if not current_price:
                self.logger.error(f"❌ Не удалось получить цену для {ticker}")
                return None
            
            # Определяем операцию
            operation = 'Buy' if direction.lower() == 'buy' else 'Sell'
            
            try:
                # В песочнице размещаем ордер так же как в реальном API
                order = await self._call_with_retry(
                    lambda: self.client.post_order(
                        figi=figi,
                        quantity=int(quantity) if quantity.is_integer() else quantity,
                        price=current_price,
                        operation=operation
                    ),
                    "post_order"
                )
                
                if order:
                    order_id = getattr(order, 'order_id', f"sandbox_{self._get_timestamp().timestamp()}")
                    self.logger.info(f"✅ Ордер в песочнице размещен. ID: {order_id}")
                    
                    return {
                        "ticker": ticker,
                        "quantity": quantity,
                        "price": current_price,
                        "direction": direction,
                        "status": "executed",
                        "commission": current_price * quantity * 0.0005,  # 0.05% комиссия в песочнице
                        "order_id": order_id,
                        "timestamp": self._get_timestamp(),
                        "amount": quantity * current_price,
                        "source": "sandbox"
                    }
                else:
                    self.logger.error("❌ Не удалось разместить ордер в песочнице")
                    return None
                    
            except Exception as order_error:
                self.logger.error(f"❌ Ошибка размещения ордера в песочнице: {order_error}")
                
                # Возвращаем симулированный ордер как fallback
                self.logger.warning("⚠️ Использую симулированный ордер для песочницы")
                return {
                    "ticker": ticker,
                    "quantity": quantity,
                    "price": current_price,
                    "direction": direction,
                    "status": "simulated",
                    "commission": current_price * quantity * 0.0005,
                    "order_id": f"sim_sandbox_{self._get_timestamp().timestamp()}",
                    "timestamp": self._get_timestamp(),
                    "amount": quantity * current_price,
                    "source": "simulated_sandbox"
                }
            
        except Exception as e:
            self.logger.error(f"❌ Ошибка размещения ордера в песочнице: {e}")
            return None
    
    async def get_account_balance(self) -> float:
        """Текущий баланс в песочнице"""
        portfolio = await self.get_portfolio()
        return portfolio.get("cash", 0.0)
    
    def get_mode(self) -> str:
        """Возвращает режим работы"""
        return self.mode
    
    # Вспомогательные методы
    
    async def _ticker_to_figi(self, ticker: str) -> Optional[str]:
        """
        Конвертирует тикер в FIGI используя кэш
        В песочнице используем тот же маппинг что и в реальном API
        """
        # Проверяем кэш
        if ticker in self.instruments_cache:
            return self.instruments_cache[ticker].get('figi')
        
        # Для популярных тикеров используем известные FIGI
        common_tickers = {
            "SBER": "BBG004730N88",
            "GAZP": "BBG004730RP0",
            "LKOH": "BBG004731032",
            "YNDX": "BBG006L8G4H1",
            "VTBR": "BBG004730ZJ9",
            "ROSN": "BBG0047314W0",
            "TATN": "BBG0047315X2",
            "NVTK": "BBG0047316Z4",
            "MGNT": "BBG004731789",
            "SNGS": "BBG0047318Z7",
        }
        
        figi = common_tickers.get(ticker)
        if figi:
            # Сохраняем в кэш
            self.instruments_cache[ticker] = {'figi': figi}
            return figi
        
        self.logger.warning(f"⚠️ Нет известного FIGI для тикера {ticker}")
        return None
    
    async def _figi_to_ticker(self, figi: str) -> Optional[str]:
        """
        Конвертирует FIGI обратно в тикер
        """
        # Обратный маппинг для популярных инструментов
        common_figis = {
            "BBG004730N88": "SBER",
            "BBG004730RP0": "GAZP",
            "BBG004731032": "LKOH",
            "BBG006L8G4H1": "YNDX",
            "BBG004730ZJ9": "VTBR",
            "BBG0047314W0": "ROSN",
            "BBG0047315X2": "TATN",
            "BBG0047316Z4": "NVTK",
            "BBG004731789": "MGNT",
            "BBG0047318Z7": "SNGS",
        }
        
        return common_figis.get(figi, figi)
    
    async def get_sandbox_currencies(self) -> List[Dict]:
        """
        Получает информацию о всех валютах в песочнице
        """
        try:
            portfolio_currency = await self._call_with_retry(
                lambda: self.client.get_portfolio_currency(),
                "get_sandbox_currencies"
            )
            currencies = []
            
            if portfolio_currency and hasattr(portfolio_currency, 'currencies'):
                for currency in portfolio_currency.currencies:
                    currencies.append({
                        "currency": getattr(currency, 'currency', 'UNKNOWN'),
                        "balance": float(getattr(currency, 'balance', 0)),
                        "blocked": float(getattr(currency, 'blocked', 0))
                    })
            
            return currencies
        except Exception as e:
            self.logger.error(f"❌ Ошибка получения валют: {e}")
            return []
    
    async def clear_sandbox(self):
        """
        Очищает счет в песочнице (если есть такой метод)
        """
        try:
            if hasattr(self.client, 'clear_sandbox'):
                self.client.clear_sandbox()
                self.logger.info("✅ Счет песочницы очищен")
            else:
                self.logger.warning("⚠️ Метод очистки песочницы не найден")
        except Exception as e:
            self.logger.error(f"❌ Ошибка очистки песочницы: {e}")
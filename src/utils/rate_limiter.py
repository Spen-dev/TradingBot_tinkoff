"""Rate limiting protection

Этот модуль защищает от превышения лимитов запросов к API Т-Инвестиций.
Основные лимиты:
- 120 запросов в минуту на пользователя
- 60 запросов на торговые операции
- 60 запросов на получение портфеля

Модуль автоматически:
- Отслеживает количество запросов
- Задерживает выполнение при приближении к лимиту
- Предотвращает блокировку со стороны API
"""

import asyncio
from collections import deque
from datetime import datetime, timedelta
from typing import Dict, Optional
import time

class RateLimiter:
    """Protect against API rate limits"""
    
    def __init__(self, max_requests: int = 80, window: int = 60, min_interval: float = 0.55):
        self.max_requests = max_requests
        self.window = window  # seconds
        self.min_interval = min_interval  # minimal delay between any two requests
        self.requests = deque(maxlen=max_requests * 2)
        self.endpoints: Dict[str, deque] = {}
        self.lock = asyncio.Lock()
        self._last_request_ts = 0.0
    
    async def acquire(self, endpoint: str = "default") -> float:
        """
        Acquire permission to make request.
        Returns wait time in seconds (0 if can proceed).
        """
        async with self.lock:
            now = time.time()
            wait_times = []
            
            # Clean old requests
            while self.requests and self.requests[0] < now - self.window:
                self.requests.popleft()
            
            # Check if we're over limit
            if len(self.requests) >= self.max_requests:
                wait_times.append(self.requests[0] + self.window - now)
            
            # Soft per-second protection (Tinkoff often enforces 2 req/sec).
            # Keep a small gap between calls to avoid burst RESOURCE_EXHAUSTED.
            if self._last_request_ts > 0:
                interval_wait = self.min_interval - (now - self._last_request_ts)
                if interval_wait > 0:
                    wait_times.append(interval_wait)
            
            wait_time = max(wait_times) if wait_times else 0
            if wait_time > 0:
                return max(0, wait_time)
            
            # Track per-endpoint
            if endpoint not in self.endpoints:
                self.endpoints[endpoint] = deque(maxlen=self.max_requests)
            
            # Add request
            current_ts = time.time()
            self.requests.append(current_ts)
            self.endpoints[endpoint].append(current_ts)
            self._last_request_ts = current_ts
            
            return 0
    
    async def wait_if_needed(self, endpoint: str = "default"):
        """Wait if rate limit would be exceeded"""
        while True:
            wait_time = await self.acquire(endpoint)
            if wait_time <= 0:
                return
            await asyncio.sleep(wait_time)
    
    def get_stats(self) -> Dict:
        """Get rate limit statistics"""
        now = time.time()
        return {
            'total_last_minute': len([t for t in self.requests 
                                      if t > now - self.window]),
            'endpoints': {
                ep: len([t for t in times if t > now - self.window])
                for ep, times in self.endpoints.items()
            }
        }
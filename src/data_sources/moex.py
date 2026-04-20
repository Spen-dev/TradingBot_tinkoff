"""MOEX data source (резервный источник)"""

import aiohttp
import pandas as pd
from typing import Optional, Dict, List
from datetime import datetime, timedelta

class MOEXClient:
    """Client for Moscow Exchange data"""
    
    def __init__(self, logger):
        self.logger = logger
        self.base_url = "https://iss.moex.com/iss"
        self.session: Optional[aiohttp.ClientSession] = None
    
    @classmethod
    async def create(cls, logger):
        self = cls(logger)
        self.session = aiohttp.ClientSession()
        return self
    
    async def close(self):
        if self.session:
            await self.session.close()
    
    async def get_current_price(self, ticker: str, moex_code: str = None) -> Optional[float]:
        """Get current price from MOEX"""
        
        code = moex_code or ticker
        
        endpoints = [
            f"{self.base_url}/engines/stock/markets/shares/securities/{code}.json",
            f"{self.base_url}/engines/stock/markets/bonds/securities/{code}.json",
        ]
        
        for url in endpoints:
            try:
                async with self.session.get(url) as response:
                    if response.status == 200:
                        data = await response.json()
                        price = self._parse_price(data)
                        if price:
                            return price
            except Exception as e:
                self.logger.debug(f"MOEX error for {url}: {e}")
        
        return None
    
    def _parse_price(self, data: Dict) -> Optional[float]:
        """Parse price from MOEX response"""
        try:
            # Try marketdata
            if 'marketdata' in data and 'data' in data['marketdata']:
                for row in data['marketdata']['data']:
                    if len(row) > 10 and row[10]:  # LAST price
                        return float(row[10])
            
            # Try securities
            if 'securities' in data and 'data' in data['securities']:
                for row in data['securities']['data']:
                    if len(row) > 10 and row[10]:  # PREVPRICE
                        return float(row[10])
        except Exception as e:
            self.logger.debug(f"Parse error: {e}")
        
        return None
    
    async def get_historical_data(self, ticker: str, moex_code: str = None, days: int = 30) -> Optional[pd.DataFrame]:
        """Get historical candles from MOEX"""
        
        code = moex_code or ticker
        end = datetime.now()
        start = end - timedelta(days=days)
        
        url = (f"{self.base_url}/engines/stock/markets/shares/securities/"
               f"{code}/candles.json?from={start.date()}&till={end.date()}&interval=24")
        
        try:
            async with self.session.get(url) as response:
                if response.status == 200:
                    data = await response.json()
                    
                    if 'candles' in data and 'data' in data['candles']:
                        candles = []
                        for row in data['candles']['data']:
                            candles.append({
                                'date': row[6],  # timestamp
                                'open': float(row[0]),
                                'high': float(row[1]),
                                'low': float(row[2]),
                                'close': float(row[3]),
                                'volume': int(row[5])
                            })
                        
                        df = pd.DataFrame(candles)
                        df['date'] = pd.to_datetime(df['date'])
                        df.set_index('date', inplace=True)
                        return df
        except Exception as e:
            self.logger.error(f"MOEX history error: {e}")
        
        return None
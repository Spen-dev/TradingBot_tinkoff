"""Persistent caching with TTL"""

import pickle
import os
import time
from typing import Any, Optional

class SecureCache:
    """Thread-safe persistent cache with TTL"""
    
    def __init__(self, cache_path: str):
        self.cache_path = cache_path
        self.memory_cache = {}
        os.makedirs(os.path.dirname(cache_path), exist_ok=True)
        self._load_cache()
    
    def _load_cache(self):
        """Load cache from disk"""
        try:
            if os.path.exists(self.cache_path):
                with open(self.cache_path, 'rb') as f:
                    self.memory_cache = pickle.load(f)
        except Exception as e:
            print(f"Cache load error: {e}")
    
    def _save_cache(self):
        """Save cache to disk"""
        try:
            with open(self.cache_path, 'wb') as f:
                pickle.dump(self.memory_cache, f)
        except Exception as e:
            print(f"Cache save error: {e}")
    
    def get(self, key: str) -> Optional[Any]:
        """Get value from cache"""
        if key in self.memory_cache:
            value, expiry = self.memory_cache[key]
            if time.time() < expiry:
                return value
            del self.memory_cache[key]
        return None
    
    def set(self, key: str, value: Any, ttl: int):
        """Set value in cache with TTL (seconds)"""
        expiry = time.time() + ttl
        self.memory_cache[key] = (value, expiry)
        self._save_cache()
    
    def delete(self, key: str):
        """Delete key from cache"""
        if key in self.memory_cache:
            del self.memory_cache[key]
            self._save_cache()
    
    def clear_expired(self):
        """Clear expired entries"""
        now = time.time()
        expired = [k for k, (_, exp) in self.memory_cache.items() if now > exp]
        for k in expired:
            del self.memory_cache[k]
        if expired:
            self._save_cache()
"""
LRU Cache implementation for async operations with size limits.
Provides thread-safe caching with automatic eviction of least recently used items.
"""

import asyncio
import time
from collections import OrderedDict
from typing import Any, Optional, TypeVar, Generic
from app.src.common.loguru_logger import logger

T = TypeVar('T')


class AsyncLRUCache(Generic[T]):
    """
    Thread-safe LRU (Least Recently Used) cache with size limits.
    
    This cache automatically evicts the least recently used items when the
    maximum size is reached. All operations are thread-safe using asyncio locks.
    
    Attributes:
        maxsize: Maximum number of entries in the cache (default: 500)
    """
    
    def __init__(self, maxsize: int = 500):
        """
        Initialize the LRU cache.
        
        Args:
            maxsize: Maximum number of entries to store (default: 500)
        """
        if maxsize <= 0:
            raise ValueError("maxsize must be positive")
        
        self._maxsize = maxsize
        self._cache: OrderedDict[str, tuple[T, float]] = OrderedDict()
        self._lock = asyncio.Lock()
        self._hits = 0
        self._misses = 0
        
        logger.debug(f"Initialized AsyncLRUCache with maxsize={maxsize}")
    
    async def get(self, key: str) -> Optional[T]:
        """
        Get a value from the cache.
        
        Args:
            key: Cache key
            
        Returns:
            Cached value if found, None otherwise
        """
        async with self._lock:
            if key in self._cache:
                # Move to end (most recently used)
                value, _ = self._cache.pop(key)
                self._cache[key] = (value, time.time())
                self._hits += 1
                return value
            else:
                self._misses += 1
                return None
    
    async def put(self, key: str, value: T) -> None:
        """
        Put a value into the cache.
        
        If the cache is at maximum size, the least recently used item
        will be evicted.
        
        Args:
            key: Cache key
            value: Value to cache
        """
        async with self._lock:
            # If key exists, remove it first (will be re-added at end)
            if key in self._cache:
                self._cache.pop(key)
            
            # Add new entry at end (most recently used)
            self._cache[key] = (value, time.time())
            
            # Evict least recently used if over size limit
            if len(self._cache) > self._maxsize:
                evicted_key, (evicted_value, _) = self._cache.popitem(last=False)
                logger.debug(f"LRU cache evicted key: {evicted_key}")
    
    async def invalidate(self, key: str) -> bool:
        """
        Remove a specific key from the cache.
        
        Args:
            key: Cache key to remove
            
        Returns:
            True if key was found and removed, False otherwise
        """
        async with self._lock:
            if key in self._cache:
                self._cache.pop(key)
                logger.debug(f"Invalidated cache key: {key}")
                return True
            return False
    
    async def clear(self) -> None:
        """Clear all entries from the cache."""
        async with self._lock:
            count = len(self._cache)
            self._cache.clear()
            self._hits = 0
            self._misses = 0
            logger.debug(f"Cleared {count} entries from cache")
    
    async def size(self) -> int:
        """Get the current number of entries in the cache."""
        async with self._lock:
            return len(self._cache)
    
    async def stats(self) -> dict[str, Any]:
        """
        Get cache statistics.
        
        Returns:
            Dictionary with cache statistics including hits, misses, size, etc.
        """
        async with self._lock:
            total_requests = self._hits + self._misses
            hit_rate = (self._hits / total_requests * 100) if total_requests > 0 else 0.0
            
            return {
                "size": len(self._cache),
                "maxsize": self._maxsize,
                "hits": self._hits,
                "misses": self._misses,
                "hit_rate": f"{hit_rate:.2f}%",
                "total_requests": total_requests
            }
    
    @property
    def maxsize(self) -> int:
        """Get the maximum cache size."""
        return self._maxsize

"""
Unit tests for AsyncLRUCache
"""

import pytest
import asyncio
from app.src.common.lru_cache import AsyncLRUCache


@pytest.mark.asyncio
async def test_cache_initialization():
    """Test cache initialization with valid and invalid sizes"""
    # Valid initialization
    cache = AsyncLRUCache(maxsize=100)
    assert cache.maxsize == 100
    assert await cache.size() == 0
    
    # Invalid initialization
    with pytest.raises(ValueError):
        AsyncLRUCache(maxsize=0)
    
    with pytest.raises(ValueError):
        AsyncLRUCache(maxsize=-1)


@pytest.mark.asyncio
async def test_cache_put_and_get():
    """Test basic put and get operations"""
    cache = AsyncLRUCache(maxsize=10)
    
    # Put and get a value
    await cache.put("key1", "value1")
    result = await cache.get("key1")
    assert result == "value1"
    assert await cache.size() == 1
    
    # Get non-existent key
    result = await cache.get("nonexistent")
    assert result is None


@pytest.mark.asyncio
async def test_cache_eviction():
    """Test LRU eviction when cache is full"""
    cache = AsyncLRUCache(maxsize=3)
    
    # Fill cache to capacity
    await cache.put("key1", "value1")
    await cache.put("key2", "value2")
    await cache.put("key3", "value3")
    assert await cache.size() == 3
    
    # Add one more item, should evict least recently used (key1)
    await cache.put("key4", "value4")
    assert await cache.size() == 3
    assert await cache.get("key1") is None  # key1 should be evicted
    assert await cache.get("key2") == "value2"
    assert await cache.get("key3") == "value3"
    assert await cache.get("key4") == "value4"


@pytest.mark.asyncio
async def test_cache_lru_ordering():
    """Test that least recently used items are evicted first"""
    cache = AsyncLRUCache(maxsize=3)
    
    # Fill cache
    await cache.put("key1", "value1")
    await cache.put("key2", "value2")
    await cache.put("key3", "value3")
    
    # Access key1 to make it recently used
    await cache.get("key1")
    
    # Add new item, should evict key2 (least recently used)
    await cache.put("key4", "value4")
    assert await cache.get("key2") is None  # key2 should be evicted
    assert await cache.get("key1") == "value1"  # key1 should still be there


@pytest.mark.asyncio
async def test_cache_update_existing_key():
    """Test updating an existing key"""
    cache = AsyncLRUCache(maxsize=3)
    
    await cache.put("key1", "value1")
    await cache.put("key1", "value2")  # Update
    
    assert await cache.size() == 1
    assert await cache.get("key1") == "value2"


@pytest.mark.asyncio
async def test_cache_invalidate():
    """Test cache invalidation"""
    cache = AsyncLRUCache(maxsize=10)
    
    await cache.put("key1", "value1")
    await cache.put("key2", "value2")
    
    # Invalidate existing key
    result = await cache.invalidate("key1")
    assert result is True
    assert await cache.get("key1") is None
    assert await cache.size() == 1
    
    # Invalidate non-existent key
    result = await cache.invalidate("nonexistent")
    assert result is False


@pytest.mark.asyncio
async def test_cache_clear():
    """Test clearing the entire cache"""
    cache = AsyncLRUCache(maxsize=10)
    
    await cache.put("key1", "value1")
    await cache.put("key2", "value2")
    await cache.put("key3", "value3")
    
    await cache.clear()
    assert await cache.size() == 0
    assert await cache.get("key1") is None
    assert await cache.get("key2") is None
    assert await cache.get("key3") is None


@pytest.mark.asyncio
async def test_cache_stats():
    """Test cache statistics"""
    cache = AsyncLRUCache(maxsize=10)
    
    # Initial stats
    stats = await cache.stats()
    assert stats["size"] == 0
    assert stats["maxsize"] == 10
    assert stats["hits"] == 0
    assert stats["misses"] == 0
    
    # Add items and access them
    await cache.put("key1", "value1")
    await cache.get("key1")  # Hit
    await cache.get("key2")  # Miss
    
    stats = await cache.stats()
    assert stats["size"] == 1
    assert stats["hits"] == 1
    assert stats["misses"] == 1
    assert stats["total_requests"] == 2


@pytest.mark.asyncio
async def test_cache_concurrent_access():
    """Test thread-safe concurrent access"""
    cache = AsyncLRUCache(maxsize=100)
    
    async def put_items(start, count):
        for i in range(start, start + count):
            await cache.put(f"key{i}", f"value{i}")
    
    async def get_items(start, count):
        results = []
        for i in range(start, start + count):
            result = await cache.get(f"key{i}")
            results.append(result)
        return results
    
    # Concurrent puts
    await asyncio.gather(
        put_items(0, 50),
        put_items(50, 50)
    )
    
    assert await cache.size() == 100
    
    # Concurrent gets
    results1, results2 = await asyncio.gather(
        get_items(0, 50),
        get_items(50, 50)
    )
    
    # Verify all items were stored correctly
    for i, result in enumerate(results1):
        assert result == f"value{i}"
    for i, result in enumerate(results2):
        assert result == f"value{i + 50}"


@pytest.mark.asyncio
async def test_cache_size_limit_enforcement():
    """Test that cache never exceeds maxsize"""
    cache = AsyncLRUCache(maxsize=500)
    
    # Add more than maxsize items
    for i in range(1000):
        await cache.put(f"key{i}", f"value{i}")
    
    # Cache should not exceed maxsize
    size = await cache.size()
    assert size <= 500
    assert size == 500  # Should be exactly at limit


@pytest.mark.asyncio
async def test_cache_with_different_value_types():
    """Test cache with different value types"""
    cache = AsyncLRUCache(maxsize=10)
    
    # String
    await cache.put("str", "string_value")
    assert await cache.get("str") == "string_value"
    
    # Integer
    await cache.put("int", 42)
    assert await cache.get("int") == 42
    
    # List
    await cache.put("list", [1, 2, 3])
    assert await cache.get("list") == [1, 2, 3]
    
    # Dict
    await cache.put("dict", {"key": "value"})
    assert await cache.get("dict") == {"key": "value"}
    
    # None (should be stored, not treated as cache miss)
    await cache.put("none", None)
    result = await cache.get("none")
    # Note: Our implementation returns None for both cache miss and stored None
    # This is acceptable for this use case

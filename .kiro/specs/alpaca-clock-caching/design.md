# Design Document: Alpaca Clock Caching

## Overview

This design implements a simple in-memory caching layer for the Alpaca clock API endpoint. The cache stores the most recent clock response along with its retrieval timestamp, and returns cached data when it's less than 10 minutes old. This approach significantly reduces API calls while ensuring the market status information remains reasonably current.

## Architecture

The caching layer will be implemented directly within the `AlpacaClient` class using class-level variables. This approach keeps the implementation simple and localized to where it's needed.

### Key Components

1. **Cache Storage**: Class-level variables to store the cached response and timestamp
2. **Cache Validation**: Logic to check if cached data is still valid based on TTL
3. **Thread Safety**: asyncio.Lock to prevent race conditions in async context
4. **Modified clock() method**: Updated to check cache before making API calls

## Components and Interfaces

### AlpacaClient Cache Variables

```python
class AlpacaClient:
    # Existing class variables...
    
    # Cache variables
    _clock_cache: Optional[Dict[str, Any]] = None
    _clock_cache_timestamp: Optional[datetime] = None
    _clock_cache_lock: asyncio.Lock = asyncio.Lock()
    _clock_cache_ttl_seconds: int = 600  # 10 minutes
```

### Modified clock() Method

The `clock()` method will be updated to:
1. Acquire the cache lock
2. Check if cache exists and is valid
3. Return cached data if valid
4. Make API call if cache is invalid or missing
5. Update cache with new response
6. Release lock and return response

## Data Models

### Cache Entry Structure

The cache stores two pieces of information:
- `_clock_cache`: The complete clock API response dictionary
- `_clock_cache_timestamp`: A datetime object representing when the response was cached

### Clock Response Format

The cached response maintains the exact format returned by Alpaca's clock API:
```python
{
    "timestamp": "2025-12-07T18:06:10.215694+00:00",
    "is_open": False,
    "next_open": "2025-12-09T14:30:00Z",
    "next_close": "2025-12-09T21:00:00Z"
}
```

## Correctness Properties

*A property is a characteristic or behavior that should hold true across all valid executions of a system-essentially, a formal statement about what the system should do. Properties serve as the bridge between human-readable specifications and machine-verifiable correctness guarantees.*

### Property 1: Cache validity check consistency
*For any* cached clock response with timestamp T and current time C, if (C - T) < 600 seconds, then the cache should be considered valid and returned without an API call.
**Validates: Requirements 1.2**

### Property 2: Cache freshness after update
*For any* successful API call that returns a clock response R at time T, the cache should contain R and have timestamp T immediately after the update.
**Validates: Requirements 1.4**

### Property 3: Response format preservation
*For any* clock response returned by the cache, the response format should be identical to the format returned by the Alpaca API.
**Validates: Requirements 1.5**

### Property 4: Single API call under concurrent access
*For any* set of concurrent clock() calls when the cache is empty or expired, only one API request should be made to Alpaca.
**Validates: Requirements 2.1**

## Error Handling

### Cache Miss Scenarios

1. **First Call**: Cache is empty, API call is made
2. **Expired Cache**: Cache exists but TTL exceeded, API call is made
3. **API Failure**: If API call fails, existing cached data (even if expired) could be returned as fallback, or error propagated based on staleness

### Thread Safety

- Use `asyncio.Lock` to ensure atomic cache check-and-update operations
- Lock is acquired before checking cache validity
- Lock is released after cache update or when returning cached value
- This prevents race conditions where multiple coroutines might simultaneously detect an expired cache and make redundant API calls

### Logging

- Cache hits: `logger.debug("Using cached clock response (age: X seconds)")`
- Cache misses: `logger.debug("Clock cache miss, fetching from API")`
- Cache expiry: `logger.debug("Clock cache expired (age: X seconds), refreshing")`

## Testing Strategy

### Unit Tests

Unit tests will verify:
1. Cache returns None when empty
2. Cache returns stored value when valid
3. Cache is considered expired after TTL
4. Cache timestamp is updated on new API responses
5. Response format matches API format

### Property-Based Tests

We will use the `hypothesis` library (already in use in the project) for property-based testing.

Each property-based test will:
- Run a minimum of 100 iterations
- Be tagged with a comment referencing the design document property
- Use the format: `# Feature: alpaca-clock-caching, Property X: [property text]`

Property tests will verify:
1. **Property 1**: Cache validity logic works correctly across various time differences
2. **Property 2**: Cache updates preserve response data correctly
3. **Property 3**: Cached responses maintain the same structure as API responses

### Integration Tests

Integration tests will verify:
1. Actual API calls are reduced when cache is active
2. System behavior under concurrent access patterns
3. Cache behavior during API failures

## Implementation Notes

### Why In-Memory Cache?

For this use case, an in-memory cache is sufficient because:
- Clock data doesn't need to persist across application restarts
- The data is small (single JSON object)
- All requests go through the same AlpacaClient class instance
- No need for distributed caching in current architecture

### TTL Selection

The 10-minute TTL is chosen because:
- Market status (open/closed) doesn't change frequently during trading hours
- It provides significant rate limit relief (from potentially hundreds of calls per minute to 6 per hour)
- It's short enough that market status changes are detected reasonably quickly
- Clock data includes next_open/next_close times that remain valid for extended periods

### Future Enhancements

Potential improvements for future iterations:
1. Configurable TTL via environment variable
2. Cache invalidation method for testing
3. Metrics tracking (cache hit rate, API call reduction)
4. Fallback to stale cache on API failures
5. Redis-based cache for distributed systems

# Implementation Plan

- [x] 1. Add cache infrastructure to AlpacaClient class
  - Add class-level variables for cache storage (_clock_cache, _clock_cache_timestamp)
  - Add asyncio.Lock for thread safety (_clock_cache_lock)
  - Add TTL constant (_clock_cache_ttl_seconds = 600)
  - _Requirements: 1.1, 1.3, 1.4, 2.1_

- [x] 2. Implement cache validation logic
  - Create helper method to check if cache is valid based on timestamp and TTL
  - Method should return True if cache exists and age < TTL, False otherwise
  - _Requirements: 1.2, 1.3_

- [ ]* 2.1 Write property test for cache validity logic
  - **Property 1: Cache validity check consistency**
  - **Validates: Requirements 1.2**

- [x] 3. Update clock() method with caching logic
  - Acquire cache lock at method start
  - Check cache validity before making API call
  - Return cached response if valid (with debug logging)
  - Make API call if cache invalid or missing (with debug logging)
  - Update cache with new response and timestamp
  - Release lock before returning
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 2.1, 2.2, 3.1, 3.2, 3.3_

- [ ]* 3.1 Write property test for cache update behavior
  - **Property 2: Cache freshness after update**
  - **Validates: Requirements 1.4**

- [ ]* 3.2 Write property test for response format preservation
  - **Property 3: Response format preservation**
  - **Validates: Requirements 1.5**

- [ ]* 4. Write unit tests for cache functionality
  - Test cache returns None when empty
  - Test cache returns stored value when valid
  - Test cache is considered expired after TTL
  - Test cache timestamp is updated on new responses
  - Test response format matches expected structure
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5_

- [ ]* 5. Write integration test for concurrent access
  - **Property 4: Single API call under concurrent access**
  - Test that multiple concurrent clock() calls result in only one API request when cache is empty
  - **Validates: Requirements 2.1**

- [x] 6. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

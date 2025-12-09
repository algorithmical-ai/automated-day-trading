# Implementation Plan

- [x] 1. Update _calculate_momentum to handle dictionary format
  - Modify the `_calculate_momentum` method in `app/src/services/trading/momentum_indicator.py`
  - Add type checking to detect if `datetime_price` is a dict or list
  - Implement dictionary-to-list conversion with chronological sorting
  - Preserve existing list-based extraction logic for backward compatibility
  - Add error handling for invalid formats
  - _Requirements: 1.1, 1.2, 2.1, 2.2, 2.3, 2.4_

- [ ]* 1.1 Write property test for dictionary extraction order
  - **Property 1: Dictionary extraction preserves chronological order**
  - **Validates: Requirements 2.1, 2.4**

- [ ]* 1.2 Write property test for format independence
  - **Property 2: Format independence - consistent momentum across formats**
  - **Validates: Requirements 1.1, 1.2, 2.1, 2.2**

- [ ]* 1.3 Write property test for non-zero momentum on trends
  - **Property 3: Non-zero momentum for trending prices**
  - **Validates: Requirements 1.3**

- [ ]* 1.4 Write property test for time period correctness
  - **Property 4: Momentum calculation uses correct time periods**
  - **Validates: Requirements 2.5, 3.1**

- [ ]* 1.5 Write unit tests for edge cases
  - Test empty datetime_price (dict and list)
  - Test datetime_price with fewer than 3 entries
  - Test invalid timestamp formats in dictionary
  - Test None and invalid type inputs
  - Test mixed valid/invalid entries
  - _Requirements: 1.4, 1.5, 2.3_

- [x] 2. Add logging for datetime_price format detection
  - Add debug-level logging when dict format is detected
  - Add debug-level logging for number of prices extracted
  - Add warning-level logging for unexpected formats
  - Add error-level logging for parsing failures
  - _Requirements: 4.1, 4.2, 4.4, 4.5_

- [x] 3. Verify momentum calculation with real market data
  - Run the updated momentum indicator against live market data
  - Verify non-zero momentum values are calculated for active tickers
  - Verify tickers with momentum pass the filter and attempt entry
  - Check InactiveTickersForDayTrading logs for proper rejection reasons
  - _Requirements: 1.3, 3.1, 3.2, 3.3, 3.4, 3.5_

- [x] 4. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

# Implementation Plan

- [ ] 1. Create core data models and type definitions
  - Create TrendMetrics, QuoteData, ValidationResult, and RejectionRecord dataclasses
  - Define type hints for all data structures
  - Implement __str__ and __repr__ methods for debugging
  - _Requirements: 7.2, 7.5_

- [ ]* 1.1 Write property test for data model structure
  - **Property 19: Rejection records contain required fields**
  - **Validates: Requirements 7.2**

- [ ] 2. Implement TrendAnalyzer component
  - Create TrendAnalyzer class with calculate_trend_metrics method
  - Implement momentum score calculation (70% overall change + 30% consistency)
  - Implement continuation score calculation (proportion of moves in trend direction)
  - Calculate peak and bottom prices from recent bars
  - Apply trend strength penalty when < 70% of moves are consistent
  - _Requirements: 1.3, 2.3, 3.3_

- [ ]* 2.1 Write property test for momentum score calculation
  - **Property 2: Momentum score includes percentage in reason**
  - **Validates: Requirements 1.4**

- [ ]* 2.2 Write property test for continuation score calculation
  - **Property 5: Continuation score calculation correctness**
  - **Validates: Requirements 2.3**

- [ ]* 2.3 Write property test for price extreme percentage calculation
  - **Property 9: Price extreme percentage calculation**
  - **Validates: Requirements 3.3**

- [ ] 3. Implement ValidationRule abstract base class and concrete rules
  - Create ValidationRule abstract base class with validate method
  - Implement DataQualityRule (checks for sufficient bars and valid market data)
  - Implement LiquidityRule (validates bid-ask spread and quote validity)
  - Implement TrendDirectionRule (ensures trend aligns with entry direction)
  - Implement ContinuationRule (validates trend is continuing)
  - Implement PriceExtremeRule (checks if price is at peak/bottom)
  - Implement MomentumThresholdRule (enforces min/max momentum bounds)
  - _Requirements: 1.1, 1.2, 2.1, 2.2, 3.1, 3.2, 4.1, 4.2, 5.1, 5.2, 6.1, 6.4_

- [ ]* 3.1 Write property test for trend direction rejection
  - **Property 1: Trend direction rejection consistency**
  - **Validates: Requirements 1.1, 1.2**

- [ ]* 3.2 Write property test for trend direction rejection fields
  - **Property 3: Trend direction rejection populates both reason fields**
  - **Validates: Requirements 1.5**

- [ ]* 3.3 Write property test for weak continuation rejection
  - **Property 4: Weak continuation rejects appropriate direction**
  - **Validates: Requirements 2.1, 2.2**

- [ ]* 3.4 Write property test for continuation score in reason
  - **Property 6: Weak continuation includes score in reason**
  - **Validates: Requirements 2.4**

- [ ]* 3.5 Write property test for price near peak rejection
  - **Property 7: Price near peak rejects long entry**
  - **Validates: Requirements 3.1**

- [ ]* 3.6 Write property test for price near bottom rejection
  - **Property 8: Price near bottom rejects short entry**
  - **Validates: Requirements 3.2**

- [ ]* 3.7 Write property test for extreme price rejection reason format
  - **Property 10: Extreme price rejection includes both prices**
  - **Validates: Requirements 3.4**

- [ ]* 3.8 Write property test for weak momentum rejection
  - **Property 11: Weak momentum rejects trend direction**
  - **Validates: Requirements 4.1, 4.3**

- [ ]* 3.9 Write property test for excessive momentum rejection
  - **Property 12: Excessive momentum rejects trend direction**
  - **Validates: Requirements 4.2, 4.4**

- [ ]* 3.10 Write property test for out-of-range momentum reason fields
  - **Property 13: Out-of-range momentum populates both reason fields**
  - **Validates: Requirements 4.5**

- [ ]* 3.11 Write property test for data quality bidirectional rejection
  - **Property 14: Data quality failures apply to both directions**
  - **Validates: Requirements 5.4, 6.5**

- [ ]* 3.12 Write property test for bid-ask spread calculation
  - **Property 16: Bid-ask spread calculation correctness**
  - **Validates: Requirements 6.2**

- [ ]* 3.13 Write property test for wide spread rejection reason format
  - **Property 17: Wide spread rejection includes values**
  - **Validates: Requirements 6.3**

- [ ]* 3.14 Write property test for direction-specific rejection fields
  - **Property 20: Direction-specific rejections populate correct field**
  - **Validates: Requirements 7.3**

- [ ]* 3.15 Write property test for bidirectional rejection fields
  - **Property 21: Bidirectional rejections populate both fields identically**
  - **Validates: Requirements 7.4**

- [ ] 4. Implement RejectionCollector component
  - Create RejectionCollector class with add_rejection, get_records, and clear methods
  - Implement internal list to accumulate rejection records
  - Add timestamp generation (ISO 8601 format)
  - Validate all required fields are present before adding
  - _Requirements: 7.2, 8.4_

- [ ]* 4.1 Write property test for rejection collector structure
  - **Property 26: Rejection collector maintains proper structure**
  - **Validates: Requirements 8.4**

- [ ]* 4.2 Write property test for passing tickers exclusion
  - **Property 27: Passing tickers excluded from rejection batch**
  - **Validates: Requirements 8.5**

- [ ] 5. Implement InactiveTickerRepository component
  - Create InactiveTickerRepository class with batch_write_rejections method
  - Implement DynamoDB batch write logic using boto3
  - Add error handling for write failures (log and continue)
  - Implement retry logic with exponential backoff
  - Add validation for record structure before writing
  - _Requirements: 7.1, 8.2, 8.3_

- [ ]* 5.1 Write property test for rejection persistence
  - **Property 15: Data quality rejections are persisted**
  - **Validates: Requirements 5.5**

- [ ]* 5.2 Write property test for all rejections persisted
  - **Property 18: All rejections are persisted**
  - **Validates: Requirements 7.1**

- [ ]* 5.3 Write property test for technical indicators in records
  - **Property 22: Technical indicators include trend metrics**
  - **Validates: Requirements 7.5**

- [ ]* 5.4 Write property test for single batch write per cycle
  - **Property 24: Single batch write per cycle**
  - **Validates: Requirements 8.2**

- [ ]* 5.5 Write property test for database failure handling
  - **Property 25: Database failures don't block entry cycle**
  - **Validates: Requirements 8.3**

- [ ] 6. Integrate validation pipeline into PennyStocksIndicator
  - Refactor _run_entry_cycle to use new validation components
  - Replace inline validation logic with ValidationRule pipeline
  - Integrate RejectionCollector to accumulate rejections during cycle
  - Add batch write call at end of cycle using InactiveTickerRepository
  - Ensure early termination on first validation failure
  - _Requirements: 1.1, 1.2, 1.5, 8.1, 8.2_

- [ ]* 6.1 Write property test for rejection collection before write
  - **Property 23: Rejections are collected before database write**
  - **Validates: Requirements 8.1**

- [ ] 7. Add configuration management for thresholds
  - Create configuration class or module for all threshold values
  - Load thresholds from environment variables with defaults
  - Add validation for threshold values (must be positive, within reasonable ranges)
  - Update all validation rules to use configurable thresholds
  - _Requirements: 4.1, 4.2, 2.1, 2.2, 3.1, 3.2, 6.1_

- [ ] 8. Implement error handling and edge cases
  - Add safe division helper for percentage calculations (handle zero denominators)
  - Add validation for price data (filter null/negative prices)
  - Implement timeout and retry logic for API calls
  - Add error logging with full context
  - Handle empty bars lists and single bar scenarios
  - _Requirements: 5.1, 5.2, 6.4_

- [ ]* 8.1 Write unit tests for edge cases
  - Test empty market data responses
  - Test insufficient bars (0, 1, 2, 3, 4 bars)
  - Test invalid bid/ask prices (zero, negative)
  - Test identical prices across all bars
  - Test null/None values in data structures

- [ ] 9. Add logging and monitoring
  - Add DEBUG logs for individual ticker validation results
  - Add INFO logs for cycle summaries and batch write results
  - Add WARNING logs for API errors and retry attempts
  - Add ERROR logs for database failures
  - Include rejection statistics in cycle summary logs
  - _Requirements: 8.3_

- [ ] 10. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [ ]* 11. Performance optimization
  - Profile validation pipeline to identify bottlenecks
  - Optimize trend calculation for large bar lists
  - Implement caching for repeated calculations within cycle
  - Verify latency requirements are met (< 1s per cycle)

- [ ]* 12. Integration testing
  - Test full entry cycle with mocked Alpaca API
  - Test batch writing with local DynamoDB or mocks
  - Test concurrent processing of 100+ tickers
  - Test error recovery and retry logic
  - Verify performance under load

- [ ] 13. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

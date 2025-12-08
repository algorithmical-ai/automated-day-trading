# Implementation Plan

- [x] 1. Create core data models
  - Create TrendMetrics dataclass with momentum_score, continuation_score, peak_price, bottom_price, and reason fields
  - Create Quote dataclass with bid, ask, mid_price property, and spread_percent property
  - Create ValidationResult dataclass with reason_not_to_enter_long and reason_not_to_enter_short fields
  - Create EvaluationRecord dataclass with all required fields for database storage
  - Add type hints and __str__ methods for debugging
  - _Requirements: 3.2, 3.5_

- [ ]* 1.1 Write property test for evaluation record structure
  - **Property 10: Evaluation records contain required fields**
  - **Validates: Requirements 3.2**

- [ ]* 1.2 Write property test for technical indicators structure
  - **Property 13: Technical indicators contain all metrics**
  - **Validates: Requirements 3.5**

- [x] 2. Implement TrendMetricsCalculator
  - Create TrendMetricsCalculator class with calculate_metrics static method
  - Implement momentum score calculation with amplification based on move consistency
  - Implement continuation score calculation (proportion of moves in trend direction)
  - Calculate peak_price (maximum) and bottom_price (minimum) from bars
  - Generate human-readable reason string in required format
  - Handle edge cases (single bar, identical prices, invalid prices)
  - _Requirements: 4.1, 4.2, 4.3, 5.1, 5.2, 6.1, 6.2, 7.1, 7.3, 7.4, 7.5_

- [ ]* 2.1 Write property test for momentum amplification
  - **Property 14: Momentum amplifies consistent moves**
  - **Validates: Requirements 4.3**

- [ ]* 2.2 Write property test for continuation score bounds
  - **Property 15: Continuation score bounds**
  - **Validates: Requirements 5.2**

- [ ]* 2.3 Write property test for continuation score calculation
  - **Property 16: Continuation score calculation**
  - **Validates: Requirements 5.1**

- [ ]* 2.4 Write property test for peak price
  - **Property 17: Peak price is maximum**
  - **Validates: Requirements 6.1**

- [ ]* 2.5 Write property test for bottom price
  - **Property 18: Bottom price is minimum**
  - **Validates: Requirements 6.2**

- [ ]* 2.6 Write property test for peak and bottom in technical indicators
  - **Property 19: Peak and bottom in technical indicators**
  - **Validates: Requirements 6.3**

- [ ]* 2.7 Write property test for reason string format
  - **Property 20: Reason string format**
  - **Validates: Requirements 7.1**

- [ ]* 2.8 Write property test for reason string in technical indicators
  - **Property 21: Reason string in technical indicators**
  - **Validates: Requirements 7.2**

- [ ]* 2.9 Write property test for bar count in reason
  - **Property 22: Reason string reflects actual bar count**
  - **Validates: Requirements 7.3**

- [ ]* 2.10 Write property test for up/down move counts
  - **Property 23: Up/down move counts are accurate**
  - **Validates: Requirements 7.4**

- [ ]* 2.11 Write property test for price formatting
  - **Property 24: Price formatting in reason**
  - **Validates: Requirements 7.5**

- [x] 3. Implement SimplifiedValidator
  - Create SimplifiedValidator class with validate method
  - Implement bid-ask spread check (reject both directions if > 2.0%)
  - Implement momentum-based trend direction check (negative momentum rejects long, positive rejects short)
  - Return ValidationResult with empty strings for valid directions
  - Handle edge cases (zero/negative bid/ask)
  - _Requirements: 1.1, 1.2, 1.4, 1.5, 2.1, 2.3, 2.4, 2.5_

- [ ]* 3.1 Write property test for spread calculation
  - **Property 6: Spread calculation correctness**
  - **Validates: Requirements 2.2**

- [ ]* 3.2 Write property test for negative momentum rejecting long
  - **Property 1: Negative momentum rejects long entry**
  - **Validates: Requirements 1.1, 1.4**

- [ ]* 3.3 Write property test for positive momentum rejecting short
  - **Property 2: Positive momentum rejects short entry**
  - **Validates: Requirements 1.2, 1.4**

- [ ]* 3.4 Write property test for negative momentum allowing short
  - **Property 3: Negative momentum allows short entry**
  - **Validates: Requirements 1.5**

- [ ]* 3.5 Write property test for positive momentum allowing long
  - **Property 4: Positive momentum allows long entry**
  - **Validates: Requirements 1.5**

- [ ]* 3.6 Write property test for wide spread rejecting both
  - **Property 5: Wide spread rejects both directions**
  - **Validates: Requirements 2.1**

- [ ]* 3.7 Write property test for wide spread rejection format
  - **Property 7: Wide spread rejection format**
  - **Validates: Requirements 2.3**

- [ ]* 3.8 Write property test for wide spread identical reasons
  - **Property 8: Wide spread applies to both directions identically**
  - **Validates: Requirements 2.4**

- [ ]* 3.9 Write property test for valid direction empty reason
  - **Property 11: Valid direction has empty reason**
  - **Validates: Requirements 3.3**

- [ ]* 3.10 Write property test for invalid direction non-empty reason
  - **Property 12: Invalid direction has non-empty reason**
  - **Validates: Requirements 3.4**

- [x] 4. Implement EvaluationRecordBuilder
  - Create EvaluationRecordBuilder class with build_record method
  - Build dictionary with ticker, indicator, reason fields, technical_indicators JSON, and timestamp
  - Format technical_indicators as nested dictionary with momentum_score, continuation_score, peak_price, bottom_price, and reason
  - Generate ISO 8601 timestamp
  - Validate all required fields are present
  - _Requirements: 3.2, 3.5, 7.2_

- [ ]* 4.1 Write property test for fully passing ticker
  - **Property 29: Fully passing ticker has empty reasons**
  - **Validates: Requirements 8.5**

- [x] 5. Implement InactiveTickerRepository
  - Create InactiveTickerRepository class with batch_write_evaluations method
  - Implement DynamoDB batch write logic using boto3
  - Add error handling for write failures (log and return False without throwing)
  - Format records for DynamoDB (convert to DynamoDB item format)
  - Add retry logic with exponential backoff for throttling
  - _Requirements: 3.1, 8.2, 8.3_

- [ ]* 5.1 Write property test for all evaluations persisted
  - **Property 9: All evaluations are persisted**
  - **Validates: Requirements 3.1**

- [ ]* 5.2 Write property test for single batch write
  - **Property 26: Single batch write per cycle**
  - **Validates: Requirements 8.2**

- [ ]* 5.3 Write property test for database failure handling
  - **Property 27: Database failures don't block cycle**
  - **Validates: Requirements 8.3**

- [x] 6. Integrate into PennyStocksIndicator entry cycle
  - Refactor _run_entry_cycle to use TrendMetricsCalculator
  - Replace existing validation logic with SimplifiedValidator
  - Use EvaluationRecordBuilder to create records for all tickers
  - Collect all evaluation records during cycle (both passing and failing)
  - Call InactiveTickerRepository.batch_write_evaluations at end of cycle
  - Ensure no database writes occur until all tickers are evaluated
  - _Requirements: 1.1, 1.2, 1.5, 8.1, 8.4_

- [ ]* 6.1 Write property test for records collected before write
  - **Property 25: Records collected before write**
  - **Validates: Requirements 8.1**

- [ ]* 6.2 Write property test for batch includes passing and failing
  - **Property 28: Batch includes passing and failing tickers**
  - **Validates: Requirements 8.4**

- [x] 7. Add configuration management
  - Create configuration class or module for threshold values
  - Load MAX_BID_ASK_SPREAD from environment variable (default: 2.0)
  - Load RECENT_BARS_COUNT from environment variable (default: 5)
  - Load INDICATOR_NAME from environment variable (default: "Penny Stocks")
  - Add validation for configuration values (must be positive, reasonable ranges)
  - Update SimplifiedValidator and TrendMetricsCalculator to use configuration
  - _Requirements: 2.1, 2.2_

- [x] 8. Implement error handling and edge cases
  - Add safe division helper for spread calculation (handle zero mid-price)
  - Add price filtering to remove null/negative prices before calculation
  - Handle empty bars list after filtering (set all metrics to 0.0)
  - Handle single bar scenario (use that bar for all calculations)
  - Handle identical prices (momentum = 0.0, continuation = 0.0)
  - Add error logging with full context for all error cases
  - _Requirements: 4.4, 4.5, 6.4, 6.5_

- [ ]* 8.1 Write unit tests for edge cases
  - Test zero and negative bid/ask prices
  - Test identical prices across all bars
  - Test single bar scenario
  - Test empty bars after filtering
  - Test division by zero in spread calculation

- [x] 9. Add logging and monitoring
  - Add DEBUG logs for individual ticker evaluation results
  - Add INFO logs for cycle summaries (N tickers evaluated, M valid for long, K valid for short)
  - Add WARNING logs for data quality issues (invalid prices, insufficient bars)
  - Add ERROR logs for database failures
  - Include momentum score distribution statistics in cycle summary
  - _Requirements: 8.3_

- [x] 10. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [ ]* 11. Performance testing and optimization
  - Profile trend calculation for performance bottlenecks
  - Verify cycle completes within 1 second for 100 tickers
  - Optimize batch write for large record sets
  - Test with realistic market data volumes

- [ ]* 12. Integration testing
  - Test full entry cycle with mocked Alpaca API
  - Test batch writing with local DynamoDB or mocks
  - Test mixed results (some tickers valid for long, some for short, some for both, some for neither)
  - Test error recovery (API failures, database failures)
  - Verify all tickers are recorded (not just rejections)

- [x] 13. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

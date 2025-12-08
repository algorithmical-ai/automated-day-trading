# Implementation Plan

- [x] 1. Create core data models
  - Create TechnicalIndicators dataclass with all TA fields (RSI, MACD, Bollinger, ADX, EMA, volume metrics, etc.)
  - Create ValidationResult dataclass with symmetric rejection support
  - Create MomentumEvaluationRecord dataclass with all required fields
  - Add type hints and __str__ methods for debugging
  - Add is_symmetric_rejection property to ValidationResult
  - _Requirements: 6.2, 6.5_

- [ ]* 1.1 Write property test for evaluation record structure
  - **Property 16: Evaluation records contain required fields**
  - **Validates: Requirements 6.2**

- [ ]* 1.2 Write property test for technical indicators completeness
  - **Property 19: Technical indicators completeness**
  - **Validates: Requirements 6.5, 7.1-7.10**

- [x] 2. Implement TechnicalIndicatorCalculator
  - Create TechnicalIndicatorCalculator class with calculate_indicators static method
  - Implement RSI calculation
  - Implement MACD calculation (3 values: macd, signal, histogram)
  - Implement Bollinger Bands calculation (3 values: upper, middle, lower)
  - Implement ADX calculation
  - Implement EMA fast and slow calculations
  - Implement volume metrics (volume_sma, OBV, MFI, A/D)
  - Implement momentum indicators (Stochastic, CCI, Williams %R, ROC)
  - Implement price averages (VWAP, VWMA, WMA)
  - Implement ATR calculation
  - Include datetime_price array with timestamp-price tuples
  - Handle edge cases (insufficient data, invalid prices)
  - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 7.7, 7.8, 7.9, 7.10_

- [x] 3. Implement MomentumValidator
  - Create MomentumValidator class with validate method
  - Implement security type check (ticker suffix: W, R, RT, WS)
  - Implement price floor check (>= $0.10)
  - Implement absolute volume check (>= 500)
  - Implement volume ratio check (>= 1.5x SMA)
  - Implement volatility check (ATR% <= 5.0%)
  - Return ValidationResult with symmetric rejection (both reasons identical)
  - Handle edge cases (zero volume SMA, zero/negative price)
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 2.1, 2.2, 2.3, 3.1, 3.2, 3.3, 4.1, 4.2, 4.3, 4.4, 5.1, 5.2, 5.3, 5.4_

- [ ]* 3.1 Write property test for warrant suffix rejection
  - **Property 1: Warrant/derivative suffix rejection**
  - **Validates: Requirements 1.1, 1.2, 1.3, 1.4**

- [ ]* 3.2 Write property test for symmetric security type rejection
  - **Property 2: Symmetric rejection for security type**
  - **Validates: Requirements 1.5**

- [ ]* 3.3 Write property test for price floor rejection
  - **Property 3: Price floor rejection**
  - **Validates: Requirements 2.1, 2.2, 2.5**

- [ ]* 3.4 Write property test for symmetric price rejection
  - **Property 4: Symmetric rejection for price**
  - **Validates: Requirements 2.3**

- [ ]* 3.5 Write property test for price floor pass-through
  - **Property 5: Price floor pass-through**
  - **Validates: Requirements 2.4**

- [ ]* 3.6 Write property test for absolute volume rejection
  - **Property 6: Absolute volume rejection**
  - **Validates: Requirements 3.1, 3.2, 3.5**

- [ ]* 3.7 Write property test for symmetric volume rejection
  - **Property 7: Symmetric rejection for volume**
  - **Validates: Requirements 3.3**

- [ ]* 3.8 Write property test for absolute volume pass-through
  - **Property 8: Absolute volume pass-through**
  - **Validates: Requirements 3.4**

- [ ]* 3.9 Write property test for volume ratio calculation
  - **Property 9: Volume ratio calculation**
  - **Validates: Requirements 4.2**

- [ ]* 3.10 Write property test for volume ratio rejection
  - **Property 10: Volume ratio rejection**
  - **Validates: Requirements 4.1, 4.3**

- [ ]* 3.11 Write property test for symmetric volume ratio rejection
  - **Property 11: Symmetric rejection for volume ratio**
  - **Validates: Requirements 4.4**

- [ ]* 3.12 Write property test for ATR percentage calculation
  - **Property 12: ATR percentage calculation**
  - **Validates: Requirements 5.2**

- [ ]* 3.13 Write property test for volatility rejection
  - **Property 13: Volatility rejection**
  - **Validates: Requirements 5.1, 5.3**

- [ ]* 3.14 Write property test for symmetric volatility rejection
  - **Property 14: Symmetric rejection for volatility**
  - **Validates: Requirements 5.4**

- [ ]* 3.15 Write property test for all symmetric rejections
  - **Property 24: All symmetric rejections are identical**
  - **Validates: Requirements 1.5, 2.3, 3.3, 4.4, 5.4, 6.4**

- [x] 4. Implement MomentumEvaluationRecordBuilder
  - Create MomentumEvaluationRecordBuilder class with build_record method
  - Build dictionary with ticker, indicator, reason fields, technical_indicators JSON, and timestamp
  - Format technical_indicators as comprehensive nested dictionary with all TA data
  - Generate ISO 8601 timestamp
  - Validate all required fields are present
  - Ensure symmetric rejection (both reason fields identical for failures)
  - _Requirements: 6.2, 6.5, 7.1-7.10_

- [ ]* 4.1 Write property test for passing ticker empty reasons
  - **Property 17: Passing ticker has empty reasons**
  - **Validates: Requirements 6.3**

- [ ]* 4.2 Write property test for failing ticker symmetric reasons
  - **Property 18: Failing ticker has symmetric reasons**
  - **Validates: Requirements 6.4**

- [x] 5. Reuse InactiveTickerRepository from penny-stock-simplified-validation
  - The existing InactiveTickerRepository already handles batch writes
  - No changes needed - it's indicator-agnostic
  - _Requirements: 6.1, 8.2, 8.3_

- [ ]* 5.1 Write property test for all evaluations persisted
  - **Property 15: All evaluations are persisted**
  - **Validates: Requirements 6.1**

- [ ]* 5.2 Write property test for single batch write
  - **Property 21: Single batch write per cycle**
  - **Validates: Requirements 8.2**

- [ ]* 5.3 Write property test for database failure handling
  - **Property 22: Database failures don't block cycle**
  - **Validates: Requirements 8.3**

- [x] 6. Implement MomentumEntryCycle
  - Create MomentumEntryCycle class for entry cycle orchestration
  - Integrate TechnicalIndicatorCalculator for comprehensive TA
  - Use MomentumValidator for symmetric validation
  - Use MomentumEvaluationRecordBuilder to create records
  - Collect all evaluation records during cycle (both passing and failing)
  - Call InactiveTickerRepository.batch_write_evaluations at end of cycle
  - Ensure no database writes occur until all tickers are evaluated
  - Add comprehensive logging for cycle statistics
  - _Requirements: 6.1, 6.3, 6.4, 8.1, 8.4_

- [ ]* 6.1 Write property test for records collected before write
  - **Property 20: Records collected before write**
  - **Validates: Requirements 8.1**

- [ ]* 6.2 Write property test for batch includes passing and failing
  - **Property 23: Batch includes passing and failing tickers**
  - **Validates: Requirements 8.4**

- [x] 7. Add configuration management
  - Create configuration class or module for threshold values
  - Load MIN_PRICE_THRESHOLD from environment variable (default: 0.10)
  - Load MIN_VOLUME_THRESHOLD from environment variable (default: 500)
  - Load MIN_VOLUME_RATIO from environment variable (default: 1.5)
  - Load MAX_ATR_PERCENT from environment variable (default: 5.0)
  - Load INDICATOR_NAME from environment variable (default: "Momentum Trading")
  - Load WARRANT_SUFFIXES from environment variable (default: "W,R,RT,WS")
  - Add validation for configuration values
  - Update MomentumValidator to use configuration
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 2.1, 3.1, 4.1, 5.1_

- [x] 8. Implement error handling and edge cases
  - Add safe division helper for ratio and percentage calculations
  - Add validation for volume SMA (handle zero/negative)
  - Add validation for price in ATR calculation (handle zero/negative)
  - Handle insufficient data for technical indicators
  - Handle invalid prices in technical indicator calculations
  - Add error logging with full context for all error cases
  - _Requirements: 4.5, 5.5_

- [ ]* 8.1 Write unit tests for edge cases
  - Test zero volume SMA
  - Test zero/negative price for ATR calculation
  - Test warrant suffix variations (case sensitivity)
  - Test boundary values for all thresholds
  - Test insufficient data for technical indicators

- [x] 9. Add logging and monitoring
  - Add DEBUG logs for individual ticker evaluation results
  - Add INFO logs for cycle summaries (N tickers evaluated, M passing, rejection breakdown)
  - Add WARNING logs for data quality issues and calculation errors
  - Add ERROR logs for database failures
  - Include rejection statistics by rule type in cycle summary
  - Log symmetric rejection verification
  - _Requirements: 8.3_

- [x] 10. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [ ]* 11. Performance testing and optimization
  - Profile technical indicator calculation for performance
  - Verify cycle completes within 2 seconds for 100 tickers
  - Optimize batch write for large record sets
  - Test with realistic market data volumes

- [ ]* 12. Integration testing
  - Test full entry cycle with mocked market data
  - Test batch writing with local DynamoDB or mocks
  - Test mixed results (some passing, some failing)
  - Test error recovery (API failures, database failures)
  - Verify symmetric rejection across all rules
  - Verify comprehensive technical indicators in all records

- [x] 13. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

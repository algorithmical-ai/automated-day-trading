# Implementation Plan

- [ ] 1. Remove LiquidityRule from validation pipeline
  - Modify `_validate_ticker_with_pipeline` method in `penny_stocks_indicator.py`
  - Remove LiquidityRule instantiation from the rules list
  - Add comment explaining why spread check was removed
  - _Requirements: 1.1, 1.2, 4.1_

- [ ]* 1.1 Write property test for spread not affecting validation
  - **Property 1: Wide spread does not reject entries**
  - **Validates: Requirements 1.3, 2.3, 2.4**

- [ ] 2. Remove spread validation from _passes_filters method
  - Remove quote fetching code used only for spread calculation
  - Remove bid/ask validation code
  - Remove spread calculation code
  - Remove spread comparison and rejection logic
  - Keep price range and volume validation
  - _Requirements: 4.2, 4.3, 4.4_

- [ ]* 2.1 Write property test for rejection reasons
  - **Property 2: Rejection reasons never mention spread**
  - **Validates: Requirements 1.5, 4.4, 5.4**

- [ ] 3. Remove spread check from _process_ticker_entry method
  - Remove spread calculation before entry
  - Remove spread percentage comparison
  - Remove spread-related logging
  - Keep entry price calculation using bid/ask
  - _Requirements: 4.5, 1.4_

- [ ]* 3.1 Write property test for entry price calculation
  - **Property 5: Entry price calculation unchanged**
  - **Validates: Requirements 1.4**

- [ ] 4. Verify all other validation rules remain active
  - Ensure DataQualityRule is still in the pipeline
  - Ensure TrendDirectionRule is still in the pipeline
  - Ensure ContinuationRule is still in the pipeline
  - Ensure PriceExtremeRule is still in the pipeline
  - Ensure MomentumThresholdRule is still in the pipeline
  - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5_

- [ ]* 4.1 Write property tests for remaining validation rules
  - **Property 6: DataQualityRule still active**
  - **Property 7: TrendDirectionRule still active**
  - **Property 8: ContinuationRule still active**
  - **Property 9: PriceExtremeRule still active**
  - **Property 10: MomentumThresholdRule still active**
  - **Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5**

- [ ] 5. Update logging to remove spread references
  - Remove spread percentage from validation logs
  - Remove spread-related rejection logs
  - Remove spread from entry price logs
  - Keep bid/ask prices in entry logs
  - _Requirements: 1.5, 7.4_

- [ ]* 5.1 Write property test for log content
  - **Property 14: Logs don't reference spread config**
  - **Validates: Requirements 7.4**

- [ ] 6. Verify database compatibility
  - Ensure rejection records maintain same structure
  - Ensure technical_indicators JSON format unchanged
  - Ensure no spread-related text in rejection reasons
  - Test batch writing with new validation logic
  - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5_

- [ ]* 6.1 Write property tests for database records
  - **Property 11: Evaluation records maintain structure**
  - **Property 12: Technical indicators unchanged**
  - **Validates: Requirements 5.1, 5.2, 5.3, 5.5**

- [ ] 7. Verify configuration compatibility
  - Ensure max_bid_ask_spread_percent is ignored
  - Ensure other configuration parameters still work
  - Ensure no configuration file updates needed
  - Test with various spread configuration values
  - _Requirements: 7.1, 7.2, 7.3, 7.5_

- [ ]* 7.1 Write property test for configuration
  - **Property 13: Configuration parameter ignored**
  - **Validates: Requirements 7.1**

- [ ] 8. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [ ]* 9. Write integration tests for end-to-end validation
  - Test full entry cycle with wide spread tickers
  - Test validation pipeline without LiquidityRule
  - Test database writes without spread rejections
  - Test entry price calculation in actual trades
  - _Requirements: All_

- [ ]* 10. Update property-based tests
  - Remove spread-related test properties
  - Update test generators to not require spread values
  - Add tests verifying spread doesn't affect validation
  - Ensure momentum-based tests still pass
  - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5_

- [ ]* 11. Write property tests for momentum-based validation
  - **Property 3: Positive momentum allows long entry regardless of spread**
  - **Property 4: Negative momentum allows short entry regardless of spread**
  - **Validates: Requirements 2.3, 2.4**

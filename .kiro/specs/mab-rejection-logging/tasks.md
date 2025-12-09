# Implementation Plan: MAB Rejection Logging

- [x] 1. Implement MAB rejection reason generation in MABService
  - Add `get_rejection_reason()` class method to generate human-readable rejection reasons
  - Format: "MAB rejected: {reason} (successes: X, failures: Y, total: Z)"
  - Handle cases: low success rate, excluded ticker, new ticker
  - _Requirements: 1.2, 2.2, 3.2, 3.3_

- [x]* 1.1 Write property test for MAB rejection reason format
  - **Feature: mab-rejection-logging, Property 2: MAB Rejection Reason Format**
  - **Validates: Requirements 1.2, 2.2, 3.2, 3.3**
  - Generate random MAB statistics (successes, failures)
  - Verify reason contains "MAB rejected:" prefix
  - Verify reason contains success rate information

- [x] 2. Enhance MABService.select_tickers_with_mab() to track rejections
  - Modify method to return both selected tickers and rejected tickers with reasons
  - Separate rejections by direction (long/short)
  - Include technical indicators for each rejected ticker
  - _Requirements: 1.1, 2.1, 3.2_

- [x]* 2.1 Write property test for MAB rejection tracking
  - **Feature: mab-rejection-logging, Property 1: MAB Rejection Logging for Long Positions**
  - **Validates: Requirements 1.1, 5.1**
  - Generate random tickers with positive momentum scores
  - Mock MAB to reject them
  - Verify rejection information is returned correctly

- [x] 3. Add MAB rejection logging to PennyStocksIndicator._run_entry_cycle()
  - After MAB selection, identify tickers that passed validation but were rejected
  - For each rejected ticker, determine direction based on momentum score
  - Log rejection with appropriate direction-specific reason
  - Handle both long and short rejections
  - _Requirements: 1.1, 2.1, 5.1, 5.2, 5.3_

- [x]* 3.1 Write property test for long position MAB rejection logging
  - **Feature: mab-rejection-logging, Property 1: MAB Rejection Logging for Long Positions**
  - **Validates: Requirements 1.1, 5.1**
  - Generate tickers with positive momentum scores
  - Mock MAB rejection
  - Verify log entry with `reason_not_to_enter_long` populated
  - Verify `reason_not_to_enter_short` is empty

- [x]* 3.2 Write property test for short position MAB rejection logging
  - **Feature: mab-rejection-logging, Property 3: MAB Rejection Logging for Short Positions**
  - **Validates: Requirements 2.1, 5.2**
  - Generate tickers with negative momentum scores
  - Mock MAB rejection
  - Verify log entry with `reason_not_to_enter_short` populated
  - Verify `reason_not_to_enter_long` is empty

- [x] 4. Add MAB rejection logging to MomentumIndicator._run_entry_cycle()
  - Mirror implementation from PennyStocksIndicator
  - Log MAB rejections for both long and short positions
  - Include technical indicators in logs
  - _Requirements: 1.1, 2.1, 5.1, 5.2, 5.3_

- [x]* 4.1 Write property test for momentum indicator MAB rejection logging
  - **Feature: mab-rejection-logging, Property 1: MAB Rejection Logging for Long Positions**
  - **Validates: Requirements 1.1, 5.1**
  - Test MAB rejection logging in MomentumIndicator context

- [x] 5. Handle new tickers (no MAB statistics) - ensure they are NOT logged as rejected
  - Verify that tickers with no historical MAB data are explored by Thompson Sampling
  - Ensure new tickers are not logged to InactiveTickersForDayTrading
  - _Requirements: 1.4, 2.4_

- [x]* 5.1 Write property test for new ticker handling
  - **Feature: mab-rejection-logging, Property 4: New Tickers Not Logged as Rejected**
  - **Validates: Requirements 1.4, 2.4**
  - Generate new tickers with no MAB statistics
  - Verify they are NOT logged to InactiveTickersForDayTrading
  - Verify they are selected by MAB (explored)

- [x] 6. Handle excluded tickers - log with exclusion reason and end time
  - When a ticker has `excluded_until` timestamp in future, log it as rejected
  - Include exclusion end time in rejection reason
  - _Requirements: 1.3, 2.3_

- [x]* 6.1 Write property test for excluded ticker handling
  - **Feature: mab-rejection-logging, Property 5: Excluded Tickers Logged with Exclusion Reason**
  - **Validates: Requirements 1.3, 2.3**
  - Generate tickers with `excluded_until` timestamp in future
  - Verify they are logged with rejection reason
  - Verify reason mentions exclusion status and end time

- [x] 7. Ensure technical indicators are included in MAB rejection logs
  - Extract technical indicators from market data for rejected tickers
  - Serialize to JSON format
  - Include momentum score, volume, price, etc.
  - _Requirements: 4.1, 4.3_

- [x]* 7.1 Write property test for technical indicators in MAB rejections
  - **Feature: mab-rejection-logging, Property 6: Technical Indicators Included in MAB Rejections**
  - **Validates: Requirements 4.1, 4.3**
  - Generate random technical indicators
  - Log MAB rejections with these indicators
  - Verify `technical_indicators` field contains the data in JSON format

- [x] 8. Handle direction-specific rejections correctly
  - When MAB rejects for long only: populate `reason_not_to_enter_long`, leave `reason_not_to_enter_short` empty
  - When MAB rejects for short only: populate `reason_not_to_enter_short`, leave `reason_not_to_enter_long` empty
  - When MAB rejects for both: populate both fields
  - _Requirements: 5.1, 5.2, 5.3_

- [x]* 8.1 Write property test for direction-specific rejection handling
  - **Feature: mab-rejection-logging, Property 7: Direction-Specific Rejection Handling**
  - **Validates: Requirements 5.3**
  - Generate tickers rejected for both long and short
  - Verify both `reason_not_to_enter_long` and `reason_not_to_enter_short` are populated

- [x] 9. Ensure selected tickers are NOT logged to InactiveTickersForDayTrading
  - Verify that tickers selected by MAB for trading are not logged
  - Only log tickers that passed validation but were rejected by MAB
  - _Requirements: 5.4_

- [x]* 9.1 Write property test for selected ticker exclusion
  - **Feature: mab-rejection-logging, Property 8: Selected Tickers Not Logged**
  - **Validates: Requirements 5.4**
  - Generate tickers selected by MAB
  - Verify they are NOT logged to InactiveTickersForDayTrading

- [x] 10. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 11. Add error handling for DynamoDB write failures
  - Log warnings if rejection logging fails
  - Continue processing other rejections (don't block entry cycle)
  - _Requirements: 1.1, 2.1_

- [x] 12. Verify timestamps are in EST/EDT timezone
  - Ensure all logged timestamps use America/New_York timezone
  - Verify EST/EDT transitions are handled correctly
  - _Requirements: 1.1, 2.1_

- [x]* 12.1 Write integration test for end-to-end MAB rejection logging
  - Test complete entry cycle with MAB rejection logging
  - Verify rejected tickers appear in InactiveTickersForDayTrading table
  - Verify selected tickers do not appear in the table
  - Verify timestamps are in EST/EDT timezone

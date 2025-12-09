# Implementation Plan

- [x] 1. Add configuration constants for profit-taking exit thresholds
  - Add `MIN_PROFIT_FOR_PROFIT_TAKING_EXIT = 0.5` constant
  - Add `DIP_RISE_THRESHOLD_PERCENT = 1.0` constant
  - Add `MIN_HOLDING_SECONDS_FOR_PROFIT_TAKING = 60` constant
  - Add constants to `MomentumIndicator` class attributes
  - _Requirements: 3.1, 3.3, 4.1_

- [x] 2. Implement `_filter_bars_after_entry()` helper method
  - [x] 2.1 Create the `_filter_bars_after_entry()` method
    - Parse `created_at` timestamp to datetime
    - Filter bars list to only include bars with timestamp > created_at
    - Handle edge cases (missing timestamp, invalid format)
    - Return filtered list of bars
    - _Requirements: 2.1, 2.2, 2.3_

  - [ ]* 2.2 Write property test for bar filtering
    - **Property 2: Peak/bottom calculation only uses post-entry bars**
    - Generate random bars with timestamps before and after entry
    - Verify filtered bars only contain post-entry timestamps
    - **Validates: Requirements 2.1, 2.2**

- [x] 3. Implement `_should_trigger_profit_taking_exit()` helper method
  - [x] 3.1 Create the `_should_trigger_profit_taking_exit()` method
    - Check if profit_from_entry > 0 (required for any profit-taking exit)
    - Check if profit_from_entry >= MIN_PROFIT_FOR_PROFIT_TAKING_EXIT (0.5%)
    - Check if holding_seconds >= MIN_HOLDING_SECONDS_FOR_PROFIT_TAKING (60s)
    - Check if dip/rise exceeds DIP_RISE_THRESHOLD_PERCENT (1.0%)
    - Return (should_exit, reason) tuple
    - _Requirements: 1.1, 1.2, 3.1, 4.1_

  - [ ]* 3.2 Write property test for profit requirement
    - **Property 1: Profit-taking exits require positive profit**
    - Generate random trades with various profit levels
    - Verify exits only trigger when profit > 0
    - **Validates: Requirements 1.1, 1.2, 1.3**

  - [ ]* 3.3 Write property test for minimum profit threshold
    - **Property 3: Minimum profit threshold enforced**
    - Generate random trades with profit < 0.5%
    - Verify profit-taking exits never trigger
    - **Validates: Requirements 3.1, 3.2**

  - [ ]* 3.4 Write property test for dip/rise threshold
    - **Property 4: Dip/rise threshold is 1.0% when profit threshold met**
    - Generate random trades with profit >= 0.5%
    - Verify 1.0% threshold is used for exit evaluation
    - **Validates: Requirements 3.3**

  - [ ]* 3.5 Write property test for minimum holding time
    - **Property 5: Profit-taking exits respect minimum holding time**
    - Generate random trades held < 60 seconds
    - Verify profit-taking exits never trigger
    - **Validates: Requirements 4.1, 4.2**

- [x] 4. Modify `_run_exit_cycle()` to use new logic
  - [x] 4.1 Update peak/bottom calculation to filter bars
    - Call `_filter_bars_after_entry()` before calculating peak/bottom
    - Use entry price as fallback if no post-entry bars exist
    - _Requirements: 2.1, 2.2, 2.3_

  - [x] 4.2 Replace inline profit-taking exit logic with helper method
    - Replace "PRIORITY 1: Exit on profitable trend reversal" section
    - Call `_should_trigger_profit_taking_exit()` instead of inline checks
    - Add logging when exits are skipped due to insufficient profit or holding time
    - _Requirements: 1.1, 1.2, 3.1, 4.1, 5.1, 5.2, 5.3_

  - [ ]* 4.3 Write property test for stop loss during holding period
    - **Property 6: Stop loss still works during holding period**
    - Generate random trades held < 60 seconds with losses exceeding stop loss
    - Verify stop loss exit still triggers
    - **Validates: Requirements 4.3**

- [x] 5. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [ ]* 6. Write integration test for complete exit cycle
  - Test full exit cycle with mock trade data
  - Verify correct behavior for profitable vs unprofitable trades
  - Verify correct behavior for short vs long holding times
  - _Requirements: 1.1, 1.2, 2.1, 2.2, 3.1, 4.1_

- [x] 7. Final Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

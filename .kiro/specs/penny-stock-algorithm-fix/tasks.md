# Implementation Plan

- [x] 1. Create utility calculators for spread and ATR
  - [x] 1.1 Implement SpreadCalculator class
    - Create `calculate_spread_percent(bid, ask)` method
    - Create `calculate_breakeven_price(entry_price, spread_percent, is_long)` method
    - Handle edge cases (zero/negative prices)
    - _Requirements: 1.1, 1.2_

  - [ ]* 1.2 Write property test for breakeven calculation
    - **Property 1: Breakeven Calculation Accounts for Spread**
    - **Validates: Requirements 1.1, 1.2**

  - [x] 1.3 Implement ATRCalculator class
    - Create `calculate_atr(bars, period)` method using true range formula
    - Create `calculate_stop_loss_percent(atr, current_price, multiplier, min_stop, max_stop)` method
    - Return None when insufficient bars, default to -2% stop
    - _Requirements: 4.1, 4.2, 4.3_

  - [ ]* 1.4 Write property test for ATR stop loss bounds
    - **Property 7: ATR-Based Stop Loss Bounds**
    - **Validates: Requirements 4.1, 4.2, 4.3**

- [x] 2. Implement TieredTrailingStop class
  - [x] 2.1 Create TrailingStopConfig dataclass and tier definitions
    - Define tiers: 1% profit → 0.5% trail, 2% profit → 0.3% trail, 3% profit → 1.5% lock
    - _Requirements: 3.1, 3.2, 3.3_

  - [x] 2.2 Implement get_trailing_stop_price method
    - Calculate trailing stop price based on current profit tier
    - Handle both long and short positions
    - Enforce minimum locked profit at 3% tier
    - _Requirements: 3.1, 3.2, 3.3, 3.4_

  - [ ]* 2.3 Write property test for tiered trailing stop
    - **Property 6: Tiered Trailing Stop Progression**
    - **Validates: Requirements 3.1, 3.2, 3.3, 3.4**

- [x] 3. Implement MomentumConfirmation class
  - [x] 3.1 Create is_momentum_confirmed method
    - Check that at least 3 of last 5 bars move in trend direction
    - Verify most recent bar confirms trend
    - Return (is_confirmed, reason) tuple
    - _Requirements: 6.1, 6.2_

  - [ ]* 3.2 Write property test for momentum confirmation
    - **Property 8: Momentum Confirmation for Entry**
    - **Validates: Requirements 6.1, 6.2**

- [x] 4. Implement ExitDecisionEngine class
  - [x] 4.1 Create ExitDecision dataclass
    - Fields: should_exit, reason, exit_type, is_spread_induced
    - _Requirements: 7.3_

  - [x] 4.2 Implement evaluate_exit method with priority-based logic
    - Priority 1: Emergency exit on loss > 3% (always active)
    - Priority 2: Block non-emergency exits during 60s holding period
    - Priority 3: Trailing stop check for profitable trades
    - Priority 4: ATR-based stop loss with consecutive check requirement
    - _Requirements: 2.1, 2.2, 2.3, 5.1, 5.2, 5.3_

  - [ ]* 4.3 Write property test for holding period restrictions
    - **Property 3: Holding Period Exit Restrictions**
    - **Validates: Requirements 2.1, 5.1, 5.2, 5.3**

  - [ ]* 4.4 Write property test for consecutive check requirement
    - **Property 5: Consecutive Check Requirement**
    - **Validates: Requirements 2.3**

- [x] 5. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 6. Integrate calculators into PennyStocksIndicator entry flow
  - [x] 6.1 Add spread validation to entry filter
    - Calculate spread using SpreadCalculator
    - Reject tickers with spread > 3%
    - _Requirements: 1.3_

  - [ ]* 6.2 Write property test for high spread rejection
    - **Property 2: High Spread Rejection**
    - **Validates: Requirements 1.3**

  - [x] 6.3 Add momentum confirmation check before entry
    - Use MomentumConfirmation.is_momentum_confirmed()
    - Skip entry if not confirmed
    - Log confirmation details
    - _Requirements: 6.1, 6.2, 6.3_

  - [x] 6.4 Calculate and store breakeven price and ATR stop on entry
    - Calculate spread at entry time
    - Compute breakeven price using SpreadCalculator
    - Calculate ATR-based stop loss using ATRCalculator
    - Store in trade record (DynamoDB)
    - _Requirements: 1.1, 1.2, 4.1, 4.2_

- [x] 7. Integrate ExitDecisionEngine into PennyStocksIndicator exit flow
  - [x] 7.1 Replace current exit logic with ExitDecisionEngine
    - Remove immediate loss exit logic
    - Use evaluate_exit() for all exit decisions
    - Pass breakeven_price, atr_stop_percent, holding_seconds to engine
    - _Requirements: 2.1, 2.2, 2.3, 5.1, 5.2, 5.3_

  - [x] 7.2 Implement tiered trailing stop in exit cycle
    - Track peak price and peak profit
    - Use TieredTrailingStop.get_trailing_stop_price()
    - Exit when trailing stop triggered
    - _Requirements: 3.1, 3.2, 3.3, 3.4_

  - [x] 7.3 Update minimum holding period to 60 seconds
    - Change min_holding_period_seconds from 15 to 60
    - Only allow emergency exits during holding period
    - _Requirements: 5.1, 5.2_

- [x] 8. Implement performance metrics tracking
  - [x] 8.1 Create DailyPerformanceMetrics dataclass
    - Track total_trades, winning_trades, losing_trades
    - Track total_profit, total_loss, spread_induced_losses
    - Implement win_rate, average_win, average_loss, profit_factor properties
    - _Requirements: 7.2_

  - [x] 8.2 Add loss classification on exit
    - Classify as spread-induced if loss <= 1.5x spread
    - Log classification with exit details
    - _Requirements: 7.3_

  - [ ]* 8.3 Write property test for loss classification
    - **Property 10: Loss Classification**
    - **Validates: Requirements 7.3**

  - [x] 8.4 Add end-of-day metrics logging
    - Calculate and log win rate, average win, average loss, profit factor
    - Reset metrics at start of new trading day
    - _Requirements: 7.2_

  - [ ]* 8.5 Write property test for performance metrics calculation
    - **Property 9: Performance Metrics Calculation**
    - **Validates: Requirements 7.2**

- [x] 9. Final Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

# Implementation Plan

- [x] 1. Set up project structure and core configuration
  - Create directory structure for services, indicators, clients, and utilities
  - Implement centralized trading configuration (trading_config.py) with ATR multipliers and bounds
  - Set up environment variable loading and validation
  - Configure logging with Loguru
  - _Requirements: 19.1, 19.2, 19.3, 19.4, 16.1_

- [x] 1.1 Write property test for configuration consistency
  - **Property 77: Stop Loss ATR Multiplier Consistency**
  - **Property 78: Trailing Stop ATR Multiplier Consistency**
  - **Property 79: Stop Loss Bounds Consistency**
  - **Property 80: Trailing Stop Bounds Consistency**
  - **Validates: Requirements 19.1, 19.2, 19.3, 19.4**

- [x] 2. Implement DynamoDB client and data models
  - Create DynamoDB client with async operations (put_item, get_item, delete_item, query, scan, update_item)
  - Implement data models (ActiveTrade, CompletedTrade, InactiveTicker, ThresholdAdjustmentEvent, MABStats)
  - Add error handling with detailed logging and graceful degradation
  - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5_

- [ ]* 2.1 Write property test for DynamoDB operations
  - **Property 27: Active Trade Storage**
  - **Property 28: Trade Movement on Exit**
  - **Property 29: Inactive Ticker Logging**
  - **Property 30: Threshold Adjustment Event Storage**
  - **Property 31: DynamoDB Error Handling**
  - **Validates: Requirements 7.1, 7.2, 7.3, 7.4, 7.5**

- [x] 3. Implement MCP API client
  - Create MCP client with HTTP POST requests and Bearer token authentication
  - Implement tool methods (get_market_clock, get_market_data, get_alpaca_screened_tickers, get_quote, enter_trade, exit_trade, send_webhook_signal)
  - Add exponential backoff retry logic for failed requests
  - Implement shared HTTP session management
  - _Requirements: 10.1, 10.2, 10.3, 10.4, 10.5, 20.1_

- [ ]* 3.1 Write property test for MCP API integration
  - **Property 41: MCP API Authentication**
  - **Property 42: MCP API Retry Logic**
  - **Property 81: Shared HTTP Session Usage**
  - **Validates: Requirements 10.4, 10.5, 20.1**

- [x] 4. Implement MAB service with Thompson Sampling
  - Create MAB service with Thompson Sampling algorithm for ticker selection
  - Implement statistics management (get_stats, update_stats, exclude_ticker)
  - Add support for separate statistics per indicator#ticker combination
  - Implement ticker exclusion for losing trades
  - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5_

- [ ]* 4.1 Write property test for MAB algorithm
  - **Property 6: MAB Ticker Selection**
  - **Property 32: MAB Statistics Separation**
  - **Property 33: MAB Statistics Update**
  - **Property 34: Losing Ticker Exclusion**
  - **Property 35: MAB Direction Separation**
  - **Validates: Requirements 8.1, 8.2, 8.3, 8.4, 8.5**

- [x] 5. Implement base trading indicator infrastructure
  - Create BaseTradingIndicator abstract class with shared functionality
  - Implement market clock checking with timezone handling (UTC internally, EST for market logic)
  - Add ticker screening integration with Alpaca
  - Implement cooldown management with thread-safe operations
  - Add daily trade limit enforcement with golden ticker bypass
  - Implement shared trade entry/exit methods with DynamoDB integration
  - Add inactive ticker logging
  - _Requirements: 1.4, 11.4, 11.5, 12.1, 12.2, 12.3, 12.4, 12.5, 14.1, 14.2, 14.3, 14.4_

- [ ]* 5.1 Write property test for thread-safe operations
  - **Property 2: Thread-Safe Concurrent Access**
  - **Property 50: Thread-Safe Cooldown Checks**
  - **Property 84: Thread-Safe Resource Access**
  - **Validates: Requirements 1.4, 12.3, 20.4**

- [ ]* 5.2 Write property test for cooldown management
  - **Property 48: Cooldown Timestamp Recording**
  - **Property 49: Cooldown Period Enforcement**
  - **Property 51: Golden Ticker Cooldown Bypass**
  - **Property 52: Daily Cooldown Reset**
  - **Validates: Requirements 12.1, 12.2, 12.4, 12.5**

- [ ]* 5.3 Write property test for market clock handling
  - **Property 58: Market Clock Check Before Operations**
  - **Property 59: Closed Market Operation Skip**
  - **Property 60: UTC Timestamp Storage**
  - **Property 61: EST Timezone Conversion for Market Logic**
  - **Validates: Requirements 14.1, 14.2, 14.3, 14.4**

- [ ]* 5.4 Write property test for trade limits
  - **Property 46: Active Trade Limit Enforcement**
  - **Property 47: Daily Trade Limit Enforcement**
  - **Validates: Requirements 11.4, 11.5**

- [x] 6. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 7. Implement Momentum Trading Indicator
  - Create MomentumTradingIndicator class extending BaseTradingIndicator
  - Implement momentum calculation (early 30% vs recent 30% of price data)
  - Add technical filter validation (ADX, RSI, stochastic, Bollinger Bands, volume, price)
  - Implement entry service with 5-second cycle
  - Implement exit service with stop loss, trailing stop, profit target, and time-based exits
  - Add MAB integration for ticker selection
  - Set dynamic stop loss at 2.0x ATR and position size at $2000
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5_

- [ ]* 7.1 Write property test for momentum calculation
  - **Property 3: Momentum Calculation Consistency**
  - **Validates: Requirements 2.1**

- [ ]* 7.2 Write property test for entry conditions
  - **Property 4: Long Entry Conditions**
  - **Property 5: Short Entry Conditions**
  - **Validates: Requirements 2.2, 2.3**

- [ ]* 7.3 Write property test for trade parameters
  - **Property 7: Trade Entry Parameters**
  - **Validates: Requirements 2.5**

- [x] 8. Implement Penny Stocks Indicator
  - Create PennyStocksIndicator class extending BaseTradingIndicator
  - Implement trend analysis for recent 5 bars
  - Add price range filtering ($0.01-$5.00)
  - Implement bid-ask spread, volume, and special security filtering
  - Add losing ticker exclusion from MAB
  - Implement trade preemption for exceptional momentum (≥8%)
  - Implement entry service with 1-second cycle
  - Implement exit service with fast exits (unprofitability, trend reversal, significant loss)
  - Set tight trailing stop (0.5%) and quick profit target (0.5%)
  - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5_

- [ ]* 8.1 Write property test for trend analysis
  - **Property 8: Penny Stock Trend Analysis**
  - **Validates: Requirements 3.1**

- [ ]* 8.2 Write property test for entry conditions
  - **Property 9: Penny Stock Long Entry Conditions**
  - **Property 10: Penny Stock Short Entry Conditions**
  - **Validates: Requirements 3.2, 3.3**

- [ ]* 8.3 Write property test for filtering
  - **Property 11: Penny Stock Filtering**
  - **Validates: Requirements 3.4**

- [ ]* 8.4 Write property test for preemption
  - **Property 12: Trade Preemption**
  - **Validates: Requirements 3.5**

- [ ] 9. Implement Deep Analyzer Indicator
  - Create DeepAnalyzerIndicator class extending BaseTradingIndicator
  - Implement MCP API integration for entry score retrieval
  - Add entry logic with score threshold (≥0.60) and portfolio correlation check (max 3 per direction)
  - Implement golden ticker detection (score ≥0.75) with daily limit bypass
  - Add exit logic with signal reversal detection and score degradation check (>50% drop)
  - Store entry score for degradation comparison
  - Implement entry and exit services with 5-second cycles
  - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5_

- [ ]* 9.1 Write property test for entry score logic
  - **Property 13: Deep Analyzer Entry Score Threshold**
  - **Property 14: Golden Ticker Bypass**
  - **Validates: Requirements 4.2, 4.3**

- [ ]* 9.2 Write property test for exit logic
  - **Property 15: Signal Reversal Exit**
  - **Property 16: Score Degradation Exit**
  - **Validates: Requirements 4.4, 4.5**

- [ ] 10. Implement UW-Enhanced Momentum Indicator
  - Create UWEnhancedMomentumIndicator class extending BaseTradingIndicator
  - Implement momentum calculation using same method as Momentum Trading Indicator
  - Add Unusual Whales API integration for options flow validation
  - Implement risk-adjusted position sizing based on volatility and penny stock risk
  - Add time-based entry cutoff (no entries after 3:00 PM ET)
  - Implement wider trailing stops for shorts (1.5x multiplier)
  - Implement entry and exit services with 5-second cycles
  - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5_

- [ ]* 10.1 Write property test for momentum consistency
  - **Property 17: UW Momentum Calculation Consistency**
  - **Validates: Requirements 5.1**

- [ ]* 10.2 Write property test for UW validation
  - **Property 18: UW Validation Before Entry**
  - **Validates: Requirements 5.2**

- [ ]* 10.3 Write property test for position sizing
  - **Property 19: Risk-Adjusted Position Sizing**
  - **Validates: Requirements 5.3**

- [ ]* 10.4 Write property test for time cutoff
  - **Property 20: Time-Based Entry Cutoff**
  - **Validates: Requirements 5.4**

- [ ]* 10.5 Write property test for short trailing stop
  - **Property 21: Short Trailing Stop Multiplier**
  - **Validates: Requirements 5.5**

- [x] 11. Implement comprehensive exit logic for all indicators
  - Add hard stop loss exit logic
  - Implement trailing stop activation at profit threshold
  - Add trailing stop exit logic (price moves beyond trailing stop distance from peak profit)
  - Implement end-of-day forced closure (15 minutes before market close)
  - Add minimum holding period enforcement
  - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5_

- [ ]* 11.1 Write property test for exit conditions
  - **Property 22: Hard Stop Loss Exit**
  - **Property 23: Trailing Stop Activation**
  - **Property 24: Trailing Stop Exit**
  - **Property 25: End-of-Day Forced Closure**
  - **Property 26: Minimum Holding Period**
  - **Validates: Requirements 6.1, 6.2, 6.3, 6.4, 6.5**

- [x] 12. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 13. Implement risk management utilities
  - Create stop loss calculation function (2.0x ATR with bounds)
  - Implement position sizing calculation ($2000 base, reduced for high volatility/risk, min $500)
  - Add entry filtering logic (momentum, ADX, volume, price)
  - Implement pricing logic (bid/ask selection for long/short entry/exit)
  - _Requirements: 11.1, 11.2, 11.3, 18.1, 18.2, 18.3, 18.4, 18.5_

- [ ]* 13.1 Write property test for stop loss calculation
  - **Property 43: Dynamic Stop Loss Calculation**
  - **Validates: Requirements 11.1**

- [ ]* 13.2 Write property test for position sizing
  - **Property 44: Position Size Calculation**
  - **Validates: Requirements 11.2**

- [ ]* 13.3 Write property test for entry filtering
  - **Property 45: Entry Filtering**
  - **Validates: Requirements 11.3**

- [ ]* 13.4 Write property test for pricing logic
  - **Property 72: Long Entry Pricing**
  - **Property 73: Long Exit Pricing**
  - **Property 74: Short Entry Pricing**
  - **Property 75: Short Exit Pricing**
  - **Property 76: Profit/Loss Calculation Correctness**
  - **Validates: Requirements 18.1, 18.2, 18.3, 18.4, 18.5**

- [x] 14. Implement webhook notification system
  - Add webhook notification on trade entry with all required fields
  - Add webhook notification on trade exit with profit/loss
  - Implement multi-webhook support for multiple configured URLs
  - Add error handling (log error but continue operation)
  - _Requirements: 13.1, 13.2, 13.3, 13.4, 13.5_

- [ ]* 14.1 Write property test for webhook notifications
  - **Property 53: Entry Webhook Notification**
  - **Property 54: Exit Webhook Notification**
  - **Property 55: Webhook Payload Completeness**
  - **Property 56: Webhook Error Handling**
  - **Property 57: Multi-Webhook Notification**
  - **Validates: Requirements 13.1, 13.2, 13.3, 13.4, 13.5**

- [x] 15. Implement Tool Discovery Service
  - Create ToolDiscoveryService class
  - Implement tool discovery on startup
  - Add 5-minute refresh cycle
  - Use HTTP fallback for MCP server compatibility
  - Implement cached tool query interface
  - Add error handling with retry on next cycle
  - _Requirements: 15.1, 15.2, 15.3, 15.4, 15.5_

- [ ]* 15.1 Write property test for tool discovery
  - **Property 62: Tool Cache Refresh Interval**
  - **Property 63: HTTP Fallback for Tool Discovery**
  - **Property 64: Cached Tool Query**
  - **Property 65: Tool Discovery Error Retry**
  - **Validates: Requirements 15.2, 15.3, 15.4, 15.5**

- [x] 16. Implement Threshold Adjustment Service
  - Create ThresholdAdjustmentService class
  - Implement 5-minute cycle during market hours
  - Add inactive ticker query (last 5 minutes)
  - Implement rejection reason grouping
  - Add AWS Bedrock LLM integration for threshold suggestions
  - Implement in-memory threshold application to indicator classes
  - Add event storage in DayTraderEvents table
  - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.5_

- [ ]* 16.1 Write property test for threshold adjustment
  - **Property 36: Inactive Ticker Query Time Range**
  - **Property 37: Rejection Reason Grouping**
  - **Property 38: LLM Threshold Adjustment Call**
  - **Property 39: In-Memory Threshold Application**
  - **Property 40: Threshold Adjustment Event Completeness**
  - **Validates: Requirements 9.1, 9.2, 9.3, 9.4, 9.5**

- [x] 17. Implement Trading Service Coordinator
  - Create TradingServiceCoordinator class
  - Add initialization for all enabled indicators (Momentum, Penny Stocks, Deep Analyzer, UW-Enhanced)
  - Implement concurrent execution with error isolation (return_exceptions=True)
  - Add graceful shutdown handling
  - _Requirements: 1.1, 1.2, 1.3, 1.5_

- [ ]* 17.1 Write property test for error isolation
  - **Property 1: Error Isolation**
  - **Validates: Requirements 1.2**

- [x] 18. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 19. Implement main application entry point
  - Create main application (app.py) with service initialization
  - Add signal handlers for graceful shutdown (SIGINT, SIGTERM)
  - Implement concurrent service execution (Trading Service Coordinator, Tool Discovery, Threshold Adjustment)
  - Add resource cleanup on shutdown
  - _Requirements: 1.1, 1.3, 20.2, 20.5_

- [ ]* 19.1 Write property test for resource management
  - **Property 82: Resource Cleanup on Stop**
  - **Property 85: Graceful Shutdown Resource Release**
  - **Validates: Requirements 20.2, 20.5**

- [x] 20. Implement Heroku web process entry point
  - Create web.py for dual-process architecture
  - Implement concurrent execution of MCP server and trading application
  - Add HTTP request routing to MCP server on /mcp endpoint
  - Configure environment variable loading
  - _Requirements: 17.1, 17.2, 17.3_

- [ ]* 20.1 Write property test for configuration loading
  - **Property 71: Environment Variable Configuration**
  - **Validates: Requirements 17.3**

- [x] 21. Implement comprehensive logging
  - Add structured logging for all operations using Loguru
  - Implement signal logging with ticker, reason, and technical indicators
  - Add error logging with full stack trace
  - Implement DynamoDB operation logging with operation type, table name, and status
  - Add threshold adjustment logging with old/new values and LLM reasoning
  - _Requirements: 16.1, 16.2, 16.3, 16.4, 16.5_

- [ ]* 21.1 Write property test for logging
  - **Property 66: Structured Operation Logging**
  - **Property 67: Signal Logging Completeness**
  - **Property 68: Error Stack Trace Logging**
  - **Property 69: DynamoDB Operation Logging**
  - **Property 70: Threshold Adjustment Logging Completeness**
  - **Validates: Requirements 16.1, 16.2, 16.3, 16.4, 16.5**

- [x] 22. Implement LRU caching with size limits
  - Add LRU cache for market data with 500 entry limit
  - Add LRU cache for tool metadata with 500 entry limit
  - Implement cache invalidation logic
  - _Requirements: 20.3_

- [ ]* 22.1 Write property test for cache management
  - **Property 83: LRU Cache Size Limit**
  - **Validates: Requirements 20.3**

- [x] 23. Final Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

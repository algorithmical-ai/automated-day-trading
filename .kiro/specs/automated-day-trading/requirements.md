# Requirements Document

## Introduction

This document specifies the requirements for an automated day trading application that monitors market conditions and executes trades using multiple sophisticated trading strategies. The system employs real-time threshold adjustment, comprehensive risk management, and intelligent ticker selection through multi-armed bandit algorithms. The application integrates with external APIs (Alpaca, AWS DynamoDB, AWS Bedrock, Unusual Whales) and provides webhook notifications for trading signals.

## Glossary

- **Trading System**: The automated day trading application
- **Trading Indicator**: A specific trading strategy implementation (e.g., Momentum Trading, Penny Stocks)
- **MCP API**: Market Data Analyzer Model Context Protocol API for market data and analysis
- **MAB**: Multi-Armed Bandit algorithm for intelligent ticker selection using Thompson Sampling
- **ATR**: Average True Range, a volatility indicator
- **DynamoDB**: AWS NoSQL database service for storing trade data
- **Alpaca API**: Stock trading and market data API
- **AWS Bedrock**: AWS service providing access to foundation models (LLMs)
- **Ticker**: Stock symbol identifier
- **Active Trade**: A currently open position in the market
- **Completed Trade**: A closed position with recorded profit/loss
- **Inactive Ticker**: A ticker that was evaluated but not traded, with logged reasons
- **Golden Ticker**: A ticker with exceptional entry score (≥0.75) that can bypass daily trade limits
- **Entry Score**: Numerical score (0-1) indicating trade entry signal strength
- **Stop Loss**: Maximum acceptable loss threshold for a trade
- **Trailing Stop**: Dynamic stop loss that follows price movement to protect profits
- **Peak Profit**: Highest profit percentage achieved during a trade
- **Cooldown Period**: Time interval during which a ticker cannot be re-traded after exit
- **Market Clock**: Service that determines if the market is currently open for trading
- **Webhook**: HTTP callback for sending real-time trading notifications
- **Threshold Adjustment Service**: LLM-powered service that optimizes trading thresholds based on market conditions
- **RSI**: Relative Strength Index, momentum oscillator measuring speed and magnitude of price changes
- **ADX**: Average Directional Index, indicator measuring trend strength
- **Stochastic**: Momentum indicator comparing closing price to price range over time
- **Bollinger Bands**: Volatility bands placed above and below a moving average
- **Penny Stock**: Stock trading below $5 USD
- **Bid-Ask Spread**: Difference between highest bid price and lowest ask price
- **Position Sizing**: Calculation of dollar amount to invest in a trade
- **Signal Reversal**: When technical analysis indicates opposite direction from current position
- **Score Degradation**: Significant decrease in entry score during an active trade

## Requirements

### Requirement 1

**User Story:** As a trader, I want the system to execute multiple trading strategies concurrently, so that I can diversify my approach and compare strategy performance.

#### Acceptance Criteria

1. WHEN the Trading System starts, THEN the Trading System SHALL initialize and run the Momentum Trading Indicator, Penny Stocks Indicator, Deep Analyzer Indicator, and UW-Enhanced Momentum Indicator concurrently
2. WHEN one Trading Indicator encounters an error, THEN the Trading System SHALL continue operating the other Trading Indicators without interruption
3. WHEN the Trading System receives a shutdown signal (SIGINT or SIGTERM), THEN the Trading System SHALL gracefully stop all Trading Indicators and clean up resources
4. WHEN multiple Trading Indicators evaluate the same Ticker simultaneously, THEN the Trading System SHALL use thread-safe operations to prevent race conditions
5. WHERE a Trading Indicator is disabled, THEN the Trading System SHALL exclude that Trading Indicator from execution

### Requirement 2

**User Story:** As a trader, I want the Momentum Trading Indicator to identify and trade stocks with strong price momentum, so that I can capitalize on trending movements.

#### Acceptance Criteria

1. WHEN the Momentum Trading Indicator evaluates a Ticker every 5 seconds, THEN the Momentum Trading Indicator SHALL calculate momentum by comparing the average price of the early 30% of price data to the average price of the recent 30% of price data
2. WHEN a Ticker shows upward momentum greater than 1.5% and less than 15%, AND the Ticker meets all technical filters (ADX ≥20, RSI 45-70, stochastic confirmation, Bollinger Band position, volume >1.5x SMA, price >$0.10), THEN the Momentum Trading Indicator SHALL enter a long position
3. WHEN a Ticker shows downward momentum less than -1.5% and greater than -15%, AND the Ticker meets all technical filters (ADX ≥20, RSI ≥50, stochastic confirmation, Bollinger Band position, volume >1.5x SMA, price >$0.10), THEN the Momentum Trading Indicator SHALL enter a short position
4. WHEN the Momentum Trading Indicator selects Tickers for entry, THEN the Momentum Trading Indicator SHALL use the MAB algorithm to select top-k Tickers per direction based on historical performance
5. WHEN the Momentum Trading Indicator enters a trade, THEN the Momentum Trading Indicator SHALL set a dynamic stop loss at 2.0x ATR and position size at $2000

### Requirement 3

**User Story:** As a trader, I want the Penny Stocks Indicator to trade low-priced stocks with clear trends, so that I can profit from rapid price movements in volatile penny stocks.

#### Acceptance Criteria

1. WHEN the Penny Stocks Indicator evaluates a Ticker every 1 second, THEN the Penny Stocks Indicator SHALL analyze the recent 5 bars to determine if a clear upward or downward trend exists
2. WHEN a Ticker has price less than $5.00 and greater than $0.01, AND shows a clear upward trend with momentum ≥1.5% and <15%, AND has ≥50% trend continuation in recent bars, AND is not at a peak, THEN the Penny Stocks Indicator SHALL enter a long position
3. WHEN a Ticker has price less than $5.00 and greater than $0.01, AND shows a clear downward trend with momentum ≥1.5% and <15%, AND has ≥50% trend continuation in recent bars, AND is not at a bottom, THEN the Penny Stocks Indicator SHALL enter a short position
4. WHEN the Penny Stocks Indicator evaluates a Ticker for entry, THEN the Penny Stocks Indicator SHALL filter out Tickers with bid-ask spread >2%, volume <500 shares in recent bars, special securities (warrants, rights, units), and Tickers that lost money today
5. WHEN the Penny Stocks Indicator has an Active Trade with low profit, AND a new Ticker shows exceptional momentum ≥8%, THEN the Penny Stocks Indicator SHALL preempt the low-profit trade to enter the exceptional opportunity

### Requirement 4

**User Story:** As a trader, I want the Deep Analyzer Indicator to use advanced technical analysis for trade decisions, so that I can leverage sophisticated signal scoring and degradation detection.

#### Acceptance Criteria

1. WHEN the Deep Analyzer Indicator evaluates a Ticker every 5 seconds, THEN the Deep Analyzer Indicator SHALL call the MCP API enter_trade method to obtain an Entry Score for both long and short opportunities
2. WHEN a Ticker receives an Entry Score ≥0.60, AND the portfolio has fewer than 3 positions in the same direction, THEN the Deep Analyzer Indicator SHALL enter a trade and store the Entry Score
3. WHEN a Ticker receives an Entry Score ≥0.75 (Golden Ticker), THEN the Deep Analyzer Indicator SHALL bypass daily trade limits for that entry
4. WHEN the Deep Analyzer Indicator evaluates an Active Trade for exit, AND the MCP API returns a qualifying signal in the opposite direction, THEN the Deep Analyzer Indicator SHALL exit the trade
5. WHEN the Deep Analyzer Indicator evaluates an Active Trade for exit, AND the current Entry Score has dropped more than 50% from the stored entry Entry Score, THEN the Deep Analyzer Indicator SHALL exit the trade due to Score Degradation

### Requirement 5

**User Story:** As a trader, I want the UW-Enhanced Momentum Indicator to combine momentum analysis with options flow validation, so that I can make more informed entries with institutional sentiment confirmation.

#### Acceptance Criteria

1. WHEN the UW-Enhanced Momentum Indicator evaluates a Ticker every 5 seconds, THEN the UW-Enhanced Momentum Indicator SHALL calculate momentum using the same method as the Momentum Trading Indicator
2. WHEN a Ticker shows qualifying momentum, THEN the UW-Enhanced Momentum Indicator SHALL validate the signal against Unusual Whales options flow sentiment before entry
3. WHEN the UW-Enhanced Momentum Indicator calculates position size, THEN the UW-Enhanced Momentum Indicator SHALL adjust the size based on volatility and Penny Stock risk scoring
4. WHEN the current time is after 3:00 PM ET, THEN the UW-Enhanced Momentum Indicator SHALL not enter any new trades
5. WHEN the UW-Enhanced Momentum Indicator sets a trailing stop for a short position, THEN the UW-Enhanced Momentum Indicator SHALL apply a 1.5x multiplier to create a wider stop

### Requirement 6

**User Story:** As a trader, I want all Trading Indicators to implement comprehensive exit logic, so that I can protect profits and limit losses effectively.

#### Acceptance Criteria

1. WHEN an Active Trade reaches the hard Stop Loss threshold, THEN the Trading Indicator SHALL immediately exit the trade
2. WHEN an Active Trade reaches the profit threshold, THEN the Trading Indicator SHALL activate a Trailing Stop at 1.5x ATR
3. WHEN an Active Trade has an activated Trailing Stop, AND the price moves against the position beyond the Trailing Stop distance from Peak Profit, THEN the Trading Indicator SHALL exit the trade
4. WHEN the market time is within 15 minutes of market close, THEN the Trading Indicator SHALL force close all Active Trades
5. WHEN an Active Trade has been held for less than the minimum holding period, THEN the Trading Indicator SHALL not exit the trade unless the hard Stop Loss is hit

### Requirement 7

**User Story:** As a trader, I want the system to store all trade data in DynamoDB, so that I can track performance, analyze patterns, and maintain audit trails.

#### Acceptance Criteria

1. WHEN a Trading Indicator enters a trade, THEN the Trading System SHALL store the trade details in the ActiveTickersForAutomatedDayTrader table with Ticker as partition key
2. WHEN a Trading Indicator exits a trade, THEN the Trading System SHALL move the trade from ActiveTickersForAutomatedDayTrader to CompletedTradesForMarketData with date as partition key and ticker#indicator as sort key
3. WHEN a Trading Indicator evaluates a Ticker but does not enter, THEN the Trading System SHALL log the rejection reason in InactiveTickersForDayTrading with Ticker as partition key and timestamp as sort key
4. WHEN the Threshold Adjustment Service modifies thresholds, THEN the Trading System SHALL store the adjustment event in DayTraderEvents with date as partition key and indicator as sort key
5. WHEN the Trading System queries DynamoDB, AND the operation fails, THEN the Trading System SHALL log the error with full details and continue operating

### Requirement 8

**User Story:** As a trader, I want the MAB algorithm to intelligently select which tickers to trade, so that the system prioritizes historically successful opportunities.

#### Acceptance Criteria

1. WHEN a Trading Indicator needs to select Tickers for entry, THEN the Trading Indicator SHALL use Thompson Sampling to rank Tickers based on historical success rates
2. WHEN the MAB algorithm evaluates Tickers, THEN the MAB algorithm SHALL maintain separate statistics for each indicator#ticker combination in the MABStats table
3. WHEN a Completed Trade is recorded, THEN the Trading System SHALL update the MAB statistics for that indicator#ticker combination
4. WHEN the Penny Stocks Indicator records a losing trade for a Ticker, THEN the Penny Stocks Indicator SHALL exclude that Ticker from MAB selection for the remainder of the trading day
5. WHEN the MAB algorithm selects top-k Tickers, THEN the MAB algorithm SHALL return separate ranked lists for long and short directions

### Requirement 9

**User Story:** As a trader, I want the Threshold Adjustment Service to optimize trading parameters based on market conditions, so that the system adapts to changing market dynamics.

#### Acceptance Criteria

1. WHEN the Threshold Adjustment Service runs every 5 minutes during market hours, THEN the Threshold Adjustment Service SHALL query Inactive Tickers from the last 5 minutes
2. WHEN the Threshold Adjustment Service has collected Inactive Ticker data, THEN the Threshold Adjustment Service SHALL group the data by rejection reason
3. WHEN the Threshold Adjustment Service analyzes rejection patterns, THEN the Threshold Adjustment Service SHALL call AWS Bedrock LLM with current thresholds and rejection patterns to obtain suggested adjustments
4. WHEN the Threshold Adjustment Service receives threshold suggestions from the LLM, THEN the Threshold Adjustment Service SHALL apply the changes to the Trading Indicator classes in memory
5. WHEN the Threshold Adjustment Service completes an adjustment cycle, THEN the Threshold Adjustment Service SHALL store the threshold changes, max trades recommendations, and full LLM response in the DayTraderEvents table

### Requirement 10

**User Story:** As a trader, I want the system to integrate with the MCP API for market data and analysis, so that I can access real-time quotes, technical indicators, and trade signals.

#### Acceptance Criteria

1. WHEN the Trading System needs market data for a Ticker, THEN the Trading System SHALL call the MCP API get_market_data tool with the Ticker symbol
2. WHEN the Trading System needs to check if the market is open, THEN the Trading System SHALL call the MCP API get_market_clock tool
3. WHEN the Trading System needs screened Tickers, THEN the Trading System SHALL call the MCP API get_alpaca_screened_tickers tool to retrieve gainers, losers, and most active Tickers
4. WHEN the Trading System calls the MCP API, THEN the Trading System SHALL use HTTP POST requests with Bearer token authentication via the Authorization header
5. WHEN the MCP API call fails, THEN the Trading System SHALL log the error with full details and retry with exponential backoff

### Requirement 11

**User Story:** As a trader, I want the system to implement comprehensive risk management, so that I can limit losses and protect capital.

#### Acceptance Criteria

1. WHEN a Trading Indicator calculates a dynamic Stop Loss, THEN the Trading Indicator SHALL use 2.0x ATR and cap the Stop Loss between -4% and -8% based on stock price category
2. WHEN a Trading Indicator calculates position size, THEN the Trading Indicator SHALL start with $2000 base and reduce for high-volatility stocks and high-risk Penny Stocks, with a minimum of $500
3. WHEN a Trading Indicator evaluates a Ticker for entry, THEN the Trading Indicator SHALL filter out Tickers with momentum <1.5% or >15%, ADX <20, volume ≤1.5x SMA, and price <$0.10
4. WHEN a Trading Indicator counts Active Trades, THEN the Trading Indicator SHALL enforce max_active_trades limit (5 for most indicators, 10 for Penny Stocks)
5. WHEN a Trading Indicator counts daily trades, THEN the Trading Indicator SHALL enforce max_daily_trades limit (5 for most indicators, 30 for Penny Stocks) unless the Ticker is a Golden Ticker

### Requirement 12

**User Story:** As a trader, I want the system to manage ticker cooldown periods, so that I avoid overtrading the same stocks.

#### Acceptance Criteria

1. WHEN a Trading Indicator exits a trade for a Ticker, THEN the Trading Indicator SHALL record the exit timestamp for that Ticker
2. WHEN a Trading Indicator evaluates a Ticker for entry, AND the Ticker was traded within the last 60 minutes, THEN the Trading Indicator SHALL skip that Ticker due to Cooldown Period
3. WHEN a Trading Indicator checks Cooldown Period, THEN the Trading Indicator SHALL use thread-safe operations to prevent race conditions
4. WHEN a Trading Indicator evaluates a Golden Ticker, THEN the Trading Indicator SHALL bypass the Cooldown Period restriction
5. WHEN the trading day ends, THEN the Trading System SHALL clear all Cooldown Period records for the next trading day

### Requirement 13

**User Story:** As a trader, I want the system to send webhook notifications for trading signals, so that I can integrate with external monitoring and alerting systems.

#### Acceptance Criteria

1. WHEN a Trading Indicator enters a trade, THEN the Trading System SHALL call the MCP API send_webhook_signal tool with trade entry details
2. WHEN a Trading Indicator exits a trade, THEN the Trading System SHALL call the MCP API send_webhook_signal tool with trade exit details and profit/loss
3. WHEN the Trading System sends a webhook signal, THEN the Trading System SHALL include Ticker, action, price, reason, technical indicators, and indicator name
4. WHEN the webhook call fails, THEN the Trading System SHALL log the error but continue normal operation
5. WHERE multiple webhook URLs are configured, THEN the Trading System SHALL send notifications to all configured webhook endpoints

### Requirement 14

**User Story:** As a trader, I want the system to handle market hours correctly, so that trading only occurs when the market is open.

#### Acceptance Criteria

1. WHEN any Trading Indicator performs an operation, THEN the Trading Indicator SHALL first check the Market Clock to verify the market is open
2. WHEN the Market Clock indicates the market is closed, THEN the Trading Indicator SHALL skip the operation and wait for the next cycle
3. WHEN the Trading System stores timestamps, THEN the Trading System SHALL use UTC format internally
4. WHEN the Trading System performs market-hour logic (e.g., end-of-day closure), THEN the Trading System SHALL convert to EST timezone for comparison
5. WHERE the DEBUG_DAY_TRADING environment variable is set to "true", THEN the Market Clock SHALL always return open status for testing purposes

### Requirement 15

**User Story:** As a trader, I want the Tool Discovery Service to cache available MCP tools, so that the system can efficiently look up tool metadata without repeated API calls.

#### Acceptance Criteria

1. WHEN the Tool Discovery Service starts, THEN the Tool Discovery Service SHALL immediately discover available MCP tools from the Market Data Analyzer API
2. WHEN the Tool Discovery Service runs, THEN the Tool Discovery Service SHALL refresh the tool cache every 5 minutes
3. WHEN the Tool Discovery Service discovers tools, THEN the Tool Discovery Service SHALL use HTTP fallback for compatibility with the MCP server
4. WHEN a Trading Indicator needs tool metadata, THEN the Trading Indicator SHALL query the cached tool list from the Tool Discovery Service
5. WHEN the Tool Discovery Service encounters an error, THEN the Tool Discovery Service SHALL log the error and retry on the next cycle

### Requirement 16

**User Story:** As a trader, I want the system to log all operations comprehensively, so that I can debug issues and monitor system behavior.

#### Acceptance Criteria

1. WHEN the Trading System performs any operation, THEN the Trading System SHALL log the operation with structured data using Loguru
2. WHEN a Trading Indicator generates an entry or exit signal, THEN the Trading Indicator SHALL log the signal with Ticker, reason, and technical indicators
3. WHEN the Trading System encounters an error, THEN the Trading System SHALL log the error with full stack trace
4. WHEN the Trading System performs a DynamoDB operation, THEN the Trading System SHALL log the operation type, table name, and success/failure status
5. WHEN the Threshold Adjustment Service modifies thresholds, THEN the Threshold Adjustment Service SHALL log the old values, new values, and LLM reasoning

### Requirement 17

**User Story:** As a system administrator, I want the application to deploy to Heroku with a dual-process architecture, so that I can run both the MCP server and trading application efficiently.

#### Acceptance Criteria

1. WHEN the Heroku web process starts, THEN the web process SHALL run both the MCP server and the trading application concurrently
2. WHEN the Heroku web process receives HTTP requests on the /mcp endpoint, THEN the web process SHALL route requests to the MCP server
3. WHEN environment variables are configured as Heroku config vars, THEN the Trading System SHALL read and use those values for configuration
4. WHEN the web process is scaled to 1 dyno, THEN both the MCP server and trading application SHALL be running
5. WHERE a worker process is configured, THEN the worker process SHALL run only the trading application without the MCP server

### Requirement 18

**User Story:** As a trader, I want the system to handle pricing correctly for long and short positions, so that profit/loss calculations are accurate.

#### Acceptance Criteria

1. WHEN a Trading Indicator enters a long position, THEN the Trading Indicator SHALL use the ask price as the entry price
2. WHEN a Trading Indicator exits a long position, THEN the Trading Indicator SHALL use the bid price as the exit price
3. WHEN a Trading Indicator enters a short position, THEN the Trading Indicator SHALL use the bid price as the entry price
4. WHEN a Trading Indicator exits a short position, THEN the Trading Indicator SHALL use the ask price as the exit price
5. WHEN a Trading Indicator calculates profit or loss, THEN the Trading Indicator SHALL use the correct entry and exit prices based on position direction

### Requirement 19

**User Story:** As a trader, I want the system to use centralized configuration for trading parameters, so that consistency is maintained across all indicators.

#### Acceptance Criteria

1. WHEN any Trading Indicator calculates a Stop Loss, THEN the Trading Indicator SHALL use the standardized 2.0x ATR multiplier from trading_config.py
2. WHEN any Trading Indicator calculates a Trailing Stop, THEN the Trading Indicator SHALL use the standardized 1.5x ATR multiplier from trading_config.py
3. WHEN any Trading Indicator applies Stop Loss bounds, THEN the Trading Indicator SHALL use the standardized bounds from trading_config.py (-8% to -4% for Penny Stocks, -6% to -4% for standard stocks)
4. WHEN any Trading Indicator applies Trailing Stop bounds, THEN the Trading Indicator SHALL use the standardized base of 2.0% and short multiplier of 1.5x from trading_config.py
5. WHEN a developer modifies trading parameters, THEN the developer SHALL update trading_config.py to ensure all Trading Indicators use the new values

### Requirement 20

**User Story:** As a trader, I want the system to manage resources efficiently, so that it can run continuously without memory leaks or connection issues.

#### Acceptance Criteria

1. WHEN the Trading System makes HTTP requests to the MCP API, THEN the Trading System SHALL use shared HTTP sessions across all requests
2. WHEN a Trading Indicator stops, THEN the Trading Indicator SHALL close all HTTP sessions and clean up resources
3. WHEN the Trading System uses LRU caching, THEN the Trading System SHALL limit cache size to 500 entries to prevent unbounded memory growth
4. WHEN multiple Trading Indicators access shared resources, THEN the Trading System SHALL use async locks to ensure thread safety
5. WHEN the Trading System shuts down, THEN the Trading System SHALL gracefully close all connections and release all resources

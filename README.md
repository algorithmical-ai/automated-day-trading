# Automated Day Trading Application

An automated day trading application that monitors market conditions and executes trades using multiple sophisticated trading strategies with real-time threshold adjustment and comprehensive risk management.

## Features

### Multi-Strategy Trading System

- **Momentum Trading Indicator**: Price momentum analysis with technical filters (RSI, ADX, stochastic, Bollinger Bands)
- **Penny Stocks Indicator**: Trend-following strategy for stocks < $5 USD with aggressive entry/exit cycles (1 second) and quick profit-taking
- **Deep Analyzer Indicator**: Advanced technical analysis via MarketDataService with signal scoring and degradation detection (currently disabled)
- **UW-Enhanced Momentum Indicator**: Momentum trading enhanced with Unusual Whales options flow validation and volatility-aware risk management (currently disabled)

### Advanced Features

- **Dynamic Threshold Adjustment**: LLM-powered analysis of inactive tickers to optimize trading thresholds in real-time
- **Multi-Armed Bandit (MAB)**: Contextual bandit algorithm for intelligent ticker selection with Thompson Sampling
- **Market-Aware Execution**: Comprehensive market clock monitoring and time-based trade management
- **Risk Management**:
  - ATR-based dynamic stop losses and trailing stops
  - Volatility-adjusted position sizing
  - Portfolio correlation checks
  - Entry/exit cooldown periods
- **Comprehensive Filtering**: Price, volume, ADX, RSI, stochastic, Bollinger Bands, mean reversion detection
- **DynamoDB Integration**: Multi-table architecture for active trades, completed trades, inactive tickers, and events
- **Webhook Integration**: Real-time trading signals to external systems
- **Tool Discovery Service**: Background service for discovering and caching available MCP tools

## Architecture

The application consists of multiple async services running concurrently:

### Core Services

#### 1. Trading Service Coordinator (`trading_service.py`)

Orchestrates multiple trading indicators running in parallel:

- **Momentum Trading Indicator**: Price momentum-based strategy (active)
- **Penny Stocks Indicator**: Trend-following strategy for stocks < $5 USD (active)
- **Deep Analyzer Indicator**: MarketDataService-based deep technical analysis (currently disabled)
- **UW-Enhanced Momentum Indicator**: Momentum + Unusual Whales validation (currently disabled)

Each indicator runs independent entry and exit services with graceful error handling.

#### 2. Tool Discovery Service (`tool_discovery.py`)

- Runs in the background, refreshing every 5 minutes
- Discovers available MCP tools from the Market Data Analyzer API
- Uses HTTP fallback for compatibility
- Caches tool metadata for efficient lookups

#### 3. Screener Monitor Service (`screener_monitor_service.py`)

- Monitors Alpaca screener for trading candidates
- Provides ticker screening for all indicators

#### 4. Threshold Adjustment Service (`threshold_adjustment_service.py`)

- Runs every 5 minutes during market hours
- Analyzes inactive ticker reasons using AWS Bedrock LLM
- Dynamically adjusts trading thresholds based on market conditions
- Stores adjustment events in `DayTraderEvents` DynamoDB table
- Supports Momentum Trading and Deep Analyzer indicators (when enabled)

## Trading Indicators

### 1. Momentum Trading Indicator (`momentum_indicator.py`)

**Entry Logic** (runs every 5 seconds):

- Analyzes `datetime_price` array from market data
- Calculates momentum: compares early 30% vs recent 30% of price data
- Technical filters:
  - ADX ≥ 20 (trend strength)
  - RSI 45-70 for longs, ≥50 for shorts
  - Stochastic confirmation
  - Bollinger Band position
  - Volume > 1.5x SMA
  - Price > $0.10
- Upward momentum (>1.5% change) → Long position
- Downward momentum (<-1.5% change) → Short position
- Uses MAB for ticker selection (top-k per direction)
- Dynamic stop loss: 2.0x ATR (standardized)
- Position size: $2000 fixed

**Exit Logic** (runs every 5 seconds):

- Hard stop loss: dynamic (2.0x ATR, capped at -4%)
- Trailing stop: 1.5x ATR after activation threshold
- Profit target: 2x stop distance
- Tiered trailing stop activation based on peak profit
- End-of-day forced closure (15 minutes before close)
- Minimum holding period: 60 seconds

**Configuration**:

- `max_active_trades`: 5
- `max_daily_trades`: 5
- `min_momentum_threshold`: 1.5%
- `max_momentum_threshold`: 15%
- `ticker_cooldown_minutes`: 60

### 2. Penny Stocks Indicator (`penny_stocks_indicator.py`)

**Entry Logic** (runs every 1 second - FAST MODE):

- Trend-following strategy for stocks < $5 USD
- Analyzes recent 5 bars to determine clear upward/downward trends
- Entry conditions:
  - Long: Clear upward trend with momentum ≥1.5% and <15%
  - Short: Clear downward trend with momentum ≥1.5% and <15%
  - Trend continuation check: Requires ≥50% continuation in recent bars
  - Avoids entry at peaks (long) or bottoms (short)
- Filters:
  - Price range: $0.01 to $5.00
  - Bid-ask spread: max 2%
  - Volume: minimum 500 shares in recent bars
  - Excludes special securities (warrants, rights, units)
  - Excludes losing tickers from today
- MAB selection: top-2 tickers per direction
- Preemption: Can preempt low-profit trades for exceptional momentum (≥8%)
- Position size: $2000 fixed

**Exit Logic** (runs every 1 second - FAST MODE):

- Priority 1: Immediate exit if trade becomes unprofitable (cuts losses fast)
- Priority 2: Trend reversal detection:
  - Long: Exit on dip from peak (trend reverses downward)
  - Short: Exit on rise from bottom (trend reverses upward)
- Priority 3: Significant loss exit: -0.25% threshold
- Profit target: 0.5% (quick cash in)
- Trailing stop: 0.5% (tight, exits quickly)
- Minimum holding period: 15 seconds
- Losing tickers excluded from MAB for rest of day

**Configuration**:

- `max_stock_price`: $5.00
- `min_stock_price`: $0.01
- `trailing_stop_percent`: 0.5%
- `profit_threshold`: 0.5%
- `immediate_loss_exit_threshold`: -0.25%
- `min_momentum_threshold`: 1.5%
- `max_momentum_threshold`: 15.0%
- `exceptional_momentum_threshold`: 8.0%
- `max_active_trades`: 10
- `max_daily_trades`: 30
- `entry_cycle_seconds`: 1
- `exit_cycle_seconds`: 1
- `min_holding_period_seconds`: 15
- `recent_bars_for_trend`: 5

### 3. Deep Analyzer Indicator (`deep_analyzer_indicator.py`) - Currently Disabled

**Entry Logic** (runs every 5 seconds):

- Uses `MarketDataService.enter_trade()` for deep technical analysis
- Evaluates both long and short opportunities
- Entry score threshold: 0.60 (dynamic, adjusts based on market conditions)
- Golden ticker detection: exceptional scores (≥0.75) bypass daily limits
- Portfolio correlation check: max 3 positions in same direction
- MAB selection: top-k tickers per direction
- Stores entry_score for degradation checks on exit

**Exit Logic** (runs every 5 seconds):

- Signal reversal detection: exits if opposite signal qualifies
- Entry score degradation: exits if score drops >50% from entry
- Uses `MarketDataService.exit_trade()` for exit signals
- Fallback to comprehensive technical analysis

**Configuration**:

- `min_entry_score`: 0.60
- `exceptional_entry_score`: 0.75
- `top_k`: 2

### 4. UW-Enhanced Momentum Indicator (`uw_enhanced_momentum_indicator.py`) - Currently Disabled

**Entry Logic** (runs every 5 seconds):

- Combines momentum analysis with Unusual Whales options flow validation
- Same momentum calculation as Momentum Indicator
- Additional filters:
  - Unusual Whales sentiment alignment check
  - Penny stock risk scoring
  - Volatility and mean reversion filters
  - Bid-ask spread validation
- Entry cutoff: 3:00 PM ET (no new entries after this time)
- Risk-adjusted position sizing based on volatility and penny stock risk

**Exit Logic** (runs every 5 seconds):

- Dynamic stop loss: 2.0x ATR
- Trailing stop: 1.5x ATR (wider for shorts: 1.5x multiplier)
- Protects against losses from peak profit (even if current profit is negative)
- Profit target: 2x stop distance

**Configuration**:

- Uses Unusual Whales API for options flow validation
- Volatility-aware position sizing
- Enhanced risk management for penny stocks

## Base Trading Indicator Infrastructure (`base_trading_indicator.py`)

All indicators inherit from `BaseTradingIndicator`, providing:

### Shared Features

- **Market Clock Monitoring**: All operations check market status
- **Ticker Screening**: Integrated Alpaca screener access
- **Cooldown Management**: Per-ticker cooldown periods (60 minutes default)
- **Daily Trade Limits**: Configurable limits with golden ticker bypass
- **Thread-Safe Operations**: Async locks for concurrent operations
- **Timezone Handling**: UTC internally, EST for market-hour logic only
- **MAB Integration**: Multi-armed bandit for intelligent ticker selection
- **DynamoDB Operations**: Standardized trade entry/exit handling

### Common Configuration

- `max_active_trades`: 5 (configurable per indicator)
- `max_daily_trades`: 5 (configurable per indicator)
- `ticker_cooldown_minutes`: 60
- `entry_cycle_seconds`: 5
- `exit_cycle_seconds`: 5
- `position_size_dollars`: $2000

## Centralized Configuration (`trading_config.py`)

Standardized constants for consistency across all indicators:

- **ATR Multipliers**:

  - Stop Loss: 2.0x ATR
  - Trailing Stop: 1.5x ATR
  - Legacy Volatility Utils: 2.5x ATR (trailing), 3.0x ATR (stop loss)

- **Stop Loss Bounds**:

  - Penny stocks: -8.0% to -4.0%
  - Standard stocks: -6.0% to -4.0%

- **Trailing Stop Bounds**:
  - Base: 2.0%
  - Short multiplier: 1.5x
  - Max for shorts: 4.0%

## DynamoDB Tables

### Active Trades Tables

#### 1. ActiveTickersForAutomatedDayTrader

**Partition Key**: `ticker` (String)

Stores active trades for all trading indicators:

- `ticker` (String): Stock symbol
- `action` (String): "buy_to_open" or "sell_to_open"
- `indicator` (String): Indicator name ("Momentum Trading", "Penny Stocks", "Deep Analyzer", "UW-Enhanced Momentum Trading")
- `enter_price` (Number): Entry price
- `enter_reason` (String): Reason for entry
- `technical_indicators_for_enter` (Map): Technical indicators at entry
- `dynamic_stop_loss` (Number): ATR-based stop loss percentage
- `trailing_stop` (Number): Current trailing stop percentage
- `peak_profit_percent` (Number): Highest profit achieved
- `entry_score` (Number): Entry score (for Deep Analyzer)
- `created_at` (String): ISO timestamp

### Completed Trades Table

#### 2. CompletedTradesForMarketData

**Partition Key**: `date` (String, format: yyyy-mm-dd)
**Sort Key**: `ticker#indicator` (String)

Stores completed trades:

- `date` (String): Trading date
- `ticker#indicator` (String): Composite key
- `ticker` (String): Stock symbol
- `indicator` (String): Indicator name
- `action` (String): Trade action
- `enter_price`, `exit_price` (Number): Prices
- `enter_timestamp`, `exit_timestamp` (String): ISO timestamps
- `profit_or_loss` (Number): Profit/loss in dollars
- `enter_reason`, `exit_reason` (String): Reasons
- `technical_indicators_for_enter`, `technical_indicators_for_exit` (Map)

### Inactive Tickers Tables

#### 3. InactiveTickersForDayTrading

**Partition Key**: `ticker` (String)
**Sort Key**: `timestamp` (String)

Logs reasons why tickers were not traded:

- `ticker` (String): Stock symbol
- `indicator` (String): Indicator name
- `timestamp` (String): ISO timestamp
- `reason_not_to_enter_long` (String): Reason for long
- `reason_not_to_enter_short` (String): Reason for short
- `technical_indicators` (Map): Technical indicators at time of evaluation

### Events Table

#### 4. DayTraderEvents

**Partition Key**: `date` (String, format: yyyy-mm-dd)
**Sort Key**: `indicator` (String)

Stores threshold adjustment events:

- `date` (String): Trading date
- `indicator` (String): Indicator name
- `last_updated` (String): ISO timestamp (EST)
- `threshold_change` (Map): Dictionary of threshold adjustments
- `max_long_trades` (Number): Maximum long trades recommended
- `max_short_trades` (Number): Maximum short trades recommended
- `llm_response` (String): Full LLM analysis response

### Other Tables

#### 5. TickerBlackList

**Partition Key**: `ticker` (String)

- Excludes tickers from all trading operations

#### 6. MABStats

**Partition Key**: `indicator#ticker` (String)

- Stores multi-armed bandit statistics for ticker selection

## Setup

### Prerequisites

- Python 3.9+
- AWS credentials configured (for DynamoDB access)
- AWS Bedrock access (for threshold adjustment service)
- Unusual Whales API token (optional, for UW-Enhanced indicator)

### Required DynamoDB Tables

1. `ActiveTickersForAutomatedDayTrader` - Active trades (partition key: `ticker`)
2. `CompletedTradesForMarketData` - Completed trades (partition key: `date`, sort key: `ticker#indicator`)
3. `InactiveTickersForDayTrading` - Inactive ticker logs (partition key: `ticker`, sort key: `timestamp`)
4. `DayTraderEvents` - Threshold adjustment events (partition key: `date`, sort key: `indicator`)
5. `TickerBlackList` - Blacklisted tickers (partition key: `ticker`)
6. `MABStats` - Multi-armed bandit statistics (partition key: `indicator#ticker`)

### Installation

1. Install dependencies:

```bash
pip install -r requirements.txt
```

2. Configure environment variables (see Environment Variables section)

3. Run the application:

```bash
PYTHONPATH=app/src python app/src/app.py
```

## Deployment to Heroku

The application uses a dual-process architecture on Heroku:

- **Web Process**: Runs MCP server and trading application (`web.py`)
- **Worker Process**: Runs trading application only (`app.py`) - optional, typically not needed

1. Create a Heroku app:

```bash
heroku create your-app-name
```

2. Set environment variables as config vars:

```bash
heroku config:set MARKET_DATA_MCP_URL=https://market-data-analyzer-d1d18da61b50.herokuapp.com/mcp
heroku config:set MCP_AUTH_HEADER_NAME=Authorization
heroku config:set MARKET_DATA_MCP_TOKEN=your_mcp_token
heroku config:set AWS_ACCESS_KEY_ID=your_key
heroku config:set AWS_SECRET_ACCESS_KEY=your_secret
heroku config:set AWS_DEFAULT_REGION=us-east-1
heroku config:set UW_API_TOKEN=your_uw_token  # Optional, for UW-Enhanced indicator (when enabled)
heroku config:set REAL_TRADE_API_KEY=your_alpaca_key  # For Alpaca API
heroku config:set REAL_TRADE_SECRET_KEY=your_alpaca_secret
```

3. Deploy:

```bash
git push heroku main
```

4. Scale the web process (runs both MCP server and trading app):

```bash
heroku ps:scale web=1
```

The web process (`web.py`) automatically starts both the MCP server and trading application concurrently. The MCP server is available at `https://your-app-name.herokuapp.com/mcp`.

## Environment Variables

### Required

- `MARKET_DATA_MCP_URL`: MCP API base URL (default: https://market-data-analyzer-d1d18da61b50.herokuapp.com/mcp)
- `MCP_AUTH_HEADER_NAME`: Authorization header name (default: Authorization)
- `MARKET_DATA_MCP_TOKEN`: MCP API authentication token
- `AWS_ACCESS_KEY_ID`: AWS access key for DynamoDB
- `AWS_SECRET_ACCESS_KEY`: AWS secret key for DynamoDB
- `AWS_DEFAULT_REGION`: AWS region (default: us-east-1)

### Optional

- `UW_API_TOKEN`: Unusual Whales API token (required for UW-Enhanced indicator)
- `REAL_TRADE_API_KEY`: Alpaca API key (for fallback ATR calculations)
- `REAL_TRADE_SECRET_KEY`: Alpaca API secret key
- `WEBHOOK_URL`: Comma-separated list of webhook URLs for trade notifications
- `DEBUG_DAY_TRADING`: Set to "true" to force market clock to always return open (for testing)

## MCP API Integration

The application connects to the Market Data Analyzer MCP API:

- **Base URL**: `https://market-data-analyzer-d1d18da61b50.herokuapp.com/mcp`
- **Protocol**: Uses HTTP POST requests (MCP protocol discovery disabled due to server compatibility)
- **Authentication**: Bearer token via `Authorization` header

### Available MCP Tools

- `get_market_clock`: Check if market is open
- `get_alpaca_screened_tickers`: Get gainers, losers, and most active tickers
- `get_quote`: Get current bid/ask prices for a ticker
- `get_market_data`: Get market data including technical analysis and price history
- `enter`: Determine if entry conditions are met (used by Deep Analyzer when enabled)
- `exit`: Determine if exit conditions are met (used by Deep Analyzer when enabled)
- `send_webhook_signal`: Send trading signals to external webhook endpoints

## Risk Management

### Stop Loss System

- **Dynamic Stop Loss**: Based on 2.0x ATR (standardized across all indicators)
- **Bounds**: Capped between -4% and -8% depending on stock price category
- **Hard Stop**: Always applies, cannot be bypassed

### Trailing Stop System

- **Activation**: After reaching profit threshold (varies by indicator)
- **Multiplier**: 1.5x ATR (standardized)
- **Base Minimum**: 2.0% minimum trailing distance
- **Short Adjustment**: 1.5x multiplier for shorts (wider stops)
- **Protection**: Protects against losses from peak profit even if current profit becomes negative

### Position Sizing

- **Base**: $2000 fixed position size
- **Volatility Adjustment**: Reduced size for high-volatility stocks
- **Penny Stock Risk**: Additional reduction for high-risk penny stocks
- **Minimum**: Never less than $500

### Entry Filters

- **Momentum**: Minimum 1.5% momentum, maximum 15%
- **Technical Indicators**: ADX ≥20, RSI ranges, stochastic confirmation
- **Volume**: Must be >1.5x SMA
- **Price**: Minimum $0.10
- **Volatility**: ATR-based filters prevent extreme volatility entries

### Exit Conditions

- **Profit Target**: 2x stop distance (e.g., 4% if stop is 2%)
- **Stop Loss**: Hard stop at dynamic threshold
- **Trailing Stop**: Activates after profit threshold, protects peak gains
- **Signal Reversal**: Deep Analyzer exits on opposite signal
- **Score Degradation**: Deep Analyzer exits if entry score drops >50%
- **Time-Based**: End-of-day forced closure (15 minutes before close)

## Threshold Adjustment Service

The Threshold Adjustment Service uses AWS Bedrock LLM to analyze why tickers are not entering trades and suggests threshold optimizations:

### Process

1. Every 5 minutes during market hours, analyzes inactive tickers from last 5 minutes
2. Groups tickers by rejection reason
3. Calls AWS Bedrock LLM with current thresholds and rejection patterns
4. LLM suggests threshold adjustments and optimal max trades
5. Applies changes to indicator classes (in-memory)
6. Stores event in `DayTraderEvents` table for audit trail

### Supported Adjustments

- Momentum thresholds (min/max)
- ADX threshold
- RSI ranges
- Volume requirements
- Stop loss and trailing stop percentages
- Entry score thresholds (Deep Analyzer)
- Max daily trades (long and short separately)

### Table Schema

- **Partition Key**: `date` (String, yyyy-mm-dd)
- **Sort Key**: `indicator` (String)
- Stores threshold changes, max trades, and full LLM response

## Logging

The application uses Loguru for structured logging:

- **Service initialization and startup**
- **Market status checks**
- **Entry/exit signals for all indicators**
- **Webhook notifications**
- **DynamoDB operations** (add, get, delete, update)
- **Threshold adjustments** (with success/failure status)
- **Error handling** with full stack traces
- **Performance metrics** (latency measurements)

## Error Handling

Comprehensive error handling throughout:

- **Network errors**: Retry logic for MCP API calls
- **DynamoDB failures**: Graceful degradation with detailed error logging
- **Invalid data**: Skips invalid trades with logging
- **Market status**: Handles closed market scenarios
- **Graceful shutdown**: SIGINT/SIGTERM signal handling
- **Service isolation**: One service failure doesn't stop others (uses `return_exceptions=True`)
- **HTTP session cleanup**: Proper resource management
- **Thread safety**: Async locks for concurrent operations

## Key Design Decisions

1. **Multi-Strategy Architecture**: Multiple independent indicators allow diversification and strategy comparison
2. **Base Class Pattern**: Shared infrastructure reduces code duplication
3. **Centralized Configuration**: `trading_config.py` ensures consistency across indicators
4. **Thread-Safe Operations**: Async locks prevent race conditions
5. **Timezone Standardization**: UTC internally, EST only for market-hour logic
6. **MAB Integration**: Intelligent ticker selection based on historical performance
7. **Dynamic Threshold Adjustment**: LLM-powered optimization adapts to market conditions
8. **Comprehensive Filtering**: Multi-layer filters reduce false signals
9. **Resource Management**: Shared HTTP sessions and proper cleanup
10. **Observability**: Detailed logging and event tracking
11. **Dual-Process Architecture**: Web process runs both MCP server and trading app on Heroku
12. **Fast-Cycle Trading**: Penny Stocks indicator uses 1-second cycles for rapid entry/exit

## Recent Improvements (Nov 2024)

### Critical Bug Fixes

- Fixed duplicate code blocks
- Fixed inverted RSI filter logic for shorts
- Fixed short exit pricing (now uses ask price, not bid)
- Added missing success tracking for long trades
- Fixed trailing stop to protect against losses from peak

### High Priority Improvements

- Added thread-safe daily trade counting with async locks
- Fixed class-level mutable state using ClassVar
- Standardized timezone usage (UTC internally)
- Added entry_score storage for degradation checks
- Added graceful shutdown handling with error monitoring

### Standardization

- Created centralized `trading_config.py` for ATR multipliers
- Standardized all indicators to use same ATR multipliers
- Improved error logging with detailed diagnostics

### Resource Management

- Optimized HTTP session usage (shared sessions)
- Added session cleanup in stop() methods
- Added LRU cache size limits (500 entries)

## Notes

- The application runs continuously until stopped (SIGINT/SIGTERM)
- All services run concurrently using `asyncio.gather()`
- Entry/exit cycle times vary by indicator:
  - Momentum Trading: 5 seconds
  - Penny Stocks: 1 second (fast mode)
  - Deep Analyzer: 5 seconds (when enabled)
  - UW-Enhanced Momentum: 5 seconds (when enabled)
- Threshold adjustment runs every 5 minutes during market hours
- Market checks occur before all trading operations
- All timestamps stored in UTC internally
- Golden tickers (exceptional opportunities) can bypass daily trade limits
- Penny Stocks indicator excludes losing tickers from MAB selection for the rest of the day
- On Heroku, the web process runs both MCP server and trading application concurrently

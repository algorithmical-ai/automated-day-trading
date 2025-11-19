# Automated Day Trading Application

An automated day trading application that monitors market conditions and executes trades using multiple strategies: technical indicator-based trading and momentum-based trading.

## Features

- **Dual Trading Strategies**:
  - **Standard Trading**: Uses MCP tools (`enter()` and `exit()`) to make trading decisions based on technical analysis
  - **Momentum Trading**: Analyzes price momentum patterns and exits when profit targets are reached
- **Market Clock Monitoring**: Checks if the market is open before executing trades
- **Ticker Screening**: Automatically identifies trading opportunities from gainers, losers, and most active stocks
- **Blacklist Support**: Filters out blacklisted tickers from trading operations
- **DynamoDB Integration**: Stores active trades in separate tables for each strategy
- **Webhook Integration**: Sends trading signals to external systems
- **Tool Discovery Service**: Background service for discovering and caching available MCP tools (currently uses HTTP fallback)

## Architecture

The application consists of three main async services running concurrently:

### 1. Tool Discovery Service

- Runs in the background, refreshing every 5 minutes (default)
- Discovers available MCP tools from the Market Data Analyzer API
- Currently uses HTTP fallback since MCP protocol has compatibility issues
- Caches tool metadata for efficient lookups

### 2. Trading Service (Standard Strategy)

- **Entry Service** (runs every 10 seconds):

  - Checks market status via `get_market_clock()`
  - Gets screened tickers (gainers, losers, most active) via `get_alpaca_screened_tickers()`
  - Filters out blacklisted tickers
  - For gainers/most_actives: Calls `enter()` MCP tool with `buy_to_open` action
  - For losers/most_actives: Calls `enter()` MCP tool with `sell_to_open` action
  - Gets current quote prices (ask for buys, bid for sells)
  - Sends webhook signals and stores entries in `ActiveTradesForAutomatedWorkflow` table when entry conditions are met

- **Exit Service** (runs every 5 seconds):
  - Monitors active trades in `ActiveTradesForAutomatedWorkflow` table
  - Skips blacklisted tickers
  - Calls `exit()` MCP tool for each active trade with appropriate exit action
  - Sends webhook signals and removes from DynamoDB when exit conditions are met

### 3. Momentum Trading Service

- **Entry Service** (runs every 10 seconds):

  - Checks market status
  - Gets screened tickers and filters blacklisted ones
  - For each ticker, gets market data via `get_market_data()`
  - Calculates price momentum from `datetime_price` array:
    - Compares early 30% vs recent 30% of price data
    - Identifies upward momentum (>0.1% change with positive trend) → `buy_to_open`
    - Identifies downward momentum (<-0.1% change with negative trend) → `sell_to_open`
  - Skips tickers that already have active momentum trades
  - Sends webhook signals and stores entries in `ActiveTickersForAutomatedDayTrader` table

- **Exit Service** (runs every 5 seconds):
  - Checks market status
  - Monitors active momentum trades in `ActiveTickersForAutomatedDayTrader` table
  - Gets current market data to check profitability
  - Exits when profit threshold is reached (default: 0.5%):
    - Long trades: exits when current price ≥ enter_price × 1.005
    - Short trades: exits when current price ≤ enter_price × 0.995
  - Sends webhook signals and removes from DynamoDB when profitable

## Setup

### Prerequisites

- Python 3.9+ (required for MCP library)
- AWS credentials configured (for DynamoDB access)
- Three DynamoDB tables must exist:
  - `ActiveTradesForAutomatedWorkflow` (for standard trading strategy)
  - `ActiveTickersForAutomatedDayTrader` (for momentum trading strategy)
  - `TickerBlackList` (for blacklisted tickers)

### Installation

1. Install dependencies:

```bash
pip install -r requirements.txt
```

2. Configure AWS credentials (for DynamoDB):

   - Set AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY environment variables
   - Or use AWS IAM role if running on EC2/ECS

3. Run the application:

```bash
PYTHONPATH=app/src python app/src/app.py
```

## Deployment to Heroku

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
```

3. Deploy:

```bash
git push heroku main
```

4. Scale the worker:

```bash
heroku ps:scale worker=1
```

## Environment Variables

- `MARKET_DATA_MCP_URL`: MCP API base URL (default: https://market-data-analyzer-d1d18da61b50.herokuapp.com/mcp)
- `MCP_AUTH_HEADER_NAME`: Authorization header name (default: Authorization)
- `MARKET_DATA_MCP_TOKEN`: MCP API authentication token (required)
- `AWS_ACCESS_KEY_ID`: AWS access key for DynamoDB
- `AWS_SECRET_ACCESS_KEY`: AWS secret key for DynamoDB
- `AWS_DEFAULT_REGION`: AWS region (default: us-east-1)
- `DYNAMODB_TABLE_NAME`: DynamoDB table name for standard trades (default: ActiveTradesForAutomatedWorkflow)
- `DEBUG_DAY_TRADING`: Set to "true" to force market clock to always return open (for testing)

## MCP API Integration

The application connects to the Market Data Analyzer MCP API:

- Base URL: `https://market-data-analyzer-d1d18da61b50.herokuapp.com/mcp`
- **Protocol**: Uses HTTP POST requests (MCP protocol discovery disabled due to server compatibility issues)
- **Authentication**: Bearer token via `Authorization` header (or custom header name via `MCP_AUTH_HEADER_NAME`)

### Available MCP Tools

The application uses the following MCP tools:

- `get_market_clock`: Check if market is open
- `get_alpaca_screened_tickers`: Get gainers, losers, and most active tickers
- `get_quote`: Get current bid/ask prices for a ticker
- `get_market_data`: Get market data including technical analysis and price history
- `enter`: Determine if entry conditions are met (standard trading strategy)
- `exit`: Determine if exit conditions are met (standard trading strategy)
- `send_webhook_signal`: Send trading signals to external webhook endpoints

## DynamoDB Tables

### 1. ActiveTradesForAutomatedWorkflow (Standard Trading Strategy)

**Partition Key**: `ticker` (String)

**Attributes**:

- `ticker` (String): Stock symbol
- `action` (String): "buy_to_open" or "sell_to_open"
- `indicator` (String): Indicator name ("Automated Trading" for buy_to_open, "Automated workflow" for sell_to_open)
- `enter_price` (Number): Entry price (ask price for buys, bid price for sells)
- `enter_reason` (String): Reason for entry from MCP tool
- `enter_response` (Map): Full response from `enter()` API call
- `created_at` (String): ISO timestamp when trade was created

### 2. ActiveTickersForAutomatedDayTrader (Momentum Trading Strategy)

**Partition Key**: `ticker` (String)

**Attributes**:

- `ticker` (String): Stock symbol
- `action` (String): "buy_to_open" or "sell_to_open"
- `indicator` (String): Always "Momentum Trading"
- `enter_price` (Number): Entry price (ask price for buys, bid price for sells)
- `enter_reason` (String): Momentum calculation details (e.g., "Momentum: 0.25% change (early_avg: 100.50, recent_avg: 100.75)")
- `created_at` (String): ISO timestamp when trade was created

### 3. TickerBlackList (Blacklisted Tickers)

**Partition Key**: `ticker` (String)

**Attributes**:

- `ticker` (String): Stock symbol to blacklist

**Usage**: Tickers in this table are automatically excluded from all trading operations (both entry and exit logic)

## Trading Strategies Details

### Standard Trading Strategy

Uses MCP tools (`enter()` and `exit()`) to make trading decisions:

- **Entry**: Calls `enter()` MCP tool which uses technical analysis to determine if entry conditions are met
- **Exit**: Calls `exit()` MCP tool which uses technical analysis to determine if exit conditions are met
- **Indicators**:
  - "Automated Trading" for long positions (buy_to_open)
  - "Automated workflow" for short positions (sell_to_open)

### Momentum Trading Strategy

Uses price momentum analysis to make trading decisions:

- **Entry Logic**:
  - Analyzes `datetime_price` array from market data
  - Compares average of first 30% of prices vs last 30% of prices
  - Upward momentum (>0.1% change with positive recent trend) → Long position
  - Downward momentum (<-0.1% change with negative recent trend) → Short position
- **Exit Logic**:
  - Monitors current price vs entry price
  - Exits when profit threshold is reached (default: 0.5%)
  - Long trades: exit when profit ≥ 0.5%
  - Short trades: exit when profit ≥ 0.5%
- **Profit Threshold**: Configurable via `self.profit_threshold` in `MomentumTradingService` (default: 0.5%)

## Logging

The application uses Loguru for structured logging and logs to stdout with INFO level by default. Logs include:

- Service initialization and startup
- Market status checks
- Entry/exit signals for both strategies
- Webhook notifications
- DynamoDB operations (add, get, delete)
- Blacklist filtering operations
- Tool discovery events
- Errors and exceptions with full stack traces

## Error Handling

The application includes comprehensive error handling:

- Network errors when calling MCP APIs (with retry logic)
- DynamoDB operation failures (graceful degradation)
- Invalid data handling (skips invalid trades)
- Blacklist checks at multiple points (entry and exit)
- Graceful shutdown on SIGINT/SIGTERM signals
- Service-level error isolation (one service failure doesn't stop others)

## Key Design Decisions

1. **Dual Strategy Architecture**: Separates standard (MCP-based) and momentum (algorithm-based) trading into independent services
2. **Separate DynamoDB Tables**: Each strategy uses its own table to avoid conflicts and enable independent monitoring
3. **Blacklist Support**: Centralized blacklist table prevents trading on specific tickers across all strategies
4. **HTTP Fallback**: Uses HTTP POST requests instead of MCP protocol due to server compatibility issues
5. **Concurrent Execution**: All services run concurrently using `asyncio.gather()` for optimal performance
6. **Market-Aware**: All trading operations check market status before execution

## Notes

- The application runs continuously until stopped (SIGINT/SIGTERM)
- All three services (Tool Discovery, Trading Service, Momentum Trading Service) run concurrently using asyncio
- Market checks occur before all trading operations
- Entry services run every 10 seconds, exit services run every 5 seconds
- Tool discovery refreshes every 5 minutes (currently disabled, uses HTTP fallback)
- Blacklisted tickers are filtered at multiple points: during ticker screening, before entry calls, and before exit calls
- Momentum trades are prevented from duplicate entries (checks for existing active trades)

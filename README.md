# Automated Day Trading Application

An automated day trading application that monitors market conditions and executes trades based on technical indicators and market sentiment.

## Features

- **Market Clock Monitoring**: Checks if the market is open every 10 seconds
- **Entry Logic**: Automatically identifies trading opportunities for gainers, losers, and most active stocks
- **Exit Logic**: Monitors active positions and exits trades based on profit targets and stop losses
- **DynamoDB Integration**: Stores active trades for monitoring
- **Webhook Integration**: Sends trading signals to external systems

## Architecture

The application consists of two main async services running concurrently:

1. **Entry Service** (runs every 10 seconds):
   - Checks market status
   - Gets screened tickers (gainers, losers, most active)
   - Calls `enter()` MCP tool for each ticker
   - Sends webhook signals and stores entries in DynamoDB when entry conditions are met

2. **Exit Service** (runs every 5 seconds):
   - Monitors active trades in DynamoDB
   - Calls `exit()` MCP tool for each active trade
   - Sends webhook signals and removes from DynamoDB when exit conditions are met

## Setup

### Prerequisites

- Python 3.8+
- AWS credentials configured (for DynamoDB access)
- DynamoDB table named `ActiveTradesForAutomatedWorkflow` must exist

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
- `MARKET_DATA_MCP_TOKEN`: MCP API authentication token
- `AWS_ACCESS_KEY_ID`: AWS access key for DynamoDB
- `AWS_SECRET_ACCESS_KEY`: AWS secret key for DynamoDB
- `AWS_DEFAULT_REGION`: AWS region (default: us-east-1)
- `DYNAMODB_TABLE_NAME`: DynamoDB table name (default: ActiveTradesForAutomatedWorkflow)

## MCP API Endpoint

The application connects to the Market Data Analyzer MCP API:
- Base URL: `https://market-data-analyzer-d1d18da61b50.herokuapp.com/mcp`

## DynamoDB Table Schema

**Table Name**: `ActiveTradesForAutomatedWorkflow`

**Partition Key**: `ticker` (String)

**Attributes**:
- `ticker` (String): Stock symbol
- `action` (String): "buy_to_open" or "sell_to_open"
- `indicator` (String): Indicator name ("Automated Trading" or "Automated workflow")
- `enter_price` (Number): Entry price
- `enter_reason` (String): Reason for entry
- `enter_response` (Map): Full response from enter() API call
- `created_at` (String): ISO timestamp when trade was created

## Logging

The application logs to stdout with INFO level by default. Logs include:
- Market status checks
- Entry/exit signals
- Webhook notifications
- DynamoDB operations
- Errors and exceptions

## Error Handling

The application includes comprehensive error handling:
- Network errors when calling MCP APIs
- DynamoDB operation failures
- Invalid data handling
- Graceful shutdown on SIGINT/SIGTERM

## Notes

- The application runs continuously until stopped
- Both services run concurrently using asyncio
- Market checks only occur during market hours
- Active trades are monitored every 5 seconds for exit opportunities

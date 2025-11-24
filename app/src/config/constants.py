"""
Constants and configuration loaded from environment variables
"""

import os
from pathlib import Path
from dotenv import load_dotenv
from typing import Optional

# Determine the project root directory (parent of app/src)
APP_DIR = Path(__file__).parent
PROJECT_ROOT = APP_DIR.parent.parent

# Load environment variables from .env file in project root
env_path = PROJECT_ROOT / ".env"
load_dotenv(dotenv_path=env_path, override=True)

# MCP API Configuration
MARKET_DATA_MCP_URL = os.getenv(
    "MARKET_DATA_MCP_URL", "https://market-data-analyzer-d1d18da61b50.herokuapp.com/mcp"
)

MCP_AUTH_HEADER_NAME = os.getenv("MCP_AUTH_HEADER_NAME", "Authorization")
MCP_AUTH_BEARER_TOKEN: Optional[str] = os.getenv("MCP_AUTH_BEARER_TOKEN", "")

MARKET_DATA_MCP_TOKEN = os.getenv("MARKET_DATA_MCP_TOKEN", "")
MARKET_DATA_MCP_NAME: str = os.getenv("MARKET_DATA_MCP_NAME", "market-data")

DEBUG_DAY_TRADING = os.environ.get("DEBUG_DAY_TRADING", False)
if isinstance(DEBUG_DAY_TRADING, str):
    if DEBUG_DAY_TRADING.lower() == "true":
        DEBUG_DAY_TRADING = True
    else:
        DEBUG_DAY_TRADING = False


# DynamoDB Configuration
DYNAMODB_TABLE_NAME = os.getenv(
    "DYNAMODB_TABLE_NAME", "ActiveTradesForAutomatedWorkflow"
)

# AWS Configuration
AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID", "")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY", "")
AWS_DEFAULT_REGION = os.getenv("AWS_DEFAULT_REGION", "us-east-1")

# Momentum Trading Configuration
MOMENTUM_TOP_K = int(
    os.getenv("MOMENTUM_TOP_K", "10")
)  # Number of top tickers to trade per direction


# ---------------------------------------------------------------------------
# Logging / environment
# ---------------------------------------------------------------------------

LOG_LEVEL: str = os.getenv("AUTOMATED_TRADING_SYSTEM_LOG_LEVEL", "INFO")
ENVIRONMENT: str = os.getenv("ENVIRONMENT", "development")


# ---------------------------------------------------------------------------
# MCP server transport configuration
# ---------------------------------------------------------------------------

MCP_SERVER_TRANSPORT: str = os.getenv("WORKFLOW_MCP_TRANSPORT", "streamable-http")
MCP_TOOL_DISCOVERY_INTERVAL_SECONDS: int = int(
    os.getenv("WORKFLOW_MCP_TOOL_DISCOVERY_SECONDS", "300")
)


# Get AWS credentials from environment variables
aws_access_key = os.getenv("AWS_ACCESS_KEY_ID")
aws_secret_key = os.getenv("AWS_SECRET_ACCESS_KEY")
aws_region = os.getenv("AWS_DEFAULT_REGION", "us-east-1")

# LONG
BUY_TO_OPEN = "BUY_TO_OPEN"
SELL_TO_CLOSE = "SELL_TO_CLOSE"

# SHORT
SELL_TO_OPEN = "SELL_TO_OPEN"
BUY_TO_CLOSE = "BUY_TO_CLOSE"


WEBHOOK_URL = os.environ.get("WEBHOOK_URL", "")
# Parse WEBHOOK_URL as comma-separated list of URLs
WEBHOOK_URLS = [url.strip() for url in WEBHOOK_URL.split(",") if url.strip()]
WEBHOOK_TIMEOUT = 10  # Increase per-attempt timeout to reduce 504s
WEBHOOK_RETRY_ATTEMPTS = 3  # Allow an extra retry during transient slowdowns
WEBHOOK_RETRY_DELAY = 2  # Slightly longer backoff between attempts

ACTIVE_TICKERS_TABLE_NAME = os.environ.get(
    "ACTIVE_TICKERS_TABLE_NAME", "ActiveTickersForMarketData"
)
WEBHOOK_NOTIFIER_TABLE_NAME = os.environ.get(
    "WEBHOOK_NOTIFIER_TABLE_NAME", "TradingSignals"
)
TRADING_PERFORMANCE_TABLE_NAME = os.environ.get(
    "TRADING_PERFORMANCE_TABLE_NAME", "CompletedTradesForMarketData"
)


CUSTOMER_TABLE_NAME = os.environ.get("CUSTOMER_TABLE", "Customer")
SYNC_DB_TIMEOUT = 30


DEBUG_SYNC_DB_SERVICE = os.environ.get("DEBUG_SYNC_DB_SERVICE", False)
if isinstance(DEBUG_SYNC_DB_SERVICE, str):
    if DEBUG_SYNC_DB_SERVICE.lower() == "true":
        DEBUG_SYNC_DB_SERVICE = True
    else:
        DEBUG_SYNC_DB_SERVICE = False


DEBUG_TRADING_SERVICE = os.environ.get("DEBUG_TRADING_SERVICE", False)
if isinstance(DEBUG_TRADING_SERVICE, str):
    if DEBUG_TRADING_SERVICE.lower() == "true":
        DEBUG_TRADING_SERVICE = True
    else:
        DEBUG_TRADING_SERVICE = False


MARKET_DATA_ANALYZER_INDICATOR = "Market Data Analyzer"

# AWS Bedrock Configuration
AWS_BEDROCK_MODEL_ID: str = os.getenv(
    "AWS_BEDROCK_MODEL_ID", "global.anthropic.claude-sonnet-4-5-20250929-v1:0"
)

"""
Backtesting configuration.

Defines ticker lists, date ranges, and indicator parameters.
"""

import os
from datetime import datetime, timedelta
from dotenv import load_dotenv

# Load environment variables from .env file
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
env_path = os.path.join(project_root, ".env")
load_dotenv(env_path)


# =============================================================================
# Alpaca API Credentials (from environment or .env)
# =============================================================================
ALPACA_API_KEY = os.environ.get("ALPACA_API_KEY", "")
ALPACA_SECRET_KEY = os.environ.get("ALPACA_SECRET_KEY", "")
ALPACA_BASE_URL = "https://data.alpaca.markets/v2"

# =============================================================================
# Date Range
# =============================================================================
# Default: 1 year lookback from today
END_DATE = datetime.now().strftime("%Y-%m-%d")
START_DATE = (datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d")

# =============================================================================
# Data Fetching
# =============================================================================
BARS_TIMEFRAME = "1Min"
CACHE_DIR = os.path.join(os.path.dirname(__file__), "cache")
REQUEST_DELAY_SECONDS = 0.35  # Rate limit: ~170 req/min (under Alpaca's 200/min)

# =============================================================================
# Ticker Lists
# =============================================================================

# Momentum indicator tickers (stocks >= $5)
MOMENTUM_TICKERS = [
    "AAPL",
    "MSFT",
    "NVDA",
    "TSLA",
    "AMD",
    "META",
    "AMZN",
    "GOOG",
    "NFLX",
    "INTC",
    "BA",
    "JPM",
    "BAC",
    "DIS",
    "UBER",
    "PLTR",
    "SOFI",
    "COIN",
    "SNAP",
    "RIVN",
]

# Penny stocks indicator tickers (stocks < $5)
PENNY_STOCK_TICKERS = [
    "SIRI",
    "PLUG",
    "CLOV",
    "WISH",
    "EXPR",
    "GSAT",
    "TELL",
    "AGEN",
    "ZYNE",
    "CRBP",
    "INPX",
    "PRTY",
    "VEON",
    "MVST",
    "NKLA",
    "GRAB",
    "VFS",
    "GEVO",
    "CLVR",
    "BIOR",
]


# =============================================================================
# Simulation Parameters
# =============================================================================

# Position sizing
MOMENTUM_BASE_POSITION_SIZE = 2000.0  # $2000 base for momentum
PENNY_STOCK_POSITION_SIZE = 300.0  # $300 for penny stocks (as configured)
MIN_POSITION_SIZE = 50.0  # Minimum position

# Spread simulation from bar OHLC (since we don't have real bid/ask)
# Estimate: spread ≈ (high - low) * SPREAD_ESTIMATE_FACTOR
SPREAD_ESTIMATE_FACTOR = 0.20

# Maximum concurrent positions per indicator
MOMENTUM_MAX_POSITIONS = 2
PENNY_STOCK_MAX_POSITIONS = 4

# Daily trade limits
MOMENTUM_MAX_DAILY_TRADES = 10
PENNY_STOCK_MAX_DAILY_TRADES = 25

# Market hours (Eastern Time)
MARKET_OPEN_HOUR = 9
MARKET_OPEN_MINUTE = 30
MARKET_CLOSE_HOUR = 16
MARKET_CLOSE_MINUTE = 0

# Entry cutoff times (ET)
MOMENTUM_ENTRY_CUTOFF_HOUR = 15
MOMENTUM_ENTRY_CUTOFF_MINUTE = 55
PENNY_STOCK_ENTRY_CUTOFF_HOUR = 15
PENNY_STOCK_ENTRY_CUTOFF_MINUTE = 45

# Force close minutes before market close
FORCE_CLOSE_MINUTES_BEFORE = 5

# Output
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "results")

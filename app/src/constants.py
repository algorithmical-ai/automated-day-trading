"""
Constants and configuration loaded from environment variables
"""
import os
from pathlib import Path
from dotenv import load_dotenv

# Determine the project root directory (parent of app/src)
APP_DIR = Path(__file__).parent
PROJECT_ROOT = APP_DIR.parent.parent

# Load environment variables from .env file in project root
env_path = PROJECT_ROOT / ".env"
load_dotenv(dotenv_path=env_path, override=True)

# MCP API Configuration
MARKET_DATA_MCP_URL = os.getenv(
    "MARKET_DATA_MCP_URL",
    "https://market-data-analyzer-d1d18da61b50.herokuapp.com/mcp"
)

MCP_AUTH_HEADER_NAME = os.getenv("MCP_AUTH_HEADER_NAME", "Authorization")

MARKET_DATA_MCP_TOKEN = os.getenv("MARKET_DATA_MCP_TOKEN", "")


DEBUG_DAY_TRADING = os.environ.get("DEBUG_DAY_TRADING", False)
if isinstance(DEBUG_DAY_TRADING, str):
    if DEBUG_DAY_TRADING.lower() == "true":
        DEBUG_DAY_TRADING = True
    else:
        DEBUG_DAY_TRADING = False


# DynamoDB Configuration
DYNAMODB_TABLE_NAME = os.getenv(
    "DYNAMODB_TABLE_NAME",
    "ActiveTradesForAutomatedWorkflow"
)

# AWS Configuration
AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID", "")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY", "")
AWS_DEFAULT_REGION = os.getenv("AWS_DEFAULT_REGION", "us-east-1")

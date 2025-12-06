"""
Loguru Logger Configuration

This module configures the Loguru logger for the Trading Oracle Service with custom formatting,
timezone handling, and environment-based log levels.
"""

import logging
import os
import sys
from datetime import timezone

from loguru import logger

LOG_LEVEL = os.getenv(
    "LOG_LEVEL", os.getenv("WORKFLOW_MANAGER_LOG_LEVEL", "INFO")
).upper()
LOCAL_TZ = timezone.utc

logger.remove()

LOG_FORMAT = "{time:YYYY-MM-DD HH:mm:ss.SSS} | {level:<8} | {file}:{line} | {function} | {message}"

# Determine if we should use colorized output (development mode only)
is_development = (
    os.getenv("ENVIRONMENT", "development").lower() == "development"
    and not os.getenv("DYNO")
)

logger.add(
    sys.stdout,
    level=LOG_LEVEL,
    format=LOG_FORMAT,
    colorize=is_development,  # Colorize in development, plain in production
    enqueue=False,
    backtrace=False,
    diagnose=False,
)

# Suppress noisy third-party library logs
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("botocore").setLevel(logging.WARNING)
logging.getLogger("boto3").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)
# Suppress all MCP client library logs
logging.getLogger("mcp").setLevel(logging.WARNING)
logging.getLogger("mcp.client").setLevel(logging.WARNING)
logging.getLogger("mcp.client.streamable_http").setLevel(logging.WARNING)
logging.getLogger("mcp.client.streamable_http_manager").setLevel(logging.WARNING)

__all__ = ["logger"]

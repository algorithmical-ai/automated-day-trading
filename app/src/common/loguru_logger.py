"""
Loguru Logger Configuration

This module configures the Loguru logger for the Trading Oracle Service with custom formatting,
timezone handling, and environment-based log levels.

Supports two output modes:
- Development: Human-readable pipe-delimited format with colors
- Production: JSON format for Datadog parsing and facets
"""

import json
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

# Human-readable format for development
LOG_FORMAT = "{time:YYYY-MM-DD HH:mm:ss.SSS} | {level:<8} | {file}:{line} | {function} | {message}"

# Determine environment
is_production = os.getenv("DYNO") or os.getenv("ENVIRONMENT", "development").lower() == "production"
is_development = not is_production


def json_serializer(record):
    """
    Serialize log record to JSON format for Datadog.
    
    This enables:
    - Automatic facet creation in Datadog
    - Easy filtering by any field
    - Full structured data visibility
    """
    subset = {
        "timestamp": record["time"].strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
        "level": record["level"].name,
        "message": record["message"],
        "logger": {
            "name": record["name"],
            "file": record["file"].name,
            "line": record["line"],
            "function": record["function"],
        },
    }
    
    # Include all extra data as top-level fields for easy Datadog faceting
    if record["extra"]:
        for key, value in record["extra"].items():
            # Avoid overwriting core fields
            if key not in subset:
                subset[key] = value
    
    # Add exception info if present
    if record["exception"]:
        subset["exception"] = {
            "type": record["exception"].type.__name__ if record["exception"].type else None,
            "value": str(record["exception"].value) if record["exception"].value else None,
            "traceback": record["exception"].traceback,
        }
    
    return json.dumps(subset, default=str)


def json_sink(message):
    """Sink that outputs JSON-formatted logs."""
    record = message.record
    print(json_serializer(record), flush=True)


if is_production:
    # Production: JSON output for Datadog
    logger.add(
        json_sink,
        level=LOG_LEVEL,
        enqueue=False,
        backtrace=True,
        diagnose=False,
    )
else:
    # Development: Human-readable output with colors
    logger.add(
        sys.stdout,
        level=LOG_LEVEL,
        format=LOG_FORMAT,
        colorize=True,
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

__all__ = ["logger"]

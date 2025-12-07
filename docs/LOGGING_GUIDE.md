# Comprehensive Logging Guide

This guide explains how to use the structured logging utilities in the Automated Day Trading System.

## Overview

The system implements comprehensive logging as specified in Requirements 16.1-16.5:

- **16.1**: Structured operation logging using Loguru
- **16.2**: Signal logging with ticker, reason, and technical indicators
- **16.3**: Error logging with full stack trace
- **16.4**: DynamoDB operation logging with operation type, table name, and status
- **16.5**: Threshold adjustment logging with old/new values and LLM reasoning

## Logging Utilities

All logging utilities are available in `app/src/common/logging_utils.py`.

### 1. Signal Logging (Requirement 16.2)

Use `log_signal()` to log trade entry and exit signals with complete structured data:

```python
from app.src.common.logging_utils import log_signal

# Entry signal
log_signal(
    signal_type="ENTRY",
    ticker="AAPL",
    action="buy_to_open",
    price=150.25,
    reason="Strong upward momentum with ADX > 20",
    technical_indicators={
        "momentum": 2.5,
        "adx": 25.3,
        "rsi": 55.2,
        "volume": 1500000,
        "atr": 1.25
    },
    indicator_name="Momentum Trading",
    stop_loss=-0.05,
    position_size=2000.0
)

# Exit signal
log_signal(
    signal_type="EXIT",
    ticker="AAPL",
    action="sell_to_close",
    price=152.75,
    reason="Trailing stop triggered",
    technical_indicators={
        "momentum": 1.2,
        "adx": 22.1,
        "rsi": 58.5
    },
    indicator_name="Momentum Trading",
    profit_loss=50.00,
    holding_period_minutes=45
)
```

**Output Example:**
```
2024-12-06 10:30:15.123 | INFO     | logging_utils.py:45 | log_signal | 📈 ENTRY SIGNAL: AAPL | buy_to_open @ $150.25 | Indicator: Momentum Trading | Reason: Strong upward momentum with ADX > 20 | Tech: Mom=2.50%, ADX=25.3, RSI=55.2, Vol=1.5M, ATR=1.25
```

### 2. Operation Logging (Requirement 16.1)

Use `log_operation()` for structured logging of system operations:

```python
from app.src.common.logging_utils import log_operation

# Operation started
log_operation(
    operation_type="ticker_screening",
    component="AlpacaScreener",
    status="started"
)

# Operation completed
log_operation(
    operation_type="ticker_screening",
    component="AlpacaScreener",
    status="completed",
    details={
        "gainers_count": 25,
        "losers_count": 30,
        "most_active_count": 50
    }
)

# Operation failed
log_operation(
    operation_type="ticker_screening",
    component="AlpacaScreener",
    status="failed",
    details={"error": "API timeout"}
)
```

### 3. Error Logging (Requirement 16.3)

Use `log_error_with_context()` to log errors with full stack trace and context:

```python
from app.src.common.logging_utils import log_error_with_context

try:
    # Some operation
    result = await risky_operation()
except Exception as e:
    log_error_with_context(
        error=e,
        context="Fetching market data for ticker AAPL",
        component="MomentumIndicator",
        additional_info={
            "ticker": "AAPL",
            "retry_count": 3,
            "timeout": 30
        }
    )
```

**Output Example:**
```
2024-12-06 10:30:15.123 | ERROR    | logging_utils.py:120 | log_error_with_context | ❌ ERROR in MomentumIndicator: Fetching market data for ticker AAPL - TimeoutError: Request timed out after 30 seconds
Traceback (most recent call last):
  File "momentum_indicator.py", line 123, in entry_service
    result = await risky_operation()
  ...
```

### 4. DynamoDB Operation Logging (Requirement 16.4)

DynamoDB operations are automatically logged in `dynamodb_client.py` using structured logging:

```python
from app.src.common.logging_utils import log_dynamodb_operation

# Success
log_dynamodb_operation(
    operation="put_item",
    table_name="ActiveTickersForAutomatedDayTrader",
    status="success"
)

# Query with item count
log_dynamodb_operation(
    operation="query",
    table_name="CompletedTradesForMarketData",
    status="success",
    item_count=15
)

# Failure
log_dynamodb_operation(
    operation="put_item",
    table_name="ActiveTickersForAutomatedDayTrader",
    status="failed",
    error_code="ProvisionedThroughputExceededException",
    error_message="Request rate exceeded"
)
```

**Note:** DynamoDB logging is already implemented in `app/src/db/dynamodb_client.py` and uses the `extra` parameter for structured data.

### 5. Threshold Adjustment Logging (Requirement 16.5)

Use `log_threshold_adjustment()` to log threshold changes with LLM reasoning:

```python
from app.src.common.logging_utils import log_threshold_adjustment

log_threshold_adjustment(
    indicator_name="Momentum Trading",
    old_values={
        "min_momentum_threshold": 1.5,
        "max_momentum_threshold": 15.0,
        "min_adx_threshold": 20.0,
        "rsi_oversold_for_long": 45.0
    },
    new_values={
        "min_momentum_threshold": 1.2,
        "max_momentum_threshold": 15.0,
        "min_adx_threshold": 18.0,
        "rsi_oversold_for_long": 42.0
    },
    llm_reasoning="Market volatility has decreased, lowering momentum threshold to 1.2% will capture more opportunities while maintaining profitability. ADX threshold reduced to 18 to allow entries in moderate trends.",
    max_long_trades=6,
    max_short_trades=4
)
```

**Output Example:**
```
2024-12-06 10:30:15.123 | INFO     | logging_utils.py:180 | log_threshold_adjustment | 🔧 THRESHOLD ADJUSTMENT for Momentum Trading: min_momentum_threshold: 1.5 → 1.2, min_adx_threshold: 20.0 → 18.0, rsi_oversold_for_long: 45.0 → 42.0 | Max trades: L=6, S=4 | Reasoning: Market volatility has decreased, lowering momentum threshold to 1.2% will capture more opportunities...
```

### 6. MAB Selection Logging

Use `log_mab_selection()` to log MAB ticker selection:

```python
from app.src.common.logging_utils import log_mab_selection

log_mab_selection(
    indicator_name="Momentum Trading",
    direction="long",
    candidates_count=50,
    selected_count=5,
    top_selections=["AAPL(s:3/f:1)", "MSFT(s:2/f:0)", "GOOGL(new)"]
)
```

### 7. Market Status Logging

Use `log_market_status()` to log market open/close status:

```python
from app.src.common.logging_utils import log_market_status

log_market_status(
    is_open=True,
    next_close="2024-12-06T16:00:00-05:00"
)

log_market_status(
    is_open=False,
    next_open="2024-12-09T09:30:00-05:00"
)
```

## Integration Examples

### Trading Indicator Entry/Exit

Here's how to integrate signal logging in a trading indicator:

```python
class MomentumIndicator(BaseTradingIndicator):
    
    async def _enter_trade(self, ticker: str, action: str, price: float, 
                          technical_indicators: Dict[str, Any], reason: str):
        """Enter a trade with comprehensive logging"""
        
        # Calculate stop loss and position size
        stop_loss = self._calculate_stop_loss(price, technical_indicators.get("atr", 0))
        position_size = self.position_size_dollars
        
        # Log the entry signal (Requirement 16.2)
        log_signal(
            signal_type="ENTRY",
            ticker=ticker,
            action=action,
            price=price,
            reason=reason,
            technical_indicators=technical_indicators,
            indicator_name=self.indicator_name(),
            stop_loss=stop_loss,
            position_size=position_size
        )
        
        # Store in DynamoDB (automatically logs via DynamoDB client)
        success = await DynamoDBClient.add_momentum_trade(
            ticker=ticker,
            action=action,
            indicator=self.indicator_name(),
            enter_price=price,
            enter_reason=reason,
            technical_indicators_for_enter=technical_indicators,
            dynamic_stop_loss=stop_loss
        )
        
        if not success:
            logger.error(f"Failed to store trade in DynamoDB for {ticker}")
        
        # Send webhook notification
        await self._send_webhook_notification(
            ticker=ticker,
            action=action,
            price=price,
            reason=reason,
            technical_indicators=technical_indicators
        )
    
    async def _exit_trade(self, ticker: str, action: str, exit_price: float,
                         enter_price: float, technical_indicators: Dict[str, Any], 
                         reason: str):
        """Exit a trade with comprehensive logging"""
        
        # Calculate profit/loss
        if action == "sell_to_close":  # Long position
            profit_loss = (exit_price - enter_price) * (self.position_size_dollars / enter_price)
        else:  # Short position
            profit_loss = (enter_price - exit_price) * (self.position_size_dollars / enter_price)
        
        # Log the exit signal (Requirement 16.2)
        log_signal(
            signal_type="EXIT",
            ticker=ticker,
            action=action,
            price=exit_price,
            reason=reason,
            technical_indicators=technical_indicators,
            indicator_name=self.indicator_name(),
            profit_loss=profit_loss,
            enter_price=enter_price
        )
        
        # Move to completed trades (automatically logs via DynamoDB client)
        # ... DynamoDB operations ...
        
        # Send webhook notification
        await self._send_webhook_notification(
            ticker=ticker,
            action=action,
            price=exit_price,
            reason=reason,
            technical_indicators=technical_indicators,
            profit_loss=profit_loss
        )
```

## Structured Logging with Extra Fields

All logging functions support the `extra` parameter for structured data that can be queried later:

```python
log_signal(
    signal_type="ENTRY",
    ticker="AAPL",
    action="buy_to_open",
    price=150.25,
    reason="Strong momentum",
    technical_indicators={"momentum": 2.5},
    indicator_name="Momentum Trading",
    # Extra fields for structured logging
    strategy_version="2.1",
    market_regime="trending",
    volatility_level="low"
)
```

## Log Levels

The system uses the following log levels:

- **DEBUG**: Detailed diagnostic information (market status checks, cache hits, etc.)
- **INFO**: General informational messages (signals, operations completed, threshold adjustments)
- **WARNING**: Warning messages (missing data, retries, degraded functionality)
- **ERROR**: Error messages with stack traces (operation failures, exceptions)

## Configuration

Log level can be configured via environment variable:

```bash
export LOG_LEVEL=DEBUG  # DEBUG, INFO, WARNING, ERROR
```

## Best Practices

1. **Always use structured logging** - Include relevant context in the `extra` parameter
2. **Log signals at entry and exit** - Use `log_signal()` for all trade signals
3. **Log errors with context** - Use `log_error_with_context()` instead of plain `logger.error()`
4. **Include technical indicators** - Always include technical indicators in signal logs
5. **Use appropriate log levels** - DEBUG for diagnostics, INFO for signals, ERROR for failures
6. **Keep messages concise** - The structured data provides details, keep messages readable
7. **Log threshold adjustments** - Always log when thresholds change with old/new values

## Querying Logs

Since all logs use structured data, you can query them efficiently:

```bash
# Find all entry signals for AAPL
grep "ENTRY SIGNAL: AAPL" logs.txt

# Find all errors in MomentumIndicator
grep "ERROR in MomentumIndicator" logs.txt

# Find all threshold adjustments
grep "THRESHOLD ADJUSTMENT" logs.txt

# Find all DynamoDB failures
grep "DynamoDB.*FAILED" logs.txt
```

For production systems, consider using log aggregation tools like:
- **Heroku Logs**: `heroku logs --tail --app your-app`
- **Papertrail**: For log aggregation and search
- **Datadog**: For advanced log analytics
- **CloudWatch**: For AWS-based deployments

## Testing Logging

To test logging in your code:

```python
import pytest
from loguru import logger
from app.src.common.logging_utils import log_signal

def test_signal_logging(caplog):
    """Test that signal logging works correctly"""
    with caplog.at_level("INFO"):
        log_signal(
            signal_type="ENTRY",
            ticker="TEST",
            action="buy_to_open",
            price=100.0,
            reason="Test signal",
            technical_indicators={"momentum": 2.0},
            indicator_name="TestIndicator"
        )
    
    assert "ENTRY SIGNAL: TEST" in caplog.text
    assert "buy_to_open" in caplog.text
```

## Summary

The comprehensive logging system provides:

✅ **Structured logging** for all operations (Requirement 16.1)  
✅ **Signal logging** with ticker, reason, and technical indicators (Requirement 16.2)  
✅ **Error logging** with full stack traces (Requirement 16.3)  
✅ **DynamoDB operation logging** with operation type, table name, and status (Requirement 16.4)  
✅ **Threshold adjustment logging** with old/new values and LLM reasoning (Requirement 16.5)

All logging is production-ready and follows best practices for observability and debugging.

"""
Logging Utilities for Automated Day Trading System

Provides structured logging helpers for consistent logging across all components.
Implements requirements 16.1, 16.2, 16.3, 16.4, 16.5
"""

from typing import Dict, Any, Optional
from loguru import logger


def log_signal(
    signal_type: str,
    ticker: str,
    action: str,
    price: float,
    reason: str,
    technical_indicators: Dict[str, Any],
    indicator_name: str,
    profit_loss: Optional[float] = None,
    **extra_fields
):
    """
    Log trading signal with complete structured data.
    
    Requirement 16.2: Signal logging with ticker, reason, and technical indicators
    
    Args:
        signal_type: "ENTRY" or "EXIT"
        ticker: Stock ticker symbol
        action: Trade action (buy_to_open, sell_to_open, buy_to_close, sell_to_close)
        price: Entry or exit price
        reason: Reason for the signal
        technical_indicators: Dictionary of technical indicators
        indicator_name: Name of the trading indicator
        profit_loss: Profit/loss amount (for exit signals)
        **extra_fields: Additional fields to include in log
    """
    log_data = {
        "signal_type": signal_type,
        "ticker": ticker,
        "action": action,
        "price": price,
        "reason": reason,
        "indicator": indicator_name,
        "technical_indicators": technical_indicators,
    }
    
    if profit_loss is not None:
        log_data["profit_loss"] = profit_loss
    
    # Add any extra fields
    log_data.update(extra_fields)
    
    # Format technical indicators for readability
    tech_summary = _format_technical_indicators(technical_indicators)
    
    if signal_type == "ENTRY":
        logger.info(
            f"📈 {signal_type} SIGNAL: {ticker} | {action} @ ${price:.2f} | "
            f"Indicator: {indicator_name} | Reason: {reason} | Tech: {tech_summary}",
            extra=log_data
        )
    else:  # EXIT
        pl_str = f"P/L: ${profit_loss:.2f}" if profit_loss is not None else ""
        logger.info(
            f"📉 {signal_type} SIGNAL: {ticker} | {action} @ ${price:.2f} | "
            f"{pl_str} | Indicator: {indicator_name} | Reason: {reason} | Tech: {tech_summary}",
            extra=log_data
        )


def log_operation(
    operation_type: str,
    component: str,
    status: str,
    details: Optional[Dict[str, Any]] = None,
    **extra_fields
):
    """
    Log system operation with structured data.
    
    Requirement 16.1: Structured operation logging
    
    Args:
        operation_type: Type of operation (e.g., "market_check", "ticker_screening", "threshold_adjustment")
        component: Component performing the operation
        status: Operation status ("started", "completed", "failed")
        details: Additional operation details
        **extra_fields: Additional fields to include in log
    """
    log_data = {
        "operation_type": operation_type,
        "component": component,
        "status": status,
    }
    
    if details:
        log_data["details"] = details
    
    log_data.update(extra_fields)
    
    if status == "failed":
        logger.error(
            f"❌ Operation {operation_type} FAILED in {component}",
            extra=log_data
        )
    elif status == "started":
        logger.debug(
            f"▶️  Operation {operation_type} STARTED in {component}",
            extra=log_data
        )
    else:  # completed
        logger.info(
            f"✅ Operation {operation_type} COMPLETED in {component}",
            extra=log_data
        )


def log_error_with_context(
    error: Exception,
    context: str,
    component: str,
    additional_info: Optional[Dict[str, Any]] = None,
    **extra_fields
):
    """
    Log error with full stack trace and context.
    
    Requirement 16.3: Error logging with full stack trace
    
    Args:
        error: The exception that occurred
        context: Description of what was being done when error occurred
        component: Component where error occurred
        additional_info: Additional contextual information
        **extra_fields: Additional fields to include in log
    """
    log_data = {
        "error_type": type(error).__name__,
        "error_message": str(error),
        "context": context,
        "component": component,
    }
    
    if additional_info:
        log_data["additional_info"] = additional_info
    
    log_data.update(extra_fields)
    
    logger.exception(
        f"❌ ERROR in {component}: {context} - {type(error).__name__}: {str(error)}",
        extra=log_data
    )


def log_dynamodb_operation(
    operation: str,
    table_name: str,
    status: str,
    item_count: Optional[int] = None,
    error_code: Optional[str] = None,
    error_message: Optional[str] = None,
    **extra_fields
):
    """
    Log DynamoDB operation with operation type, table name, and status.
    
    Requirement 16.4: DynamoDB operation logging
    
    Args:
        operation: DynamoDB operation type (put_item, get_item, delete_item, query, scan, update_item)
        table_name: Name of the DynamoDB table
        status: Operation status ("success" or "failed")
        item_count: Number of items affected (for query/scan)
        error_code: Error code if operation failed
        error_message: Error message if operation failed
        **extra_fields: Additional fields to include in log
    """
    log_data = {
        "operation": operation,
        "table": table_name,
        "status": status,
        "service": "DynamoDB"
    }
    
    if item_count is not None:
        log_data["item_count"] = item_count
    
    if error_code:
        log_data["error_code"] = error_code
    
    if error_message:
        log_data["error_message"] = error_message
    
    log_data.update(extra_fields)
    
    if status == "success":
        count_str = f" ({item_count} items)" if item_count is not None else ""
        logger.debug(
            f"💾 DynamoDB {operation} SUCCESS on {table_name}{count_str}",
            extra=log_data
        )
    else:
        logger.error(
            f"❌ DynamoDB {operation} FAILED on {table_name}: {error_code} - {error_message}",
            extra=log_data
        )


def log_threshold_adjustment(
    indicator_name: str,
    old_values: Dict[str, Any],
    new_values: Dict[str, Any],
    llm_reasoning: str,
    max_long_trades: int,
    max_short_trades: int,
    **extra_fields
):
    """
    Log threshold adjustment with old/new values and LLM reasoning.
    
    Requirement 16.5: Threshold adjustment logging with old/new values and LLM reasoning
    
    Args:
        indicator_name: Name of the trading indicator
        old_values: Dictionary of old threshold values
        new_values: Dictionary of new threshold values
        llm_reasoning: LLM's reasoning for the adjustments
        max_long_trades: Recommended max long trades
        max_short_trades: Recommended max short trades
        **extra_fields: Additional fields to include in log
    """
    log_data = {
        "indicator": indicator_name,
        "old_values": old_values,
        "new_values": new_values,
        "llm_reasoning": llm_reasoning,
        "max_long_trades": max_long_trades,
        "max_short_trades": max_short_trades,
        "operation_type": "threshold_adjustment"
    }
    
    log_data.update(extra_fields)
    
    # Calculate changes
    changes = []
    for key in new_values:
        old_val = old_values.get(key, "N/A")
        new_val = new_values[key]
        if old_val != new_val:
            changes.append(f"{key}: {old_val} → {new_val}")
    
    changes_str = ", ".join(changes) if changes else "No changes"
    
    logger.info(
        f"🔧 THRESHOLD ADJUSTMENT for {indicator_name}: {changes_str} | "
        f"Max trades: L={max_long_trades}, S={max_short_trades} | "
        f"Reasoning: {llm_reasoning[:100]}...",
        extra=log_data
    )


def log_mab_selection(
    indicator_name: str,
    direction: str,
    candidates_count: int,
    selected_count: int,
    top_selections: list,
    **extra_fields
):
    """
    Log MAB ticker selection with details.
    
    Args:
        indicator_name: Name of the trading indicator
        direction: "long" or "short"
        candidates_count: Number of candidate tickers
        selected_count: Number of selected tickers
        top_selections: List of top selected tickers with stats
        **extra_fields: Additional fields to include in log
    """
    log_data = {
        "indicator": indicator_name,
        "direction": direction,
        "candidates_count": candidates_count,
        "selected_count": selected_count,
        "top_selections": top_selections,
        "operation_type": "mab_selection"
    }
    
    log_data.update(extra_fields)
    
    logger.info(
        f"🎯 MAB SELECTION for {indicator_name} ({direction}): "
        f"Selected {selected_count} from {candidates_count} candidates | "
        f"Top picks: {', '.join(str(t) for t in top_selections[:3])}",
        extra=log_data
    )


def log_market_status(
    is_open: bool,
    next_open: Optional[str] = None,
    next_close: Optional[str] = None,
    **extra_fields
):
    """
    Log market status check.
    
    Args:
        is_open: Whether market is currently open
        next_open: Next market open time
        next_close: Next market close time
        **extra_fields: Additional fields to include in log
    """
    log_data = {
        "market_open": is_open,
        "next_open": next_open,
        "next_close": next_close,
        "operation_type": "market_status_check"
    }
    
    log_data.update(extra_fields)
    
    if is_open:
        logger.debug(
            f"🟢 Market is OPEN | Next close: {next_close}",
            extra=log_data
        )
    else:
        logger.debug(
            f"🔴 Market is CLOSED | Next open: {next_open}",
            extra=log_data
        )


def _format_technical_indicators(tech_indicators: Dict[str, Any]) -> str:
    """Format technical indicators for readable logging"""
    if not tech_indicators:
        return "N/A"
    
    # Extract key indicators for summary
    key_indicators = []
    
    if "momentum" in tech_indicators:
        key_indicators.append(f"Mom={tech_indicators['momentum']:.2f}%")
    
    if "adx" in tech_indicators:
        key_indicators.append(f"ADX={tech_indicators['adx']:.1f}")
    
    if "rsi" in tech_indicators:
        key_indicators.append(f"RSI={tech_indicators['rsi']:.1f}")
    
    if "volume" in tech_indicators:
        vol = tech_indicators['volume']
        if vol >= 1_000_000:
            key_indicators.append(f"Vol={vol/1_000_000:.1f}M")
        elif vol >= 1_000:
            key_indicators.append(f"Vol={vol/1_000:.1f}K")
        else:
            key_indicators.append(f"Vol={vol}")
    
    if "atr" in tech_indicators:
        key_indicators.append(f"ATR={tech_indicators['atr']:.2f}")
    
    return ", ".join(key_indicators) if key_indicators else "N/A"


__all__ = [
    "log_signal",
    "log_operation",
    "log_error_with_context",
    "log_dynamodb_operation",
    "log_threshold_adjustment",
    "log_mab_selection",
    "log_market_status",
]

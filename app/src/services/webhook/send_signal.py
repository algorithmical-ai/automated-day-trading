import asyncio
from typing import Optional

import requests

from app.src.common.loguru_logger import logger
from app.src.config.constants import (
    BUY_TO_CLOSE,
    BUY_TO_OPEN,
    SELL_TO_CLOSE,
    SELL_TO_OPEN,
    WEBHOOK_RETRY_ATTEMPTS,
    WEBHOOK_RETRY_DELAY,
    WEBHOOK_TIMEOUT,
    WEBHOOK_URLS,
)

from app.src.services.mcp.mcp_client import MCPClient


async def send_signal_to_webhook(
    ticker: str,
    action: str,
    indicator: str,
    enter_reason: str = "",
    is_golden_exception: bool = False,
    portfolio_allocation_percent: Optional[float] = None,
) -> None:
    """Send buy/sell signal to webhook and manage DynamoDB entries with timeout protection."""
    # Add overall timeout protection
    try:
        return await asyncio.wait_for(
            _send_signal_to_webhook_impl(
                ticker,
                action,
                indicator,
                enter_reason,
                is_golden_exception,
                portfolio_allocation_percent,
            ),
            timeout=8.0,
        )
    except asyncio.TimeoutError:
        logger.debug(f"Webhook signal timeout for {ticker} {action}")


async def _send_signal_to_webhook_impl(  # noqa: C901
    ticker: str,
    action: str,
    indicator: str,
    enter_reason: str = "",
    is_golden_exception: bool = False,
    portfolio_allocation_percent: Optional[float] = None,
) -> None:
    """Internal implementation of webhook signal sending."""

    # Input validation
    if not ticker or not ticker.strip():
        raise ValueError("Ticker is required")
    if not action or not action.strip():
        raise ValueError("Action is required")
    if not indicator or not indicator.strip():
        raise ValueError("Indicator is required")

    ticker = ticker.strip().upper()
    action = action.strip().upper()
    indicator = indicator.strip()

    # Validate action against allowed values
    valid_actions = [BUY_TO_OPEN, SELL_TO_OPEN, BUY_TO_CLOSE, SELL_TO_CLOSE]
    if action not in valid_actions:
        raise ValueError(f"Invalid action '{action}'. Must be one of: {valid_actions}")

    # Enhanced logging for signal initiation
    action_desc = {
        BUY_TO_OPEN: "🚀 OPEN LONG",
        SELL_TO_OPEN: "🔻 OPEN SHORT",
        BUY_TO_CLOSE: "🌈 CLOSE SHORT",
        SELL_TO_CLOSE: "💰 CLOSE LONG",
    }.get(action, action)

    logger.info(f"{action_desc} signal initiated: {ticker} via {indicator}")

    # Log webhook URLs being used
    if WEBHOOK_URLS:
        logger.info(
            f"📡 Sending signal to {len(WEBHOOK_URLS)} webhook URL(s): {', '.join(WEBHOOK_URLS)}"
        )
    else:
        logger.warning(
            "⚠️ No webhook URLs configured - signal will not be sent to external service"
        )

    # Log portfolio allocation if provided
    if portfolio_allocation_percent is not None:
        logger.info(
            f"📊 Portfolio allocation: {portfolio_allocation_percent:.1%} for {ticker} {action}"
        )
    else:
        logger.info(
            f"📊 Portfolio allocation: Default (not specified) for {ticker} {action}"
        )

    # Get current price for the payload
    current_price = None
    if action in [BUY_TO_OPEN, SELL_TO_OPEN]:
        try:
            # Get quote for ask price (buy price)
            quote_response = await MCPClient.get_quote(ticker)
            if not quote_response:
                logger.warning(f"Failed to get quote for {ticker}")

            quote_data = quote_response.get("quote", {})
            quotes = quote_data.get("quotes", {})
            ticker_quote = quotes.get(ticker, {})
            current_price = ticker_quote.get("ap", 0.0)  # Ask price for buy

        except Exception as e:
            logger.debug(f"⚠️ Could not fetch current price for {ticker}: {e}")

    payload = {
        "ticker_symbol": ticker,
        "action": action,
        "indicator": indicator,
        "portfolio_allocation_percent": portfolio_allocation_percent,
        "current_price": current_price,
        "enter_reason": enter_reason if action in [BUY_TO_OPEN, SELL_TO_OPEN] else "",
        "is_golden_exception": is_golden_exception,
    }

    # Log payload for debugging (excluding sensitive data)
    logger.debug(f"📦 Webhook payload for {ticker} {action}: {payload}")

    # Send to all webhook URLs with improved retry logic and circuit breaker pattern
    webhook_success = False
    last_error = None

    def _send_webhook_request(url: str, data: dict) -> requests.Response:
        """Helper function to send webhook request."""
        return requests.post(
            url,
            json=data,
            timeout=WEBHOOK_TIMEOUT,
            headers={
                "Content-Type": "application/json",
                "Connection": "close",
            },
        )

    for attempt in range(WEBHOOK_RETRY_ATTEMPTS):
        # Try all webhook URLs for each attempt
        for webhook_url in WEBHOOK_URLS:
            try:
                # Use asyncio wait_for for timeout control (compatible with Python
                # 3.10)
                loop = asyncio.get_event_loop()
                # Run the blocking request in a thread pool to avoid blocking the
                # event loop
                response = await asyncio.wait_for(
                    loop.run_in_executor(
                        None,
                        _send_webhook_request,
                        webhook_url,
                        payload,
                    ),
                    timeout=WEBHOOK_TIMEOUT,
                )
                response.raise_for_status()
                logger.info(
                    f"✅ Webhook sent {action} signal for {ticker} to {webhook_url} (attempt {attempt + 1}) | "
                    f"Status: {response.status_code} | Response: {response.text[:200]}"
                )
                webhook_success = True

            except asyncio.TimeoutError:
                last_error = f"Webhook timeout ({WEBHOOK_TIMEOUT}s)"
                logger.warning(
                    f"⏰ Webhook timeout {attempt + 1}/{WEBHOOK_RETRY_ATTEMPTS} for {ticker} to {webhook_url}"
                )
            except requests.RequestException as e:
                last_error = str(e)
                logger.warning(
                    f"🔄 Webhook retry {attempt + 1}/{WEBHOOK_RETRY_ATTEMPTS} for {ticker} to {webhook_url}: {str(e)}"
                )
            except Exception as e:
                last_error = str(e)
                logger.warning(
                    f"❌ Unexpected webhook error for {ticker} to {webhook_url}: {last_error}"
                )

        # Only retry if we have attempts left and haven't succeeded
        if webhook_success:
            break
        if attempt < WEBHOOK_RETRY_ATTEMPTS - 1:
            await asyncio.sleep(WEBHOOK_RETRY_DELAY)

    if not webhook_success:
        logger.error(
            f"❌ All webhook attempts failed for {action} signal {ticker}: {last_error}"
        )
        # Continue with database operations even if webhook fails
        # This prevents losing trade signals due to webhook issues


# Log webhook configuration on module load
if WEBHOOK_URLS:
    logger.info(
        f"✅ Webhook URLs loaded from environment: {len(WEBHOOK_URLS)} URL(s) configured"
    )
    for idx, url in enumerate(WEBHOOK_URLS, 1):
        logger.info(f"   Webhook {idx}: {url}")
else:
    logger.warning("⚠️ No webhook URLs configured in environment variable WEBHOOK_URL")

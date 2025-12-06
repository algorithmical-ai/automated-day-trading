"""
Alpaca API Client for direct market data access
"""

import asyncio
import os
from typing import Optional, Dict, Any
import aiohttp
from app.src.common.loguru_logger import logger


class AlpacaClient:
    """Client for interacting with Alpaca API directly"""

    # TODO: Move these to environment variables for security
    # Note: Environment variables use underscores, but Alpaca headers require hyphens
    API_KEY_ID = os.getenv("APCA_API_KEY_ID", "AKRCLJRMZTZ5KUCPLPQUQUCZM5")
    API_SECRET_KEY = os.getenv("APCA_API_SECRET_KEY", "6eKEZ157DaixSWmc6DCSSdCHuzJRduA5HK1fHjdt43MK")
    BASE_URL = "https://data.alpaca.markets/v2/stocks"

    @classmethod
    async def quote(cls, ticker: str) -> Optional[Dict[str, Any]]:
        """
        Get latest quote for a ticker from Alpaca API.
        
        Retries up to 3 times with 2 second timeout per retry.
        
        Args:
            ticker: Stock ticker symbol (e.g., "AAPL")
            
        Returns:
            Dict with transformed quote data matching expected format:
            {
                "quote": {
                    "quotes": {
                        ticker: {
                            "bp": bid_price,
                            "ap": ask_price,
                            ...
                        }
                    }
                }
            }
            or None if all retries fail
        """
        url = f"{cls.BASE_URL}/{ticker}/quotes/latest"
        headers = {
            "accept": "application/json",
            "APCA-API-KEY-ID": cls.API_KEY_ID,
            "APCA-API-SECRET-KEY": cls.API_SECRET_KEY,
        }

        max_retries = 3
        timeout_seconds = 2

        for attempt in range(max_retries):
            try:
                timeout = aiohttp.ClientTimeout(total=timeout_seconds)
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.get(url, headers=headers) as response:
                        if response.status == 200:
                            data = await response.json()
                            
                            # Transform Alpaca response to match expected format
                            # Alpaca returns: {"quote": {...}, "symbol": "AAPL"}
                            # Expected format: {"quote": {"quotes": {ticker: {...}}}}
                            alpaca_quote = data.get("quote", {})
                            symbol = data.get("symbol", ticker)
                            
                            if not alpaca_quote:
                                logger.warning(
                                    f"No quote data in Alpaca response for {ticker}"
                                )
                                return None
                            
                            # Transform to expected format
                            transformed_response = {
                                "quote": {
                                    "quotes": {
                                        symbol: alpaca_quote
                                    }
                                }
                            }
                            
                            logger.debug(
                                f"Successfully retrieved quote for {ticker} from Alpaca API"
                            )
                            return transformed_response
                        else:
                            error_text = await response.text()
                            logger.warning(
                                f"Alpaca API error for {ticker}: HTTP {response.status} - {error_text[:200]}"
                            )
                            
                            # Retry on server errors (5xx)
                            if response.status >= 500 and attempt < max_retries - 1:
                                logger.info(
                                    f"Retrying Alpaca quote request for {ticker} "
                                    f"(attempt {attempt + 1}/{max_retries})"
                                )
                                await asyncio.sleep(timeout_seconds)
                                continue
                            
                            # Don't retry on client errors (4xx)
                            return None

            except asyncio.TimeoutError:
                if attempt < max_retries - 1:
                    logger.warning(
                        f"Timeout getting quote for {ticker} from Alpaca API "
                        f"(attempt {attempt + 1}/{max_retries}), retrying..."
                    )
                    await asyncio.sleep(timeout_seconds)
                    continue
                logger.error(
                    f"Timeout getting quote for {ticker} from Alpaca API after {max_retries} attempts"
                )
                return None

            except aiohttp.ClientError as e:
                if attempt < max_retries - 1:
                    logger.warning(
                        f"HTTP client error getting quote for {ticker} from Alpaca API: {e} "
                        f"(attempt {attempt + 1}/{max_retries}), retrying..."
                    )
                    await asyncio.sleep(timeout_seconds)
                    continue
                logger.exception(
                    f"HTTP client error getting quote for {ticker} from Alpaca API after {max_retries} attempts"
                )
                return None

            except Exception as e:  # pylint: disable=broad-except
                logger.exception(
                    f"Unexpected error getting quote for {ticker} from Alpaca API: {e}"
                )
                # Don't retry on unexpected errors
                return None

        return None


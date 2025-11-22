"""
Alpaca Screener Service
Fetches most active stocks and movers (gainers/losers) from Alpaca screener API
"""

# pylint: disable=import-error

import asyncio
import os
from typing import Dict, List, Set

import aiohttp

from app.src.common.loguru_logger import logger
from app.src.common.singleton import SingletonMeta

ALPACA_API_KEY = os.environ.get("REAL_TRADE_API_KEY")
ALPACA_API_SECRET = os.environ.get("REAL_TRADE_SECRET_KEY")
ALPACA_SCREENER_BASE_URL = "https://data.alpaca.markets/v1beta1/screener/stocks"


class AlpacaScreenerService(metaclass=SingletonMeta):
    """Service for fetching screened stocks from Alpaca"""

    def __init__(self):
        """Initialize Alpaca Screener Service"""
        # Screener API may work without auth for public endpoints, but include if available
        self._headers = {"accept": "application/json"}
        if ALPACA_API_KEY and ALPACA_API_SECRET:
            self._headers["APCA-API-KEY-ID"] = ALPACA_API_KEY
            self._headers["APCA-API-SECRET-KEY"] = ALPACA_API_SECRET
            logger.debug("Alpaca API credentials configured for screener service")
        else:
            logger.warning("⚠️  Alpaca API credentials not found - screener API calls may fail")
        self._screener_max_tickers = 100

        # Shared cache for screened tickers (updated every 10 seconds)
        self._cached_screened_tickers: Dict[str, Set[str]] = {
            "most_actives": set(),
            "gainers": set(),
            "losers": set(),
            "all": set(),
        }
        self._cache_lock = asyncio.Lock()
        self._running = False
        self._update_task = None
        self._update_interval = 10  # Update every 10 seconds

    async def get_most_actives(self, top: int = 10, by: str = "volume") -> List[str]:
        """
        Get most active stocks by volume or trade count

        Args:
            top: Number of top stocks to return
            by: "volume" or "trade_count"

        Returns:
            List of ticker symbols
        """
        try:
            url = f"{ALPACA_SCREENER_BASE_URL}/most-actives"
            params = {
                "by": by,
                "top": top,
            }

            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url,
                    headers=self._headers,
                    params=params,
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        most_actives = data.get("most_actives", [])
                        tickers = [
                            item.get("symbol", "").upper()  # noqa: E501
                            for item in most_actives
                            if item.get("symbol")  # noqa: E501
                        ]
                        logger.debug(
                            f"Fetched {len(tickers)} most active tickers from Alpaca screener"  # noqa: E501  # pylint: disable=line-too-long
                        )
                        return tickers
                    logger.warning(f"Alpaca screener API returned status {response.status}")
                    return []
        except Exception as e:
            logger.error(f"Error fetching most active stocks: {str(e)}", exc_info=True)
            return []

    async def get_movers(self, top: int = 10) -> Dict[str, List[str]]:
        """
        Get top gainers and losers

        Args:
            top: Number of top stocks to return per category

        Returns:
            Dict with "gainers" and "losers" lists of ticker symbols
        """
        try:
            url = f"{ALPACA_SCREENER_BASE_URL}/movers"
            params = {"top": top}

            logger.debug(
                f"Fetching movers from {url} with params {params} "
                f"and headers {list(self._headers.keys())}"  # pylint: disable=line-too-long
            )

            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url,
                    headers=self._headers,
                    params=params,
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as response:
                    logger.debug(f"Movers API response status: {response.status}")

                    if response.status == 200:
                        try:
                            data = await response.json()
                        except Exception as json_error:
                            response_text = await response.text()
                            error_msg = f"Failed to parse JSON response: {json_error}."
                            logger.error(f"{error_msg} Response text: {response_text[:500]}")
                            return {"gainers": [], "losers": []}

                        logger.debug(f"Parsed JSON data keys: {list(data.keys())}")

                        gainers_raw = data.get("gainers", [])
                        losers_raw = data.get("losers", [])

                        logger.debug(
                            f"Raw data: {len(gainers_raw)} gainers, {len(losers_raw)} losers. "
                            f"Sample gainer: {gainers_raw[0] if gainers_raw else 'N/A'}, "
                            f"Sample loser: {losers_raw[0] if losers_raw else 'N/A'}"
                        )

                        gainers = [
                            item.get("symbol", "").upper()  # noqa: E501
                            for item in gainers_raw
                            if item.get("symbol")  # noqa: E501
                        ]
                        losers = [
                            item.get("symbol", "").upper()  # noqa: E501
                            for item in losers_raw
                            if item.get("symbol")  # noqa: E501
                        ]

                        logger.debug(
                            f"Fetched {len(gainers)} gainers and {len(losers)} losers "
                            f"from Alpaca screener (raw: {len(gainers_raw)} gainers, "
                            f"{len(losers_raw)} losers)"
                        )

                        if len(gainers) == 0 and len(gainers_raw) > 0:
                            logger.warning(
                                f"⚠️  Parsed 0 gainers from {len(gainers_raw)} raw items. "
                                f"Sample raw data: {gainers_raw[:2] if gainers_raw else 'N/A'}"
                            )
                        if len(losers) == 0 and len(losers_raw) > 0:
                            logger.warning(
                                f"⚠️  Parsed 0 losers from {len(losers_raw)} raw items. "
                                f"Sample raw data: {losers_raw[:2] if losers_raw else 'N/A'}"
                            )

                        return {
                            "gainers": gainers,
                            "losers": losers,
                        }

                    response_text = await response.text()
                    status_msg = f"Alpaca screener API returned status {response.status}:"
                    logger.warning(f"{status_msg} {response_text[:500]}")
                    return {"gainers": [], "losers": []}
        except Exception as e:
            logger.error(f"Error fetching movers: {str(e)}", exc_info=True)
            return {"gainers": [], "losers": []}

    async def _update_cache(self):
        """Update the cached screened tickers by fetching from API"""
        try:
            logger.debug("Fetching screener data from Alpaca API...")
            # Alpaca API limits: most_actives can be up to 100,
            # but movers (gainers/losers) max is 50
            most_actives = await self.get_most_actives(top=self._screener_max_tickers)
            movers_top = min(50, self._screener_max_tickers)  # Movers endpoint max is 50
            movers = await self.get_movers(top=movers_top)

            gainers = movers.get("gainers", [])
            losers = movers.get("losers", [])
            all_screened = set(most_actives) | set(gainers) | set(losers)

            async with self._cache_lock:
                self._cached_screened_tickers = {
                    "most_actives": set(most_actives),
                    "gainers": set(gainers),
                    "losers": set(losers),
                    "all": all_screened,
                }

            if len(all_screened) == 0:
                logger.warning(
                    f"⚠️  Screener cache update returned empty results: "
                    f"{len(most_actives)} most actives, {len(gainers)} gainers, "
                    f"{len(losers)} losers. "
                    f"This might indicate the market is closed or API issue."
                )
            else:
                logger.info(
                    f"✅ Updated screener cache: {len(most_actives)} most actives, "
                    f"{len(gainers)} gainers, {len(losers)} losers "
                    f"(total unique: {len(all_screened)})"
                )
        except Exception as e:
            logger.error(f"Error updating screener cache: {str(e)}", exc_info=True)

    async def _background_cache_updater(self):
        """Background task that updates the cache every 10 seconds"""
        while self._running:
            try:
                await self._update_cache()
                await asyncio.sleep(self._update_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in background cache updater: {str(e)}", exc_info=True)
                await asyncio.sleep(self._update_interval)

    async def start_background_updates(self):
        """Start the background task that updates the cache every 10 seconds"""
        if self._running:
            logger.debug("Background cache updater already running")
            return

        self._running = True
        # Initial cache update
        await self._update_cache()
        # Start background task
        self._update_task = asyncio.create_task(self._background_cache_updater())
        logger.info("🚀 Started background screener cache updater (updates every 10 seconds)")

    async def stop_background_updates(self):
        """Stop the background cache updater"""
        if not self._running:
            return

        self._running = False
        if self._update_task:
            self._update_task.cancel()
            try:
                await self._update_task
            except asyncio.CancelledError:
                pass
        logger.info("Stopped background screener cache updater")

    async def get_all_screened_tickers(self) -> Dict[str, Set[str]]:
        """
        Get all screened tickers (most actives, gainers, losers) from cache

        Returns cached data that is updated every 10 seconds by background task.
        If cache is empty, triggers an immediate update before returning.

        Returns:
            Dict with:
                - most_actives: Set of ticker symbols
                - gainers: Set of ticker symbols
                - losers: Set of ticker symbols
                - all: Combined set of all screened tickers
        """
        async with self._cache_lock:
            cache_empty = (
                len(self._cached_screened_tickers["all"]) == 0
                and len(self._cached_screened_tickers["most_actives"]) == 0
                and len(self._cached_screened_tickers["gainers"]) == 0
                and len(self._cached_screened_tickers["losers"]) == 0
            )

        # If cache is empty, trigger an immediate update
        if cache_empty:
            logger.info("Cache is empty, triggering immediate screener data fetch...")
            await self._update_cache()

        async with self._cache_lock:
            # Return a copy of the cached data
            return {
                "most_actives": self._cached_screened_tickers["most_actives"].copy(),
                "gainers": self._cached_screened_tickers["gainers"].copy(),
                "losers": self._cached_screened_tickers["losers"].copy(),
                "all": self._cached_screened_tickers["all"].copy(),
            }

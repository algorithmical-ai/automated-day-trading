"""
Screener Monitor Service
Monitors Alpaca screener for movers and most actives, and adds new tickers to InactiveTickers
"""

import asyncio
from typing import Set

from app.src.common.loguru_logger import logger
from app.src.common.singleton import SingletonMeta
from app.src.common.utils import measure_latency
from app.src.db.dynamodb_client import DynamoDBClient
from app.src.services.candidate_generator.alpaca_screener import AlpacaScreenerService
from app.src.services.mcp.mcp_client import MCPClient


class ScreenerMonitorService(metaclass=SingletonMeta):
    """Service to monitor Alpaca screener and add new tickers to InactiveTickers"""

    def __init__(self):
        """Initialize ScreenerMonitorService"""
        self._screener = AlpacaScreenerService()
        self._dynamodb = DynamoDBClient()
        self._running = False
        self._check_interval = 60  # Check every 60 seconds (1 minute)

    @measure_latency
    async def _check_and_add_tickers(self):
        """
        Check Alpaca screener for movers and most actives,
        and add any missing tickers to InactiveTickers
        """
        try:
            # Get movers and most actives from Alpaca screener
            most_actives = await self._screener.get_most_actives(top=10)
            movers = await self._screener.get_movers(top=10)

            # Combine all tickers
            all_screened_tickers: Set[str] = set()
            all_screened_tickers.update(most_actives)
            all_screened_tickers.update(movers.get("gainers", []))
            all_screened_tickers.update(movers.get("losers", []))

            if not all_screened_tickers:
                logger.debug("No tickers found in Alpaca screener")
                return

            logger.debug(
                f"Checking {len(all_screened_tickers)} screened tickers "
                f"({len(most_actives)} most actives, "
                f"{len(movers.get('gainers', []))} gainers, "
                f"{len(movers.get('losers', []))} losers)"
            )

            # Check each ticker and add if not present in InactiveTickers
            added_count = 0
            existing_count = 0

            # Convert lists to sets for O(1) membership checks
            most_actives_set = set(most_actives)
            gainers_set = set(movers.get("gainers", []))
            losers_set = set(movers.get("losers", []))

            for ticker in all_screened_tickers:
                if not ticker or not ticker.strip():
                    continue

                ticker_upper = ticker.upper()

                # Check if ticker exists in InactiveTickers
                exists = await self._dynamodb.ticker_exists_in_inactive(ticker_upper)

                if not exists:
                    # Add ticker to InactiveTickers
                    categories = []
                    if ticker_upper in most_actives_set:
                        categories.append("most_actives")
                    if ticker_upper in gainers_set:
                        categories.append("gainers")
                    if ticker_upper in losers_set:
                        categories.append("losers")

                    reason = f"Auto-added from Alpaca screener: {', '.join(categories) if categories else 'screener'}"

                    success = await self._dynamodb.add_ticker_to_inactive(
                        ticker_upper, reason
                    )

                    if success:
                        added_count += 1
                        logger.info(
                            f"✅ Added new ticker {ticker_upper} to InactiveTickers "
                            f"(will be picked up by DynamoDB polling)"
                        )
                else:
                    existing_count += 1

            if added_count > 0:
                logger.info(
                    f"📊 Screener monitor: Added {added_count} new ticker(s) to InactiveTickers, "
                    f"{existing_count} already existed"
                )
            elif existing_count > 0:
                logger.debug(
                    f"📊 Screener monitor: All {existing_count} ticker(s) already in InactiveTickers"
                )

        except Exception as e:
            logger.error(f"Error in screener monitor check: {str(e)}", exc_info=True)

    @measure_latency
    async def start(self):
        """Start the screener monitor service"""
        if self._running:
            logger.warning("ScreenerMonitorService already running")
            return

        logger.info("Starting ScreenerMonitorService...")
        self._running = True

        # Initial check
        await self._check_and_add_tickers()

        # Periodic checks
        while self._running:
            try:
                await asyncio.sleep(self._check_interval)

                if not self._running:
                    break

                # Check market open status
                try:
                    clock_response = await MCPClient.get_market_clock()
                    if clock_response:
                        clock = clock_response.get("clock", {})
                        is_open = clock.get("is_open", False)
                        if not is_open:
                            next_open = clock.get("next_open")
                            logger.debug(
                                f"⏸️  Market closed. Skipping screener monitor check. Next open: {next_open}"
                            )
                            continue
                except Exception as e:
                    logger.warning(
                        f"Could not retrieve market clock, proceeding cautiously: {e}"
                    )

                await self._check_and_add_tickers()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(
                    f"Error in screener monitor service loop: {str(e)}", exc_info=True
                )
                await asyncio.sleep(self._check_interval)

    async def stop(self):
        """Stop the screener monitor service"""
        logger.info("Stopping ScreenerMonitorService...")
        self._running = False

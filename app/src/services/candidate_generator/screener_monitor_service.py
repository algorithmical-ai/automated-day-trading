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
        self._top_n = 50  # Check top 50 from each category (increased from 10)

    @measure_latency
    async def _check_and_add_tickers(self):
        """
        Check Alpaca screener for movers and most actives,
        and add any missing tickers to InactiveTickers
        """
        try:
            # Get movers and most actives from Alpaca screener
            logger.debug(f"Fetching top {self._top_n} from each screener category...")
            most_actives = await self._screener.get_most_actives(top=self._top_n)
            movers = await self._screener.get_movers(top=self._top_n)

            # Combine all tickers
            all_screened_tickers: Set[str] = set()
            all_screened_tickers.update(most_actives)
            all_screened_tickers.update(movers.get("gainers", []))
            all_screened_tickers.update(movers.get("losers", []))

            if not all_screened_tickers:
                logger.warning("⚠️  No tickers found in Alpaca screener - API may be down or market closed")
                return

            logger.info(
                f"📊 Screener monitor: Checking {len(all_screened_tickers)} unique screened tickers "
                f"({len(most_actives)} most actives, "
                f"{len(movers.get('gainers', []))} gainers, "
                f"{len(movers.get('losers', []))} losers)"
            )

            # Convert to list and filter empty tickers
            ticker_list = [t.upper() for t in all_screened_tickers if t and t.strip()]
            
            if not ticker_list:
                logger.warning("⚠️  No valid tickers after filtering")
                return

            # Batch check all tickers in parallel
            logger.debug(f"Batch checking existence of {len(ticker_list)} tickers in InactiveTickers...")
            existence_map = await self._dynamodb.batch_check_tickers_exist_in_inactive(ticker_list)

            # Convert lists to sets for O(1) membership checks
            most_actives_set = set(most_actives)
            gainers_set = set(movers.get("gainers", []))
            losers_set = set(movers.get("losers", []))

            # Prepare tickers to add (those that don't exist)
            tickers_to_add = []
            added_count = 0
            existing_count = 0

            for ticker_upper in ticker_list:
                exists = existence_map.get(ticker_upper, False)
                
                if not exists:
                    # Prepare to add ticker
                    categories = []
                    if ticker_upper in most_actives_set:
                        categories.append("most_actives")
                    if ticker_upper in gainers_set:
                        categories.append("gainers")
                    if ticker_upper in losers_set:
                        categories.append("losers")

                    reason = f"Auto-added from Alpaca screener: {', '.join(categories) if categories else 'screener'}"
                    tickers_to_add.append((ticker_upper, reason))
                else:
                    existing_count += 1

            # Add all new tickers in parallel
            if tickers_to_add:
                logger.debug(f"Adding {len(tickers_to_add)} new ticker(s) to InactiveTickers...")
                add_tasks = [
                    self._dynamodb.add_ticker_to_inactive(ticker, reason)
                    for ticker, reason in tickers_to_add
                ]
                add_results = await asyncio.gather(*add_tasks, return_exceptions=True)
                
                for (ticker_upper, reason), success in zip(tickers_to_add, add_results):
                    if isinstance(success, Exception):
                        logger.error(f"Error adding ticker {ticker_upper}: {success}")
                    elif success:
                        added_count += 1
                        logger.info(
                            f"✅ Added new ticker {ticker_upper} to InactiveTickers "
                            f"(will be picked up by DynamoDB polling)"
                        )

            if added_count > 0:
                logger.info(
                    f"📊 Screener monitor: Added {added_count} new ticker(s) to InactiveTickers, "
                    f"{existing_count} already existed (checked {len(ticker_list)} total)"
                )
            elif existing_count > 0:
                logger.info(
                    f"📊 Screener monitor: All {existing_count} ticker(s) already in InactiveTickers "
                    f"(checked {len(ticker_list)} total)"
                )
            else:
                logger.warning(f"⚠️  Screener monitor: No valid tickers to process")

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

        # Initial check (only if market is open)
        try:
            clock_response = await MCPClient.get_market_clock()
            if clock_response:
                clock = clock_response.get("clock", {})
                is_open = clock.get("is_open", False)
                if is_open:
                    await self._check_and_add_tickers()
                else:
                    next_open = clock.get("next_open")
                    logger.info(
                        f"⏸️  Market closed. Skipping initial screener check. Next open: {next_open}"
                    )
        except Exception as e:
            logger.warning(
                f"Could not retrieve market clock for initial check, proceeding cautiously: {e}"
            )
            # Proceed with initial check if we can't determine market status
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

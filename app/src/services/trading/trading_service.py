"""
Trading Service Coordinator
Manages multiple trading indicators running concurrently with error isolation
"""

import asyncio
import os
from typing import List, Tuple, Any
from app.src.common.loguru_logger import logger
from app.src.common.memory_monitor import MemoryMonitor
from app.src.services.trading.momentum_indicator import MomentumIndicator
from app.src.services.trading.deep_analyzer_indicator import DeepAnalyzerIndicator
from app.src.services.trading.uw_enhanced_momentum_indicator import UWEnhancedMomentumIndicator
from app.src.services.trading.penny_stocks_indicator import PennyStocksIndicator


class TradingServiceCoordinator:
    """
    Trading Service Coordinator
    Manages all trading indicators (Momentum, Penny Stocks, Deep Analyzer, UW-Enhanced) 
    running concurrently with error isolation and graceful shutdown handling.
    
    Requirements: 1.1, 1.2, 1.3, 1.5
    """

    _enabled_indicators: List[str] = []

    @classmethod
    def configure(
        cls,
        *,
        top_k: int = 10,  # noqa: ARG002
    ):
        """
        Configure dependencies and runtime parameters for all indicators.
        
        Supports disabling indicators via environment variables:
        - ENABLE_MOMENTUM_INDICATOR (default: true)
        - ENABLE_PENNY_STOCKS_INDICATOR (default: true)
        - ENABLE_DEEP_ANALYZER_INDICATOR (default: true)
        - ENABLE_UW_ENHANCED_INDICATOR (default: true)
        """

        # Determine which indicators are enabled via environment variables
        # Requirement 1.5: WHERE a Trading Indicator is disabled, THEN exclude from execution
        cls._enabled_indicators = []
        
        enable_momentum = os.getenv("ENABLE_MOMENTUM_INDICATOR", "false").lower() == "true"  # DISABLED: unprofitable in backtesting, penny stocks covers <$5 universe
        enable_penny_stocks = os.getenv("ENABLE_PENNY_STOCKS_INDICATOR", "true").lower() == "true"
        enable_deep_analyzer = os.getenv("ENABLE_DEEP_ANALYZER_INDICATOR", "true").lower() == "true"
        enable_uw_enhanced = os.getenv("ENABLE_UW_ENHANCED_INDICATOR", "true").lower() == "true"

        # Configure enabled indicators
        if enable_momentum:
            MomentumIndicator.configure()
            cls._enabled_indicators.append("Momentum Trading Indicator")
            logger.info("Momentum Trading Indicator enabled")
        else:
            logger.info("Momentum Trading Indicator disabled via configuration")

        if enable_penny_stocks:
            PennyStocksIndicator.configure()
            cls._enabled_indicators.append("Penny Stocks Indicator")
            logger.info("Penny Stocks Indicator enabled")
        else:
            logger.info("Penny Stocks Indicator disabled via configuration")

        if enable_deep_analyzer:
            DeepAnalyzerIndicator.configure()
            cls._enabled_indicators.append("Deep Analyzer Indicator")
            logger.info("Deep Analyzer Indicator enabled")
        else:
            logger.info("Deep Analyzer Indicator disabled via configuration")

        if enable_uw_enhanced:
            UWEnhancedMomentumIndicator.configure()
            cls._enabled_indicators.append("UW-Enhanced Momentum Indicator")
            logger.info("UW-Enhanced Momentum Indicator enabled")
        else:
            logger.info("UW-Enhanced Momentum Indicator disabled via configuration")

        # Configure shared services
        from app.src.db.dynamodb_client import DynamoDBClient
        from app.src.services.mab.mab_service import MABService

        DynamoDBClient.configure()
        MABService.configure()

        logger.info(f"Trading Service Coordinator configured with {len(cls._enabled_indicators)} enabled indicators")

    @classmethod
    def stop(cls):
        """
        Stop all trading indicators gracefully.
        Requirement 1.3: Gracefully stop all Trading Indicators and clean up resources
        """
        logger.info("Stopping all trading indicators...")
        
        # Stop all indicators regardless of enabled status (in case they were running)
        MomentumIndicator.stop()
        PennyStocksIndicator.stop()
        DeepAnalyzerIndicator.stop()
        UWEnhancedMomentumIndicator.stop()
        
        logger.info("All trading indicators stopped")

    @classmethod
    async def run(cls):
        """
        Run all enabled indicators concurrently with error isolation and graceful shutdown handling.
        
        Requirements:
        - 1.1: Initialize and run all indicators concurrently
        - 1.2: Error isolation - one indicator's failure doesn't stop others
        - 1.3: Graceful shutdown handling
        - 1.5: Exclude disabled indicators from execution
        """
        if not cls._enabled_indicators:
            logger.warning("No trading indicators are enabled. Nothing to run.")
            return

        logger.info("Starting Trading Service Coordinator with enabled indicators:")
        for indicator_name in cls._enabled_indicators:
            logger.info(f"  - {indicator_name}")

        # BASIC DYNO (512MB): Long stagger delay between indicators
        # Each indicator starts with a delay to avoid simultaneous memory spikes
        stagger_delay = int(os.getenv("INDICATOR_STAGGER_DELAY_SECONDS", "30"))
        
        async def run_with_delay(name: str, coro, delay: int):
            """Run a coroutine after a delay"""
            if delay > 0:
                logger.info(f"⏳ {name} will start in {delay} seconds...")
                await asyncio.sleep(delay)
            logger.info(f"🚀 Starting {name}")
            return await coro
        
        # Build list of indicator tasks based on what's enabled
        # Stagger each indicator by stagger_delay seconds
        tasks: List[Tuple[str, Any]] = []
        current_delay = 0
        
        if "Momentum Trading Indicator" in cls._enabled_indicators:
            tasks.append(("Momentum Trading Indicator", 
                         run_with_delay("Momentum Trading Indicator", MomentumIndicator.run(), current_delay)))
            current_delay += stagger_delay
        
        if "Penny Stocks Indicator" in cls._enabled_indicators:
            tasks.append(("Penny Stocks Indicator", 
                         run_with_delay("Penny Stocks Indicator", PennyStocksIndicator.run(), current_delay)))
            current_delay += stagger_delay
        
        if "Deep Analyzer Indicator" in cls._enabled_indicators:
            tasks.append(("Deep Analyzer Indicator", 
                         run_with_delay("Deep Analyzer Indicator", DeepAnalyzerIndicator.run(), current_delay)))
            current_delay += stagger_delay
        
        if "UW-Enhanced Momentum Indicator" in cls._enabled_indicators:
            tasks.append(("UW-Enhanced Momentum Indicator", 
                         run_with_delay("UW-Enhanced Momentum Indicator", UWEnhancedMomentumIndicator.run(), current_delay)))

        # Add periodic memory monitoring task
        async def periodic_memory_monitor():
            """Periodically log memory usage every 5 minutes"""
            while True:
                await asyncio.sleep(300)  # 5 minutes
                MemoryMonitor.log_memory_usage(
                    "Trading Service Coordinator (Periodic)",
                    level="INFO"
                )
                # Check memory threshold and warn if high
                MemoryMonitor.check_memory_threshold(
                    threshold_mb=400.0,
                    context="Trading Service Coordinator",
                    action="WARNING"
                )
        
        tasks.append(("Memory Monitor", periodic_memory_monitor()))

        # Run all enabled indicators concurrently with error isolation
        # Requirement 1.2: Using return_exceptions=True to capture exceptions without stopping others
        indicator_names = [name for name, _ in tasks]
        indicator_tasks = [task for _, task in tasks]
        
        results = await asyncio.gather(
            *indicator_tasks,
            return_exceptions=True,
        )
        
        # Check for exceptions and log them
        # Requirement 1.2: Continue operating other indicators when one encounters an error
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error(
                    f"{indicator_names[i]} crashed with exception: {type(result).__name__}: {result}",
                    exc_info=result,
                )
            elif result is not None:
                logger.warning(
                    f"{indicator_names[i]} returned unexpected result: {result}"
                )
        
        logger.info("All trading indicators have completed")


# Maintain backward compatibility with old class name
TradingService = TradingServiceCoordinator


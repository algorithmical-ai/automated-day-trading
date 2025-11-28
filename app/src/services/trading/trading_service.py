"""
Trading Service Coordinator
Manages multiple trading indicators running concurrently
"""

import asyncio
from typing import Optional
from app.src.common.loguru_logger import logger
from app.src.services.tool_discovery.tool_discovery import ToolDiscoveryService
from app.src.services.trading.momentum_indicator import MomentumIndicator
from app.src.services.trading.deep_analyzer_indicator import DeepAnalyzerIndicator
from app.src.services.trading.uw_enhanced_momentum_indicator import UWEnhancedMomentumIndicator


class TradingService:
    """
    Trading Service Coordinator
    Manages Momentum Trading, Deep Analyzer, and UW-Enhanced Momentum indicators running concurrently
    """

    tool_discovery_cls: Optional[type] = ToolDiscoveryService

    @classmethod
    def configure(
        cls,
        *,
        tool_discovery_cls: Optional[type] = ToolDiscoveryService,
        top_k: int = 10,  # noqa: ARG002
    ):
        """Configure dependencies and runtime parameters for all indicators"""
        if tool_discovery_cls is not None:
            cls.tool_discovery_cls = tool_discovery_cls

        # Configure all indicators
        MomentumIndicator.configure()
        DeepAnalyzerIndicator.configure()
        UWEnhancedMomentumIndicator.configure()

        # Configure MCP client (shared by both indicators)
        from app.src.services.mcp.mcp_client import MCPClient

        MCPClient.configure(tool_discovery_cls=tool_discovery_cls)

        # Configure shared services
        from app.src.db.dynamodb_client import DynamoDBClient
        from app.src.services.mab.mab_service import MABService

        DynamoDBClient.configure()
        MABService.configure()

        logger.info("Trading Service Coordinator configured with all indicators")

    @classmethod
    def stop(cls):
        """Stop all trading indicators"""
        MomentumIndicator.stop()
        DeepAnalyzerIndicator.stop()
        UWEnhancedMomentumIndicator.stop()
        logger.info("All trading indicators stopped")

    @classmethod
    async def run(cls):
        """Run all indicators concurrently"""
        logger.info("Starting Trading Service Coordinator with all indicators...")
        logger.info("- Momentum Trading Indicator")
        logger.info("- Deep Analyzer Indicator")
        logger.info("- UW-Enhanced Momentum Indicator (with Unusual Whales & Volatility)")

        # Run all indicators concurrently
        # Each indicator runs its own entry_service and exit_service concurrently
        await asyncio.gather(
            MomentumIndicator.run(),
            DeepAnalyzerIndicator.run(),
            UWEnhancedMomentumIndicator.run(),
        )


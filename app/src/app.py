"""
Automated Day Trading Application
Main entry point for the Heroku worker process
"""

import asyncio
import signal
import sys
from app.src.common.loguru_logger import logger
from app.src.services.trading.trading_service import TradingService
from app.src.services.tool_discovery.tool_discovery import ToolDiscoveryService
from app.src.services.candidate_generator.screener_monitor_service import (
    ScreenerMonitorService,
)
from app.src.services.threshold_adjustment.threshold_adjustment_service import (
    ThresholdAdjustmentService,
)
from app.src.config.constants import MOMENTUM_TOP_K, MCP_SERVER_TRANSPORT
from app.src.services.mcp.server import main as mcp_server_main


def setup_signal_handlers():
    """Setup signal handlers for graceful shutdown"""

    def signal_handler(sig, frame):
        logger.info("Received shutdown signal, stopping services...")
        TradingService.stop()
        ToolDiscoveryService.stop()
        ScreenerMonitorService().stop()
        ThresholdAdjustmentService.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)


async def _run_mcp_server():
    """Start the MCP server in the background"""
    try:
        logger.info("Starting MCP server...")
        await mcp_server_main()
    except asyncio.CancelledError:
        logger.info("MCP server task cancelled")
        raise
    except Exception as e:
        logger.exception(f"Error in MCP server: {str(e)}")


async def main():
    """Main application entry point"""
    logger.info("Initializing Automated Day Trading Application...")

    # Initialize tool discovery service
    ToolDiscoveryService.configure(refresh_interval=300)

    # Initialize momentum trading service with tool discovery and top_k configuration
    TradingService.configure(
        tool_discovery_cls=ToolDiscoveryService, top_k=MOMENTUM_TOP_K
    )

    # Setup signal handlers
    setup_signal_handlers()

    # MCP server is now running as a separate web process on Heroku
    # Only start MCP server in worker if explicitly needed (e.g., for local development)
    # For Heroku, the web process handles MCP server via app.src.web
    start_mcp_server = False  # Disabled - web process handles MCP server

    try:
        # Prepare tasks list
        tasks = [
            ToolDiscoveryService.discovery_job(),
            TradingService.run(),
            ScreenerMonitorService().start(),
            ThresholdAdjustmentService.start()
        ]

        # Add MCP server task if applicable (typically only for local dev)
        if start_mcp_server:
            tasks.append(_run_mcp_server())
            logger.info(f"MCP server will start with transport: {MCP_SERVER_TRANSPORT}")
        else:
            logger.info("MCP server is running as separate web process (not in worker)")

        # Run all services concurrently
        await asyncio.gather(*tasks)
    except Exception as e:
        logger.exception(f"Fatal error in application: {str(e)}")
        ToolDiscoveryService.stop()
        TradingService.stop()
        ScreenerMonitorService().stop()
        ThresholdAdjustmentService.stop()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())

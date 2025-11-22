"""
Automated Day Trading Application
Main entry point for the Heroku worker process
"""

import asyncio
import signal
import sys
from app.src.common.loguru_logger import logger
from app.src.services.momentum.momentum_trading_service import MomentumTradingService
from app.src.services.tool_discovery.tool_discovery import ToolDiscoveryService
from app.src.config.constants import MOMENTUM_TOP_K, MCP_SERVER_TRANSPORT
from app.src.services.mcp.server import main as mcp_server_main


def setup_signal_handlers():
    """Setup signal handlers for graceful shutdown"""

    def signal_handler(sig, frame):
        logger.info("Received shutdown signal, stopping services...")
        MomentumTradingService.stop()
        ToolDiscoveryService.stop()
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
    MomentumTradingService.configure(
        tool_discovery_cls=ToolDiscoveryService, top_k=MOMENTUM_TOP_K
    )

    # Setup signal handlers
    setup_signal_handlers()

    # Check if MCP server should be started
    # Only start MCP server if transport is not stdio (which needs stdin/stdout)
    start_mcp_server = MCP_SERVER_TRANSPORT in ("sse", "streamable-http")
    
    try:
        # Prepare tasks list
        tasks = [
            ToolDiscoveryService.discovery_job(),
            MomentumTradingService.run(),
        ]
        
        # Add MCP server task if applicable
        if start_mcp_server:
            tasks.append(_run_mcp_server())
            logger.info(f"MCP server will start with transport: {MCP_SERVER_TRANSPORT}")
        
        # Run all services concurrently
        await asyncio.gather(*tasks)
    except Exception as e:
        logger.exception(f"Fatal error in application: {str(e)}")
        ToolDiscoveryService.stop()
        MomentumTradingService.stop()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())

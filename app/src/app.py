"""
Automated Day Trading Application
Main entry point for the Heroku worker process
"""
import asyncio
import signal
import sys
from loguru_logger import logger
from trading_service import TradingService
from momentum_trading_service import MomentumTradingService
from tool_discovery import ToolDiscoveryService
from constants import MOMENTUM_TOP_K


# Global references for signal handlers
trading_service = None
momentum_trading_service = None
tool_discovery_service = None


def setup_signal_handlers(
    trading_svc: TradingService,
    momentum_svc: MomentumTradingService,
    discovery_svc: ToolDiscoveryService
):
    """Setup signal handlers for graceful shutdown"""
    def signal_handler(sig, frame):
        logger.info("Received shutdown signal, stopping services...")
        trading_svc.stop()
        momentum_svc.stop()
        discovery_svc.stop()
        sys.exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)


async def main():
    """Main application entry point"""
    global trading_service, momentum_trading_service, tool_discovery_service
    
    logger.info("Initializing Automated Day Trading Application...")
    
    # Initialize tool discovery service
    tool_discovery_service = ToolDiscoveryService(refresh_interval=300)  # Refresh every 5 minutes
    
    # Initialize trading service with tool discovery
    trading_service = TradingService(tool_discovery=tool_discovery_service)
    
    # Initialize momentum trading service with tool discovery and top_k configuration
    momentum_trading_service = MomentumTradingService(
        tool_discovery=tool_discovery_service,
        top_k=MOMENTUM_TOP_K
    )
    
    # Setup signal handlers
    setup_signal_handlers(trading_service, momentum_trading_service, tool_discovery_service)
    
    try:
        # Run all services concurrently
        await asyncio.gather(
            tool_discovery_service.discovery_job(),
            # trading_service.run(),
            momentum_trading_service.run()
        )
    except Exception as e:
        logger.exception(f"Fatal error in application: {str(e)}")
        if tool_discovery_service:
            tool_discovery_service.stop()
        if trading_service:
            trading_service.stop()
        if momentum_trading_service:
            momentum_trading_service.stop()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())


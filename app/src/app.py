"""
Automated Day Trading Application
Main entry point for the trading application

Requirements: 1.1, 1.3, 20.2, 20.5
"""

import asyncio
import signal
from app.src.common.loguru_logger import logger
from app.src.common.logging_utils import log_operation, log_error_with_context
from app.src.services.trading.trading_service import TradingServiceCoordinator
from app.src.services.threshold_adjustment.threshold_adjustment_service import (
    ThresholdAdjustmentService,
)

# Global flag for graceful shutdown
_shutdown_event: asyncio.Event = None


def setup_signal_handlers():
    """
    Setup signal handlers for graceful shutdown (SIGINT, SIGTERM)
    Requirement 1.3: Gracefully stop all Trading Indicators and clean up resources
    """

    def signal_handler(sig, frame):
        logger.info(f"Received shutdown signal ({signal.Signals(sig).name}), initiating graceful shutdown...")
        if _shutdown_event:
            _shutdown_event.set()

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)


async def main():
    """
    Main application entry point
    
    Requirements:
    - 1.1: Initialize and run Trading Service Coordinator, Tool Discovery, Threshold Adjustment
    - 1.3: Graceful shutdown handling
    - 20.2: Resource cleanup on stop
    - 20.5: Graceful connection closure and resource release
    """
    global _shutdown_event
    _shutdown_event = asyncio.Event()
    
    logger.info("=" * 80)
    logger.info("Automated Day Trading Application Starting")
    logger.info("=" * 80)

    # Configure services
    log_operation(
        operation_type="service_configuration",
        component="MainApplication",
        status="started"
    )
    
    # Configure Trading Service Coordinator with all indicators
    TradingServiceCoordinator.configure()
    
    log_operation(
        operation_type="service_configuration",
        component="MainApplication",
        status="completed",
        details={
            "services": ["TradingServiceCoordinator", "ThresholdAdjustmentService"]
        }
    )

    # Setup signal handlers for graceful shutdown
    setup_signal_handlers()

    try:
        # Requirement 1.1: Run all services concurrently
        # Using return_exceptions=True for error isolation (Requirement 1.2)
        logger.info("Starting concurrent service execution...")
        logger.info("  - Trading Service Coordinator")
        logger.info("  - Threshold Adjustment Service")
        
        # Create service tasks
        tasks = [
            asyncio.create_task(TradingServiceCoordinator.run(), name="TradingCoordinator"),
            asyncio.create_task(ThresholdAdjustmentService.start(), name="ThresholdAdjustment"),
        ]
        
        # Wait for either all tasks to complete or shutdown signal
        done, pending = await asyncio.wait(
            tasks + [asyncio.create_task(_shutdown_event.wait(), name="ShutdownEvent")],
            return_when=asyncio.FIRST_COMPLETED
        )
        
        # If shutdown was triggered, cancel remaining tasks
        if _shutdown_event.is_set():
            logger.info("Shutdown signal received, cancelling running tasks...")
            for task in pending:
                if not task.done():
                    task.cancel()
            
            # Wait for all tasks to complete cancellation
            await asyncio.gather(*pending, return_exceptions=True)
        
        # Check for exceptions in completed tasks
        for task in done:
            if task.get_name() != "ShutdownEvent" and not task.cancelled():
                try:
                    result = task.result()
                    if isinstance(result, Exception):
                        logger.error(f"Task {task.get_name()} failed with exception: {result}")
                except Exception as e:
                    logger.error(f"Task {task.get_name()} raised exception: {e}")
        
    except KeyboardInterrupt:
        logger.info("Received keyboard interrupt, shutting down...")
    except Exception as e:
        log_error_with_context(
            error=e,
            context="Running main application",
            component="MainApplication"
        )
    finally:
        # Requirement 20.2 & 20.5: Resource cleanup on shutdown
        logger.info("=" * 80)
        logger.info("Initiating resource cleanup...")
        logger.info("=" * 80)
        
        # Stop all services gracefully
        logger.info("Stopping Trading Service Coordinator...")
        TradingServiceCoordinator.stop()
        
        logger.info("Stopping Threshold Adjustment Service...")
        ThresholdAdjustmentService.stop()
        
        # Give services a moment to clean up
        await asyncio.sleep(1)
        
        logger.info("=" * 80)
        logger.info("All services stopped. Application shutdown complete.")
        logger.info("=" * 80)


if __name__ == "__main__":
    asyncio.run(main())

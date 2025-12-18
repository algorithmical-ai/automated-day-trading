"""
Automated Day Trading Application
Main entry point for the trading application

Requirements: 1.1, 1.3, 20.2, 20.5
"""

import asyncio
import gc
import os
import signal
from app.src.common.loguru_logger import logger
from app.src.common.logging_utils import log_operation, log_error_with_context
from app.src.common.memory_monitor import MemoryMonitor
from app.src.services.trading.trading_service import TradingServiceCoordinator
from app.src.services.threshold_adjustment.threshold_adjustment_service import (
    ThresholdAdjustmentService,
)
from app.src.services.technical_analysis.technical_analysis_lib import TechnicalAnalysisLib

# Global flag for graceful shutdown
_shutdown_event: asyncio.Event = None

# Memory management configuration
MEMORY_CLEANUP_INTERVAL_SECONDS = int(os.getenv("MEMORY_CLEANUP_INTERVAL_SECONDS", "30"))
MEMORY_WARNING_THRESHOLD_MB = float(os.getenv("MEMORY_WARNING_THRESHOLD_MB", "600"))
MEMORY_CRITICAL_THRESHOLD_MB = float(os.getenv("MEMORY_CRITICAL_THRESHOLD_MB", "800"))


def setup_signal_handlers():
    """
    Setup signal handlers for graceful shutdown (SIGINT, SIGTERM)
    Requirement 1.3: Gracefully stop all Trading Indicators and clean up resources
    """

    def signal_handler(sig, frame):
        logger.info(
            f"Received shutdown signal ({signal.Signals(sig).name}), initiating graceful shutdown..."
        )
        if _shutdown_event:
            _shutdown_event.set()

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)


async def memory_management_task():
    """
    Background task to monitor and manage memory usage.
    Periodically cleans up caches and runs garbage collection.
    """
    logger.info(f"🧹 Memory management task started (interval: {MEMORY_CLEANUP_INTERVAL_SECONDS}s)")
    
    while not _shutdown_event.is_set():
        try:
            # Wait for interval or shutdown
            try:
                await asyncio.wait_for(
                    _shutdown_event.wait(), 
                    timeout=MEMORY_CLEANUP_INTERVAL_SECONDS
                )
                # If we get here, shutdown was triggered
                break
            except asyncio.TimeoutError:
                # Normal timeout - continue with cleanup
                pass
            
            # Get current memory usage
            current_mem = MemoryMonitor.get_current_memory_mb()
            
            # Log memory status periodically
            if current_mem > MEMORY_WARNING_THRESHOLD_MB:
                logger.warning(
                    f"⚠️ Memory usage high: {current_mem:.0f}MB "
                    f"(warning: {MEMORY_WARNING_THRESHOLD_MB:.0f}MB, "
                    f"critical: {MEMORY_CRITICAL_THRESHOLD_MB:.0f}MB)"
                )
            else:
                logger.debug(f"💾 Memory usage: {current_mem:.0f}MB")
            
            # Clean up indicator cache
            expired_count = await TechnicalAnalysisLib.cleanup_cache()
            if expired_count > 0:
                logger.debug(f"🧹 Cleaned up {expired_count} expired cache entries")
            
            # Run garbage collection
            gc.collect()
            
            # Log cache stats periodically
            cache_stats = await TechnicalAnalysisLib.get_cache_stats()
            logger.debug(
                f"📊 Indicator cache: {cache_stats['size']}/{cache_stats['max_size']} entries, "
                f"hit rate: {cache_stats['hit_rate']}"
            )
            
            # If memory is critical, force clear cache
            if current_mem > MEMORY_CRITICAL_THRESHOLD_MB:
                logger.warning(
                    f"🚨 Memory critical ({current_mem:.0f}MB), clearing indicator cache"
                )
                await TechnicalAnalysisLib.clear_cache()
                gc.collect()
                new_mem = MemoryMonitor.get_current_memory_mb()
                logger.info(f"💾 Memory after cleanup: {new_mem:.0f}MB")
            
        except asyncio.CancelledError:
            logger.info("Memory management task cancelled")
            break
        except Exception as e:
            logger.error(f"Error in memory management task: {e}", exc_info=True)
            await asyncio.sleep(MEMORY_CLEANUP_INTERVAL_SECONDS)
    
    logger.info("🧹 Memory management task stopped")


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

    # Start memory monitoring
    MemoryMonitor.start_tracking()
    memory_config = MemoryMonitor.get_memory_config()
    MemoryMonitor.log_memory_usage("Application Startup", level="INFO")
    logger.info(
        f"Memory-optimized configuration: "
        f"fetch_batch={memory_config['market_data_batch_size']}, "
        f"dynamodb_batch={memory_config['dynamodb_batch_size']}"
    )

    # Configure services
    log_operation(
        operation_type="service_configuration",
        component="MainApplication",
        status="started",
    )

    # Configure Trading Service Coordinator with all indicators
    TradingServiceCoordinator.configure()

    log_operation(
        operation_type="service_configuration",
        component="MainApplication",
        status="completed",
        details={
            "services": ["TradingServiceCoordinator", "ThresholdAdjustmentService"]
        },
    )

    # Setup signal handlers for graceful shutdown
    setup_signal_handlers()

    try:
        # Requirement 1.1: Run all services concurrently
        # Using return_exceptions=True for error isolation (Requirement 1.2)
        logger.info("Starting concurrent service execution...")
        logger.info("  - Trading Service Coordinator")
        logger.info("  - Memory Management Task")

        # Create service tasks
        tasks = [
            asyncio.create_task(
                TradingServiceCoordinator.run(), name="TradingCoordinator"
            ),
            asyncio.create_task(
                memory_management_task(), name="MemoryManagement"
            ),
        ]

        # Conditionally add Threshold Adjustment Service if enabled
        if ThresholdAdjustmentService.is_enabled():
            logger.info("  - Threshold Adjustment Service (enabled)")
            tasks.append(
                asyncio.create_task(
                    ThresholdAdjustmentService.start(), name="ThresholdAdjustment"
                )
            )
        else:
            logger.info(
                "  - Threshold Adjustment Service (disabled via ENABLE_THRESHOLD_ADJUSTMENT)"
            )

        # Wait for either all tasks to complete or shutdown signal
        done, pending = await asyncio.wait(
            tasks + [asyncio.create_task(_shutdown_event.wait(), name="ShutdownEvent")],
            return_when=asyncio.FIRST_COMPLETED,
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
                        logger.error(
                            f"Task {task.get_name()} failed with exception: {result}"
                        )
                except Exception as e:
                    logger.error(f"Task {task.get_name()} raised exception: {e}")

    except KeyboardInterrupt:
        logger.info("Received keyboard interrupt, shutting down...")
    except Exception as e:
        log_error_with_context(
            error=e, context="Running main application", component="MainApplication"
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

        # Log final memory usage
        MemoryMonitor.log_memory_usage("Application Shutdown", level="INFO")
        MemoryMonitor.stop_tracking()
        
        logger.info("=" * 80)
        logger.info("All services stopped. Application shutdown complete.")
        logger.info("=" * 80)


if __name__ == "__main__":
    asyncio.run(main())

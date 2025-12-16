"""
Memory monitoring utilities for tracking and optimizing memory usage.

This module provides tools to monitor memory consumption, identify bottlenecks,
and help optimize memory usage in the trading application.
"""

import gc
import os
import sys
import tracemalloc
from typing import Dict, Optional, Tuple
from app.src.common.loguru_logger import logger


class MemoryMonitor:
    """
    Memory monitoring utility for tracking memory usage and identifying bottlenecks.
    """

    _is_tracking: bool = False
    _snapshots: Dict[str, tracemalloc.Snapshot] = {}

    @classmethod
    def start_tracking(cls) -> None:
        """Start tracking memory allocations."""
        if not cls._is_tracking:
            tracemalloc.start()
            cls._is_tracking = True
            logger.info("Memory tracking started")

    @classmethod
    def stop_tracking(cls) -> None:
        """Stop tracking memory allocations."""
        if cls._is_tracking:
            tracemalloc.stop()
            cls._is_tracking = False
            logger.info("Memory tracking stopped")

    @classmethod
    def get_current_memory_mb(cls) -> float:
        """
        Get current memory usage in MB using psutil if available, else tracemalloc.

        Returns:
            Current memory usage in megabytes
        """
        try:
            import psutil

            process = psutil.Process(os.getpid())
            return process.memory_info().rss / 1024 / 1024
        except ImportError:
            # Fallback to tracemalloc if psutil not available
            if cls._is_tracking:
                current, peak = tracemalloc.get_traced_memory()
                return current / 1024 / 1024
            return 0.0

    @classmethod
    def get_peak_memory_mb(cls) -> float:
        """
        Get peak memory usage in MB.

        Returns:
            Peak memory usage in megabytes
        """
        try:
            import psutil

            process = psutil.Process(os.getpid())
            return process.memory_info().rss / 1024 / 1024
        except ImportError:
            if cls._is_tracking:
                current, peak = tracemalloc.get_traced_memory()
                return peak / 1024 / 1024
            return 0.0

    @classmethod
    def log_memory_usage(
        cls,
        context: str,
        level: str = "INFO",
        include_top_stats: bool = False,
        top_n: int = 10,
    ) -> Dict[str, float]:
        """
        Log current memory usage with optional top memory allocations.

        Args:
            context: Context description for the memory log
            level: Log level (INFO, WARNING, DEBUG)
            include_top_stats: Whether to include top memory allocations
            top_n: Number of top allocations to show

        Returns:
            Dictionary with memory statistics
        """
        current_mb = cls.get_current_memory_mb()
        peak_mb = cls.get_peak_memory_mb()

        stats = {
            "current_mb": current_mb,
            "peak_mb": peak_mb,
        }

        log_msg = f"💾 MEMORY [{context}]: Current: {current_mb:.2f} MB, Peak: {peak_mb:.2f} MB"

        # Add top memory allocations if requested and tracking is enabled
        if include_top_stats and cls._is_tracking:
            snapshot = tracemalloc.take_snapshot()
            top_stats = snapshot.statistics("lineno")

            log_msg += "\n   Top memory allocations:"
            for index, stat in enumerate(top_stats[:top_n], 1):
                log_msg += f"\n   {index}. {stat.traceback.format()[-1]}: {stat.size / 1024 / 1024:.2f} MB"

        if level.upper() == "WARNING":
            logger.warning(log_msg)
        elif level.upper() == "DEBUG":
            logger.debug(log_msg)
        else:
            logger.info(log_msg)

        return stats

    @classmethod
    def take_snapshot(cls, name: str) -> Optional[tracemalloc.Snapshot]:
        """
        Take a memory snapshot for comparison.

        Args:
            name: Name identifier for the snapshot

        Returns:
            Memory snapshot or None if tracking not enabled
        """
        if not cls._is_tracking:
            return None

        snapshot = tracemalloc.take_snapshot()
        cls._snapshots[name] = snapshot
        return snapshot

    @classmethod
    def compare_snapshots(
        cls, snapshot1_name: str, snapshot2_name: str, top_n: int = 10
    ) -> None:
        """
        Compare two memory snapshots and log the differences.

        Args:
            snapshot1_name: Name of first snapshot
            snapshot2_name: Name of second snapshot
            top_n: Number of top differences to show
        """
        if not cls._is_tracking:
            return

        if snapshot1_name not in cls._snapshots or snapshot2_name not in cls._snapshots:
            logger.warning(
                f"Cannot compare snapshots: {snapshot1_name} or {snapshot2_name} not found"
            )
            return

        snapshot1 = cls._snapshots[snapshot1_name]
        snapshot2 = cls._snapshots[snapshot2_name]

        top_stats = snapshot2.compare_to(snapshot1, "lineno")

        logger.info(f"📊 MEMORY DIFF [{snapshot1_name} -> {snapshot2_name}]:")
        for index, stat in enumerate(top_stats[:top_n], 1):
            size_mb = abs(stat.size_diff) / 1024 / 1024
            logger.info(
                f"   {index}. {stat.traceback.format()[-1]}: "
                f"{'+' if stat.size_diff > 0 else '-'}{size_mb:.2f} MB"
            )

    @classmethod
    def check_memory_threshold(
        cls, threshold_mb: float, context: str, action: str = "WARNING"
    ) -> bool:
        """
        Check if current memory usage exceeds a threshold.

        Args:
            threshold_mb: Memory threshold in MB
            context: Context description
            action: Action to take if threshold exceeded (WARNING, ERROR, or custom)

        Returns:
            True if threshold exceeded, False otherwise
        """
        current_mb = cls.get_current_memory_mb()

        if current_mb > threshold_mb:
            if action.upper() == "WARNING":
                logger.warning(
                    f"⚠️ MEMORY THRESHOLD EXCEEDED [{context}]: "
                    f"{current_mb:.2f} MB > {threshold_mb:.2f} MB"
                )
            elif action.upper() == "ERROR":
                logger.error(
                    f"🚨 MEMORY THRESHOLD EXCEEDED [{context}]: "
                    f"{current_mb:.2f} MB > {threshold_mb:.2f} MB"
                )
            return True

        return False

    @classmethod
    def get_memory_config(cls) -> Dict[str, int]:
        """
        Get memory-optimized configuration based on environment.

        Returns:
            Dictionary with optimized batch sizes and concurrency limits
        """
        # Check if running on Heroku Basic dyno (limited memory)
        is_heroku_basic = (
            os.getenv("DYNO_TYPE", "").lower() == "basic"
            or os.getenv("HEROKU_DYNO_TYPE", "").lower() == "basic"
        )

        # Get memory limit from environment (Heroku Basic = ~512MB)
        memory_limit_mb = float(os.getenv("MEMORY_LIMIT_MB", "512"))

        # Determine if we should use conservative settings
        use_conservative = is_heroku_basic or memory_limit_mb < 1024

        if use_conservative:
            # Conservative settings for Basic dyno
            return {
                "max_concurrent_fetch": int(os.getenv("MAX_CONCURRENT_FETCH", "10")),
                "max_concurrent_batch": int(os.getenv("MAX_CONCURRENT_BATCH", "10")),
                "dynamodb_batch_size": int(os.getenv("DYNAMODB_BATCH_SIZE", "15")),
                "market_data_batch_size": int(
                    os.getenv("MARKET_DATA_BATCH_SIZE", "10")
                ),
            }
        else:
            # Standard settings for larger dynos
            return {
                "max_concurrent_fetch": int(os.getenv("MAX_CONCURRENT_FETCH", "25")),
                "max_concurrent_batch": int(os.getenv("MAX_CONCURRENT_BATCH", "25")),
                "dynamodb_batch_size": int(os.getenv("DYNAMODB_BATCH_SIZE", "25")),
                "market_data_batch_size": int(
                    os.getenv("MARKET_DATA_BATCH_SIZE", "25")
                ),
            }

    @classmethod
    def force_garbage_collection(cls, context: str = "") -> Dict[str, float]:
        """
        Force garbage collection and return memory stats before/after.

        Args:
            context: Context description for logging

        Returns:
            Dictionary with memory statistics before and after GC
        """
        before_mb = cls.get_current_memory_mb()

        # Run garbage collection
        collected = gc.collect()

        after_mb = cls.get_current_memory_mb()
        freed_mb = before_mb - after_mb

        if context:
            logger.debug(
                f"🗑️ GC [{context}]: Collected {collected} objects, "
                f"Freed {freed_mb:.2f} MB ({before_mb:.2f} MB -> {after_mb:.2f} MB)"
            )

        return {
            "before_mb": before_mb,
            "after_mb": after_mb,
            "freed_mb": freed_mb,
            "collected": collected,
        }

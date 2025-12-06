"""
Web Server Entry Point for Heroku
This runs both the MCP server and the trading application
"""

import asyncio
from app.src.common.loguru_logger import logger
from app.src.services.mcp.server import main as mcp_server_main
from app.src.app import main as trading_app_main


async def _safe_mcp_server():
    """Wrapper to safely start MCP server with error handling"""
    try:
        logger.info("🔄 Attempting to start MCP server...")
        await mcp_server_main()
    except Exception as e:
        logger.exception(f"❌ MCP server crashed: {e}")
        # Re-raise to be caught by gather
        raise


async def _safe_trading_app():
    """Wrapper to safely start trading app with error handling"""
    try:
        logger.info("🔄 Attempting to start trading application...")
        await trading_app_main()
    except Exception as e:
        logger.exception(f"❌ Trading application crashed: {e}")
        # Re-raise to be caught by gather
        raise


async def main():
    """Main entry point for web server - starts both MCP server and trading app"""
    logger.info("Starting web process with MCP server and trading application...")
    
    try:
        # Start both services concurrently with error handling
        mcp_task = asyncio.create_task(_safe_mcp_server())
        trading_task = asyncio.create_task(_safe_trading_app())
        
        logger.info("✅ MCP server and trading application tasks created")
        
        # Wait for both tasks (they run indefinitely)
        results = await asyncio.gather(mcp_task, trading_task, return_exceptions=True)
        
        # Check for exceptions in results
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                task_name = "MCP server" if i == 0 else "Trading application"
                logger.error(f"❌ {task_name} task ended with exception: {result}")
                # Log full traceback if available
                if hasattr(result, '__traceback__'):
                    import traceback
                    logger.error(f"Traceback for {task_name}:\n{traceback.format_exception(type(result), result, result.__traceback__)}")
    except Exception as e:
        logger.exception(f"❌ Fatal error in web process: {str(e)}")
        raise


if __name__ == "__main__":
    asyncio.run(main())

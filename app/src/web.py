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
    import os
    
    port = os.environ.get("PORT", "8000")
    dyno = os.environ.get("DYNO")
    is_heroku = bool(dyno)
    
    if is_heroku:
        heroku_app_name = (
            os.environ.get("HEROKU_APP_NAME") or
            os.environ.get("APP_NAME") or
            None
        )
        if heroku_app_name:
            public_url = f"https://{heroku_app_name}.herokuapp.com"
        else:
            public_url = "https://YOUR-APP-NAME.herokuapp.com"
        
        logger.info("=" * 70)
        logger.info("🚀 Starting web process on Heroku")
        logger.info(f"📦 DYNO: {dyno}")
        logger.info(f"🔌 Internal PORT: {port}")
        logger.info(f"🌐 Public URL: {public_url}")
        logger.info("=" * 70)
    else:
        logger.info(f"Starting web process with MCP server and trading application on PORT={port}...")
    
    try:
        # Start MCP server first (it's the web server, must start first)
        logger.info("🚀 Starting MCP server task...")
        mcp_task = asyncio.create_task(_safe_mcp_server())
        
        # Give MCP server a moment to start
        await asyncio.sleep(2)
        logger.info("✅ MCP server task started, waiting for it to initialize...")
        
        # Start trading app in background (non-blocking)
        logger.info("🚀 Starting trading application task...")
        trading_task = asyncio.create_task(_safe_trading_app())
        logger.info("✅ Trading application task started")
        
        logger.info("✅ Both tasks created and running")
        if is_heroku:
            logger.info(f"📡 MCP server available at: {public_url}/mcp")
        else:
            logger.info(f"📡 MCP server should be available at: http://0.0.0.0:{port}/mcp")
        
        # Wait for both tasks (they run indefinitely)
        # If MCP server crashes, we want to know about it
        # If trading app crashes, we can continue with just MCP server
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
                
                # If MCP server crashed, that's fatal
                if i == 0:
                    logger.error("❌ MCP server crashed - this is fatal for the web process")
                    raise result
    except Exception as e:
        logger.exception(f"❌ Fatal error in web process: {str(e)}")
        raise


if __name__ == "__main__":
    asyncio.run(main())

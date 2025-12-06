"""
Web Server Entry Point for Heroku
This runs both the MCP server and the trading application
"""

import asyncio
from app.src.common.loguru_logger import logger
from app.src.services.mcp.server import main as mcp_server_main
from app.src.app import main as trading_app_main


async def main():
    """Main entry point for web server - starts both MCP server and trading app"""
    logger.info("Starting web process with MCP server and trading application...")
    
    try:
        # Start both services concurrently
        mcp_task = asyncio.create_task(mcp_server_main())
        trading_task = asyncio.create_task(trading_app_main())
        
        logger.info("✅ MCP server and trading application started")
        
        # Wait for both tasks (they run indefinitely)
        await asyncio.gather(mcp_task, trading_task, return_exceptions=True)
    except Exception as e:
        logger.exception(f"Fatal error in web process: {str(e)}")
        raise


if __name__ == "__main__":
    asyncio.run(main())

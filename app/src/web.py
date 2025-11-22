"""
Web Server Entry Point for MCP Server
This runs the MCP server as a web process on Heroku
"""

import asyncio
from app.src.common.loguru_logger import logger
from app.src.services.mcp.server import main as mcp_server_main


async def main():
    """Main entry point for web server (MCP server only)"""
    logger.info("Starting MCP Server as web process...")
    try:
        await mcp_server_main()
    except Exception as e:
        logger.exception(f"Fatal error in MCP server: {str(e)}")
        raise


if __name__ == "__main__":
    asyncio.run(main())


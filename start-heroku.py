#!/usr/bin/env python3
"""
Heroku startup script for MCP server.
This script starts the MCP server with HTTP transport for Heroku deployment.
"""

import asyncio
import json
import os
import sys
import traceback
from pathlib import Path

# Force unbuffered output for Docker/Heroku logging
try:
    sys.stdout.reconfigure(line_buffering=True)
    sys.stderr.reconfigure(line_buffering=True)
except AttributeError:
    pass

# Add the project root to Python path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

# Import logger after path setup
try:
    from app.src.common.loguru_logger import logger

    print("✅ Loguru logger imported successfully", flush=True)
    logger.info("🚀 Loguru logger initialized for Heroku")
except ImportError as e:
    print(f"❌ Failed to import loguru logger: {e}", flush=True)
    # Create a simple fallback logger
    import logging

    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)

# Verify conda environment and ta-lib import
TALIB_AVAILABLE = False
CONDA_ENV_PATH = os.getenv("CONDA_PREFIX")
CONDA_ENV_NAME = os.getenv("CONDA_DEFAULT_ENV", "unknown")

try:
    import talib  # type: ignore # noqa: F401

    print("✅ TA-Lib imported successfully from conda environment", flush=True)
    logger.info("✅ TA-Lib imported successfully from conda environment")
    TALIB_AVAILABLE = True
except ImportError as e:
    print(f"⚠️ Warning: TA-Lib not available: {e}", flush=True)
    logger.warning(f"⚠️ Warning: TA-Lib not available: {e}")

    # Check if we're in the conda environment
    if CONDA_ENV_PATH:
        conda_python = os.path.join(CONDA_ENV_PATH, "bin", "python")
        if os.path.exists(conda_python):
            print(f"⚠️ Detected conda environment: {CONDA_ENV_NAME}", flush=True)
            print(f"⚠️ Current Python: {sys.executable}", flush=True)
            print(f"⚠️ Expected conda Python: {conda_python}", flush=True)
            if sys.executable != conda_python:
                print(f"⚠️ Please use: {conda_python} start-heroku.py", flush=True)
                print(
                    f"⚠️ Or activate conda env and use: python start-heroku.py",
                    flush=True,
                )
    else:
        print(
            "⚠️ Conda environment not detected. Please activate: conda activate automated_trading_system_env",
            flush=True,
        )

    print("⚠️ Some technical analysis features may not work", flush=True)
    TALIB_AVAILABLE = False


async def handle_mcp_request(request_data: dict, mcp_instance) -> dict:
    """Handle MCP protocol request"""
    method = request_data.get("method")
    params = request_data.get("params", {})

    # Handle MCP protocol initialize method
    if method == "initialize":
        # Return server capabilities and protocol info
        return {
            "protocolVersion": "2024-11-05",
            "capabilities": {
                "tools": {},
                "resources": {},
            },
            "serverInfo": {
                "name": "Automated Trading System",
                "version": "1.0.0",
            },
        }
    elif method == "tools/list":
        # FastMCP uses list_tools() method, not get_tools()
        if hasattr(mcp_instance, "list_tools"):
            tools = await mcp_instance.list_tools()
            # FastMCP returns Tool objects (Pydantic models), need to convert to dict
            tools_list = []
            for tool in tools:
                tool_dict = None
                # Try model_dump() first (Pydantic v2)
                if hasattr(tool, "model_dump"):
                    try:
                        tool_dict = tool.model_dump(mode="json")
                    except (TypeError, ValueError):
                        tool_dict = tool.model_dump()
                # Fallback to dict() (Pydantic v1)
                elif hasattr(tool, "dict"):
                    tool_dict = tool.dict()
                # Already a dict
                elif isinstance(tool, dict):
                    tool_dict = tool
                else:
                    # Manual serialization as last resort
                    tool_dict = {
                        "name": getattr(tool, "name", ""),
                        "description": getattr(tool, "description", ""),
                    }
                    if hasattr(tool, "inputSchema"):
                        input_schema = tool.inputSchema
                        if hasattr(input_schema, "model_dump"):
                            tool_dict["inputSchema"] = (
                                input_schema.model_dump(mode="json")
                                if hasattr(input_schema.model_dump, "__call__")
                                else input_schema.model_dump()
                            )
                        elif hasattr(input_schema, "dict"):
                            tool_dict["inputSchema"] = input_schema.dict()
                        else:
                            tool_dict["inputSchema"] = input_schema

                # Ensure required MCP protocol fields are present
                if tool_dict:
                    # MCP protocol requires 'title' field (use 'name' if title not present or null)
                    if "title" not in tool_dict or tool_dict.get("title") is None:
                        tool_dict["title"] = tool_dict.get("name", "")

                    # MCP protocol requires 'annotations' field (empty object if not present or null)
                    if (
                        "annotations" not in tool_dict
                        or tool_dict.get("annotations") is None
                    ):
                        tool_dict["annotations"] = {}

                    # Remove outputSchema for all tools to suppress validation warnings
                    if "outputSchema" in tool_dict:
                        del tool_dict["outputSchema"]

                    tools_list.append(tool_dict)

            return {"tools": tools_list}
        elif hasattr(mcp_instance, "get_tools"):
            # Fallback for custom implementation
            tools = mcp_instance.get_tools()
            return {
                "tools": [
                    {
                        "name": tool_info["name"],
                        "description": tool_info.get("description", ""),
                    }
                    for tool_info in tools.values()
                ]
            }
        else:
            return {"tools": []}
    elif method == "tools/call":
        tool_name = params.get("name")
        arguments = params.get("arguments", {})

        # FastMCP uses call_tool() method
        if hasattr(mcp_instance, "call_tool"):
            result = await mcp_instance.call_tool(tool_name, arguments)

            # Helper function to extract the actual data from TextContent or other formats
            def extract_actual_data(item):
                """Extract the actual data from TextContent objects or return the item itself"""
                # If it's already a plain dict (not MCP format), return it
                if isinstance(item, dict) and "type" not in item:
                    return item

                # If it's a dict with MCP format, extract the text field
                if isinstance(item, dict) and "type" in item and "text" in item:
                    text_value = item["text"]
                    # Try to parse as JSON
                    try:
                        return json.loads(text_value)
                    except (json.JSONDecodeError, TypeError):
                        return text_value

                # Check if it's a Pydantic model (TextContent, ImageContent, etc.)
                if hasattr(item, "model_dump"):
                    try:
                        dumped = item.model_dump(mode="json")
                        if (
                            isinstance(dumped, dict)
                            and "type" in dumped
                            and "text" in dumped
                        ):
                            # Extract text and parse as JSON
                            text_value = dumped["text"]
                            try:
                                return json.loads(text_value)
                            except (json.JSONDecodeError, TypeError):
                                return text_value
                    except (TypeError, ValueError):
                        if hasattr(item, "dict"):
                            dumped = item.dict()
                            if (
                                isinstance(dumped, dict)
                                and "type" in dumped
                                and "text" in dumped
                            ):
                                text_value = dumped["text"]
                                try:
                                    return json.loads(text_value)
                                except (json.JSONDecodeError, TypeError):
                                    return text_value

                # Check if it has type and text attributes directly
                if hasattr(item, "type") and hasattr(item, "text"):
                    text_value = getattr(item, "text", "")
                    try:
                        return json.loads(text_value)
                    except (json.JSONDecodeError, TypeError):
                        return text_value

                # For other types, return as-is
                return item

            # Extract the actual data from FastMCP's result
            actual_data = None

            if isinstance(result, dict) and "content" in result:
                # Already in MCP response format - extract from content items
                content_list = result["content"]
                # Extract data from each content item
                extracted_items = [extract_actual_data(item) for item in content_list]
                # Use the first dict item, or the first item if only one
                if extracted_items:
                    # Prefer dict items over strings
                    dict_items = [
                        item for item in extracted_items if isinstance(item, dict)
                    ]
                    if dict_items:
                        actual_data = dict_items[0]
                    else:
                        actual_data = extracted_items[0]
            elif isinstance(result, (list, tuple)):
                # Result is a sequence of content blocks
                extracted_items = [extract_actual_data(item) for item in result]
                if extracted_items:
                    dict_items = [
                        item for item in extracted_items if isinstance(item, dict)
                    ]
                    if dict_items:
                        actual_data = dict_items[0]
                    else:
                        actual_data = extracted_items[0]
            else:
                # Single item - extract the data
                actual_data = extract_actual_data(result)

            # If we still don't have actual_data, use result directly
            if actual_data is None:
                actual_data = result

            # If actual_data is a string (JSON), parse it
            if isinstance(actual_data, str):
                try:
                    actual_data = json.loads(actual_data)
                except (json.JSONDecodeError, TypeError):
                    pass  # Keep as string if not valid JSON

            # Ensure actual_data is a dict (the tool's return type)
            if not isinstance(actual_data, dict):
                # Try to convert to dict or wrap
                try:
                    actual_data = {"result": actual_data}
                except (TypeError, ValueError):
                    actual_data = {"error": "Invalid result format"}

            # Return as simple JSON blob in TextContent format
            # The JSON string will be parseable and match the output schema
            json_str = json.dumps(
                actual_data, ensure_ascii=False, allow_nan=False, default=str
            )
            return {"content": [{"type": "text", "text": json_str}]}
        elif hasattr(mcp_instance, "get_tools"):
            # Fallback for custom implementation
            tools = mcp_instance.get_tools()
            if tool_name not in tools:
                raise ValueError(f"Unknown tool: {tool_name}")
            tool_info = tools[tool_name]
            handler = tool_info["handler"]
            result = await handler(**arguments)
            return {"content": [{"type": "text", "text": json.dumps(result)}]}
        else:
            raise ValueError("Tool execution not supported")
    elif method == "resources/list":
        # FastMCP uses list_resources() method, not get_resources()
        if hasattr(mcp_instance, "list_resources"):
            resources = await mcp_instance.list_resources()
            # FastMCP returns Resource objects (Pydantic models), need to convert to dict
            resources_list = []
            for resource in resources:
                # Try model_dump() first (Pydantic v2) with JSON mode to convert AnyUrl to string
                if hasattr(resource, "model_dump"):
                    try:
                        # Use mode='json' to properly serialize AnyUrl and other special types
                        resource_dict = resource.model_dump(mode="json")
                    except TypeError:
                        # Fallback to default mode if 'json' mode not supported
                        resource_dict = resource.model_dump()
                        # Manually convert AnyUrl to string
                        if "uri" in resource_dict and hasattr(
                            resource_dict["uri"], "__str__"
                        ):
                            resource_dict["uri"] = str(resource_dict["uri"])
                    resources_list.append(resource_dict)
                # Fallback to dict() (Pydantic v1)
                elif hasattr(resource, "dict"):
                    resource_dict = resource.dict()
                    # Convert AnyUrl to string for Pydantic v1
                    if "uri" in resource_dict and hasattr(
                        resource_dict["uri"], "__str__"
                    ):
                        resource_dict["uri"] = str(resource_dict["uri"])
                    resources_list.append(resource_dict)
                # Already a dict
                elif isinstance(resource, dict):
                    resources_list.append(resource)
                else:
                    # Manual serialization as last resort
                    resource_dict = {
                        "uri": str(getattr(resource, "uri", "")),  # Convert to string
                        "name": getattr(resource, "name", ""),
                    }
                    if hasattr(resource, "description"):
                        resource_dict["description"] = resource.description
                    if hasattr(resource, "mimeType"):
                        resource_dict["mimeType"] = resource.mimeType
                    resources_list.append(resource_dict)
            return {"resources": resources_list}
        elif hasattr(mcp_instance, "get_resources"):
            # Fallback for custom implementation
            resources = mcp_instance.get_resources()
            return {
                "resources": [
                    {"uri": res_info["uri"], "name": res_info.get("name", "")}
                    for res_info in resources.values()
                ]
            }
        else:
            return {"resources": []}
    elif method == "resources/read":
        uri = params.get("uri")

        # FastMCP uses read_resource() method
        if hasattr(mcp_instance, "read_resource"):
            result = await mcp_instance.read_resource(uri)
            # FastMCP returns resource data, wrap in contents format if needed
            if isinstance(result, dict) and "contents" in result:
                # Ensure AnyUrl objects in contents are converted to strings
                contents = result["contents"]
                for content in contents:
                    if isinstance(content, dict) and "uri" in content:
                        if hasattr(content["uri"], "__str__") and not isinstance(
                            content["uri"], str
                        ):
                            content["uri"] = str(content["uri"])
                return result
            # Convert result to JSON-serializable format
            try:
                json.dumps(result)  # Test if serializable
                return {
                    "contents": [
                        {
                            "uri": uri,
                            "mimeType": "application/json",
                            "text": json.dumps(result),
                        }
                    ]
                }
            except (TypeError, ValueError):
                # If not directly serializable, convert AnyUrl and other types
                serializable_result = {}
                for key, value in (
                    result.items()
                    if isinstance(result, dict)
                    else enumerate(result) if isinstance(result, (list, tuple)) else []
                ):
                    if hasattr(value, "__str__") and not isinstance(
                        value, (str, int, float, bool, type(None))
                    ):
                        serializable_result[key] = str(value)
                    else:
                        serializable_result[key] = value
                return {
                    "contents": [
                        {
                            "uri": uri,
                            "mimeType": "application/json",
                            "text": json.dumps(serializable_result),
                        }
                    ]
                }
        elif hasattr(mcp_instance, "get_resources"):
            # Fallback for custom implementation
            resources = mcp_instance.get_resources()
            if uri not in resources:
                raise ValueError(f"Unknown resource: {uri}")
            resource_info = resources[uri]
            handler = resource_info["handler"]
            result = await handler()
            return {
                "contents": [
                    {
                        "uri": uri,
                        "mimeType": "application/json",
                        "text": json.dumps(result),
                    }
                ]
            }
        else:
            raise ValueError("Resource reading not supported")
    else:
        raise ValueError(f"Unknown method: {method}")


async def start_mcp_http_server():
    """Start MCP server with HTTP transport for Heroku"""
    # Early check: Verify talib is available before importing modules that require it
    if not TALIB_AVAILABLE:
        conda_env_path = os.getenv("CONDA_PREFIX")
        conda_env_name = os.getenv("CONDA_DEFAULT_ENV", "unknown")

        error_msg = "❌ TA-Lib is required but not available. Cannot start MCP server."
        logger.error(error_msg)
        print(error_msg, flush=True)

        if conda_env_path:
            conda_python = os.path.join(conda_env_path, "bin", "python")
            print(f"\n⚠️ Current Python: {sys.executable}", flush=True)
            print(f"⚠️ Conda environment: {conda_env_name}", flush=True)
            print(f"⚠️ Expected conda Python: {conda_python}", flush=True)
            if sys.executable != conda_python:
                print(f"\n✅ Solution: Use the conda Python interpreter:", flush=True)
                print(f"   {conda_python} start-heroku.py", flush=True)
                print(f"\n   Or activate the conda environment and use:", flush=True)
                print(f"   conda activate automated_trading_system_env", flush=True)
                print(f"   python start-heroku.py", flush=True)
                print(
                    f"\n   For VS Code debugging, update .vscode/launch.json to use:",
                    flush=True,
                )
                print(f"   {conda_python}", flush=True)
            else:
                print(
                    f"\n⚠️ Please install TA-Lib in the conda environment:", flush=True
                )
                print(f"   conda install -c conda-forge ta-lib", flush=True)
        else:
            print(f"\n⚠️ Please activate the conda environment first:", flush=True)
            print(f"   conda activate automated_trading_system_env", flush=True)
            print(f"   python start-heroku.py", flush=True)

        # Raise an exception instead of sys.exit() for better debugger handling
        raise RuntimeError(
            "TA-Lib is required but not available. "
            "Please use the conda Python interpreter or install TA-Lib in the current environment."
        )

    try:
        # Import the main function from server.py which handles everything
        from app.src.services.mcp.server import main as mcp_main
        # Import the main trading application
        from app.src.app import main as trading_app_main

        logger.info("✅ Successfully imported MCP server and trading application")
        print("✅ Successfully imported MCP server and trading application", flush=True)

        # Get port from Heroku environment (defaults to 8000 for local development)
        port_str = os.getenv("PORT", "8000")
        if not port_str:
            port_str = "8000"  # Default for local development
            logger.info("⚠️ PORT not set, defaulting to 8000 for local development")
            print(
                "⚠️ PORT not set, defaulting to 8000 for local development", flush=True
            )

        try:
            port = int(port_str)
        except ValueError:
            raise ValueError(f"Invalid PORT value: {port_str}")

        # Set environment variables for server.py to use
        os.environ["PORT"] = port_str
        os.environ["HOST"] = "0.0.0.0"  # Must bind to 0.0.0.0 for Heroku
        # Ensure we use streamable-http transport for Heroku
        if "MCP_SERVER_TRANSPORT" not in os.environ:
            os.environ["MCP_SERVER_TRANSPORT"] = "streamable-http"

        host = "0.0.0.0"

        logger.info(f"🚀 Starting MCP server on {host}:{port}")
        print(f"🚀 Starting MCP server on {host}:{port}", flush=True)
        logger.info(f"📡 MCP endpoint: http://{host}:{port}/mcp")
        print(f"📡 MCP endpoint: http://{host}:{port}/mcp", flush=True)
        logger.info(f"🏥 Health check: http://{host}:{port}/health")
        print(f"🏥 Health check: http://{host}:{port}/health", flush=True)

        # Use the existing server infrastructure from server.py
        # This will handle all MCP protocol requests, tool registration, background tasks, etc.
        # The main() function from server.py will run the uvicorn server and handle everything
        logger.info("✅ Starting MCP server using existing server infrastructure...")
        print(
            "✅ Starting MCP server using existing server infrastructure...", flush=True
        )
        
        # Start the trading application in the background
        logger.info("✅ Starting trading application...")
        print("✅ Starting trading application...", flush=True)
        
        # Create tasks for both services
        mcp_task = asyncio.create_task(mcp_main())
        trading_task = asyncio.create_task(trading_app_main())
        
        # Wait for both tasks, handling exceptions individually
        try:
            # Wait for both tasks to complete (they run indefinitely, so this will run until one fails)
            done, pending = await asyncio.wait(
                [mcp_task, trading_task],
                return_when=asyncio.FIRST_EXCEPTION
            )
            
            # Check for exceptions
            for task in done:
                if task.exception():
                    logger.error(f"❌ Task failed: {task.exception()}", exc_info=task.exception())
                    print(f"❌ Task failed: {task.exception()}", flush=True)
                    # Cancel the other task
                    for pending_task in pending:
                        pending_task.cancel()
                        try:
                            await pending_task
                        except asyncio.CancelledError:
                            pass
                    raise task.exception()
        except KeyboardInterrupt:
            logger.info("🛑 Shutting down services...")
            print("🛑 Shutting down services...", flush=True)
            mcp_task.cancel()
            trading_task.cancel()
            try:
                await asyncio.gather(mcp_task, trading_task, return_exceptions=True)
            except Exception:
                pass
            raise

    except ImportError as e:
        error_msg = f"❌ Failed to import required module: {e}"
        logger.error(error_msg, exc_info=True)
        print(error_msg, flush=True)

        # Check if this is a talib import error and provide helpful guidance
        if "talib" in str(e).lower():
            conda_env_path = os.getenv("CONDA_PREFIX")
            if conda_env_path:
                conda_python = os.path.join(conda_env_path, "bin", "python")
                print(
                    f"\n⚠️ TA-Lib is not available in the current Python interpreter.",
                    flush=True,
                )
                print(f"⚠️ Current Python: {sys.executable}", flush=True)
                print(
                    f"⚠️ Conda environment detected: {os.getenv('CONDA_DEFAULT_ENV', 'unknown')}",
                    flush=True,
                )
                print(f"⚠️ Expected conda Python: {conda_python}", flush=True)
                if sys.executable != conda_python:
                    print(
                        f"\n✅ Solution: Use the conda Python interpreter:", flush=True
                    )
                    print(f"   {conda_python} start-heroku.py", flush=True)
                    print(
                        f"\n   Or activate the conda environment and use:", flush=True
                    )
                    print(f"   conda activate automated_trading_system_env", flush=True)
                    print(f"   python start-heroku.py", flush=True)
            else:
                print(f"\n⚠️ Please activate the conda environment first:", flush=True)
                print(f"   conda activate automated_trading_system_env", flush=True)

        traceback.print_exc()
        sys.exit(1)
    except ValueError as e:
        error_msg = f"❌ Configuration error: {e}"
        logger.error(error_msg, exc_info=True)
        print(error_msg, flush=True)
        traceback.print_exc()
        sys.exit(1)
    except Exception as e:
        error_msg = f"❌ Error starting MCP server: {e}"
        logger.error(error_msg, exc_info=True)
        print(error_msg, flush=True)
        traceback.print_exc()
        raise


def main():
    """Main startup function for Heroku"""
    print("🚀 Starting Automated Trading System MCP Service", flush=True)
    print(f"📊 Environment: {os.getenv('ENVIRONMENT', 'production')}", flush=True)
    print(
        f"🔧 Python: {sys.version.split()[0]} | Conda: automated_trading_system_env",
        flush=True,
    )
    print(f"📍 Working Directory: {os.getcwd()}", flush=True)
    print(f"🐍 Python Path: {sys.path[:3]}", flush=True)  # Show first 3 paths

    logger.info("🚀 Automated Trading System MCP Service starting...")
    logger.info(f"📊 Environment: {os.getenv('ENVIRONMENT', 'production')}")
    logger.info(
        f"🔧 DYNO: {os.getenv('DYNO', 'N/A')} | PORT: {os.getenv('PORT', 'N/A')}"
    )
    logger.info(f"📍 Working Directory: {os.getcwd()}")

    try:
        # Verify required environment variables
        logger.info("🔧 Configuring MCP server and environment...")
        print("🔧 Configuring MCP server and environment...")

        required_env_vars = [
            "REAL_TRADE_API_KEY",
            "REAL_TRADE_SECRET_KEY",
            "UW_API_TOKEN",
            "WEBHOOK_URL",
            "AWS_ACCESS_KEY_ID",
            "AWS_SECRET_ACCESS_KEY",
        ]
        missing_vars = [var for var in required_env_vars if not os.getenv(var)]
        if missing_vars:
            logger.warning(f"⚠️ Missing environment variables: {missing_vars}")
            print(f"⚠️ Missing environment variables: {missing_vars}")

        # Check AWS credentials
        if not os.getenv("AWS_ACCESS_KEY_ID") or not os.getenv("AWS_SECRET_ACCESS_KEY"):
            logger.warning("⚠️ AWS credentials not set - DynamoDB integration may fail")
            print(
                "⚠️ AWS credentials not set - DynamoDB integration may fail", flush=True
            )
        else:
            logger.info("✅ AWS credentials detected")
            print("✅ AWS credentials detected", flush=True)

        # Get PORT (required by Heroku, but default to 8000 for local development)
        port = os.getenv("PORT")
        if not port:
            # Default to 8000 for local development
            port = "8000"
            logger.info("⚠️ PORT not set, defaulting to 8000 for local development")
            print(
                "⚠️ PORT not set, defaulting to 8000 for local development", flush=True
            )
        else:
            logger.info(f"✅ PORT configured: {port}")
            print(f"✅ PORT configured: {port}", flush=True)

        logger.info("✅ MCP server configuration complete")
        print("✅ MCP server configuration complete", flush=True)

        print("", flush=True)
        logger.info("🚀 Starting MCP HTTP server...")
        print("🚀 Starting MCP HTTP server...", flush=True)
        print("=" * 60, flush=True)

        # Run MCP server
        asyncio.run(start_mcp_http_server())

    except Exception as e:
        logger.error(f"❌ Fatal error during startup: {e}")
        logger.error(f"Stack trace: {traceback.format_exc()}")
        print(f"❌ Fatal error during startup: {e}")
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()

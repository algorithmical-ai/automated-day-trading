"""Configuration utilities for the Workflow Manager MCP server."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal, Optional, cast

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.src.config import constants

class MCPClientSettings(BaseModel):
    """Endpoints and authentication for external MCP servers."""

    market_data_url: str = Field(default=constants.MARKET_DATA_MCP_URL)
    market_data_token: Optional[str] = Field(default=constants.MARKET_DATA_MCP_TOKEN)
    market_data_name: str = Field(default=constants.MARKET_DATA_MCP_NAME)
    
    model_config = SettingsConfigDict(populate_by_name=True)


class ServerSettings(BaseSettings):
    """Top-level server configuration."""

    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = Field(
        default=cast(Literal["DEBUG", "INFO", "WARNING", "ERROR"], constants.LOG_LEVEL)
    )
    environment: Literal["development", "production", "test"] = Field(
        default=cast(
            Literal["development", "production", "test"], constants.ENVIRONMENT
        )
    )
    transport: Literal["stdio", "sse", "streamable-http"] = Field(
        default=cast(
            Literal["stdio", "sse", "streamable-http"], constants.MCP_SERVER_TRANSPORT
        )
    )
    mcp_auth_header_name: str = Field(default=constants.MCP_AUTH_HEADER_NAME)
    mcp_auth_bearer_token: Optional[str] = Field(
        default=constants.MCP_AUTH_BEARER_TOKEN
    )
    mcp_clients: MCPClientSettings = Field(default_factory=MCPClientSettings)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_nested_delimiter="__",
        extra="ignore",
    )


@lru_cache(maxsize=1)
def get_settings() -> ServerSettings:
    """Return cached server settings populated from environment variables."""
    return ServerSettings()  # type: ignore[arg-type]

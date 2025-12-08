# Requirements Document

## Introduction

The MCP tools `enter()` and `exit()` currently return the `indicators` field as a JSON string instead of a dictionary object. This makes it difficult for MCP clients to parse and use the indicator data. The indicators should be returned as a properly structured dictionary to enable easier programmatic access to individual indicator values.

## Glossary

- **MCP Tool**: Model Context Protocol tool that provides trading analysis functionality
- **TechnicalIndicators**: A Pydantic model containing technical analysis indicators (RSI, MACD, Bollinger Bands, etc.)
- **MarketDataService**: Service class that provides enter_trade and exit_trade methods
- **Indicators Field**: The field in the response containing technical analysis data

## Requirements

### Requirement 1

**User Story:** As an MCP client, I want the indicators field to be returned as a dictionary object, so that I can easily access individual indicator values without parsing JSON strings.

#### Acceptance Criteria

1. WHEN the enter() MCP tool returns a response THEN the indicators field in the analysis object SHALL be a dictionary, not a JSON string
2. WHEN the exit() MCP tool returns a response THEN the indicators field in the analysis object SHALL be a dictionary, not a JSON string
3. WHEN the TechnicalIndicators model is included in a response THEN the system SHALL call the to_dict() method to convert it to a dictionary
4. WHEN the response is serialized by the MCP server THEN the indicators field SHALL maintain its dictionary structure
5. WHEN an MCP client receives the response THEN the client SHALL be able to access indicator values directly (e.g., response["analysis"]["indicators"]["rsi"]) without JSON parsing

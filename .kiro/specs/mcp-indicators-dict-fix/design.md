# Design Document

## Overview

This design addresses the issue where the `indicators` field in MCP tool responses is returned as a JSON string instead of a dictionary. The fix involves converting `TechnicalIndicators` Pydantic model instances to dictionaries using the existing `to_dict()` method before including them in response objects.

## Architecture

The fix is localized to the `MarketDataService` class in `app/src/services/market_data/market_data_service.py`. No architectural changes are required - we simply need to ensure that `TechnicalIndicators` objects are converted to dictionaries before being included in return values.

### Current Flow
1. `enter()` or `exit()` MCP tool is called
2. Tool calls `MarketDataService.enter_trade()` or `MarketDataService.exit_trade()`
3. Service converts market data to `TechnicalIndicators` object using `dict_to_technical_indicators()`
4. Service returns response dict with `TechnicalIndicators` object in `analysis.indicators`
5. MCP server serializes response, converting `TechnicalIndicators` to JSON string
6. Client receives indicators as string instead of dict

### Fixed Flow
1. `enter()` or `exit()` MCP tool is called
2. Tool calls `MarketDataService.enter_trade()` or `MarketDataService.exit_trade()`
3. Service converts market data to `TechnicalIndicators` object using `dict_to_technical_indicators()`
4. Service calls `indicators.to_dict()` before including in response
5. Service returns response dict with dictionary in `analysis.indicators`
6. MCP server serializes response, maintaining dict structure
7. Client receives indicators as properly structured dictionary

## Components and Interfaces

### Modified Components

#### MarketDataService.enter_trade()
- Location: `app/src/services/market_data/market_data_service.py`
- Change: Convert `indicators` to dict using `indicators.to_dict()` before including in all return statements
- All return statements that include `"indicators": indicators` should be changed to `"indicators": indicators.to_dict()`

#### MarketDataService.exit_trade()
- Location: `app/src/services/market_data/market_data_service.py`
- Change: Convert `indicators` to dict using `indicators.to_dict()` before including in all return statements
- All return statements that include `"indicators": indicators` should be changed to `"indicators": indicators.to_dict()`

### Unchanged Components

#### TechnicalIndicators Model
- Already has `to_dict()` method that properly converts the model to a dictionary
- No changes needed

#### MCP Tools (enter, exit)
- No changes needed - they simply pass through the response from MarketDataService

## Data Models

### TechnicalIndicators Dictionary Structure

The `to_dict()` method returns a dictionary with the following structure:

```python
{
    "rsi": float,
    "macd": {
        "macd": float,
        "signal": float,
        "hist": float
    },
    "bollinger": {
        "upper": float,
        "middle": float,
        "lower": float
    },
    "adx": float,
    "ema_fast": float,
    "ema_slow": float,
    "volume_sma": float,
    "obv": float,
    "mfi": float,
    "ad": float,
    "stoch": {
        "k": float,
        "d": float
    },
    "cci": float,
    "atr": float,
    "willr": float,
    "roc": float,
    "vwap": float,
    "vwma": float,
    "wma": float,
    "volume": float,
    "close_price": float,
    "datetime_price": list
}
```

## Correctness Properties

*A property is a characteristic or behavior that should hold true across all valid executions of a system-essentially, a formal statement about what the system should do. Properties serve as the bridge between human-readable specifications and machine-verifiable correctness guarantees.*

### Property 1: Indicators field type consistency

*For any* response from `enter_trade()` or `exit_trade()` that includes an `indicators` field, the indicators field should be a dictionary (dict type), not a string.

**Validates: Requirements 1.1, 1.2, 1.3**

### Property 2: Dictionary structure preservation

*For any* `TechnicalIndicators` object converted using `to_dict()`, all nested structures (macd, bollinger, stoch) should be dictionaries with the expected keys, not tuples or strings.

**Validates: Requirements 1.4**

### Property 3: Direct access to indicator values

*For any* response containing indicators, accessing nested indicator values (e.g., `response["analysis"]["indicators"]["rsi"]`) should succeed without requiring JSON parsing.

**Validates: Requirements 1.5**

## Error Handling

No new error handling is required. The `to_dict()` method is already implemented and tested on the `TechnicalIndicators` model. If `indicators` is None, we should handle that case appropriately (though this should not occur in normal operation based on existing validation).

## Testing Strategy

### Unit Tests

We will write unit tests to verify:
1. The `enter_trade()` method returns indicators as a dict
2. The `exit_trade()` method returns indicators as a dict
3. The returned dict has the expected structure with nested dicts for macd, bollinger, and stoch

### Property-Based Tests

We will use Hypothesis (the existing PBT library in the project) to write property-based tests:

1. **Property 1 Test**: Generate random valid `TechnicalIndicators` objects, call `enter_trade()` and `exit_trade()`, verify the indicators field is always a dict type
2. **Property 2 Test**: Generate random valid `TechnicalIndicators` objects, convert using `to_dict()`, verify all nested structures are dicts with correct keys
3. **Property 3 Test**: Generate random valid responses, verify direct dictionary access works without exceptions

Each property-based test will run a minimum of 100 iterations. Each test will be tagged with a comment referencing the correctness property using the format: `**Feature: mcp-indicators-dict-fix, Property {number}: {property_text}**`

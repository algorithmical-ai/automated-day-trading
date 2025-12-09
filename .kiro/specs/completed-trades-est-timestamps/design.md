# Design Document

## Overview

This design converts exit_timestamp storage for CompletedTradesForAutomatedDayTrading records from GMT (UTC) to EST (America/New_York) timezone, and verifies that enter_timestamp is correctly copied from the created_at field of ActiveTickersForAutomatedDayTrader records. The change affects one main component: BaseTradingIndicator's `_exit_trade()` method. The exit_timestamp generation will use `_get_est_timestamp()` (which calls `datetime.now(ZoneInfo('America/New_York')).isoformat()`) instead of `datetime.now(timezone.utc).isoformat()`.

The design maintains consistency with the existing codebase, as the `created_at` field in ActiveTickersForAutomatedDayTrader already uses EST timestamps via the `_get_est_timestamp()` helper function.

## Architecture

The timestamp conversion follows a simple replacement pattern:

1. **BaseTradingIndicator** (`app/src/services/trading/base_trading_indicator.py`): Updates exit_timestamp generation in `_exit_trade()` method (line 379)
2. **Verification**: Confirms that enter_timestamp is correctly copied from `created_at` field (lines 367-371)
3. **No changes needed** to DynamoDBClient since it already uses `_get_est_timestamp()` for active trade creation

The system already has the necessary infrastructure:
- `_get_est_timestamp()` helper function exists in `app/src/db/dynamodb_client.py` (lines 38-47)
- `ZoneInfo` is already imported in `dynamodb_client.py`
- Active trades already store `created_at` in EST format

## Components and Interfaces

### BaseTradingIndicator

**Location:** `app/src/services/trading/base_trading_indicator.py`

**Changes:**
- Line 379: Replace `datetime.now(timezone.utc).isoformat()` with `_get_est_timestamp()`
- Add import: `from app.src.db.dynamodb_client import _get_est_timestamp`

**Current Code (line 379):**
```python
exit_timestamp = datetime.now(timezone.utc).isoformat()
```

**Updated Code:**
```python
exit_timestamp = _get_est_timestamp()
```

**Verification (lines 367-371):**
The code already correctly copies `created_at` to `enter_timestamp`:
```python
enter_timestamp = (
    trade_data.get("created_at", datetime.now(timezone.utc).isoformat())
    if trade_data
    else datetime.now(timezone.utc).isoformat()
)
```

**Improvement for fallback:**
The fallback should also use EST for consistency:
```python
enter_timestamp = (
    trade_data.get("created_at", _get_est_timestamp())
    if trade_data
    else _get_est_timestamp()
)
```

**Interface (unchanged):**
```python
@classmethod
async def _exit_trade(
    cls,
    ticker: str,
    original_action: str,
    enter_price: float,
    exit_price: float,
    exit_reason: str,
    technical_indicators_enter: Optional[Dict[str, Any]] = None,
    technical_indicators_exit: Optional[Dict[str, Any]] = None,
) -> bool
```

### _get_est_timestamp Helper

**Location:** `app/src/db/dynamodb_client.py` (lines 38-47)

**No changes needed** - this function already exists and provides EST timestamps:
```python
def _get_est_timestamp() -> str:
    """
    Get current timestamp in EST (Eastern Standard Time) timezone.
    
    Returns:
        ISO format timestamp string in EST
    """
    est_tz = ZoneInfo('America/New_York')
    return datetime.now(est_tz).isoformat()
```

## Data Models

### Timestamp Format

**Before (UTC):**
```
2025-12-08T14:30:45.123456+00:00
```

**After (EST/EDT):**
```
2025-12-08T09:30:45.123456-05:00  # EST (winter)
2025-06-15T10:30:45.123456-04:00  # EDT (summer)
```

Both formats are ISO 8601 compliant and include timezone offset information. The `ZoneInfo` class automatically handles DST transitions.

### Completed Trade Structure (unchanged)

```python
{
    "ticker": str,
    "action": str,
    "enter_price": float,
    "enter_reason": str,
    "enter_timestamp": str,  # ISO 8601 with EST/EDT offset (from created_at)
    "exit_price": float,
    "exit_timestamp": str,   # ISO 8601 with EST/EDT offset (NEW: now in EST)
    "exit_reason": str,
    "profit_or_loss": float,
    "technical_indicators_for_enter": Dict[str, Any],
    "technical_indicators_for_exit": Dict[str, Any]
}
```

## Correctness Properties

*A property is a characteristic or behavior that should hold true across all valid executions of a system-essentially, a formal statement about what the system should do. Properties serve as the bridge between human-readable specifications and machine-verifiable correctness guarantees.*

### Property 1: Exit timestamps use America/New_York timezone

*For any* completed trade created by BaseTradingIndicator, the exit_timestamp should be in America/New_York timezone (indicated by -05:00 or -04:00 offset in ISO 8601 format).

**Validates: Requirements 1.1, 1.2**

### Property 2: Enter timestamp matches created_at from active trade

*For any* completed trade where the active trade record exists, the enter_timestamp should equal the created_at field from the corresponding active trade record.

**Validates: Requirements 2.1, 2.2, 2.4**

### Property 3: Exit timestamp is after enter timestamp

*For any* completed trade, parsing both enter_timestamp and exit_timestamp as timezone-aware datetimes should show that exit_timestamp is chronologically after enter_timestamp.

**Validates: Requirements 3.3**

### Property 4: Timestamp format is ISO 8601 with timezone

*For any* completed trade, both enter_timestamp and exit_timestamp should parse successfully as ISO 8601 format and the parsed datetimes should have timezone information (not naive).

**Validates: Requirements 1.3, 3.2**

### Property 5: DST transition handling for exit timestamps

*For any* exit timestamp generated during DST transition periods (spring forward, fall back), the system should use the correct offset (-04:00 for EDT, -05:00 for EST) based on the America/New_York timezone rules.

**Validates: Requirements 1.5, 3.5**

## Error Handling

### Missing Active Trade Data

If the active trade record is not found when exiting a trade, the system falls back to using the current EST timestamp for enter_timestamp. This ensures the completed trade is still recorded even if the active trade data is missing.

**Current behavior (line 367-371):**
```python
enter_timestamp = (
    trade_data.get("created_at", datetime.now(timezone.utc).isoformat())
    if trade_data
    else datetime.now(timezone.utc).isoformat()
)
```

**Updated behavior:**
```python
enter_timestamp = (
    trade_data.get("created_at", _get_est_timestamp())
    if trade_data
    else _get_est_timestamp()
)
```

### Backward Compatibility

Existing UTC timestamps in the database will continue to work correctly because:
1. ISO 8601 format includes timezone offset information
2. DynamoDB string comparisons work correctly with ISO 8601 timestamps
3. Python's datetime parsing handles both UTC and EST timestamps
4. The system doesn't perform timestamp arithmetic that would be affected by timezone differences

## Testing Strategy

### Unit Tests

1. **Test exit timestamp format**: Verify generated exit_timestamp matches ISO 8601 format with EST/EDT offset
2. **Test timezone extraction**: Parse generated exit_timestamp and verify timezone is America/New_York
3. **Test enter timestamp copying**: Mock active trade with created_at, verify it's copied to enter_timestamp
4. **Test fallback behavior**: Test enter_timestamp fallback when active trade is missing
5. **Test timestamp ordering**: Verify exit_timestamp is always after enter_timestamp
6. **Test DST boundaries**: Create exit timestamps around DST transition dates and verify correct offsets

### Property-Based Tests

Property-based tests will use the Hypothesis library (already in use based on `.hypothesis` directory).

1. **Property 1 Test**: Generate random completed trades and verify exit_timestamp contains -05:00 or -04:00 offset
   - **Feature: completed-trades-est-timestamps, Property 1: Exit timestamps use America/New_York timezone**
   
2. **Property 2 Test**: Generate random active trades with created_at, exit them, and verify enter_timestamp matches created_at
   - **Feature: completed-trades-est-timestamps, Property 2: Enter timestamp matches created_at from active trade**
   
3. **Property 3 Test**: Generate random completed trades and verify exit_timestamp > enter_timestamp chronologically
   - **Feature: completed-trades-est-timestamps, Property 3: Exit timestamp is after enter timestamp**
   
4. **Property 4 Test**: Generate random completed trades, parse both timestamps, and verify they are timezone-aware
   - **Feature: completed-trades-est-timestamps, Property 4: Timestamp format is ISO 8601 with timezone**
   
5. **Property 5 Test**: Generate exit timestamps across DST transition dates, verify correct offset usage
   - **Feature: completed-trades-est-timestamps, Property 5: DST transition handling for exit timestamps**

### Test Configuration

- Minimum 100 iterations per property test
- Use Hypothesis strategies for generating valid tickers, indicators, prices, and timestamps
- Test both EST (-05:00) and EDT (-04:00) periods
- Test edge cases: midnight, market open/close times, DST transition moments
- Mock DynamoDB operations to avoid actual database calls during testing

## Implementation Notes

### Import Statement

`base_trading_indicator.py` will need to import the helper function:
```python
from app.src.db.dynamodb_client import _get_est_timestamp
```

### No Database Migration Required

Since we're only changing how new timestamps are generated (not modifying existing data), no database migration is needed. Old UTC timestamps will coexist with new EST timestamps, and both will work correctly in queries due to ISO 8601 format.

### Consistency with Active Trades

This change brings completed trades into alignment with active trades, which already use EST timestamps via `_get_est_timestamp()` for the `created_at` field (line 627 in dynamodb_client.py).

### Performance Considerations

`_get_est_timestamp()` uses `ZoneInfo` which caches timezone data after first access, so repeated calls have minimal overhead. The performance impact is negligible compared to database operations.

### All Trading Indicators Affected

This change affects all trading indicators that inherit from `BaseTradingIndicator`:
- Momentum Trading Service
- Penny Stock Trading Service  
- Deep Analyzer Service
- Any future indicators

All will automatically use EST timestamps for exit_timestamp after this change.

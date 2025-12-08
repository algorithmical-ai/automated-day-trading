# Design Document

## Overview

This design converts timestamp storage for InactiveTickersForDayTrading records from GMT (UTC) to EST (America/New_York) timezone. The change affects three main components: RejectionCollector, RejectionRecord model, and DynamoDBClient. All timestamp generation will use `datetime.now(ZoneInfo('America/New_York'))` instead of `datetime.now(timezone.utc)`, and time window calculations will be adjusted accordingly.

The design maintains backward compatibility by preserving ISO 8601 format and ensuring existing UTC timestamps can still be read and compared correctly.

## Architecture

The timestamp conversion follows a straightforward replacement pattern across the codebase:

1. **RejectionCollector** (`app/src/services/trading/validation/rejection_collector.py`): Updates timestamp generation in `add_rejection()` method
2. **RejectionRecord Model** (`app/src/services/trading/validation/models.py`): Updates default timestamp factory in dataclass field
3. **DynamoDBClient** (`app/src/db/dynamodb_client.py`): Updates timestamp generation in `log_inactive_ticker()` and cutoff calculation in `get_inactive_tickers_for_indicator()`

All components will import `ZoneInfo` from the `zoneinfo` module (Python 3.9+) to handle EST/EDT transitions automatically.

## Components and Interfaces

### RejectionCollector

**Location:** `app/src/services/trading/validation/rejection_collector.py`

**Changes:**
- Line 63: Replace `datetime.now(timezone.utc).isoformat()` with `datetime.now(ZoneInfo('America/New_York')).isoformat()`
- Add import: `from zoneinfo import ZoneInfo`

**Interface (unchanged):**
```python
def add_rejection(
    self,
    ticker: str,
    indicator: str,
    reason_long: Optional[str] = None,
    reason_short: Optional[str] = None,
    technical_indicators: Optional[Dict[str, Any]] = None
) -> None
```

### RejectionRecord Model

**Location:** `app/src/services/trading/validation/models.py`

**Changes:**
- Line 152: Replace default factory `lambda: datetime.now(timezone.utc).isoformat()` with `lambda: datetime.now(ZoneInfo('America/New_York')).isoformat()`
- Line 207: Replace fallback `datetime.now(timezone.utc).isoformat()` with `datetime.now(ZoneInfo('America/New_York')).isoformat()`
- Add import: `from zoneinfo import ZoneInfo`

**Interface (unchanged):**
```python
@dataclass
class RejectionRecord:
    ticker: str
    indicator: str
    reason_not_to_enter_long: Optional[str] = None
    reason_not_to_enter_short: Optional[str] = None
    technical_indicators: Optional[Dict[str, Any]] = None
    timestamp: str = field(default_factory=lambda: datetime.now(ZoneInfo('America/New_York')).isoformat())
```

### DynamoDBClient

**Location:** `app/src/db/dynamodb_client.py`

**Changes:**
- Line 800: Replace `datetime.now(timezone.utc).isoformat()` with `datetime.now(ZoneInfo('America/New_York')).isoformat()`
- Line 870-871: Replace cutoff calculation to use EST:
  ```python
  cutoff_time = datetime.now(ZoneInfo('America/New_York')) - timedelta(minutes=minutes_window)
  cutoff_timestamp = cutoff_time.isoformat()
  ```
- Add import: `from zoneinfo import ZoneInfo`

**Interface (unchanged):**
```python
@classmethod
async def log_inactive_ticker(
    cls,
    ticker: str,
    indicator: str,
    reason_not_to_enter_long: str,
    reason_not_to_enter_short: str,
    technical_indicators: Optional[Dict[str, Any]] = None
) -> bool

@classmethod
async def get_inactive_tickers_for_indicator(
    cls,
    indicator: str,
    minutes_window: int = 5
) -> List[Dict[str, Any]]
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

### RejectionRecord Structure (unchanged)

```python
{
    "ticker": str,
    "indicator": str,
    "timestamp": str,  # ISO 8601 with EST/EDT offset
    "reason_not_to_enter_long": Optional[str],
    "reason_not_to_enter_short": Optional[str],
    "technical_indicators": Optional[Dict[str, Any]]
}
```

## Correctness Properties

*A property is a characteristic or behavior that should hold true across all valid executions of a system-essentially, a formal statement about what the system should do. Properties serve as the bridge between human-readable specifications and machine-verifiable correctness guarantees.*

### Property 1: Timestamps use America/New_York timezone

*For any* rejection record created by RejectionCollector or DynamoDBClient, the timestamp should be in America/New_York timezone (indicated by -05:00 or -04:00 offset in ISO 8601 format).

**Validates: Requirements 1.1, 1.2**

### Property 2: Timestamp format is ISO 8601 with timezone

*For any* rejection record timestamp, parsing it as ISO 8601 should succeed and the parsed datetime should have timezone information (not naive).

**Validates: Requirements 1.3**

### Property 3: Time window cutoff uses America/New_York timezone

*For any* time window query, the cutoff timestamp should be calculated using America/New_York timezone, ensuring the time difference is measured in EST/EDT.

**Validates: Requirements 1.4**

### Property 4: Timezone-aware comparison correctness

*For any* two timestamps (one UTC, one EST) representing the same moment in time, comparing them should correctly account for timezone differences, with UTC timestamps being 4-5 hours ahead of EST timestamps.

**Validates: Requirements 1.5**

### Property 5: DST transition handling

*For any* timestamp generated during DST transition periods (spring forward, fall back), the system should use the correct offset (-04:00 for EDT, -05:00 for EST) based on the America/New_York timezone rules.

**Validates: Requirements 2.5**

## Error Handling

### Import Errors

If `zoneinfo` module is not available (Python < 3.9), the system should fail fast with a clear error message during import. However, since the project already uses Python 3.13 (based on mypy cache), this is not a concern.

### Timezone Data Errors

If timezone data for 'America/New_York' is unavailable, `ZoneInfo` will raise `ZoneInfoNotFoundError`. This should be caught and logged, but is unlikely in standard Python installations.

### Backward Compatibility

Existing UTC timestamps in the database will continue to work correctly because:
1. ISO 8601 format includes timezone offset information
2. DynamoDB string comparisons work correctly with ISO 8601 timestamps
3. Python's datetime parsing handles both UTC and EST timestamps

## Testing Strategy

### Unit Tests

1. **Test timestamp format**: Verify generated timestamps match ISO 8601 format with EST/EDT offset
2. **Test timezone extraction**: Parse generated timestamps and verify timezone is America/New_York
3. **Test cutoff calculation**: Verify time window calculations use EST timezone
4. **Test DST boundaries**: Create timestamps around DST transition dates and verify correct offsets

### Property-Based Tests

Property-based tests will use the Hypothesis library (already in use based on `.hypothesis` directory).

1. **Property 1 Test**: Generate random rejection records and verify all timestamps contain -05:00 or -04:00 offset
2. **Property 2 Test**: Generate random rejection records, parse timestamps, and verify they are timezone-aware
3. **Property 3 Test**: Generate random time windows, calculate cutoffs, and verify they use EST timezone
4. **Property 4 Test**: Generate pairs of UTC and EST timestamps for the same moment, verify comparison correctness
5. **Property 5 Test**: Generate timestamps across DST transition dates, verify correct offset usage

### Test Configuration

- Minimum 100 iterations per property test
- Use Hypothesis strategies for generating valid tickers, indicators, and time ranges
- Test both EST (-05:00) and EDT (-04:00) periods
- Test edge cases: midnight, market open/close times, DST transition moments

## Implementation Notes

### Import Statement

All three files will need:
```python
from zoneinfo import ZoneInfo
```

### Timezone Constant

Consider defining a constant for reusability:
```python
TRADING_TIMEZONE = ZoneInfo('America/New_York')
```

However, for this minimal change, inline usage is acceptable.

### No Database Migration Required

Since we're only changing how new timestamps are generated (not modifying existing data), no database migration is needed. Old UTC timestamps will coexist with new EST timestamps, and both will work correctly in queries due to ISO 8601 format.

### Performance Considerations

`ZoneInfo` caches timezone data after first access, so repeated calls to `ZoneInfo('America/New_York')` have minimal overhead. The performance impact is negligible compared to database operations.

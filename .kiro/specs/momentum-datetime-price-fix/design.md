# Design Document

## Overview

This design addresses the data structure mismatch between `TechnicalAnalysisLib.calculate_all_indicators()` and `MomentumIndicator._calculate_momentum()`. The root cause is that `datetime_price` is returned as a dictionary (timestamp string → price float) but the momentum calculation expects a list format. The fix involves updating the `_calculate_momentum` method to handle dictionary format by converting it to a sorted list of prices.

## Architecture

The fix is localized to the `MomentumIndicator` class in `app/src/services/trading/momentum_indicator.py`. No changes are needed to `TechnicalAnalysisLib` since the dictionary format is the correct output structure.

### Component Interaction

```
TechnicalAnalysisLib.calculate_all_indicators()
    ↓ (returns dict with datetime_price as dict)
MomentumIndicator._calculate_momentum()
    ↓ (converts dict to sorted list of prices)
Momentum calculation (early avg vs recent avg)
    ↓
Trade entry decision
```

## Components and Interfaces

### Modified Component: `MomentumIndicator._calculate_momentum`

**Current Signature:**
```python
@classmethod
def _calculate_momentum(cls, datetime_price: List[Any]) -> Tuple[float, str]
```

**Updated Signature:**
```python
@classmethod
def _calculate_momentum(cls, datetime_price: Union[List[Any], Dict[str, float]]) -> Tuple[float, str]
```

**Input:**
- `datetime_price`: Either a list of entries (legacy format) or a dict mapping timestamp strings to prices (current format)

**Output:**
- `Tuple[float, str]`: (momentum_score, reason_string)

**Behavior:**
1. Check if `datetime_price` is a dict
2. If dict: Extract prices sorted by timestamp
3. If list: Use existing extraction logic
4. Calculate momentum using early vs recent average comparison
5. Return momentum score and descriptive reason

### Helper Method: `_extract_prices_from_dict`

**New Method:**
```python
@classmethod
def _extract_prices_from_dict(cls, datetime_price_dict: Dict[str, float]) -> List[float]
```

**Purpose:** Convert datetime_price dictionary to sorted list of prices

**Input:**
- `datetime_price_dict`: Dictionary mapping ISO timestamp strings to price floats

**Output:**
- `List[float]`: Prices sorted chronologically (oldest to newest)

**Algorithm:**
1. Extract (timestamp, price) pairs from dict
2. Parse timestamp strings to datetime objects
3. Sort by datetime
4. Return list of prices in chronological order

## Data Models

### datetime_price Dictionary Format (Current)

```python
{
    "2024-12-08T09:30:00": 150.25,
    "2024-12-08T09:31:00": 150.30,
    "2024-12-08T09:32:00": 150.28,
    ...
}
```

### datetime_price List Format (Legacy)

```python
[
    ["2024-12-08T09:30:00", 150.25],
    ["2024-12-08T09:31:00", 150.30],
    {"timestamp": "2024-12-08T09:32:00", "price": 150.28},
    ...
]
```

### Momentum Calculation Data Flow

```
datetime_price (dict or list)
    ↓
prices: List[float] (sorted chronologically)
    ↓
early_prices: List[float] (first 1/3)
recent_prices: List[float] (last 1/3)
    ↓
early_avg: float
recent_avg: float
    ↓
change_percent: float = ((recent_avg - early_avg) / early_avg) * 100
trend_percent: float = (recent_trend / early_avg) * 100
    ↓
momentum_score: float = (0.7 * change_percent) + (0.3 * trend_percent)
```

## Correctness Properties

*A property is a characteristic or behavior that should hold true across all valid executions of a system-essentially, a formal statement about what the system should do. Properties serve as the bridge between human-readable specifications and machine-verifiable correctness guarantees.*

### Property 1: Dictionary extraction preserves chronological order

*For any* datetime_price dictionary with valid ISO timestamp keys, extracting prices should result in a list ordered from oldest to newest timestamp.

**Validates: Requirements 2.1, 2.4**

### Property 2: Format independence - consistent momentum across formats

*For any* price sequence, if represented as both a dictionary (timestamp → price) and a list format, the calculated momentum score should be identical.

**Validates: Requirements 1.1, 1.2, 2.1, 2.2**

### Property 3: Non-zero momentum for trending prices

*For any* datetime_price input with at least 3 prices showing a consistent upward or downward trend (>1% change), the momentum calculation should return a non-zero value.

**Validates: Requirements 1.3**

### Property 4: Momentum calculation uses correct time periods

*For any* valid datetime_price input with N prices (N >= 10), the momentum calculation should use the first max(1, N/3) prices for early average and the last max(1, N/3) prices for recent average.

**Validates: Requirements 2.5, 3.1**

## Error Handling

### Invalid datetime_price Format

**Scenario:** datetime_price is neither a dict nor a list, or contains invalid data

**Handling:**
- Log warning with actual type received
- Return (0.0, "Invalid datetime_price format: {type}")
- Continue processing other tickers

### Unparseable Timestamps

**Scenario:** Dictionary keys cannot be parsed as ISO timestamps

**Handling:**
- Skip invalid entries
- Log debug message for each skipped entry
- Continue with valid entries
- If no valid entries remain, return (0.0, "No valid timestamps in datetime_price")

### Missing or Invalid Prices

**Scenario:** Price values are None, negative, or non-numeric

**Handling:**
- Skip invalid price entries
- Log debug message
- Continue with valid prices
- If fewer than 3 valid prices, return (0.0, "Insufficient valid price data")

### Calculation Errors

**Scenario:** Division by zero or other arithmetic errors during momentum calculation

**Handling:**
- Catch exception
- Log error with ticker and details
- Return (0.0, "Error calculating momentum: {error_message}")

## Testing Strategy

### Unit Tests

1. **Test dict format parsing**
   - Input: datetime_price as dict with 10 entries
   - Expected: Prices extracted in chronological order

2. **Test list format parsing (backward compatibility)**
   - Input: datetime_price as list with mixed formats
   - Expected: Prices extracted correctly using existing logic

3. **Test insufficient data**
   - Input: datetime_price with 2 entries
   - Expected: (0.0, "Insufficient price data")

4. **Test empty input**
   - Input: Empty dict or empty list
   - Expected: (0.0, "Insufficient price data")

5. **Test momentum calculation**
   - Input: Prices showing 5% upward trend
   - Expected: Positive momentum score around 5%

6. **Test invalid timestamp handling**
   - Input: Dict with some invalid timestamp keys
   - Expected: Valid entries processed, invalid ones skipped

### Property-Based Tests

Property-based testing will use the Hypothesis library for Python to generate random test cases.

#### Property Test 1: Dictionary to list conversion preserves order
- **Property 1: Dictionary to list conversion preserves chronological order**
- Generate random datetime_price dicts with valid timestamps
- Convert to price list
- Verify prices are in chronological order
- **Validates: Requirements 2.1, 2.4**

#### Property Test 2: Format independence
- **Property 2: Momentum calculation produces consistent results regardless of input format**
- Generate random price sequences
- Create both dict and list representations
- Calculate momentum for both
- Verify results are identical
- **Validates: Requirements 1.1, 2.1, 2.2, 2.5**

#### Property Test 3: Insufficient data handling
- **Property 3: Insufficient data returns zero momentum**
- Generate datetime_price inputs with 0-2 entries
- Verify all return 0.0 momentum
- **Validates: Requirements 1.4, 1.5**

#### Property Test 4: Empty input handling
- **Property 4: Empty or invalid input returns zero momentum**
- Generate various invalid inputs (None, empty dict, empty list, invalid types)
- Verify all return 0.0 momentum with appropriate reason
- **Validates: Requirements 1.4, 2.3**

#### Property Test 5: Time period correctness
- **Property 5: Momentum calculation uses correct time periods**
- Generate datetime_price with N entries (N >= 10)
- Verify early period uses first N/3 prices
- Verify recent period uses last N/3 prices
- **Validates: Requirements 3.1**

### Integration Tests

1. **End-to-end momentum calculation**
   - Fetch real market data for a ticker
   - Calculate momentum
   - Verify non-zero result for active tickers

2. **Trade entry flow**
   - Mock market data with strong momentum
   - Verify ticker passes momentum filter
   - Verify trade entry is attempted

3. **Rejection logging**
   - Mock market data with weak momentum
   - Verify ticker is rejected
   - Verify rejection logged to InactiveTickersForDayTrading

## Implementation Notes

### Backward Compatibility

The updated `_calculate_momentum` method maintains backward compatibility by:
1. Checking input type before processing
2. Preserving existing list-based extraction logic
3. Only adding new dict-based extraction path

### Performance Considerations

- Dictionary sorting is O(n log n) where n is number of price points
- Typical n = 200 bars, so sorting overhead is negligible
- No caching needed since momentum is recalculated each cycle

### Logging Strategy

- **Debug level**: Successful parsing, number of prices extracted
- **Info level**: Momentum calculation results for tickers that pass filters
- **Warning level**: Unexpected datetime_price formats, parsing failures
- **Error level**: Exceptions during momentum calculation

### Code Location

All changes are in: `app/src/services/trading/momentum_indicator.py`

Methods to modify:
- `_calculate_momentum()` - Add dict format handling
- Add new helper: `_extract_prices_from_dict()` (optional, can inline)

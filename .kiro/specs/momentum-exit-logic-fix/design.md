# Design Document: Momentum Exit Logic Fix

## Overview

This design addresses critical bugs in the Momentum Trading Indicator's exit logic that cause premature exits and consistent losses. The fix modifies the "dip from peak" and "rise from bottom" profit-taking exit logic to:

1. Only trigger when the trade is actually profitable
2. Filter price bars to only include post-entry prices
3. Use a wider dip/rise threshold (1.0% instead of 0.5%)
4. Enforce a minimum holding time before profit-taking exits

## Architecture

The changes are localized to the `MomentumIndicator` class in `app/src/services/trading/momentum_indicator.py`. No new components are needed.

```
┌─────────────────────────────────────────────────────────────┐
│                    MomentumIndicator                         │
├─────────────────────────────────────────────────────────────┤
│  _run_exit_cycle()                                          │
│    ├── _filter_bars_after_entry() [NEW]                     │
│    ├── _calculate_peak_since_entry() [MODIFIED]             │
│    ├── _calculate_bottom_since_entry() [MODIFIED]           │
│    └── _should_trigger_profit_taking_exit() [NEW]           │
└─────────────────────────────────────────────────────────────┘
```

## Components and Interfaces

### Modified: `_run_exit_cycle()` method

The exit cycle will be modified to:
1. Filter bars to only include post-entry timestamps
2. Add profit threshold checks before profit-taking exits
3. Add minimum holding time check for profit-taking exits

### New: `_filter_bars_after_entry()` method

```python
@classmethod
def _filter_bars_after_entry(
    cls,
    bars: List[Dict[str, Any]],
    created_at: str
) -> List[Dict[str, Any]]:
    """
    Filter bars to only include those with timestamps after trade entry.
    
    Args:
        bars: List of bar dictionaries with 't' (timestamp) and 'c' (close) keys
        created_at: ISO timestamp string when trade was created
        
    Returns:
        List of bars with timestamps after created_at
    """
```

### New: `_should_trigger_profit_taking_exit()` method

```python
@classmethod
def _should_trigger_profit_taking_exit(
    cls,
    profit_from_entry: float,
    dip_or_rise_percent: float,
    holding_seconds: float,
    is_long: bool,
) -> Tuple[bool, str]:
    """
    Determine if profit-taking exit should trigger.
    
    Args:
        profit_from_entry: Current profit percentage from entry price
        dip_or_rise_percent: Percentage dip from peak (long) or rise from bottom (short)
        holding_seconds: Seconds since trade entry
        is_long: True for long trades, False for short trades
        
    Returns:
        Tuple of (should_exit: bool, reason: str)
    """
```

## Data Models

### New Configuration Constants

```python
# Profit-taking exit configuration
MIN_PROFIT_FOR_PROFIT_TAKING_EXIT: float = 0.5  # Minimum 0.5% profit required
DIP_RISE_THRESHOLD_PERCENT: float = 1.0  # 1.0% dip/rise threshold (was 0.5%)
MIN_HOLDING_SECONDS_FOR_PROFIT_TAKING: int = 60  # 60 seconds minimum hold time
```

## Correctness Properties

*A property is a characteristic or behavior that should hold true across all valid executions of a system-essentially, a formal statement about what the system should do. Properties serve as the bridge between human-readable specifications and machine-verifiable correctness guarantees.*

### Property 1: Profit-taking exits require positive profit

*For any* trade (long or short), when evaluating "dip from peak" or "rise from bottom" exit conditions, the exit should only trigger if profit_from_entry > 0.

**Validates: Requirements 1.1, 1.2, 1.3**

### Property 2: Peak/bottom calculation only uses post-entry bars

*For any* set of price bars and trade entry timestamp, the calculated peak_price_since_entry (for longs) or bottom_price_since_entry (for shorts) should only consider bars with timestamps strictly after the trade's created_at timestamp.

**Validates: Requirements 2.1, 2.2**

### Property 3: Minimum profit threshold enforced

*For any* trade with profit_from_entry < 0.5%, the profit-taking exit should not trigger regardless of dip/rise calculations.

**Validates: Requirements 3.1, 3.2**

### Property 4: Dip/rise threshold is 1.0% when profit threshold met

*For any* trade with profit_from_entry >= 0.5%, the dip/rise threshold used for exit evaluation should be 1.0% (not 0.5%).

**Validates: Requirements 3.3**

### Property 5: Profit-taking exits respect minimum holding time

*For any* trade held for less than 60 seconds, profit-taking exits ("dip from peak" or "rise from bottom") should not trigger, regardless of profit level or dip/rise calculations.

**Validates: Requirements 4.1, 4.2**

### Property 6: Stop loss still works during holding period

*For any* trade held for less than 60 seconds, if the loss exceeds the stop loss threshold, the stop loss exit should still trigger.

**Validates: Requirements 4.3**

## Error Handling

- If `created_at` timestamp is missing or invalid, use current time minus a safe buffer (e.g., 5 minutes) to avoid filtering out all bars
- If no bars remain after filtering, use entry price as initial peak/bottom
- Log warnings when profit-taking exits are skipped due to insufficient profit or holding time

## Testing Strategy

### Property-Based Testing

The implementation will use **Hypothesis** (Python's property-based testing library) to verify correctness properties.

Each property-based test will include a comment tag:
```python
# Feature: momentum-exit-logic-fix, Property N: [property description]
```

Property tests will run a minimum of 100 iterations to ensure coverage of edge cases.

### Unit Tests

Unit tests will cover:
- `_filter_bars_after_entry()` with various timestamp scenarios
- `_should_trigger_profit_taking_exit()` with boundary conditions
- Integration of the new logic into `_run_exit_cycle()`

### Test Data Generation

For property tests, generate:
- Random trade entry prices ($0.10 to $500)
- Random current prices (±20% from entry)
- Random bar data with timestamps spanning before and after entry
- Random holding times (0 to 300 seconds)

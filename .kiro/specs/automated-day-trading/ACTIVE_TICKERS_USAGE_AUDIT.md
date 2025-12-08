# ActiveTickersForAutomatedDayTrader Usage Audit

## Summary
Both `penny_stocks_indicator.py` and `momentum_indicator.py` are using `ActiveTickersForAutomatedDayTrader` correctly through the base class methods.

## How It Works

### Data Flow
1. **Entry**: Both indicators call `cls._enter_trade()` (inherited from `BaseTradingIndicator`)
2. **Storage**: `_enter_trade()` calls `DynamoDBClient.add_momentum_trade()`
3. **add_momentum_trade()** stores the trade in `ActiveTickersForAutomatedDayTrader` table with:
   - **Partition Key**: `ticker` (String)
   - **Attributes**: action, indicator, enter_price, enter_reason, technical_indicators_for_enter, dynamic_stop_loss, trailing_stop, peak_profit_percent, created_at

### Retrieval
- Both indicators call `cls._get_active_trades()` to fetch active trades
- This calls `DynamoDBClient.get_all_momentum_trades(indicator_name)`
- Filters trades by indicator name

### Exit
- Both indicators call `cls._exit_trade()` which:
  1. Calls `DynamoDBClient.delete_momentum_trade(ticker, indicator_name)` to remove from `ActiveTickersForAutomatedDayTrader`
  2. Calls `DynamoDBClient.add_completed_trade()` to move to `CompletedTradesForMarketData`

## Specific Usage in Each Indicator

### MomentumIndicator
**File**: `app/src/services/trading/momentum_indicator.py`

**Entry** (line ~1110):
```python
entry_success = await cls._enter_trade(
    ticker=ticker,
    action=action,
    enter_price=enter_price,
    enter_reason=ranked_reason,
    technical_indicators=technical_indicators_for_enter,
    dynamic_stop_loss=dynamic_stop_loss,
)
```

**Active Trades Retrieval** (line ~1009):
```python
active_trades = await cls._get_active_trades()
active_count = len(active_trades)
```

**Exit** (via base class):
- Calls `_exit_trade()` which handles deletion and completion

### PennyStocksIndicator
**File**: `app/src/services/trading/penny_stocks_indicator.py`

**Entry** (line ~1110):
```python
entry_success = await cls._enter_trade(
    ticker=ticker,
    action=action,
    enter_price=enter_price,
    enter_reason=ranked_reason,
    technical_indicators=technical_indicators,
    dynamic_stop_loss=-cls.trailing_stop_percent,  # 0.5% stop loss (tight)
)
```

**Post-Entry Update** (line ~1127):
```python
await DynamoDBClient.update_momentum_trade_trailing_stop(
    ticker=ticker,
    indicator=cls.indicator_name(),
    trailing_stop=cls.trailing_stop_percent,
    peak_profit_percent=0.0,
    current_profit_percent=0.0,
)
```

**Active Trades Retrieval** (line ~388):
```python
active_trades = await cls._get_active_trades()
active_count = len(active_trades)
```

**Exit** (via base class):
- Calls `_exit_trade()` which handles deletion and completion

## Correctness Assessment

✅ **CORRECT USAGE**

Both indicators correctly use `ActiveTickersForAutomatedDayTrader`:

1. **Consistent API**: Both use the same base class methods (`_enter_trade`, `_get_active_trades`, `_exit_trade`)
2. **Proper Storage**: Trades are stored with all required fields
3. **Proper Retrieval**: Trades are filtered by indicator name
4. **Proper Cleanup**: Trades are deleted on exit and moved to completed trades table
5. **Partition Key**: Both use `ticker` as partition key correctly
6. **Indicator Isolation**: Each indicator's trades are isolated by the `indicator` field

## Key Differences

### MomentumIndicator
- Uses dynamic stop loss calculated from ATR
- Does NOT update trailing stop after entry (relies on exit logic to manage it)

### PennyStocksIndicator
- Uses fixed tight stop loss (0.5%)
- **ADDITIONALLY** calls `update_momentum_trade_trailing_stop()` after entry to set initial trailing stop
- This is correct - it initializes the trailing stop for quick exits

## Potential Issues Found

None. Both indicators are using the table correctly.

## Recommendations

1. **No changes needed** - Current implementation is correct
2. Both indicators properly isolate their trades using the `indicator` field
3. The partition key (`ticker`) is appropriate for the access patterns
4. The base class abstraction ensures consistency across all indicators

## Related Files
- `app/src/db/dynamodb_client.py` - DynamoDB operations
- `app/src/services/trading/base_trading_indicator.py` - Base class with shared logic
- `app/src/services/trading/momentum_indicator.py` - Momentum indicator
- `app/src/services/trading/penny_stocks_indicator.py` - Penny stocks indicator

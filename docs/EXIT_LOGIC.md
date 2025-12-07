# Comprehensive Exit Logic Documentation

## Overview

The comprehensive exit logic is implemented in the `BaseTradingIndicator` class and provides a unified, reusable framework for all trading indicators to manage trade exits. The exit logic follows a priority-based approach to ensure trades are exited at the right time to protect capital and lock in profits.

## Exit Conditions (Priority Order)

### 1. Minimum Holding Period (Pre-check)
**Priority**: Highest (blocks all other checks)
**Purpose**: Prevent premature exits due to noise

- Checks if the trade has been held for the minimum required time
- Default: 30 seconds (configurable per indicator)
- If not met, no other exit conditions are evaluated
- Exception: Hard stop loss can still trigger even during holding period

**Implementation**: `_check_holding_period()`

### 2. Hard Stop Loss
**Priority**: 1 (Highest)
**Purpose**: Limit maximum loss on any trade

- Triggers when profit percentage falls below the stop loss threshold
- Uses dynamic stop loss if available (calculated from ATR)
- Default threshold: -2.5% (configurable per indicator)
- Always evaluated first to protect capital

**Requirements**: 6.1
**Implementation**: `_check_hard_stop_loss()`

**Example**:
```python
# Long position: bought at $100, current price $97
# Profit: -3%, Stop loss: -2.5%
# Result: EXIT (loss exceeds threshold)
```

### 3. End-of-Day Forced Closure
**Priority**: 2
**Purpose**: Close positions before market close to avoid overnight risk

- Triggers within 15 minutes of market close (4:00 PM ET)
- **Only exits profitable trades** - losing trades are held overnight
- Allows losing trades to potentially recover the next day
- Configurable minutes before close (default: 15)

**Requirements**: 6.4
**Implementation**: `_check_end_of_day_closure()`, `_is_near_market_close()`

**Example**:
```python
# Time: 3:46 PM ET (14 minutes before close)
# Trade profit: +2.5%
# Result: EXIT (profitable trade near close)

# Time: 3:46 PM ET (14 minutes before close)
# Trade profit: -1.5%
# Result: HOLD (losing trade, wait for recovery)
```

### 4. Trailing Stop
**Priority**: 3
**Purpose**: Protect profits by exiting when price moves against position

- Only activates after reaching profit threshold (default: 0.5%)
- Tracks peak profit percentage achieved during the trade
- Exits when profit drops by trailing stop distance from peak
- Uses ATR-based dynamic trailing stop when available
- Wider stops for short positions (1.5x multiplier)
- Cooldown period prevents premature activation (default: 30 seconds)

**Requirements**: 6.2, 6.3, 6.5
**Implementation**: `_check_trailing_stop_exit()`

**Example**:
```python
# Peak profit: 5.0%
# Current profit: 2.0%
# Trailing stop: 2.5%
# Drop from peak: 3.0% (5.0% - 2.0%)
# Result: EXIT (drop exceeds trailing stop)
```

## Main Entry Point

### `_should_exit_trade()`

Comprehensive exit logic check that evaluates all conditions in priority order.

**Parameters**:
- `trade`: Trade dictionary with ticker, action, enter_price, etc.
- `technical_indicators`: Optional technical indicators for ATR-based calculations

**Returns**:
- `should_exit`: Boolean indicating if trade should be exited
- `exit_reason`: String describing why exit was triggered (or None)
- `current_price`: Current market price for the ticker
- `profit_percent`: Current profit/loss percentage

**Usage Example**:
```python
trade = {
    "ticker": "AAPL",
    "action": "buy_to_open",
    "enter_price": 150.0,
    "peak_profit_percent": 3.5,
    "created_at": "2024-01-15T14:30:00Z",
    "dynamic_stop_loss": -2.8,
}

should_exit, reason, price, profit = await cls._should_exit_trade(
    trade, technical_indicators
)

if should_exit:
    await cls._exit_trade(...)
```

## Helper Methods

### `_get_current_price_for_exit()`
Gets the appropriate exit price from Alpaca API:
- **Long positions**: Uses bid price (selling to market makers)
- **Short positions**: Uses ask price (buying from market makers)

### `_calculate_profit_percent()`
Calculates profit percentage based on position direction:
- **Long**: `((current - enter) / enter) * 100`
- **Short**: `((enter - current) / enter) * 100`

### `_is_near_market_close()`
Checks if current time is within configured minutes of market close (4:00 PM ET).

## Configuration

All exit logic parameters are configurable at the indicator class level:

```python
class MyIndicator(BaseTradingIndicator):
    # Holding period
    min_holding_period_seconds: int = 30
    
    # Stop loss
    stop_loss_threshold: float = -2.5
    
    # End-of-day
    minutes_before_close_to_exit: int = 15
    
    # Trailing stop
    trailing_stop_activation_profit: float = 0.5
    trailing_stop_percent: float = 2.5
    trailing_stop_short_multiplier: float = 1.5
    trailing_stop_cooldown_seconds: int = 30
```

## ATR-Based Dynamic Stops

When technical indicators are provided, the exit logic uses ATR (Average True Range) for dynamic stop calculations:

### Stop Loss
- Base: 2.0x ATR (from `trading_config.py`)
- Capped between -4% and -8% for penny stocks
- Capped between -2.5% and -6% for standard stocks

### Trailing Stop
- Base: 1.5x ATR (from `trading_config.py`)
- Minimum: 2% (from `BASE_TRAILING_STOP_PERCENT`)
- Short positions: Multiplied by 1.5x (wider stops)
- Maximum for shorts: 4% (from `MAX_TRAILING_STOP_SHORT`)

## Integration with Indicators

All trading indicators should use the comprehensive exit logic in their `exit_service()` method:

```python
@classmethod
async def exit_service(cls):
    """Exit service - monitor trades and exit based on conditions"""
    while cls.running:
        if not await AlpacaClient.is_market_open():
            await asyncio.sleep(cls.exit_cycle_seconds)
            continue
        
        active_trades = await cls._get_active_trades()
        
        for trade in active_trades:
            # Get technical indicators
            indicators = await TechnicalAnalysisLib.calculate_all_indicators(
                trade["ticker"]
            )
            
            # Check exit conditions
            should_exit, reason, price, profit = await cls._should_exit_trade(
                trade, indicators
            )
            
            if should_exit:
                await cls._exit_trade(
                    ticker=trade["ticker"],
                    original_action=trade["action"],
                    enter_price=trade["enter_price"],
                    exit_price=price,
                    exit_reason=reason,
                    technical_indicators_enter=trade.get("technical_indicators_for_enter"),
                    technical_indicators_exit=indicators,
                )
            else:
                # Update peak profit and trailing stop in database
                if profit > trade.get("peak_profit_percent", 0):
                    await DynamoDBClient.update_momentum_trade_trailing_stop(
                        ticker=trade["ticker"],
                        indicator=cls.indicator_name(),
                        trailing_stop=...,
                        peak_profit_percent=profit,
                        skipped_exit_reason=f"Trade profitable: {profit:.2f}%",
                    )
        
        await asyncio.sleep(cls.exit_cycle_seconds)
```

## Testing

Comprehensive unit tests are provided in `tests/test_exit_logic.py`:

- Profit calculation (long and short)
- Holding period checks
- Hard stop loss triggering
- End-of-day closure (profitable vs losing)
- Trailing stop activation and triggering
- Current price retrieval (bid/ask)
- Comprehensive exit logic integration

Run tests:
```bash
python -m pytest tests/test_exit_logic.py -v
```

## Design Principles

1. **Priority-based**: Exit conditions are checked in order of importance
2. **Capital protection**: Stop loss is always checked first
3. **Profit protection**: Trailing stops lock in gains
4. **Risk management**: End-of-day closure prevents overnight risk on profitable trades
5. **Flexibility**: All parameters are configurable per indicator
6. **Reusability**: Shared logic in base class reduces code duplication
7. **Testability**: Comprehensive unit tests ensure correctness

## Requirements Validation

| Requirement | Description | Implementation |
|-------------|-------------|----------------|
| 6.1 | Hard stop loss exit | `_check_hard_stop_loss()` |
| 6.2 | Trailing stop activation at profit threshold | `_check_trailing_stop_exit()` with activation check |
| 6.3 | Trailing stop exit logic | `_check_trailing_stop_exit()` with drop from peak |
| 6.4 | End-of-day forced closure (15 min before close) | `_check_end_of_day_closure()` |
| 6.5 | Minimum holding period enforcement | `_check_holding_period()` |

All requirements are fully implemented and tested.

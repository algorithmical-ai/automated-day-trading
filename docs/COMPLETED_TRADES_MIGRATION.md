# CompletedTradesForAutomatedDayTrading Table Migration

## Overview
Migrated the `CompletedTradesForAutomatedDayTrading` table from storing individual trade records to an aggregated format.

## Previous Format (Individual Records)
Each completed trade was stored as a separate item:
```json
{
  "date": "2025-12-08",
  "ticker_indicator": "VGASW#Penny Stocks",
  "ticker": "VGASW",
  "indicator": "Penny Stocks",
  "action": "buy_to_open",
  "enter_price": 0.118,
  "exit_price": 0.116,
  "profit_or_loss": -33.89,
  ...
}
```

**Schema:**
- Partition key: `date`
- Sort key: `ticker_indicator`

## New Format (Aggregated Records)
One record per date+indicator containing all trades:
```json
{
  "date": "2025-11-22",
  "indicator": "Momentum Trading",
  "completed_trades": [
    {
      "ticker": "BMNR",
      "action": "SELL_TO_OPEN",
      "enter_price": 26.22,
      "exit_price": 26.5962,
      "profit_or_loss": -0.376,
      "technical_indicators_for_enter": {},
      "technical_indicators_for_exit": {...}
    }
  ],
  "completed_trade_count": 1,
  "overall_profit_loss": -0.376,
  "overall_profit_loss_long": 0,
  "overall_profit_loss_short": -0.376
}
```

**Schema:**
- Partition key: `date`
- Sort key: `indicator`

## Benefits
1. **Reduced Storage**: One record per date+indicator instead of one per trade
2. **Faster Queries**: Single query to get all trades for a date+indicator
3. **Aggregated Metrics**: Pre-calculated profit/loss totals
4. **Better Analytics**: Easy to track daily performance per indicator

## Changes Made

### 1. DynamoDB Client (`app/src/db/dynamodb_client.py`)
- Updated `add_completed_trade()` to use aggregated format
  - Fetches existing record for date+indicator
  - Appends new trade to `completed_trades` list
  - Updates aggregated metrics (count, profit/loss totals)
  - Separates long/short profit/loss tracking
- Updated `get_completed_trade_count()` to read from aggregated record

### 2. Table Creation Script (`scripts/create_dynamodb_tables.py`)
- Changed sort key from `ticker_indicator` to `indicator`
- Added documentation about aggregated format

### 3. Base Trading Indicator (`app/src/services/trading/base_trading_indicator.py`)
- No changes needed - uses same `add_completed_trade()` interface

## Migration Steps

### For Existing Tables
If you have existing data in the old format, you need to migrate it:

1. **Backup existing data:**
   ```bash
   aws dynamodb scan --table-name CompletedTradesForAutomatedDayTrading > backup.json
   ```

2. **Delete old table:**
   ```bash
   aws dynamodb delete-table --table-name CompletedTradesForAutomatedDayTrading
   ```

3. **Create new table:**
   ```bash
   python scripts/create_dynamodb_tables.py
   ```

4. **Migrate data (Python script):**
   ```python
   import json
   from collections import defaultdict
   
   # Load backup
   with open('backup.json') as f:
       data = json.load(f)
   
   # Group by date+indicator
   aggregated = defaultdict(lambda: {
       'completed_trades': [],
       'overall_profit_loss': 0,
       'overall_profit_loss_long': 0,
       'overall_profit_loss_short': 0
   })
   
   for item in data['Items']:
       date = item['date']['S']
       indicator = item['indicator']['S']
       key = (date, indicator)
       
       trade = {
           'ticker': item['ticker']['S'],
           'action': item['action']['S'],
           'enter_price': float(item['enter_price']['N']),
           'exit_price': float(item['exit_price']['N']),
           'profit_or_loss': float(item['profit_or_loss']['N']),
           # ... other fields
       }
       
       aggregated[key]['completed_trades'].append(trade)
       profit = float(item['profit_or_loss']['N'])
       aggregated[key]['overall_profit_loss'] += profit
       
       if item['action']['S'].upper() in ['BUY_TO_OPEN', 'SELL_TO_CLOSE']:
           aggregated[key]['overall_profit_loss_long'] += profit
       else:
           aggregated[key]['overall_profit_loss_short'] += profit
   
   # Write aggregated records
   for (date, indicator), data in aggregated.items():
       data['completed_trade_count'] = len(data['completed_trades'])
       # Use DynamoDBClient.add_completed_trade() for each trade
   ```

### For New Deployments
Simply run:
```bash
python scripts/create_dynamodb_tables.py
```

## Testing
All 176 tests pass with the new format:
```bash
pytest tests/ -v
```

## Backward Compatibility
⚠️ **Breaking Change**: This is a breaking change. Old code expecting individual records will not work with the new aggregated format.

If you need to support both formats temporarily, you can:
1. Check if `completed_trades` field exists
2. If yes, use new format
3. If no, use old format

## Rollback
To rollback:
1. Restore from backup
2. Revert changes to `app/src/db/dynamodb_client.py`
3. Revert changes to `scripts/create_dynamodb_tables.py`
4. Redeploy

## Date
December 8, 2025

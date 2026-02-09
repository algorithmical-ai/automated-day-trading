# Trading Indicators Backtesting Script

This script allows you to backtest various technical indicators using historical data from Alpaca's API.

## Features

- **Multiple Indicators**: Supports RSI, MACD, Bollinger Bands, Stochastic, CCI, and Williams %R
- **Historical Data**: Fetches minute-level historical data from Alpaca
- **CSV Output**: Generates detailed CSV files with buy/sell signals
- **Flexible Time Periods**: Test any date range from 2022-2025
- **Multiple Tickers**: Backtest multiple symbols simultaneously

## Setup

1. **Install Dependencies**:
```bash
pip install requests python-dotenv
```

2. **Configure Environment Variables**:
   - Copy `.env.example` to `.env`
   - Fill in your Alpaca API credentials:
   ```bash
   cp .env.example .env
   # Edit .env with your actual API keys
   ```

3. **Get Alpaca API Keys**:
   - Sign up at [Alpaca](https://alpaca.markets/)
   - Get your API key and secret key from the dashboard
   - Add them to your `.env` file

## Usage

### Basic Usage

```bash
python scripts/backtest_indicators.py \
    --start-date 2022-01-01 \
    --end-date 2022-12-31 \
    --tickers AAPL TSLA MSFT \
    --indicators RSI MACD Bollinger \
    --output results_2022.csv
```

### Advanced Usage

```bash
# Test all indicators for multiple stocks over 3 years
python scripts/backtest_indicators.py \
    --start-date 2022-01-01 \
    --end-date 2025-01-01 \
    --tickers AAPL TSLA MSFT GOOGL AMZN \
    --indicators RSI MACD Bollinger Stochastic CCI Williams_R \
    --output comprehensive_backtest.csv

# Test specific indicators
python scripts/backtest_indicators.py \
    --start-date 2023-06-01 \
    --end-date 2023-12-31 \
    --tickers AAPL \
    --indicators RSI MACD \
    --output aapl_rsi_macd.csv
```

## Parameters

- `--start-date`: Start date in YYYY-MM-DD format (required)
- `--end-date`: End date in YYYY-MM-DD format (required)  
- `--tickers`: List of ticker symbols (default: AAPL TSLA)
- `--indicators`: Indicators to test (default: all available)
  - Available: RSI, MACD, Bollinger, Stochastic, CCI, Williams_R
- `--output`: Output CSV filename (default: backtest_results.csv)

## Indicator Strategies

### RSI (Relative Strength Index)
- **Buy Signal**: RSI < 30 (oversold condition)
- **Sell Signal**: RSI > 70 (overbought condition)

### MACD (Moving Average Convergence Divergence)
- **Buy Signal**: Histogram crosses above zero (bullish crossover)
- **Sell Signal**: Histogram crosses below zero (bearish crossover)

### Bollinger Bands
- **Buy Signal**: Price touches or falls below lower band
- **Sell Signal**: Price touches or rises above upper band

### Stochastic Oscillator
- **Buy Signal**: %K < 20 (oversold)
- **Sell Signal**: %K > 80 (overbought)

### CCI (Commodity Channel Index)
- **Buy Signal**: CCI < -100 (oversold)
- **Sell Signal**: CCI > 100 (overbought)

### Williams %R
- **Buy Signal**: Williams %R < -80 (oversold)
- **Sell Signal**: Williams %R > -20 (overbought)

## Output Format

The CSV file contains the following columns:

- `timestamp`: When the signal was generated
- `ticker`: Stock symbol
- `action`: Trade action (buy_to_open or sell_to_open)
- `price`: Price at signal time
- `indicator`: Which indicator generated the signal
- `signal_type`: Type of signal (entry)
- `reason`: Detailed explanation of the signal
- `rsi`, `macd`, `bollinger_*`, `stoch_*`, etc.: Indicator values at signal time

## Example Output

```csv
timestamp,ticker,action,price,indicator,signal_type,reason,rsi,macd,...
2022-01-03T09:30:00Z,AAPL,buy_to_open,175.43,RSI,entry,RSI oversold: 28.45,28.45,...
2022-01-03T10:15:00Z,TSLA,sell_to_open,950.21,MACD,entry,MACD bearish crossover: hist -0.1234,...
```

## Rate Limits

- Alpaca API has rate limits (200 requests per minute)
- The script includes rate limiting and batch processing
- For long time periods, the script automatically splits requests into batches

## Performance Tips

1. **Start Small**: Test with short time periods first
2. **Limit Tickers**: More tickers = more API calls
3. **Choose Indicators**: Testing all indicators takes longer
4. **Consider Timeframes**: Minute data generates lots of points

## Troubleshooting

### Common Issues

1. **API Key Errors**:
   - Ensure `.env` file is properly configured
   - Check that API keys are valid and active

2. **No Data Available**:
   - Some tickers may not have data for the requested period
   - Check if the ticker was trading during that time

3. **Rate Limiting**:
   - If you hit rate limits, wait and try again
   - Reduce the number of tickers or shorten the time period

4. **Memory Issues**:
   - Very long time periods with minute data can use significant memory
   - Consider breaking into smaller chunks

## Example Results Analysis

After running the backtest, you can analyze the CSV file to:

1. **Count signals per indicator**: See which indicators are most active
2. **Analyze timing**: Look at when signals occur
3. **Compare performance**: Different indicators for different stocks
4. **Identify patterns**: Market conditions that trigger signals

## Notes

- This script generates entry signals only (no exit strategies)
- All signals are based on standard technical analysis thresholds
- Real-world trading should include additional risk management
- Past performance does not guarantee future results

## Support

For issues with:
- **Alpaca API**: Check Alpaca documentation
- **Script errors**: Verify dependencies and environment setup
- **Data issues**: Ensure tickers and date ranges are valid

# Requirements Document

## Introduction

This specification defines the trade entry validation logic for the Momentum Trading Indicator system. The system analyzes stocks using technical indicators and determines whether to enter positions based on tradability filters including liquidity, volatility, and security type. Unlike directional indicators, the Momentum Indicator uses symmetric validation where rejections apply to both long and short positions equally.

## Glossary

- **Momentum Trading**: Trading strategy based on technical indicators and market momentum
- **Long Entry**: Buying a stock with the expectation that its price will increase
- **Short Entry**: Selling a stock short with the expectation that its price will decrease
- **Volume Ratio**: Current volume divided by volume SMA (Simple Moving Average)
- **ATR (Average True Range)**: Measure of volatility
- **ATR Percentage**: ATR divided by current price, expressed as percentage
- **Volume SMA**: Simple Moving Average of volume over a period
- **Warrant/Derivative**: Special securities like warrants, rights, or units (identified by ticker suffix)
- **InactiveTickersForDayTrading**: DynamoDB table storing tickers that failed entry validation with rejection reasons
- **Valid Entry**: A direction (long or short) where the rejection reason field is an empty string ("")
- **Symmetric Rejection**: Rejection that applies to both long and short directions equally

## Requirements

### Requirement 1

**User Story:** As a trading system, I want to filter out warrants and derivative securities, so that I only trade standard equity securities.

#### Acceptance Criteria

1. WHEN a ticker ends with "W" THEN the system SHALL reject both long and short entry with reason "Excluded: {TICKER} is a warrant/option (ends with W/R/RT/etc)"
2. WHEN a ticker ends with "R" THEN the system SHALL reject both long and short entry with the same exclusion reason
3. WHEN a ticker ends with "RT" THEN the system SHALL reject both long and short entry with the same exclusion reason
4. WHEN a ticker ends with "WS" THEN the system SHALL reject both long and short entry with the same exclusion reason
5. WHEN a ticker is excluded as a warrant/derivative THEN the system SHALL apply the same rejection reason to both reason_not_to_enter_long and reason_not_to_enter_short

### Requirement 2

**User Story:** As a trading system, I want to validate minimum price levels, so that I avoid extremely low-priced stocks that are too risky.

#### Acceptance Criteria

1. WHEN close price is less than $0.10 THEN the system SHALL reject both long and short entry
2. WHEN recording price rejection THEN the system SHALL include the actual price and threshold ($0.10) in the reason as "Price too low: ${price} < $0.10 minimum (too risky)"
3. WHEN price is too low THEN the system SHALL apply the same rejection reason to both reason_not_to_enter_long and reason_not_to_enter_short
4. WHEN close price is greater than or equal to $0.10 THEN the system SHALL not reject based on price
5. WHEN price validation fails THEN the system SHALL include the price value in the rejection reason

### Requirement 3

**User Story:** As a trading system, I want to validate absolute volume levels, so that I avoid stocks with insufficient trading activity.

#### Acceptance Criteria

1. WHEN volume is less than 500 THEN the system SHALL reject both long and short entry
2. WHEN recording volume rejection THEN the system SHALL include the actual volume and threshold (500) in the reason as "Volume too low: {vol} < 500 minimum"
3. WHEN volume is too low THEN the system SHALL apply the same rejection reason to both reason_not_to_enter_long and reason_not_to_enter_short
4. WHEN volume is greater than or equal to 500 THEN the system SHALL not reject based on absolute volume
5. WHEN volume validation fails THEN the system SHALL include the volume value in the rejection reason

### Requirement 4

**User Story:** As a trading system, I want to validate volume ratio against SMA, so that I only trade during periods of elevated trading activity.

#### Acceptance Criteria

1. WHEN volume ratio (volume / volume_sma) is less than 1.5 THEN the system SHALL reject both long and short entry
2. WHEN calculating volume ratio THEN the system SHALL divide current volume by volume SMA
3. WHEN recording volume ratio rejection THEN the system SHALL include the ratio, current volume, and SMA in the reason as "Volume ratio too low: {ratio}x < 1.5x SMA (volume: {vol}, SMA: {sma})"
4. WHEN volume ratio is too low THEN the system SHALL apply the same rejection reason to both reason_not_to_enter_long and reason_not_to_enter_short
5. WHEN volume SMA is zero or negative THEN the system SHALL reject with reason "Invalid volume SMA"

### Requirement 5

**User Story:** As a trading system, I want to validate volatility levels, so that I avoid excessively volatile stocks that are too risky.

#### Acceptance Criteria

1. WHEN ATR percentage exceeds 5.0% THEN the system SHALL reject both long and short entry
2. WHEN calculating ATR percentage THEN the system SHALL divide ATR by close price and multiply by 100
3. WHEN recording volatility rejection THEN the system SHALL include the ATR percentage and limit in the reason as "Too volatile: ATR: {atr_pct}% (exceeds {limit}% limit)"
4. WHEN volatility is too high THEN the system SHALL apply the same rejection reason to both reason_not_to_enter_long and reason_not_to_enter_short
5. WHEN close price is zero or negative THEN the system SHALL reject with reason "Invalid price for ATR calculation"

### Requirement 6

**User Story:** As a trading system, I want to store rejection reasons and technical indicators in a structured format, so that I can analyze patterns and improve the trading strategy over time.

#### Acceptance Criteria

1. WHEN a ticker is evaluated THEN the system SHALL write a record to InactiveTickersForDayTrading table
2. WHEN writing records THEN the system SHALL include ticker symbol, indicator name ("Momentum Trading"), timestamp, and technical_indicators JSON
3. WHEN a ticker passes all validation THEN the system SHALL set both reason_not_to_enter_long and reason_not_to_enter_short to empty strings ("")
4. WHEN a ticker fails validation THEN the system SHALL populate both reason fields with the same rejection message (symmetric rejection)
5. WHEN storing technical indicators THEN the system SHALL include RSI, MACD, Bollinger Bands, ADX, EMA, volume metrics, and other technical analysis data

### Requirement 7

**User Story:** As a trading system, I want to calculate comprehensive technical indicators, so that I can provide rich data for analysis even when trades are rejected.

#### Acceptance Criteria

1. WHEN calculating technical indicators THEN the system SHALL compute RSI (Relative Strength Index)
2. WHEN calculating technical indicators THEN the system SHALL compute MACD (Moving Average Convergence Divergence) with 3 values
3. WHEN calculating technical indicators THEN the system SHALL compute Bollinger Bands with 3 values (upper, middle, lower)
4. WHEN calculating technical indicators THEN the system SHALL compute ADX (Average Directional Index)
5. WHEN calculating technical indicators THEN the system SHALL compute volume-based indicators (volume_sma, OBV, MFI, A/D)
6. WHEN calculating technical indicators THEN the system SHALL compute momentum indicators (Stochastic, CCI, Williams %R, ROC)
7. WHEN calculating technical indicators THEN the system SHALL compute price averages (EMA fast/slow, VWAP, VWMA, WMA)
8. WHEN calculating technical indicators THEN the system SHALL include ATR for volatility measurement
9. WHEN storing technical indicators THEN the system SHALL include datetime_price array with timestamp-price tuples
10. WHEN storing technical indicators THEN the system SHALL include current volume and close_price

### Requirement 8

**User Story:** As a trading system, I want to batch write all ticker evaluations efficiently, so that I minimize database operations and improve performance.

#### Acceptance Criteria

1. WHEN processing multiple tickers in an entry cycle THEN the system SHALL collect all evaluation records before writing to the database
2. WHEN the entry cycle completes THEN the system SHALL write all collected records in a single batch operation
3. WHEN batch writing fails THEN the system SHALL log the error without blocking the entry cycle
4. WHEN collecting records THEN the system SHALL include both passing tickers (empty rejection reasons) and failing tickers (populated rejection reasons)
5. WHEN a ticker passes validation THEN the system SHALL write a record with both reason fields as empty strings

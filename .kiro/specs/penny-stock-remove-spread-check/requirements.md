# Requirements Document

## Introduction

This specification defines the removal of bid-ask spread validation from the Penny Stock Indicator system. The system currently validates liquidity through bid-ask spread checks before entering trades. However, for penny stocks traded on momentum strategies where entries and exits happen quickly, the bid-ask spread check is overly restrictive and prevents capturing profitable momentum opportunities. This change removes the spread validation to allow the system to ride momentum for both long and short trades without liquidity constraints.

## Glossary

- **Penny Stock**: A stock with a price below $5.00 USD
- **Momentum Trading**: A trading strategy that enters and exits positions quickly based on price momentum
- **Bid-Ask Spread**: The difference between the highest price a buyer is willing to pay (bid) and the lowest price a seller is willing to accept (ask)
- **Long Entry**: Buying a stock with the expectation that its price will increase
- **Short Entry**: Selling a stock short with the expectation that its price will decrease
- **Momentum Score**: A calculated value representing the strength and direction of price movement over recent bars
- **LiquidityRule**: The validation rule class that checks bid-ask spread percentage
- **ValidationPipeline**: The sequence of validation rules applied to determine trade entry eligibility

## Requirements

### Requirement 1

**User Story:** As a momentum trader, I want to remove bid-ask spread validation from penny stock entries, so that I can capture fast momentum opportunities without liquidity restrictions.

#### Acceptance Criteria

1. WHEN validating a ticker for entry THEN the system SHALL NOT check bid-ask spread percentage
2. WHEN the validation pipeline executes THEN the system SHALL NOT include LiquidityRule in the rule sequence
3. WHEN a ticker has a wide bid-ask spread THEN the system SHALL still allow entry if momentum criteria are met
4. WHEN calculating entry price THEN the system SHALL continue to use bid price for long exits and ask price for short exits
5. WHEN logging validation results THEN the system SHALL NOT include bid-ask spread information in rejection reasons

### Requirement 2

**User Story:** As a trading system, I want to validate entries based solely on momentum direction, so that the validation logic is simplified and focused on trend-following.

#### Acceptance Criteria

1. WHEN validating a ticker for long entry THEN the system SHALL only check that momentum score is positive
2. WHEN validating a ticker for short entry THEN the system SHALL only check that momentum score is negative
3. WHEN momentum score is positive THEN the system SHALL allow long entry regardless of bid-ask spread
4. WHEN momentum score is negative THEN the system SHALL allow short entry regardless of bid-ask spread
5. WHEN momentum score is zero THEN the system SHALL reject both long and short entries

### Requirement 3

**User Story:** As a trading system, I want to maintain existing data quality and trend validation rules, so that only the spread check is removed without affecting other validation logic.

#### Acceptance Criteria

1. WHEN validating a ticker THEN the system SHALL continue to apply DataQualityRule to ensure sufficient bars
2. WHEN validating a ticker THEN the system SHALL continue to apply TrendDirectionRule to validate momentum direction
3. WHEN validating a ticker THEN the system SHALL continue to apply ContinuationRule to check trend consistency
4. WHEN validating a ticker THEN the system SHALL continue to apply PriceExtremeRule to avoid extreme price movements
5. WHEN validating a ticker THEN the system SHALL continue to apply MomentumThresholdRule to ensure momentum is within acceptable range

### Requirement 4

**User Story:** As a trading system, I want to remove spread-related code from the entry validation flow, so that the codebase is cleaner and easier to maintain.

#### Acceptance Criteria

1. WHEN creating the validation rule list THEN the system SHALL NOT instantiate LiquidityRule
2. WHEN the _passes_filters method executes THEN the system SHALL NOT calculate bid-ask spread percentage
3. WHEN the _passes_filters method executes THEN the system SHALL NOT compare spread percentage against max_bid_ask_spread_percent threshold
4. WHEN the _passes_filters method executes THEN the system SHALL NOT return rejection reasons related to bid-ask spread
5. WHEN the _process_ticker_entry method executes THEN the system SHALL NOT check spread before entering trades

### Requirement 5

**User Story:** As a trading system, I want to maintain the existing rejection record structure, so that database schema and analysis tools remain compatible.

#### Acceptance Criteria

1. WHEN writing rejection records THEN the system SHALL continue to use the same InactiveTickersForDayTrading table structure
2. WHEN writing rejection records THEN the system SHALL continue to include ticker, indicator, timestamp, and technical_indicators fields
3. WHEN writing rejection records THEN the system SHALL continue to populate reason_not_to_enter_long and reason_not_to_enter_short fields
4. WHEN a ticker is rejected THEN the system SHALL NOT include spread-related information in rejection reasons
5. WHEN storing technical indicators THEN the system SHALL continue to include momentum_score, continuation_score, peak_price, and bottom_price

### Requirement 6

**User Story:** As a developer, I want to update property-based tests to reflect the removal of spread validation, so that the test suite accurately validates the new behavior.

#### Acceptance Criteria

1. WHEN running property-based tests THEN the system SHALL NOT test spread-related validation properties
2. WHEN running property-based tests THEN the system SHALL continue to test momentum-based validation properties
3. WHEN generating test data THEN the system SHALL NOT need to generate bid-ask spread values
4. WHEN testing validation results THEN the system SHALL verify that spread does not affect entry decisions
5. WHEN testing rejection reasons THEN the system SHALL verify that no spread-related text appears in rejection messages

### Requirement 7

**User Story:** As a trading system, I want to maintain backward compatibility with existing configuration, so that deployment is seamless without configuration changes.

#### Acceptance Criteria

1. WHEN the system starts THEN the system SHALL ignore the max_bid_ask_spread_percent configuration parameter
2. WHEN the system starts THEN the system SHALL continue to use other configuration parameters unchanged
3. WHEN the system processes entries THEN the system SHALL not require any configuration file updates
4. WHEN the system logs information THEN the system SHALL not reference spread-related configuration values
5. WHEN the system operates THEN the system SHALL maintain the same entry_cycle_seconds and exit_cycle_seconds timing

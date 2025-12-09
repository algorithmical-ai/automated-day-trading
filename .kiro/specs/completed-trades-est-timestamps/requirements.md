# Requirements Document

## Introduction

This document specifies the requirements for converting exit_timestamp storage in the CompletedTradesForAutomatedDayTrading DynamoDB table from GMT (UTC) timezone to EST (America/New_York) timezone. Currently, exit_timestamp is generated in UTC format when trades are completed. Since the trading system operates on US market hours (EST/EDT), storing exit timestamps in EST will improve readability and alignment with trading operations. Additionally, this document verifies that enter_timestamp is correctly copied from the created_at field of ActiveTickersForAutomatedDayTrader records for all trading indicators.

## Glossary

- **CompletedTradesForAutomatedDayTrading**: DynamoDB table storing aggregated completed trades per date and indicator
- **ActiveTickersForAutomatedDayTrader**: DynamoDB table storing active trades with created_at timestamp
- **exit_timestamp**: ISO 8601 formatted datetime string representing when a trade was exited
- **enter_timestamp**: ISO 8601 formatted datetime string representing when a trade was entered
- **created_at**: Timestamp field in ActiveTickersForAutomatedDayTrader table that records trade entry time
- **GMT/UTC**: Greenwich Mean Time / Coordinated Universal Time (timezone offset +00:00)
- **EST/EDT**: Eastern Standard Time / Eastern Daylight Time (America/New_York timezone, automatically handles DST)
- **BaseTradingIndicator**: Base class for all trading indicators that handles trade entry and exit logic
- **DynamoDBClient**: Client component providing database operations including add_completed_trade method
- **Completed Trade Record**: A database record containing ticker, action, enter/exit prices, timestamps, profit/loss, and technical indicators

## Requirements

### Requirement 1

**User Story:** As a trading system operator, I want completed trade exit timestamps stored in EST timezone, so that I can easily correlate trade exits with market hours and trading events.

#### Acceptance Criteria

1. WHEN BaseTradingIndicator exits a trade THEN the system SHALL generate exit_timestamp in America/New_York timezone
2. WHEN exit_timestamp is stored in CompletedTradesForAutomatedDayTrading THEN the system SHALL format it as ISO 8601 with timezone offset
3. WHEN the system logs a completed trade THEN the system SHALL include timezone information in the exit_timestamp
4. WHEN displaying or analyzing exit timestamps THEN the system SHALL preserve the timezone information in the ISO 8601 format
5. WHEN the system handles daylight saving time transitions THEN the system SHALL automatically adjust between EST and EDT for exit timestamps

### Requirement 2

**User Story:** As a developer, I want to verify that enter_timestamp is correctly copied from created_at for all indicators, so that trade entry times are accurately recorded in completed trades.

#### Acceptance Criteria

1. WHEN BaseTradingIndicator exits a trade THEN the system SHALL retrieve the created_at timestamp from the active trade record
2. WHEN the active trade record contains created_at THEN the system SHALL use it as enter_timestamp for the completed trade
3. WHEN the active trade record is missing created_at THEN the system SHALL use current time in America/New_York timezone as fallback
4. WHEN enter_timestamp is stored in CompletedTradesForAutomatedDayTrading THEN the system SHALL preserve the original timezone information from created_at
5. WHEN multiple trading indicators exit trades THEN the system SHALL consistently copy created_at to enter_timestamp for all indicators

### Requirement 3

**User Story:** As a quality assurance engineer, I want property-based tests to verify timestamp correctness, so that I can ensure the timestamp conversion works correctly across all trading scenarios.

#### Acceptance Criteria

1. WHEN property tests generate random completed trades THEN the system SHALL verify exit_timestamp uses America/New_York timezone
2. WHEN property tests verify timestamp format THEN the system SHALL confirm ISO 8601 format with timezone offset for both enter and exit timestamps
3. WHEN property tests validate trade exit operations THEN the system SHALL ensure exit_timestamp is always later than enter_timestamp
4. WHEN property tests check enter_timestamp copying THEN the system SHALL verify it matches the created_at from active trade
5. WHEN property tests run during DST transitions THEN the system SHALL verify correct EST/EDT handling for exit timestamps

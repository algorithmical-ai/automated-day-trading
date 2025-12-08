# Requirements Document

## Introduction

This document specifies the requirements for converting timestamp storage in the InactiveTickersForDayTrading DynamoDB table from GMT (UTC) timezone to EST (America/New_York) timezone. Currently, all timestamps for inactive ticker rejection records are stored in UTC format. Since the trading system operates on US market hours (EST/EDT), storing timestamps in EST will improve readability and alignment with trading operations.

## Glossary

- **InactiveTickersForDayTrading**: DynamoDB table storing tickers that were evaluated but not traded, with rejection reasons
- **Timestamp**: ISO 8601 formatted datetime string stored as the sort key in InactiveTickersForDayTrading table
- **GMT/UTC**: Greenwich Mean Time / Coordinated Universal Time (timezone offset +00:00)
- **EST/EDT**: Eastern Standard Time / Eastern Daylight Time (America/New_York timezone, automatically handles DST)
- **Rejection Record**: A database record containing ticker symbol, indicator name, rejection reasons, technical indicators, and timestamp
- **RejectionCollector**: Service component that accumulates rejection records during an entry cycle
- **InactiveTickerRepository**: Repository component that performs batch writes to InactiveTickersForDayTrading table
- **DynamoDBClient**: Client component providing database operations including log_inactive_ticker method

## Requirements

### Requirement 1

**User Story:** As a trading system operator, I want inactive ticker timestamps stored in EST timezone, so that I can easily correlate rejection records with market hours and trading events.

#### Acceptance Criteria

1. WHEN the RejectionCollector creates a new rejection record THEN the system SHALL generate the timestamp in America/New_York timezone
2. WHEN the DynamoDBClient logs an inactive ticker THEN the system SHALL generate the timestamp in America/New_York timezone
3. WHEN a timestamp is stored in InactiveTickersForDayTrading THEN the system SHALL format it as ISO 8601 with timezone offset
4. WHEN the system queries inactive tickers by time window THEN the system SHALL calculate cutoff timestamps using America/New_York timezone
5. WHEN comparing timestamps for filtering THEN the system SHALL handle timezone-aware comparisons correctly

### Requirement 2

**User Story:** As a developer, I want consistent timezone handling across all inactive ticker operations, so that the system behavior is predictable and maintainable.

#### Acceptance Criteria

1. WHEN any component creates a timestamp for inactive tickers THEN the system SHALL use America/New_York timezone
2. WHEN the RejectionRecord model generates a default timestamp THEN the system SHALL use America/New_York timezone
3. WHEN the system reads existing UTC timestamps THEN the system SHALL continue to function correctly during the transition period
4. WHEN displaying or logging timestamps THEN the system SHALL preserve the timezone information in the ISO 8601 format
5. WHEN the system handles daylight saving time transitions THEN the system SHALL automatically adjust between EST and EDT

### Requirement 3

**User Story:** As a quality assurance engineer, I want property-based tests to verify timezone correctness, so that I can ensure the timestamp conversion works correctly across all scenarios.

#### Acceptance Criteria

1. WHEN property tests generate random rejection records THEN the system SHALL verify all timestamps use America/New_York timezone
2. WHEN property tests verify timestamp format THEN the system SHALL confirm ISO 8601 format with timezone offset
3. WHEN property tests check time window queries THEN the system SHALL verify cutoff calculations use America/New_York timezone
4. WHEN property tests validate round-trip operations THEN the system SHALL ensure timezone information is preserved
5. WHEN property tests run during DST transitions THEN the system SHALL verify correct EST/EDT handling

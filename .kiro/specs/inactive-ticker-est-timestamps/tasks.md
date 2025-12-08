# Implementation Plan

- [x] 1. Update RejectionCollector to use EST timezone
  - Modify `app/src/services/trading/validation/rejection_collector.py`
  - Add import: `from zoneinfo import ZoneInfo`
  - Replace `datetime.now(timezone.utc).isoformat()` with `datetime.now(ZoneInfo('America/New_York')).isoformat()` on line 63
  - _Requirements: 1.1_

- [ ]* 1.1 Write property test for RejectionCollector timestamps
  - **Property 1: Timestamps use America/New_York timezone**
  - **Validates: Requirements 1.1**
  - Generate random rejection records using RejectionCollector
  - Verify all timestamps contain -05:00 or -04:00 offset
  - Verify timestamps parse as timezone-aware datetimes with America/New_York timezone

- [x] 2. Update RejectionRecord model to use EST timezone
  - Modify `app/src/services/trading/validation/models.py`
  - Add import: `from zoneinfo import ZoneInfo`
  - Replace default factory on line 152: `lambda: datetime.now(ZoneInfo('America/New_York')).isoformat()`
  - Replace fallback on line 207: `datetime.now(ZoneInfo('America/New_York')).isoformat()`
  - _Requirements: 1.1_

- [ ]* 2.1 Write property test for RejectionRecord timestamp format
  - **Property 2: Timestamp format is ISO 8601 with timezone**
  - **Validates: Requirements 1.3**
  - Generate random RejectionRecord instances
  - Parse timestamps using datetime.fromisoformat()
  - Verify parsed datetimes have timezone information (not naive)
  - Verify timezone offset is -05:00 or -04:00

- [x] 3. Update DynamoDBClient to use EST timezone
  - Modify `app/src/db/dynamodb_client.py`
  - Add import: `from zoneinfo import ZoneInfo`
  - Replace timestamp generation on line 800: `datetime.now(ZoneInfo('America/New_York')).isoformat()`
  - Update cutoff calculation on lines 870-871 to use `datetime.now(ZoneInfo('America/New_York'))`
  - _Requirements: 1.2, 1.4_

- [ ]* 3.1 Write property test for DynamoDBClient log_inactive_ticker
  - **Property 1: Timestamps use America/New_York timezone**
  - **Validates: Requirements 1.2**
  - Generate random ticker and indicator combinations
  - Call log_inactive_ticker method
  - Verify generated timestamps use EST/EDT timezone

- [ ]* 3.2 Write property test for time window cutoff calculation
  - **Property 3: Time window cutoff uses America/New_York timezone**
  - **Validates: Requirements 1.4**
  - Generate random time window values (1-60 minutes)
  - Call get_inactive_tickers_for_indicator method
  - Verify cutoff timestamp is calculated using America/New_York timezone
  - Verify time difference between now and cutoff matches the window in EST

- [x] 4. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [ ]* 5. Write property test for timezone-aware comparisons
  - **Property 4: Timezone-aware comparison correctness**
  - **Validates: Requirements 1.5**
  - Generate random moments in time
  - Create both UTC and EST timestamps for the same moment
  - Verify that when parsed and compared, they represent the same instant
  - Verify UTC timestamp is 4-5 hours ahead of EST timestamp (depending on DST)

- [ ]* 6. Write property test for DST transition handling
  - **Property 5: DST transition handling**
  - **Validates: Requirements 2.5**
  - Generate timestamps around DST transition dates (March and November)
  - Verify timestamps before spring forward use -05:00 (EST)
  - Verify timestamps after spring forward use -04:00 (EDT)
  - Verify timestamps before fall back use -04:00 (EDT)
  - Verify timestamps after fall back use -05:00 (EST)

- [x] 7. Final Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

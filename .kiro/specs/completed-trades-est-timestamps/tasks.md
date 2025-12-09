# Implementation Plan

- [x] 1. Update BaseTradingIndicator to use EST timestamps
  - Import `_get_est_timestamp` helper function from dynamodb_client
  - Replace UTC timestamp generation with EST timestamp for exit_timestamp
  - Update fallback timestamp generation for enter_timestamp to use EST
  - _Requirements: 1.1, 1.2, 1.3, 2.3_

- [x]* 1.1 Write property test for exit timestamp timezone
  - **Property 1: Exit timestamps use America/New_York timezone**
  - **Validates: Requirements 1.1, 1.2**

- [x]* 1.2 Write property test for enter timestamp copying
  - **Property 2: Enter timestamp matches created_at from active trade**
  - **Validates: Requirements 2.1, 2.2, 2.4**

- [x]* 1.3 Write property test for timestamp ordering
  - **Property 3: Exit timestamp is after enter timestamp**
  - **Validates: Requirements 3.3**

- [x]* 1.4 Write property test for timestamp format validation
  - **Property 4: Timestamp format is ISO 8601 with timezone**
  - **Validates: Requirements 1.3, 3.2**

- [x]* 1.5 Write property test for DST transition handling
  - **Property 5: DST transition handling for exit timestamps**
  - **Validates: Requirements 1.5, 3.5**

- [x]* 1.6 Write unit tests for timestamp generation
  - Test exit_timestamp uses EST timezone
  - Test enter_timestamp fallback uses EST timezone
  - Test timestamp format includes timezone offset
  - Test DST boundary cases
  - _Requirements: 1.1, 1.2, 1.3, 1.5, 2.3_

- [x] 2. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

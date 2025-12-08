# Implementation Plan

- [x] 1. Set up project structure and utilities
  - Create directory structure for scripts and logs
  - Create shared utility functions for logging, date handling, and process management
  - Set up configuration file for customizable settings
  - _Requirements: 1.4, 2.2, 3.1, 3.2, 4.1_

- [ ]* 1.1 Write property test for log file naming
  - **Property 5: Log file naming convention**
  - **Validates: Requirements 3.2**

- [ ]* 1.2 Write property test for monitor log timestamps
  - **Property 7: Monitor log timestamps**
  - **Validates: Requirements 3.4**

- [x] 2. Implement start log monitor script
  - Create `start-log-monitor.sh` with weekday detection logic
  - Implement Heroku CLI validation and error handling
  - Add process startup with output redirection to dated log file
  - Implement PID file creation for process tracking
  - Add startup confirmation logging
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5_

- [ ]* 2.1 Write property test for weekday execution
  - **Property 1: Weekday execution only**
  - **Validates: Requirements 1.2**

- [ ]* 2.2 Write property test for successful startup logging
  - **Property 2: Successful startup logging**
  - **Validates: Requirements 1.4**

- [ ]* 2.3 Write unit test for exact Heroku command
  - Test that the script constructs the correct Heroku CLI command
  - _Requirements: 1.3_

- [x] 3. Implement stop log monitor script
  - Create `stop-log-monitor.sh` with PID file reading
  - Implement graceful process termination (SIGTERM then SIGKILL)
  - Add orphaned process cleanup logic
  - Implement shutdown confirmation logging
  - Handle case where no process is running
  - _Requirements: 2.1, 2.2, 2.3, 2.4_

- [ ]* 3.1 Write property test for process termination
  - **Property 3: Process termination completeness**
  - **Validates: Requirements 2.1, 2.3**

- [ ]* 3.2 Write property test for shutdown logging
  - **Property 4: Shutdown logging**
  - **Validates: Requirements 2.2**

- [x] 4. Implement log file management
  - Add log file append behavior (don't overwrite existing files)
  - Implement timestamp inclusion in monitor log entries
  - Create log cleanup script for files older than 30 days
  - Add disk space checking before writing logs
  - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5_

- [ ]* 4.1 Write property test for log file append behavior
  - **Property 6: Log file append behavior**
  - **Validates: Requirements 3.3**

- [ ]* 4.2 Write property test for log file retention
  - **Property 8: Log file retention**
  - **Validates: Requirements 3.5**

- [x] 5. Implement error handling and retry logic
  - Add detailed error logging to error log file
  - Implement network retry logic with exponential backoff (3 attempts)
  - Add specific error messages for authentication failures
  - Add specific error messages for network failures
  - Implement final failure logging after all retries exhausted
  - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5_

- [ ]* 5.1 Write property test for error logging
  - **Property 9: Error logging**
  - **Validates: Requirements 4.1**

- [ ]* 5.2 Write property test for retry attempt limit
  - **Property 10: Retry attempt limit**
  - **Validates: Requirements 4.3**

- [x] 6. Implement manual control script
  - Create `log-monitor-ctl.sh` with start/stop/status/logs commands
  - Implement start command with force flag (bypass time checks)
  - Implement stop command (reuse stop-log-monitor.sh logic)
  - Implement status command with process detection
  - Implement logs command to tail recent log files
  - Add confirmation messages for all commands
  - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5_

- [ ]* 6.1 Write property test for status reporting
  - **Property 11: Status reporting accuracy**
  - **Validates: Requirements 5.3**

- [ ]* 6.2 Write property test for command confirmation
  - **Property 12: Command confirmation messages**
  - **Validates: Requirements 5.5**

- [ ]* 6.3 Write unit test for manual start command
  - Test that manual start bypasses time checks with --force flag
  - _Requirements: 5.1_

- [x] 7. Implement timezone handling and cron installation
  - Create timezone conversion utility for EST/EDT
  - Implement DST detection and adjustment logic
  - Create `install-cron.sh` script to add cron entries
  - Add cron entries for 9:30 AM EST start (weekdays only)
  - Add cron entry for 4:00 PM EST stop (weekdays only)
  - Add cron entry for daily log cleanup at midnight
  - Add timezone validation during installation
  - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5_

- [ ]* 7.1 Write property test for timezone conversion
  - **Property 13: Timezone conversion accuracy**
  - **Validates: Requirements 6.1, 6.2**

- [ ]* 7.2 Write unit test for cron installation
  - Test that cron entries are correctly formatted and installed
  - _Requirements: 6.4_

- [x] 8. Create installation and documentation
  - Create README with installation instructions
  - Document configuration options and environment variables
  - Add troubleshooting guide with common issues
  - Create uninstall script to remove cron entries
  - Add usage examples for manual control commands

- [x] 9. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 10. Manual integration testing
  - Test full start-to-stop cycle manually
  - Verify log files are created with correct names and content
  - Test manual control commands (start, stop, status, logs)
  - Verify error handling with simulated failures
  - Test cron job execution at scheduled times (may require waiting or time manipulation)
  - Verify log cleanup removes old files correctly

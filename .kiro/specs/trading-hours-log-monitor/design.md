# Design Document: Trading Hours Log Monitor

## Overview

The Trading Hours Log Monitor is a lightweight automation system that manages Heroku log tailing during market trading hours (9:30 AM - 4 PM EST). The system consists of shell scripts orchestrated by cron jobs, with proper timezone handling, error management, and log rotation capabilities.

The design prioritizes simplicity and reliability, using native Unix tools (cron, bash) to minimize dependencies while providing robust monitoring capabilities.

## Architecture

### High-Level Architecture

```
┌─────────────────┐
│   Cron Daemon   │
└────────┬────────┘
         │
         ├─── 9:30 AM EST ───> start-log-monitor.sh
         │                            │
         │                            ├─> Check weekday
         │                            ├─> Validate Heroku CLI
         │                            ├─> Start log tail
         │                            └─> Write to log file
         │
         └─── 4:00 PM EST ───> stop-log-monitor.sh
                                      │
                                      ├─> Find running process
                                      ├─> Terminate gracefully
                                      └─> Log shutdown
```

### Component Interaction

1. **Cron Scheduler**: Triggers start/stop scripts at specified times
2. **Start Script**: Validates environment, starts Heroku log tail, manages output
3. **Stop Script**: Finds and terminates running log tail process
4. **Manual Control Script**: Provides CLI for manual start/stop/status operations
5. **Log Rotation**: Cleans up old log files automatically

## Components and Interfaces

### 1. Start Log Monitor Script (`start-log-monitor.sh`)

**Purpose**: Initiates Heroku log tailing during trading hours

**Responsibilities**:
- Validate current day is a weekday
- Check Heroku CLI availability
- Start log tail process in background
- Redirect output to dated log file
- Handle errors and retry logic

**Interface**:
```bash
./start-log-monitor.sh [--force]
```

**Exit Codes**:
- 0: Success
- 1: Weekend (not started)
- 2: Heroku CLI not found
- 3: Authentication failure
- 4: Network error after retries

### 2. Stop Log Monitor Script (`stop-log-monitor.sh`)

**Purpose**: Terminates running Heroku log tail process

**Responsibilities**:
- Find running Heroku log tail process
- Send SIGTERM for graceful shutdown
- Wait for process termination
- Force kill if necessary (SIGKILL after timeout)
- Log shutdown status

**Interface**:
```bash
./stop-log-monitor.sh
```

**Exit Codes**:
- 0: Success (process stopped or not running)
- 1: Failed to stop process

### 3. Manual Control Script (`log-monitor-ctl.sh`)

**Purpose**: Provide manual control interface

**Responsibilities**:
- Start monitoring on demand
- Stop monitoring on demand
- Display current status
- Show recent logs

**Interface**:
```bash
./log-monitor-ctl.sh {start|stop|status|logs}
```

### 4. Cron Configuration

**Purpose**: Schedule automatic start/stop

**Cron Entries** (in user's crontab):
```cron
# Start log monitoring at 9:30 AM EST (weekdays only)
30 14 * * 1-5 /path/to/start-log-monitor.sh >> /path/to/logs/cron.log 2>&1

# Stop log monitoring at 4:00 PM EST
0 21 * * 1-5 /path/to/stop-log-monitor.sh >> /path/to/logs/cron.log 2>&1

# Clean up old logs daily at midnight
0 5 * * * find /path/to/logs/heroku-logs-*.log -mtime +30 -delete
```

**Note**: Times shown are UTC (EST+5). The scripts will handle timezone conversion internally.

## Data Models

### Log File Structure

**Heroku Log Files**:
- Location: `./logs/heroku-logs-YYYY-MM-DD.log`
- Format: Raw Heroku log output with timestamps
- Rotation: Daily (new file per day)
- Retention: 30 days

**Monitor Log Files**:
- Location: `./logs/monitor.log`
- Format: ISO 8601 timestamp + log level + message
- Example: `2025-12-07T09:30:00-05:00 [INFO] Log monitoring started`

**Error Log Files**:
- Location: `./logs/monitor-error.log`
- Format: ISO 8601 timestamp + error details + stack trace if applicable

### Process Tracking

**PID File**:
- Location: `./logs/heroku-tail.pid`
- Content: Process ID of running Heroku log tail
- Purpose: Enable stop script to find and terminate process

## Correctness Properties

*A property is a characteristic or behavior that should hold true across all valid executions of a system-essentially, a formal statement about what the system should do. Properties serve as the bridge between human-readable specifications and machine-verifiable correctness guarantees.*


### Property 1: Weekday execution only
*For any* date and time when the start script is invoked, if the date falls on a weekend (Saturday or Sunday), the script should exit without starting the Heroku log tail process.
**Validates: Requirements 1.2**

### Property 2: Successful startup logging
*For any* successful start of the log monitor, a startup confirmation message with timestamp should appear in the monitor log file.
**Validates: Requirements 1.4**

### Property 3: Process termination completeness
*For any* running Heroku log tail process, when the stop script executes, the process should no longer be running and no orphaned child processes should remain.
**Validates: Requirements 2.1, 2.3**

### Property 4: Shutdown logging
*For any* execution of the stop script, a shutdown confirmation message should be written to the monitor log file.
**Validates: Requirements 2.2**

### Property 5: Log file naming convention
*For any* date when the log monitor runs, the output log file should be named following the pattern `heroku-logs-YYYY-MM-DD.log` where YYYY-MM-DD matches the current date.
**Validates: Requirements 3.2**

### Property 6: Log file append behavior
*For any* log file that already exists for the current date, starting the monitor again should append new content to the existing file rather than overwriting it.
**Validates: Requirements 3.3**

### Property 7: Monitor log timestamps
*For any* entry written to the monitor log file, the entry should include an ISO 8601 formatted timestamp.
**Validates: Requirements 3.4**

### Property 8: Log file retention
*For any* log files older than 30 days, the cleanup process should remove them while preserving files that are 30 days old or newer.
**Validates: Requirements 3.5**

### Property 9: Error logging
*For any* error condition encountered during startup or operation, detailed error information should be written to the error log file.
**Validates: Requirements 4.1**

### Property 10: Retry attempt limit
*For any* network connection failure, the monitor should attempt exactly 3 retries before giving up and logging a final failure message.
**Validates: Requirements 4.3**

### Property 11: Status reporting accuracy
*For any* execution of the status command, the output should correctly indicate whether a Heroku log tail process is currently running.
**Validates: Requirements 5.3**

### Property 12: Command confirmation messages
*For any* manual command (start, stop, status) that completes, a confirmation message should be displayed to the user.
**Validates: Requirements 5.5**

### Property 13: Timezone conversion accuracy
*For any* system timezone, the cron schedule should correctly convert 9:30 AM and 4:00 PM Eastern time to the appropriate local time for scheduling.
**Validates: Requirements 6.1, 6.2**

## Error Handling

### Error Categories and Responses

**1. Environment Errors**
- Missing Heroku CLI: Log error with installation instructions, exit code 2
- Missing permissions: Log error with permission requirements, exit code 1
- Invalid configuration: Log error with configuration guidance, exit code 1

**2. Network Errors**
- Connection timeout: Retry up to 3 times with exponential backoff (1s, 2s, 4s)
- Authentication failure: Log error with auth troubleshooting, exit code 3
- DNS resolution failure: Treat as network error, apply retry logic

**3. Process Management Errors**
- Process already running: Log warning, exit gracefully (not an error)
- Process not found during stop: Log info message, exit successfully
- Process won't terminate: Escalate from SIGTERM to SIGKILL after 5-second timeout

**4. File System Errors**
- Log directory doesn't exist: Create directory automatically
- Insufficient disk space: Log error, attempt to clean old logs, retry once
- Permission denied on log file: Log error with permission fix instructions, exit code 1

### Error Recovery Strategies

**Automatic Recovery**:
- Network errors: Retry with backoff
- Missing directories: Create automatically
- Disk space: Clean old logs and retry

**Manual Intervention Required**:
- Missing Heroku CLI: User must install
- Authentication issues: User must run `heroku login`
- Permission problems: User must fix file permissions

**Graceful Degradation**:
- If log file write fails, continue monitoring but log to stderr
- If PID file write fails, continue but warn that stop may be difficult

## Testing Strategy

### Unit Testing

The system will use **Bash Automated Testing System (bats)** for shell script testing.

**Test Coverage**:
- Weekday/weekend detection logic
- Timezone conversion calculations
- File naming and path construction
- Process management (start/stop/status)
- Error handling and exit codes
- Log message formatting

**Example Test Structure**:
```bash
@test "start script exits on weekend" {
  # Mock date to return Saturday
  run ./start-log-monitor.sh
  [ "$status" -eq 1 ]
  [[ "$output" =~ "Weekend detected" ]]
}
```

### Property-Based Testing

The system will use **Hypothesis** (Python) for property-based testing of core logic components.

**Property Test Coverage**:
- Date/time calculations across various timezones
- Log file naming for all valid dates
- Process lifecycle management
- Retry logic with various failure scenarios
- Log rotation with different file age distributions

**Test Configuration**:
- Minimum 100 iterations per property test
- Use Hypothesis strategies for dates, times, and timezones
- Test edge cases: DST transitions, leap years, timezone boundaries

### Integration Testing

**Manual Integration Tests**:
1. Install cron jobs and verify they trigger at correct times
2. Test full start-to-stop cycle during trading hours
3. Verify log files are created and contain expected content
4. Test manual control commands
5. Verify cleanup of old log files

**Automated Integration Tests**:
- Use Docker container with controlled time to test scheduling
- Mock Heroku CLI responses for testing without actual Heroku access
- Test error scenarios (network failures, auth failures, etc.)

### Testing Approach

1. **Test-After-Implementation**: Implement core functionality first, then write comprehensive tests
2. **Focus on Critical Paths**: Prioritize testing scheduling logic, process management, and error handling
3. **Mock External Dependencies**: Mock Heroku CLI and system time for reliable testing
4. **Validate Properties**: Use property-based tests to verify correctness across wide input ranges

## Implementation Considerations

### Platform Compatibility

**Primary Target**: macOS (user's current platform)
**Secondary Target**: Linux (for potential server deployment)

**macOS-Specific Considerations**:
- Use `launchd` as alternative to cron for better reliability
- Handle macOS timezone database location
- Account for macOS-specific process management tools

### Dependencies

**Required**:
- Heroku CLI (must be installed and authenticated)
- Bash 4.0+ (for associative arrays and modern features)
- Standard Unix tools: `date`, `ps`, `kill`, `find`

**Optional**:
- `bats` for testing
- Python 3.8+ with Hypothesis for property testing
- `jq` for JSON parsing if needed

### Security Considerations

**Credentials**:
- Rely on Heroku CLI's existing authentication
- Never store Heroku credentials in scripts
- Use user's existing `~/.netrc` or Heroku auth token

**File Permissions**:
- Log files: 644 (readable by user and group)
- Scripts: 755 (executable by user, readable by all)
- PID file: 644 (readable for status checks)

**Process Isolation**:
- Run as user's own process (not root)
- Use process groups for clean termination
- Validate all file paths to prevent injection

### Performance Considerations

**Resource Usage**:
- Log tail process: Minimal CPU, moderate network I/O
- Log file writes: Buffered I/O to minimize disk writes
- Cron overhead: Negligible (runs twice per day)

**Scalability**:
- Log files grow linearly with application activity
- 30-day retention should keep total size under 1GB for typical usage
- Cleanup runs daily to prevent unbounded growth

### Monitoring and Observability

**Health Checks**:
- Monitor log file should show regular activity during trading hours
- Error log should be empty or contain only transient errors
- PID file should exist when monitoring is active

**Metrics to Track**:
- Number of successful starts/stops per week
- Error frequency and types
- Log file sizes and retention
- Network retry frequency

**Alerting** (future enhancement):
- Email notification on repeated failures
- Slack webhook for critical errors
- Daily summary of monitoring activity

## Deployment

### Installation Steps

1. Clone or copy scripts to desired location (e.g., `~/trading-log-monitor/`)
2. Make scripts executable: `chmod +x *.sh`
3. Create logs directory: `mkdir -p logs`
4. Verify Heroku CLI: `heroku --version`
5. Test manual start: `./log-monitor-ctl.sh start`
6. Install cron jobs: `./install-cron.sh`
7. Verify cron installation: `crontab -l`

### Configuration

**Environment Variables** (optional):
- `LOG_MONITOR_DIR`: Base directory for logs (default: `./logs`)
- `HEROKU_APP`: Heroku app name (default: `automated-day-trading`)
- `TZ`: Timezone for cron (default: system timezone)

**Cron Installation Script** (`install-cron.sh`):
```bash
#!/bin/bash
# Adds cron entries to user's crontab
# Handles timezone conversion automatically
# Backs up existing crontab before modification
```

### Maintenance

**Regular Tasks**:
- Weekly: Review error logs for recurring issues
- Monthly: Verify disk space usage for log files
- Quarterly: Update Heroku CLI to latest version

**Troubleshooting**:
- Check cron logs: `tail -f logs/cron.log`
- Check monitor logs: `tail -f logs/monitor.log`
- Check error logs: `tail -f logs/monitor-error.log`
- Verify cron schedule: `crontab -l`
- Test manual operation: `./log-monitor-ctl.sh status`

## Future Enhancements

1. **Web Dashboard**: Simple web interface to view logs and status
2. **Alert Integration**: Email/Slack notifications for errors
3. **Log Analysis**: Automated parsing for error patterns
4. **Multi-App Support**: Monitor multiple Heroku apps simultaneously
5. **Cloud Storage**: Archive logs to S3 or similar for long-term retention
6. **Metrics Dashboard**: Visualize monitoring uptime and error rates

# Test Suite for runpod_monitor.py

This document describes the comprehensive test suite for the RunPod Monitor Telegram Bot.

## Test Coverage

The test suite provides **79% code coverage** with **76 comprehensive tests** covering:

### Tested Components

1. **Utility Functions (20 tests)**
   - `get_allowed_users()` - User ID parsing and validation
   - `is_authorized()` - Authorization logic for chat and user restrictions
   - `format_pod_info()` - Pod information formatting
   - `generate_pod_name()` - Pod name generation with timestamps

2. **RunPod REST API Helpers (8 tests)**
   - `runpod_rest_get()` - GET requests to RunPod API
   - `runpod_rest_post()` - POST requests to RunPod API
   - `fetch_templates()` - Template retrieval
   - `fetch_network_volumes()` - Network volume retrieval
   - `create_pod_api()` - Pod creation API calls

3. **Telegram Command Handlers (18 tests)**
   - `/start` - Welcome message and command list
   - `/help` - Help information
   - `/status` - Running pod status
   - `/pods` - All pods listing
   - `/create` - Pod creation flow initiation
   - `/terminate` - Pod termination menu
   - `/stop` - Pod stop menu
   - Authorization checks for all commands
   - Error handling for API failures

4. **Callback Handlers (13 tests)**
   - Cancel action
   - Template selection (create pod flow)
   - Volume selection (create pod flow)
   - GPU selection (create pod flow)
   - Pod creation confirmation and execution
   - Pod termination with validation
   - Pod stop with validation
   - Error handling for all callback actions
   - API error responses
   - Invalid input validation

5. **Pod Monitoring & Alerts (6 tests)**
   - `send_alert()` - Telegram alert sending
   - `check_pods()` - Pod status checking and notification
   - Multiple running pods scenario
   - No pods scenario
   - Cost calculation
   - Error handling

6. **Edge Cases & Integration (11 tests)**
   - High-cost pod formatting
   - Empty template names
   - Invalid user ID formats
   - Many pods (scalability)
   - Expired sessions
   - Zero-cost pods
   - Configuration validation

## Running the Tests

### Prerequisites

Install test dependencies:

```bash
pip install -r requirements-test.txt
```

Or install individually:

```bash
pip install pytest pytest-asyncio pytest-mock pytest-cov
```

### Basic Test Execution

Run all tests:

```bash
pytest test_runpod_monitor.py -v
```

Run with brief output:

```bash
pytest test_runpod_monitor.py -q
```

### Coverage Reports

Generate coverage report:

```bash
pytest test_runpod_monitor.py --cov=runpod_monitor --cov-report=term-missing
```

Generate HTML coverage report:

```bash
pytest test_runpod_monitor.py --cov=runpod_monitor --cov-report=html
```

View HTML report:

```bash
open htmlcov/index.html  # macOS
xdg-open htmlcov/index.html  # Linux
```

### Running Specific Tests

Run a specific test class:

```bash
pytest test_runpod_monitor.py::TestGetAllowedUsers -v
```

Run a specific test method:

```bash
pytest test_runpod_monitor.py::TestGetAllowedUsers::test_get_allowed_users_with_valid_ids -v
```

Run tests matching a pattern:

```bash
pytest test_runpod_monitor.py -k "authorized" -v
```

## Test Architecture

The test suite uses:

- **pytest** - Testing framework
- **pytest-asyncio** - Async test support
- **unittest.mock** - Mocking and patching
- **httpx** - HTTP client mocking

### Mocking Strategy

Tests mock external dependencies:
- RunPod SDK calls (`runpod.get_pods`, `runpod.terminate_pod`, etc.)
- HTTP requests (`httpx.AsyncClient`)
- Telegram Bot API calls (`update.message.reply_text`)
- Environment variables (for authorization testing)
- System time (for deterministic pod name generation)

### Test Organization

Tests are organized into logical test classes:
- Each test class focuses on a specific module/function
- Test methods follow the naming pattern `test_<function>_<scenario>`
- Clear docstrings describe what each test validates

## Key Test Scenarios

### Authorization Tests
- Valid user and chat ID combinations
- Invalid user IDs
- Invalid chat IDs
- No restrictions (open access)
- Chat ID only restrictions
- User ID only restrictions

### Error Handling Tests
- API timeouts
- HTTP errors (404, 400, etc.)
- Network failures
- Invalid input data
- Missing data scenarios

### Pod Creation Flow Tests
- Complete flow from template selection to creation
- Volume selection (with and without volumes)
- GPU selection
- API errors during creation
- Session expiration

### Pod Management Tests
- Terminating pods
- Stopping pods
- Invalid pod ID formats
- API errors during management operations

## Current Coverage: 79%

Uncovered lines are primarily:
- Main function and application initialization (lines 712-757)
- Some edge cases in callback error handling
- Logging statements
- Exception handlers for rare scenarios

## Contributing

When adding new features to `runpod_monitor.py`:

1. Add corresponding tests to `test_runpod_monitor.py`
2. Aim for >75% coverage for new code
3. Include both success and error scenarios
4. Add edge case tests where applicable
5. Run the full test suite before submitting changes

## Continuous Integration

To integrate with CI/CD pipelines:

```yaml
# Example GitHub Actions workflow
- name: Run tests
  run: |
    pip install -r requirements-test.txt
    pytest test_runpod_monitor.py --cov=runpod_monitor --cov-report=xml

- name: Upload coverage
  uses: codecov/codecov-action@v3
  with:
    file: ./coverage.xml
```

## Troubleshooting

### Import Errors

If you get import errors, ensure environment variables are set:

```bash
export RUNPOD_API_KEY="test_key"
export TELEGRAM_BOT_TOKEN="test_token"
export TELEGRAM_CHAT_ID="123456789"
```

Or run tests with the environment variables inline:

```bash
RUNPOD_API_KEY=test pytest test_runpod_monitor.py
```

### Async Test Warnings

If you see asyncio warnings, ensure pytest-asyncio is installed:

```bash
pip install pytest-asyncio
```

### Mock Issues

If mocks aren't working as expected, check that patches are targeting the correct module namespace.

## License

Same license as the main project.
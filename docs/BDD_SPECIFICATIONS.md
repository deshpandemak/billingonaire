# BDD Specifications Guide

Billingonaire uses [pytest-bdd](https://pytest-bdd.readthedocs.io/) for Behaviour-Driven Development (BDD) tests in the backend. BDD specs are written in [Gherkin](https://cucumber.io/docs/gherkin/) syntax and live alongside conventional unit tests in the repository.

## Directory Structure

```
billingonaire_backend/
└── specs/
    ├── __init__.py
    ├── conftest.py          # Shared BDD fixtures (e.g. API test client, sample PDFs)
    ├── features/            # Gherkin feature files (.feature)
    │   ├── bill_generation.feature
    │   ├── board_upload.feature
    │   ├── dashboard.feature
    │   ├── order_analysis.feature
    │   ├── order_management.feature
    │   └── user_management.feature
    └── steps/               # Python step definition files
        ├── __init__.py
        ├── bill_generation_steps.py
        ├── board_upload_steps.py
        ├── dashboard_steps.py
        ├── order_analysis_steps.py
        ├── order_management_steps.py
        └── user_management_steps.py
```

## Running BDD Specs Locally

Install the backend runtime and test dependencies (BDD steps import the FastAPI app and other backend modules):

```bash
cd billingonaire_backend
pip install -r requirements.txt -r requirements-test.txt
```

Run all BDD specification tests:

```bash
cd billingonaire_backend
pytest specs/ -v
```

Run a single feature's scenarios via its step definition module:

```bash
cd billingonaire_backend
pytest specs/steps/board_upload_steps.py -v
```

Or filter by name using the `-k` flag:

```bash
cd billingonaire_backend
pytest specs/ -v -k "board_upload"
```

Run all backend tests (unit tests + BDD specs) together:

```bash
cd billingonaire_backend
pytest tests/unit specs/ -v
```

Run with coverage:

```bash
cd billingonaire_backend
pytest specs/ -v --cov=. --cov-report=term-missing
```

## CI/CD Integration

BDD specifications run automatically in the GitHub Actions CI pipeline on every push and pull request to `main` and `develop`.

The **Backend Tests** job in [`.github/workflows/ci.yml`](../.github/workflows/ci.yml) includes two test steps:

| Step | Command | Purpose |
|------|---------|---------|
| Run unit tests | `pytest tests/unit -v --cov=. --cov-report=xml --cov-report=term` | Fast unit tests; generates initial coverage |
| Run BDD specification tests | `pytest specs/ -v --tb=short --cov=. --cov-append --cov-report=xml --cov-report=term` | Behaviour specifications; appends to coverage |

Combined coverage from both test runs is uploaded to Codecov after the BDD step completes. BDD spec results appear in the GitHub Actions log under the "Run BDD specification tests" step.

## Writing a New Feature Specification

### 1. Create the feature file

Add a new `.feature` file in `billingonaire_backend/specs/features/`:

```gherkin
# billingonaire_backend/specs/features/my_feature.feature
Feature: My Feature
  As a legal professional
  I want to do something
  So that I get some value

  Background:
    Given the Billingonaire API is running
    And a valid authenticated user is logged in

  Scenario: Happy path
    Given some precondition
    When I perform an action
    Then the result should be as expected
```

### 2. Create the step definition file

Add a corresponding `_steps.py` file in `billingonaire_backend/specs/steps/`:

```python
# billingonaire_backend/specs/steps/my_feature_steps.py
import pytest
from pytest_bdd import given, parsers, scenarios, then, when

# Link to the feature file
scenarios("../features/my_feature.feature")


@pytest.fixture
def ctx():
    """Mutable context shared between steps within a scenario."""
    return {}


@given("some precondition")
def some_precondition(ctx):
    ctx["data"] = "value"


@when("I perform an action")
def perform_action(ctx, api_client):
    response = api_client.get("/my-endpoint")
    ctx["response"] = response


@then("the result should be as expected")
def check_result(ctx):
    assert ctx["response"].status_code == 200
```

### 3. Use shared fixtures

The `specs/conftest.py` provides shared fixtures available to all step definitions:

- `api_client` — a FastAPI `TestClient` authenticated as a regular user with mocked Firebase.
- `admin_api_client` — a FastAPI `TestClient` authenticated as an admin user with mocked Firebase.
- `sample_pdf_bytes` — minimal valid PDF bytes for upload tests.
- `mock_firestore_client` — the mocked Firestore client for inspecting Firestore interactions.
- `sample_case_data` — a dict with a pre-populated case record for convenience.

Add new shared fixtures to `specs/conftest.py` when they apply to multiple feature files.

## Gherkin Best Practices

- **Feature** describes the business capability being tested.
- **Scenario** describes one concrete example (a single behaviour).
- **Background** lists steps that run before every scenario in the feature.
- **Given** describes the initial context (preconditions).
- **When** describes the action taken.
- **Then** describes the expected outcome.
- Use `parsers.parse(...)` (or `parsers.cfparse(...)`) for parameterized step text:
  ```python
  @given(parsers.parse('a court board PDF for date "{date}"'))
  def board_for_date(ctx, date):
      ctx["date"] = date
  ```

## Markers and Filtering

BDD step files are discovered automatically via `pytest.ini`:

```ini
[pytest]
testpaths = tests specs
python_files = test_*.py *_steps.py
```

You can tag scenarios with custom markers and filter from the command line:

```bash
# Run only fast specs (tagged with @fast in the feature file)
pytest specs/ -v -m "fast and not slow"
```

To add a marker to a scenario, add it as a tag in the feature file:

```gherkin
  @fast
  Scenario: Quick smoke test
    Given ...
```

And register the marker in `pytest.ini`:

```ini
[pytest]
markers =
    fast: Fast-running smoke tests
```

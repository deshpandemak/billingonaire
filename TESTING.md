# Billingonaire Testing Guide

## Overview
This document describes the comprehensive testing strategy for Billingonaire, including unit tests, integration tests, end-to-end tests, and CI/CD pipelines.

## Backend Testing (Python/FastAPI)

### Test Structure
```
billingonaire-backend/
├── tests/
│   ├── __init__.py
│   ├── conftest.py          # Shared fixtures and configuration
│   ├── unit/                # Unit tests
│   │   └── test_auto_order_manager.py
│   ├── integration/         # Integration tests
│   │   └── test_api_endpoints.py
│   ├── e2e/                 # End-to-end tests
│   └── fixtures/            # Test data
│       └── pdfs/            # Sample PDF files
├── pytest.ini               # Pytest configuration
└── requirements-test.txt    # Test dependencies
```

### Running Backend Tests

#### Install Test Dependencies
```bash
cd billingonaire-backend
pip install -r requirements-test.txt
```

#### Run All Tests
```bash
pytest
```

#### Run Unit Tests Only
```bash
pytest tests/unit -v
```

#### Run Integration Tests
```bash
pytest tests/integration -v
```

#### Run with Coverage
```bash
pytest --cov=. --cov-report=html --cov-report=term
```

### Key Test Areas

#### 1. AutoOrderManager Tests (`test_auto_order_manager.py`)
- `_analyze_existing_order` with validation and fallback
- `_process_single_case` for order_linked vs not_linked cases
- `_validate_order_date` for date matching
- `_parse_case_reference` for case reference parsing

#### 2. API Endpoint Tests (`test_api_endpoints.py`)
- Health check endpoints
- Order processing endpoints
- Authentication and authorization
- Error handling

### Coverage Targets
- **Overall**: ≥85%
- **Critical modules** (AutoOrderManager, order_analyzer): ≥90%
- **API endpoints**: ≥80%

## Frontend Testing (React/Vite)

### Test Structure
```
billingonaire-ui/
├── src/
│   ├── __tests__/           # Component tests
│   │   └── Table.test.jsx
│   └── setupTests.js        # Test setup and mocks
├── e2e/                     # End-to-end tests
│   └── login.spec.js
├── vitest.config.js         # Vitest configuration
└── playwright.config.js     # Playwright configuration
```

### Running Frontend Tests

#### Install Test Dependencies
```bash
cd billingonaire-ui
npm install
```

#### Run Unit/Component Tests
```bash
npm run test:unit
```

#### Run Tests in Watch Mode
```bash
npm test
```

#### Run with Coverage
```bash
npm run test:coverage
```

#### Run E2E Tests
```bash
# Install Playwright browsers first
npx playwright install --with-deps

# Run E2E tests
npm run test:e2e

# Run E2E tests in UI mode
npm run test:e2e:ui
```

### Key Test Areas

#### 1. Component Tests
- Table component rendering
- Form validation
- User interactions
- State management

#### 2. E2E Tests
- Login flow
- Dashboard navigation
- Order processing workflow
- Search functionality

### Coverage Targets
- **Overall**: ≥80%
- **Critical components** (Table, Login, Dashboard): ≥85%
- **Auth flows**: 100%

## CI/CD Pipeline

### Continuous Integration (`.github/workflows/ci.yml`)

The CI pipeline runs on every push and pull request:

1. **Backend Linting**
   - Black (code formatting)
   - isort (import sorting)
   - flake8 (linting)

2. **Backend Tests**
   - Unit tests with Firestore emulator
   - Integration tests
   - Coverage reporting

3. **Frontend Linting**
   - ESLint

4. **Frontend Tests**
   - Vitest unit tests
   - Playwright e2e tests
   - Coverage reporting

5. **Security Scanning**
   - Snyk vulnerability scanning

### Continuous Deployment (`.github/workflows/cd.yml`)

The CD pipeline runs on main branch merges:

1. **Run All Tests**
   - Reuses CI workflow
   - Must pass before deployment

2. **Deploy Backend**
   - Build Docker image
   - Push to Google Container Registry
   - Deploy to Cloud Run
   - Health check verification

3. **Deploy Frontend**
   - Build production bundle
   - Deploy to Firebase Hosting
   - Verify deployment

4. **Create Release**
   - Generate release notes
   - Tag with version
   - Link to deployments

### Required Secrets

Configure these in GitHub repository settings:

**Backend (Google Cloud)**:
- `GCP_WORKLOAD_IDENTITY_PROVIDER`
- `GCP_SERVICE_ACCOUNT`
- `GCLOUD_SERVICE_ACCOUNT_KEY`

**Frontend (Firebase)**:
- `FIREBASE_SERVICE_ACCOUNT`

**Security**:
- `SNYK_TOKEN` (optional, for security scanning)

## Test Data Strategy

### Backend
- Use Firestore emulator for integration tests
- Mock external APIs (court website, PDF downloads)
- Golden sample PDFs for regression testing
- Fixture-based test data in `tests/fixtures/`

### Frontend
- Mock Firebase Auth
- Mock backend API responses
- Use MSW (Mock Service Worker) for API mocking
- Test data factories for consistent test data

## Best Practices

### Writing Tests

1. **Follow AAA Pattern**: Arrange, Act, Assert
2. **One assertion per test** (when possible)
3. **Use descriptive test names**: `test_should_fallback_when_order_link_expired`
4. **Mock external dependencies**: APIs, databases, time
5. **Keep tests independent**: No test should depend on another

### Mocking

```python
# Backend: Mock Firestore
@pytest.fixture
def mock_firestore_client():
    mock_client = MagicMock()
    # Setup mock chain
    return mock_client

# Frontend: Mock Firebase
vi.mock('firebase/auth', () => ({
  getAuth: vi.fn(),
  signInWithEmailAndPassword: vi.fn(),
}));
```

### Testing Async Code

```python
# Backend: Use pytest-asyncio
@pytest.mark.asyncio
async def test_async_function():
    result = await some_async_function()
    assert result == expected

# Frontend: Use waitFor
await waitFor(() => {
  expect(screen.getByText('Success')).toBeInTheDocument();
});
```

## Debugging Tests

### Backend
```bash
# Run specific test
pytest tests/unit/test_auto_order_manager.py::TestClass::test_method -v

# Debug with pdb
pytest --pdb

# Show print statements
pytest -s
```

### Frontend
```bash
# Run specific test
npm test -- Table.test.jsx

# Debug in browser
npm run test:e2e:ui

# Show console logs
npm test -- --reporter=verbose
```

## Pre-Commit Hooks

Consider adding pre-commit hooks:

```bash
# .pre-commit-config.yaml
repos:
  - repo: local
    hooks:
      - id: backend-tests
        name: Backend Tests
        entry: cd billingonaire-backend && pytest tests/unit
        language: system
        pass_filenames: false
        
      - id: frontend-tests
        name: Frontend Tests
        entry: cd billingonaire-ui && npm run test:unit
        language: system
        pass_filenames: false
```

## Performance Testing

For load testing the backend:

```bash
# Install locust
pip install locust

# Run load test
locust -f tests/performance/locustfile.py
```

## Monitoring and Alerting

- **Backend**: Cloud Run metrics, error rates
- **Frontend**: Firebase Hosting analytics
- **E2E Tests**: Run nightly on production
- **Coverage**: Track trends over time

## Troubleshooting

### Common Issues

1. **Firestore emulator not starting**
   ```bash
   gcloud emulators firestore start --host-port=localhost:8080
   ```

2. **Playwright browsers missing**
   ```bash
   npx playwright install --with-deps
   ```

3. **Tests timing out**
   - Increase timeout in pytest.ini or playwright.config.js
   - Check for missing mocks causing real API calls

4. **Coverage not generated**
   - Ensure pytest-cov is installed
   - Check .coveragerc for exclusions

## Resources

- [Pytest Documentation](https://docs.pytest.org/)
- [Vitest Documentation](https://vitest.dev/)
- [Playwright Documentation](https://playwright.dev/)
- [Testing Library](https://testing-library.com/)
- [GitHub Actions](https://docs.github.com/en/actions)

## Maintenance

- **Weekly**: Review test coverage trends
- **Monthly**: Update test dependencies
- **Quarterly**: Audit and refactor slow tests
- **On new features**: Add tests before merging

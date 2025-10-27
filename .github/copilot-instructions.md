# Copilot Instructions for Billingonaire

## Project Overview

Billingonaire is a professional legal billing management system designed for the legal industry. It automates processing of daily court board PDF files, extracts AGP assignments, fetches court orders, and generates comprehensive billing analytics.

## Architecture

- **Backend**: Python 3.11 + FastAPI + Uvicorn
- **Frontend**: React 19 + Vite + React Bootstrap
- **Database**: Firebase Firestore
- **Authentication**: Firebase Auth
- **Deployment**: 
  - Backend: Google Cloud Run
  - Frontend: Firebase Hosting
- **CI/CD**: GitHub Actions

## Project Structure

```
billingonaire/
├── billingonaire_backend/     # FastAPI backend
│   ├── main.py               # Main API server
│   ├── Board.py              # PDF parsing and board management
│   ├── requirements.txt      # Python dependencies
│   └── tests/               # Backend tests
├── billingonaire-ui/         # React frontend (Vite)
│   ├── src/                 # React components
│   ├── package.json         # Node dependencies
│   └── vite.config.js       # Vite configuration
├── firebase/                # Deployment scripts
└── .github/workflows/       # CI/CD pipelines
```

## Development Workflow

### Backend (billingonaire_backend/)

#### Setup
```bash
cd billingonaire_backend
pip install -r requirements.txt
```

#### Run Development Server
```bash
cd billingonaire_backend
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

#### Testing
```bash
cd billingonaire_backend
pytest tests/unit -v --cov=. --cov-report=xml --cov-report=term
```

#### Linting & Formatting
```bash
cd billingonaire_backend
black .                    # Format code
isort .                    # Sort imports
flake8 .                   # Lint code
```

### Frontend (billingonaire-ui/)

#### Setup
```bash
cd billingonaire-ui
npm install
```

#### Run Development Server
```bash
cd billingonaire-ui
npm run dev
# Access at: http://localhost:5000
```

#### Testing
```bash
cd billingonaire-ui
npm run test:unit          # Run unit tests
npm run test:unit:fast     # Run unit tests (fast, no coverage)
npm run test:e2e           # Run e2e tests
npm run test:e2e:fast      # Run e2e tests (Chrome only)
```

#### Linting
```bash
cd billingonaire-ui
npm run lint
```

#### Build
```bash
cd billingonaire-ui
npm run build
```

## Coding Standards

### Python (Backend)

- **Style Guide**: PEP 8
- **Formatter**: Black (line length: 88)
- **Import Sorter**: isort
- **Linter**: flake8
- **Type Hints**: Use type hints for function signatures
- **Python Version**: 3.11

#### Key Conventions
- Use async/await for asynchronous operations
- Follow FastAPI best practices for endpoint definitions
- Use Pydantic models for request/response validation
- Keep business logic separate from API route handlers
- Write comprehensive docstrings for classes and functions
- Use Firebase Admin SDK for Firestore operations

### JavaScript/React (Frontend)

- **Framework**: React 19 with functional components and hooks
- **Build Tool**: Vite
- **Styling**: React Bootstrap + custom CSS
- **Linter**: ESLint
- **Node Version**: 20

#### Key Conventions
- Use functional components with hooks (no class components)
- Follow React best practices for component composition
- Use `useState`, `useEffect`, and custom hooks appropriately
- Keep components focused and single-purpose
- Use PropTypes or TypeScript for prop validation
- Organize components in logical directory structure
- Use React Router DOM for navigation

## Testing Requirements

### Backend Tests
- Write unit tests for all business logic
- Test API endpoints with FastAPI's test client
- Mock external dependencies (Firebase, external APIs)
- Aim for >80% code coverage
- Use pytest fixtures for common test setup

### Frontend Tests
- Write unit tests for components using Vitest + Testing Library
- Write e2e tests for critical user flows using Playwright
- Test user interactions and component state changes
- Mock API calls in unit tests
- Use Playwright for browser automation in e2e tests

## Dependencies

### Adding Backend Dependencies
1. Add to `billingonaire_backend/requirements.txt`
2. Pin exact versions (e.g., `fastapi==0.104.1`)
3. Run security scan if available
4. Update requirements and test

### Adding Frontend Dependencies
1. Use `npm install <package>` in `billingonaire-ui/`
2. Commit both `package.json` and `package-lock.json`
3. Verify build still works

## Key Features & Modules

### Backend Modules
- **Board.py**: PDF parsing and court board management
- **CourtScraper.py**: Web scraping for court data
- **OrderManager.py**: Court order management
- **Dashboard.py**: Analytics and dashboard data
- **UserManager.py**: User authentication and management
- **ml_enhanced_parser.py**: ML-powered document parsing
- **order_analyzer.py**: Court order analysis

### Frontend Components
- **Login.jsx**: Authentication UI
- **Dashboard.jsx**: Main dashboard with analytics
- **Upload.jsx**: PDF file upload interface
- **OrderManagement.jsx**: Order management interface
- **AdminUserManagement.jsx**: Admin user management
- **BillGeneration.jsx**: AGP-compliant bill export

## CI/CD Pipeline

### Continuous Integration (ci.yml)
- Backend linting (Black, isort, flake8)
- Backend tests (pytest)
- Frontend linting (ESLint)
- Frontend tests (Vitest unit tests, Playwright e2e tests)
- Security scanning (Snyk)

### Continuous Deployment (cd.yml)
- Deploy backend to Google Cloud Run
- Deploy frontend to Firebase Hosting
- Triggered on push to `main` branch

## Environment Variables

### Backend
- Firebase service account credentials (for Firestore)
- `TESTING=true` for test environment

### Frontend
- Firebase config (apiKey, authDomain, projectId, etc.)
- Backend API URL

## Common Tasks

### Running Full Test Suite Locally
```bash
# Backend
cd billingonaire_backend
pytest tests/ -v --cov=. --cov-report=term

# Frontend
cd billingonaire-ui
npm run test:unit
npm run test:e2e
```

### Deploying to Production
```bash
# Deploy both frontend and backend
./firebase/deploy-all.sh

# Or deploy individually
./firebase/backend-cloudrun-deploy.sh
./firebase/frontend-deploy.sh
```

## Security Considerations

- Never commit secrets or API keys
- Use environment variables for sensitive configuration
- Validate all user inputs on backend
- Implement proper authentication checks
- Use Firebase Auth for user management
- Follow OWASP security best practices

## Performance Guidelines

- Optimize PDF parsing for large files
- Use Firebase queries efficiently (proper indexing)
- Implement pagination for large datasets
- Lazy load components in frontend where appropriate
- Cache frequently accessed data

## Documentation

- Keep README.md up to date
- Document API endpoints in FastAPI (auto-generated docs at `/docs`)
- Add JSDoc comments for complex frontend functions
- Update deployment documentation when process changes

## When Making Changes

1. **Understand the Context**: Review related code and tests before making changes
2. **Test Locally**: Run tests and linters before committing
3. **Follow Conventions**: Adhere to project coding standards
4. **Update Tests**: Add/update tests for new functionality
5. **Check CI**: Ensure CI pipeline passes before merging
6. **Update Documentation**: Update README or comments if needed

## Useful Links

- Frontend (Production): https://billingonaire.web.app
- Backend API (Production): https://billingonaire-backend-819125105651.asia-south1.run.app
- API Docs (Local): http://localhost:8000/docs
- Frontend (Local): http://localhost:5000

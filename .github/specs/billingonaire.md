# Billingonaire — Project Specification

## Overview

Billingonaire is a professional legal billing management system built for Additional Government Pleaders (AGPs) working in the Indian legal system. It automates the end-to-end workflow from daily court board PDF ingestion through court order retrieval, ML-powered order analysis, and AGP-compliant billing report generation.

## Domain Concepts

| Term | Definition |
|------|-----------|
| **AGP** | Additional Government Pleader — a government-appointed advocate representing the State in High Court matters |
| **Court Board** | A daily PDF published by the High Court listing all matters scheduled for hearing, with assigned AGPs |
| **Court Order** | A PDF document issued by the court after a hearing, describing the outcome of the matter |
| **Matter** | A single case reference (e.g. `WP/3373/2024`) appearing on a court board |
| **Lifecycle Status** | A state machine field tracking each case from board ingestion through order analysis |
| **Analysis Category** | ML classification of a court order outcome (e.g. `ADJOURNED`, `HEARD_AND_ADJOURNED`, `DISPOSED_OFF`) |
| **Bill** | An AGP-compliant fee claim document, exported as Excel, covering all appearances in a date range |

## Architecture

```
billingonaire/
├── billingonaire_backend/     # Python 3.11 · FastAPI · Uvicorn
│   ├── main.py                # API route registration entry point
│   ├── Board.py               # PDF parsing, board ingestion, case extraction
│   ├── CourtScraper.py        # Bombay High Court scraping for order PDFs
│   ├── OrderManager.py        # Court order download, storage, lifecycle management
│   ├── AutoOrderManager.py    # Background job orchestration (fetch + analyse)
│   ├── Dashboard.py           # Analytics aggregations (weekly, monthly, AGP stats)
│   ├── UserManager.py         # Firebase Auth + Firestore user/role management
│   ├── UserMatterMatcher.py   # Name-variation based AGP→case matching
│   ├── order_analyzer.py      # ML rule-based order classification
│   ├── ml_enhanced_parser.py  # LLM-assisted fallback parsing
│   ├── llm_extractor.py       # LLM extraction with Ollama/Firecrawl
│   ├── case_data_store.py     # Firestore read/write helpers
│   └── specs/                 # BDD feature specs and step definitions
│       ├── features/          # Gherkin .feature files
│       └── steps/             # pytest-bdd step implementations
│
├── billingonaire-ui/          # React 19 · Vite · React Bootstrap
│   └── src/
│       ├── Login.jsx
│       ├── Dashboard.jsx
│       ├── Upload.jsx
│       ├── OrderManagement.jsx
│       ├── AdminUserManagement.jsx
│       └── BillGeneration.jsx
│
├── firebase/                  # Deployment shell scripts
├── .github/
│   ├── workflows/             # CI (ci.yml) and CD (cd.yml)
│   ├── SDLC_SPEC.md           # Engineering governance document
│   ├── copilot-instructions.md
│   └── specs/                 # Specify skill and spec files (this directory)
└── docs/
    └── CURRENT_WORKFLOW.md    # Async board/case/order workflow details
```

## Technology Stack

| Layer | Technology |
|-------|-----------|
| Backend language | Python 3.11 |
| Backend framework | FastAPI + Uvicorn |
| Backend formatter | Black (line length 88) |
| Backend linter | flake8 · isort · mypy |
| Database | Firebase Firestore |
| Auth | Firebase Auth (Admin SDK) |
| Frontend framework | React 19 · Vite |
| Frontend styling | React Bootstrap |
| Frontend linter | ESLint |
| Frontend tests | Vitest (unit) · Playwright (e2e) |
| Backend tests | pytest · pytest-asyncio · pytest-mock |
| Backend BDD specs | pytest-bdd (Gherkin features + steps) |
| CI/CD | GitHub Actions |
| Backend hosting | Google Cloud Run (asia-south1) |
| Frontend hosting | Firebase Hosting |
| LLM fallback | Ollama (GKE preferred, Cloud Run alternate) |

## Case Lifecycle State Machine

```
board_ingested
      │
      ▼
fetch_queued  ──► fetch_in_progress ──► fetch_succeeded ──► analysis_queued
      │                                                              │
      └─► fetch_failed_retryable                                     ▼
               │                                          analysis_in_progress
               ▼                                                     │
        fetch_failed_terminal                        ┌───────────────┼───────────────────┐
                                                     ▼               ▼                   ▼
                                              analysed  analysis_failed_retryable  analysis_failed_terminal
```

Manual override is available from any terminal state.

## API Surface Summary

### Board Ingestion
| Endpoint | Method | Auth | Description |
|----------|--------|------|-------------|
| `/upload-pdf` | POST | Admin only (`require_admin`) | Upload court board PDF; returns `{ "results": [...] }` with parse status and case counts |
| `/save-data` | POST | Admin only (`require_admin`) | Persist parsed board records to Firestore |
| `/get-data` | POST | Authenticated active user | Retrieve board records for a given date |

### Court Orders
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/orders/cases-without-orders` | GET | List cases not yet linked to an order |
| `/orders/create-link` | POST | Attach an order URL to a case |
| `/orders/update-status` | PUT | Update order lifecycle status |
| `/jobs/fetch-orders` | POST | Trigger background order-fetch job |
| `/jobs/retry-failed` | POST | Re-queue retryable failed fetches |
| `/jobs/analyze-orders` | POST | Trigger background order-analysis job |
| `/auto-orders/analyze-case/{id}` | POST | Analyze a single case order |

### Analysis
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/analyze-order` | POST | Classify a court order PDF |
| `/analysis-history` | GET | Retrieve past analysis for a case |
| `/analysis-stats` | GET | Aggregate counts per analysis_category |

### Dashboard
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/dashboard/weekly-status` | GET | Case counts grouped by category for current week |
| `/dashboard/agp-stats` | GET | Per-AGP matter counts and categories |
| `/dashboard/monthly-avg` | GET | Monthly average appearance counts |
| `/dashboard/matters-by-date-range` | GET | Matters filtered by date range |
| `/dashboard/agp-distribution-weekly` | GET | Per-AGP appearances for current week |
| `/dashboard/agp-distribution-monthly` | GET | Per-AGP appearances for current month |
| `/dashboard/board-date-summary` | GET | Board dates with total case counts |
| `/dashboard/board-date-agp-distribution` | GET | Per-AGP case count for a board date |
| `/dashboard/board-date-cases` | GET | All cases for a specific board date |

### Bills
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/bills/generate` | GET | Generate billable matters for a date range |
| `/bills/export/excel` | GET | Download bill as Excel workbook |
| `/bills/save` | POST | Save generated bill to Firestore |
| `/bills/my-bills` | GET | List saved bills for current user |
| `/bills/{bill_id}` | GET | Retrieve a specific saved bill |
| `/bills/{bill_id}` | DELETE | Delete a saved bill |

### Users & Roles
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/user/profile` | GET | Get current user's profile |
| `/user/profile` | POST | Update current user's profile |
| `/user/change-password` | POST | Change user password |
| `/user-matters/configure-role` | POST | Set AGP role and name variants |
| `/user-matters/role-config` | GET | Get current user's role configuration |
| `/user-matters/generate-name-variations` | POST | Generate AGP name variants for matching |
| `/user-matters/my-matters` | GET | List matters matched to current user |
| `/admin/users` | GET | List all users (admin only) |
| `/admin/user/{uid}/role` | POST | Set a user's role (admin only) |
| `/admin/sync-firebase-users` | POST | Sync Firebase Auth users to Firestore |
| `/admin/create-user` | POST | Create a new user in Firebase Auth + Firestore |
| `/admin/order-status-overview` | GET | Count cases per lifecycle status (admin only) |
| `/queue/status` | GET | Report pending job queue sizes |
| `/cases/lifecycle` | GET | Full lifecycle view for a board date |
| `/cases/{case_ref}/manual-override` | POST | Manual override for terminal-state cases |

## Firestore Collections

| Collection | Purpose |
|-----------|---------|
| `daily-boards` | Parsed case records from court board PDFs |
| `case-details` | Per-case lifecycle state, order metadata, and ML analysis results |
| `users` | User profiles (auth-linked metadata) |
| `user-roles` | User role assignments and name-variation configuration |
| `user-case-mappings` | AGP-to-case match records |
| `user-bills` | Saved AGP billing reports per user |

## Environment Variables

| Variable | Required | Purpose |
|----------|----------|---------|
| `GCLOUD_SERVICE_ACCOUNT_KEY` | Production | Google Cloud auth for Cloud Run deployment |
| `FIRECRAWL_API_KEY` | Production | Firecrawl PDF extraction API |
| `ORDER_ENABLE_LLM_FALLBACK` | Optional | Enable LLM fallback for low-confidence analysis |
| `ORDER_LLM_PROVIDER` | Optional | LLM provider (e.g. `ollama`) |
| `ORDER_LLM_MODEL` | Optional | LLM model name |
| `OLLAMA_BASE_URL` | Optional | Ollama service endpoint URL |
| `ORDER_LLM_TIMEOUT_SECONDS` | Optional | LLM request timeout |
| `ORDER_LLM_FALLBACK_MIN_QUALITY` | Optional | Minimum quality score to accept LLM result |
| `ORDER_LLM_FALLBACK_MIN_CATEGORY_CONFIDENCE` | Optional | Confidence threshold to skip LLM fallback |
| `ORDER_LLM_FALLBACK_MIN_CASES` | Optional | Minimum case count to attempt LLM fallback |
| `TESTING` | Test only | Set to `true` to activate test mocks |

## Development Commands

```bash
# --- Backend ---
cd billingonaire_backend
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8000 --reload   # dev server
pytest tests/unit -v --cov=. --cov-report=term          # unit tests
black .                                                  # format
isort .                                                  # sort imports
flake8 . --config=.flake8                               # lint

# --- Frontend ---
cd billingonaire-ui
npm install
npm run dev                   # dev server (http://localhost:5000)
npm run test:unit             # Vitest unit tests
npm run test:e2e              # Playwright e2e tests
npm run lint                  # ESLint
npm run build                 # production build
```

## Coding Conventions

- Backend: PEP 8, Black-formatted (88 chars), isort-sorted imports, type hints on all public functions
- Frontend: functional React components only; hooks (`useState`, `useEffect`); no class components
- Tests: pytest for backend; Vitest + React Testing Library for frontend unit tests; Playwright for e2e
- Secrets: never committed; production secrets in Google Secret Manager; local dev uses `.env` (gitignored)
- All PRs must pass CI (lint + tests) before merge; direct commits to `main` are disallowed

# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

### Backend (`billingonaire_backend/`)

```bash
# Install
pip install -r requirements.txt -r requirements-test.txt

# Dev server
uvicorn main:app --host 0.0.0.0 --port 8000 --reload

# Tests
pytest tests/unit -v                          # unit tests only
pytest tests/unit -k "test_name"              # single test
pytest tests/unit specs/ -v                   # unit + BDD specs
TESTING=true pytest tests/unit -v             # with TESTING flag (skips real Firebase)

# Linting (CI-pinned versions — use venv if system black differs)
black .
isort .
flake8 . --config=.flake8
```

The Stop hook in `.claude/settings.json` runs black (CI-pinned `==23.12.1` from `/tmp/black-ci-venv/`), isort, and flake8 automatically after every Claude turn. CI pins: `black==23.12.1`, `isort==5.13.2`, `flake8==6.1.0`.

flake8 ignores E203/E501/W503 (line length 88, matching black). Test files suppress F401/F841.

### Frontend (`billingonaire-ui/`)

```bash
npm install
npm run dev                 # http://localhost:5000
npm run test:unit:fast      # Vitest, no coverage
npm run test:unit           # Vitest with coverage
npm run test:e2e:fast       # Playwright, Chromium only
npm run lint                # ESLint
npm run build
```

## Architecture

**Billingonaire** automates AGP (Assistant Government Pleader) billing for the Bombay High Court. It ingests daily board PDFs, fetches and classifies court orders, then generates billing exports.

**Stack:** FastAPI + Python 3.11 backend · React 19 + Vite frontend · Firebase Firestore · Google Cloud Run (backend) + Firebase Hosting (frontend)

### Backend modules

| File | Responsibility |
|------|---------------|
| `main.py` | FastAPI app (~3500 lines). All REST endpoints. Lazy Firebase init guarded by `TESTING` env var. ThreadPoolExecutor pools for async order fetch and analysis. |
| `Board.py` | Parses court board PDFs via `pdfplumber`. Extracts case records, deduplicates, saves to `daily-boards` Firestore collection. Contains `create_record()` for per-row lawyer extraction. |
| `order_analyzer.py` | `OrderDocumentAnalyzer` — classifies orders as `ADJOURNED` / `HEARD_AND_ADJOURNED` / `DISPOSED_OFF` using weighted regex scoring plus a `NO_TIME_PATTERNS` hard gate (paucity/want of time → always ADJOURNED). Also extracts parties, advocates, and AGPs from order PDFs. |
| `AutoOrderManager.py` | Orchestrates background fetch → analysis pipeline. `_process_single_case()` drives the lifecycle state machine; `_process_all_orders_from_api()` fetches PDFs from the court API. |
| `case_data_store.py` | `CaseDataStore` — enforces the case lifecycle state machine. States flow: `board_ingested → fetch_queued → fetch_in_progress → fetch_succeeded → analysis_queued → analysis_in_progress → analysed`. Call `transition_lifecycle()` for all state changes. |
| `CourtScraper.py` | Scrapes Bombay HC eCourts portal for case status and order links. |
| `UserMatterMatcher.py` | Fuzzy-matches AGP names on board records to registered user accounts (50% threshold). Drives the "my matters" and billing export features. |
| `Dashboard.py` | Aggregation queries for the analytics dashboard. |
| `ml_enhanced_parser.py` | `MLEnhancedParser` wraps `pdfplumber` + optional spaCy (`en_core_web_sm`) for richer PDF text extraction. spaCy is optional — code degrades gracefully when the model is absent. |

### Firestore collections

- **`daily-boards`** — one document per board row (case on a given date). Primary workhorse collection. Fields include `lifecycle_status`, `board_date`, `case_id`, `petitioner_lawyer`, `respondent_lawyer`, `government_pleader`, `order_category`, `order_petitioner`, `order_respondent`.
- **`case-details`** — order analysis results keyed by `case_id`. Written by `order_analyzer` after successful analysis.
- **`user-roles`** — user account records with `legal_category` (e.g. `assistant_government_pleader`).
- **`user-case-mappings`** — fuzzy-match results linking users to board rows.

### Order classification

`OrderDocumentAnalyzer._classify_order_enhanced()` is the entry point. Flow:

1. **`NO_TIME_PATTERNS` gate** — if text contains `paucity of time` or `want of time`, return `ADJOURNED` immediately (confidence 0.95) without running the scorer.
2. **Weighted regex scorer** (`_classify_order()`) — accumulates scores across `DISPOSED_OFF` / `ADJOURNED` / `HEARD_AND_ADJOURNED` pattern lists. Patterns have explicit weights (2.5 for strong, 2.0 for medium, 1.5 for reliable, 1.0 default). `STRONG_DISPOSAL_PATTERNS` triggers an absolute `DISPOSED_OFF` override.
3. **Business-rule overrides** — prefer `HEARD_AND_ADJOURNED` over `ADJOURNED` when its score ≥ 30% of ADJOURNED's score, unless a non-hearing adjournment is detected.

Key classification rules:
- `"stand over"` alone is an ADJOURNED signal (weight 1.5) but NOT a hard gate — it also appears in `"heard, stand over to [date]"` (HEARD_AND_ADJOURNED).
- `"issue notice"` / `"notice returnable"` / `"interim relief granted"` → HEARD_AND_ADJOURNED (weight 2.5).
- `"rule made absolute"` → DISPOSED_OFF (STRONG_DISPOSAL).
- `"petition is granted"` is NOT a DISPOSED_OFF pattern (too broad — fires on interim relief orders).

### Testing patterns

All unit tests mock Firebase. The root `conftest.py` provides a `mock_firestore_client` fixture. Modules that call `firestore.client()` at import time are patched via `unittest.mock.patch`. Set `TESTING=true` to suppress real Firebase initialization in `main.py`.

BDD specs live in `specs/` using pytest-bdd (Gherkin). Run with `pytest specs/`.

## CI pipeline

GitHub Actions (`.github/workflows/ci.yml`) is path-filtered — backend jobs only run when `billingonaire_backend/` files change, frontend jobs only when `billingonaire-ui/` files change. Backend jobs: lint (black/isort/flake8/mypy on `CourtScraper.py` only) → unit tests → BDD specs. Frontend jobs: ESLint → Vitest → Playwright.

## Deployment

```bash
./firebase/backend-cloudrun-deploy.sh   # Cloud Run (asia-south1)
./firebase/frontend-deploy.sh           # Firebase Hosting
./firebase/deploy-all.sh                # Both
```

Production URLs: backend `https://billingonaire-backend-819125105651.asia-south1.run.app` · frontend `https://billingonaire.web.app`.

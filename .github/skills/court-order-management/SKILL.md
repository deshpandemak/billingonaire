---
name: court-order-management
description: Manage the full lifecycle of court orders — from linking an order URL to a case through background fetch, retry, and manual override — using the case lifecycle state machine.
---

## Overview

Court order management covers everything that happens after a case appears on the court board. Each case moves through a well-defined lifecycle state machine as its associated court order is discovered, downloaded, and (eventually) analysed. Background jobs handle bulk fetching and retrying; admin endpoints expose the status overview and manual override.

## Key Files

- `billingonaire_backend/OrderManager.py` — order download, link creation, status updates
- `billingonaire_backend/AutoOrderManager.py` — background job orchestration (fetch + analyse)
- `billingonaire_backend/CourtScraper.py` — Bombay High Court scraping to find order PDFs
- `billingonaire_backend/case_data_store.py` — Firestore helpers for case-details collection
- `billingonaire_backend/main.py` — route handlers under `/orders/`, `/jobs/`, `/cases/`, `/queue/`, `/admin/`
- `billingonaire_backend/specs/features/order_management.feature` — acceptance scenarios
- `billingonaire_backend/specs/steps/order_management_steps.py` — step implementations

## Firestore Collections Used

| Collection | Operation | Key Fields |
|-----------|-----------|-----------|
| `case-details` | read/write | `case_ref`, `lifecycle_status`, `order_url`, `order_pdf_path`, `lifecycle_events[]` |

## Case Lifecycle State Machine

```
board_ingested
      │  (queue for fetch)
      ▼
fetch_queued ──► fetch_in_progress ──► fetch_succeeded ──► analysis_queued
      │                                                           │
      └─► fetch_failed_retryable                                  ▼
               │                                       analysis_in_progress
               ▼                                                  │
        fetch_failed_terminal            ┌─────────────────────────┼──────────────────────────┐
                                         ▼                         ▼                          ▼
                                      analysed     analysis_failed_retryable   analysis_failed_terminal
```

Valid forward transitions only. Invalid transitions must be rejected. A `lifecycle_events` array records every transition with timestamp and source.

## API Endpoints

| Endpoint | Method | Auth | Description |
|----------|--------|------|-------------|
| `/orders/cases-without-orders` | GET | Authenticated | Cases with `order_status = fetch_queued` |
| `/orders/create-link` | POST | Authenticated | Attach `order_url` to a case; set status to `linked` |
| `/orders/update-status` | PUT | Authenticated | Update `lifecycle_status` for a case |
| `/jobs/fetch-orders` | POST | Admin active (`require_admin_active`) | Enqueue all `fetch_queued` cases for download |
| `/jobs/retry-failed` | POST | Admin active (`require_admin_active`) | Re-queue `fetch_failed_retryable` cases |
| `/jobs/analyze-orders` | POST | Admin active (`require_admin_active`) | Enqueue all `fetch_succeeded` cases for analysis |
| `/auto-orders/analyze-case/{id}` | POST | Authenticated | Analyze a single case synchronously |
| `/queue/status` | GET | Authenticated | Pending fetch queue size |
| `/cases/lifecycle` | GET | Authenticated | Full lifecycle view for a board date |
| `/cases/{case_ref}/manual-override` | POST | Admin active (`require_admin_active`) | Override terminal-state case with manual order data |
| `/admin/order-status-overview` | GET | Admin (`require_admin`) | Count of cases per lifecycle_status |

## Business Rules

- Only `fetch_failed_retryable` cases are eligible for the retry job; `fetch_failed_terminal` cases require a manual override.
- Background jobs must be non-blocking; job enqueueing endpoints return 200 immediately.
- `CourtScraper` uses the Bombay High Court direct API as the primary mechanism for discovering order download URLs, with Playwright as the fallback when the direct path does not produce structured data.
- Manual override records a `manual_override` event in `lifecycle_events`.

## Web Scraping

`CourtScraper` (`BombayHighCourtScraper`) uses the Bombay High Court direct API to fetch case details and order links, then falls back to Playwright if the API path is unavailable or incomplete.

### How It Works

1. The caller invokes `get_case_details(case_ref)` or `get_case_orders(case_ref, date)`.
2. `CourtScraper` parses the Bombay High Court direct API response, normalises case details, and extracts order links from the returned HTML table.
3. If the direct path cannot provide usable results, `CourtScraper` uses Playwright to follow the supported browser flow.
4. Results are normalised into the shared order dict shape (`case_details`, `court_orders[]`, `source: "direct_api"` or `"playwright_new_scraper"`).

### Environment Variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `COURT_SCRAPER_PROVIDER` | `direct_api` | Scraper mode (`direct_api` or `playwright`) |

### Extension Pattern

To add a new field to the scraper output:
1. Update the direct API or Playwright extraction logic in `CourtScraper.py`.
2. Map the new field into the returned dict shape.
3. Add a unit test in `tests/unit/test_court_scraper.py` covering the normalization logic.



When adding a new lifecycle transition or job type:

1. Define the new status constant in `case_data_store.py`.
2. Add the transition guard in `OrderManager.py` — reject invalid source states.
3. Append a `lifecycle_events` entry with `{"status": "...", "timestamp": "...", "source": "..."}`.
4. Add the corresponding route in `main.py` following the existing pattern.
5. Write a unit test for the transition guard and a BDD scenario in `specs/features/order_management.feature`.

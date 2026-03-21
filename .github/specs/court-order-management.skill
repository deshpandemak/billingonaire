---
name: court-order-management
description: Manage the full lifecycle of court orders — from linking an order URL to a case through background fetch, retry, and manual override — using the case lifecycle state machine.
tags: [backend, orders, lifecycle, firestore, jobs]
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
- `CourtScraper` uses **Firecrawl as the primary mechanism** for discovering order download URLs. Firecrawl crawls `bombayhighcourt.nic.in` using an AI agent prompt, bypassing the CAPTCHA that blocks direct e-courts scraping. When `FIRECRAWL_API_KEY` is not configured, the endpoint returns a `captcha_required` stub instead of order data.
- Manual override records a `manual_override` event in `lifecycle_events`.

## Web Scraping — Firecrawl Integration

`CourtScraper` (`BombayHighCourtScraper`) uses the **Firecrawl SDK** to scrape `bombayhighcourt.nic.in` for case details and court order download URLs. Firecrawl is required because the Bombay High Court's e-courts portal returns a CAPTCHA challenge when accessed programmatically, making traditional HTTP scraping unreliable.

### How It Works

1. The caller invokes `get_case_details(case_ref)` or `get_case_orders(case_ref, date)`.
2. `CourtScraper` builds a structured extraction prompt describing the case (e.g. "Civil Writ Petition 3373 of 2025") and passes a wildcard `bombayhighcourt.nic.in/*` URL to Firecrawl.
3. Firecrawl's AI agent crawls the site, extracts petitioner/respondent names, case status URL, and a list of court orders with their download links.
4. Results are returned as a `FirecrawlOrderExtraction` Pydantic model normalised into the shared order dict shape (`case_details`, `court_orders[]`, `source: "firecrawl"`).
5. If `FIRECRAWL_API_KEY` is absent or the extraction fails, the endpoint returns a `captcha_required` stub — **no order data is available in this fallback path**.

### Environment Variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `FIRECRAWL_API_KEY` | _(required for live use)_ | API key for the Firecrawl service |
| `FIRECRAWL_MODEL` | `spark-1-mini` | Firecrawl AI model used for structured extraction |

### Key Pydantic Models (CourtScraper.py)

| Model | Fields |
|-------|--------|
| `FirecrawlCaseDetails` | `petitioner_name`, `respondent_name`, `case_number`, `case_status_url` (each with `_citation`) |
| `FirecrawlCourtOrder` | `listing_date`, `download_url`, `order_description` (each with `_citation`) |
| `FirecrawlOrderExtraction` | `case_details: FirecrawlCaseDetails`, `court_orders: List[FirecrawlCourtOrder]` |

### Extension Pattern

To add a new field to the Firecrawl extraction output:
1. Add the field to the appropriate Pydantic model in `CourtScraper.py`.
2. Update `_build_firecrawl_prompt` to instruct the AI agent to extract the new field.
3. Update `_normalize_firecrawl_payload` to map the new field into the returned dict.
4. Add a unit test in `tests/unit/test_court_scraper.py` covering the normalisation logic.



When adding a new lifecycle transition or job type:

1. Define the new status constant in `case_data_store.py`.
2. Add the transition guard in `OrderManager.py` — reject invalid source states.
3. Append a `lifecycle_events` entry with `{"status": "...", "timestamp": "...", "source": "..."}`.
4. Add the corresponding route in `main.py` following the existing pattern.
5. Write a unit test for the transition guard and a BDD scenario in `specs/features/order_management.feature`.

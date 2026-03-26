---
name: order-analysis
description: Classify court order PDFs using Billingonaire's rule-based analyzer, then persist the analysis result and update the case lifecycle status.
---

## Overview

Order analysis takes a downloaded court order PDF and produces a structured classification result. The primary path is a deterministic rule-based classifier implemented inside `order_analyzer.py`. `ml_enhanced_parser.py` provides extraction utilities used before classification. Analysis results are stored on the `case-details` Firestore document (`latest_order_*` fields and `orders[]` array) and the case lifecycle is advanced to `analysed`.

## Key Files

- `billingonaire_backend/order_analyzer.py` — rule-based classification
- `billingonaire_backend/ml_enhanced_parser.py` — additional ML-assisted extraction utilities
- `billingonaire_backend/main.py` — `/analyze-order`, `/analysis-history`, `/analysis-stats`, `/jobs/analyze-orders`, `/auto-orders/analyze-case/{id}`
- `billingonaire_backend/specs/features/order_analysis.feature` — acceptance scenarios
- `billingonaire_backend/specs/steps/order_analysis_steps.py` — step implementations

## Firestore Collections Used

| Collection | Operation | Key Fields |
|-----------|-----------|-----------|
| `case-details` | read/write | `lifecycle_status`, `latest_order_category`, `latest_order_date`, `latest_order_status`, `orders[]` |

## Analysis Categories

The classifier currently supports exactly these three categories (see `order_analyzer.py`):

| Category | Description |
|---------|-------------|
| `ADJOURNED` | Matter adjourned without substantive hearing |
| `HEARD_AND_ADJOURNED` | Matter heard and adjourned to a future date |
| `DISPOSED_OFF` | Petition dismissed or otherwise finally disposed |

## API Endpoints

| Endpoint | Method | Auth | Description |
|----------|--------|------|-------------|
| `/analyze-order` | POST | Authenticated | Classify a court order PDF |
| `/analysis-history` | GET | Authenticated | Past analysis records for a `case_ref` |
| `/analysis-stats` | GET | Authenticated | Aggregate counts per `analysis_category` |
| `/jobs/analyze-orders` | POST | Admin active (`require_admin_active`) | Background job: analyse all `fetch_succeeded` cases |
| `/auto-orders/analyze-case/{id}` | POST | Authenticated | Synchronously analyse one case by ID |

## Business Rules

- Deterministic extraction and classification are the only analysis path.
- An empty or corrupt PDF returns HTTP 400 with a descriptive error.
- `category_confidence` must be included in every response; ≥ 0.70 is considered reliable.
- A successful analysis advances the case to `analysed`; failure advances to `analysis_failed_retryable` or `analysis_failed_terminal`.

## Implementation Pattern

When adding a new analysis category or extraction rule:

1. Add the new category constant and rule patterns to `order_analyzer.py`.
2. Ensure the new rule does not degrade confidence on already-classified categories — run existing unit tests.
3. Add a Gherkin scenario to `specs/features/order_analysis.feature` covering the new category.
4. Write a unit test for the new rule in `tests/unit/`.

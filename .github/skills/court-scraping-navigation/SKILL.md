---
name: court-scraping-navigation
description: Understand the supported Bombay High Court order lookup flow and make changes to the direct API and Playwright fallback scraper paths.
---

## Overview

Billingonaire now supports two scraper paths only:

- `direct_api` — default path against `https://bombayhighcourt.gov.in/bhc/casestatus/casenumber`
- `playwright` — browser fallback when the direct API path cannot return usable results

All scraping work should preserve that architecture. Do not reintroduce Firecrawl, Ollama, or older multi-provider routing.

## Supported Flow

1. Load the case-number search form from the `gov.in` portal.
2. Extract `_token` and the first `form_secret` hidden input.
3. Request case types for `side=1` from `/bhc/get-case-types-by-side`.
4. Submit the case search form with side, stamp/register mode, case type, case number, and year.
5. Parse the JSON response payload and read the HTML in the `page` field.
6. Extract case details from `#cn_CaseNoUpdates`.
7. Extract order rows from `#cn_CaseNoOrders table tbody tr`.
8. If the direct path fails to provide usable data, follow the equivalent user flow in Playwright.

## Key Files

- `billingonaire_backend/CourtScraper.py` — direct API and Playwright scraper implementation
- `billingonaire_backend/tests/unit/test_court_scraper.py` — scraper regression coverage
- `billingonaire_backend/main.py` — scraper configuration endpoints

## Working Rules

- Keep `direct_api` as the default provider.
- Keep `playwright` as the only fallback provider.
- Return normalized result shapes consistently across both providers.
- Prefer fixing selector or payload parsing issues at the extraction layer instead of adding provider-specific hacks elsewhere.

## When Updating Scraper Logic

1. Update the parsing or provider-selection code in `CourtScraper.py`.
2. Add or adjust unit coverage in `tests/unit/test_court_scraper.py`.
3. Validate that `get_case_details`, `get_case_orders`, and `debug_case_orders` still return the expected shape.

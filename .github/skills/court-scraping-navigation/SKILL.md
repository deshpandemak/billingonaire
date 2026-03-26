---
name: court-scraping-navigation
description: Understand the sequence of navigation to fetch court order links from the Bombay High Court website, and make changes to Playwright, Firecrawl and Ollama-based scraping to follow that sequence.
tags: [backend, scraping, playwright, firecrawl, ollama, court, orders]
---

## Overview

The Bombay High Court case status portal at `https://bombayhighcourt.gov.in/bhc/casestatus/casenumber` provides direct case number search. Playwright (primary), Firecrawl AI-agent, and Ollama HTML-extraction all follow the same logical navigation sequence to find petitioner/respondent names, case summary, and court order links.

## Navigation Sequence

```
https://bombayhighcourt.gov.in/bhc/casestatus/casenumber
        │
  [Case Number Search Form]
  ┌─────────────────────────────────────────────────────────────────────┐
  │ Side        : AS  (Appellate Side — default for WP/PIL)             │
  │               OS  (Original Side)                                   │
  │ Stamp/Regn. : Register  ← default                                   │
  │               Stamp     ← set when case type ends with "(ST)"        │
  │               (e.g. WP(ST)/294/2025 → Type=WP, Stamp/Regn=Stamp)   │
  │ Type        : e.g. WP  (base type, without "(ST)")                  │
  │ Number      : e.g. 3373  (the numeric part only)                    │
  │ Year        : e.g. 2025                                             │
  └─────────────────────────────────────────────────────────────────────┘
        │ click Search
        ▼
  [Case Details Page]
  ┌──────────────────────────────────────────────────────────────────────┐
  │ Case No. WP/3373/2025 with CNR No. HCBM010116572025, was filed on   │
  │ 26/02/2025 at Bombay High Court by <petitioner> against <respondent>│
  │                                                                      │
  │ Petitioner: <petitioner name>  ← extract                            │
  │ Respondent: <respondent name>  ← extract                            │
  │                                                                      │
  │ [ Orders/Judgements ]  ← click this tab/button                      │
  └──────────────────────────────────────────────────────────────────────┘
        │
        ▼
  [Orders/Judgements Table]
  ┌──────────────────────────────────────────────────────────────────────┐
  │ Date        │  Order link                                            │
  │─────────────┼──────────────────────────────────────────────────────  │
  │ 09/04/2025  │ <a href="…/order-1.pdf">Order/Judg-1</a>              │ ← collect date + href
  │ 08/04/2025  │ <a href="…/order-2.pdf">Order/Judg-2</a>              │ ← collect date + href
  └──────────────────────────────────────────────────────────────────────┘
        │
        ▼
  Return ALL rows — no date filtering
```

## Key Files

| File | Responsibility |
|------|----------------|
| `billingonaire_backend/CourtScraper.py` | All scraping logic: Playwright flow, Firecrawl prompt, Ollama extraction, candidate URL building |
| `billingonaire_backend/tests/unit/test_court_scraper.py` | Unit tests for prompts, navigation URLs, extraction logic |
| `.github/skills/court-order-management/SKILL.md` | Order lifecycle and broader court order management |

## Side Field Determination

The BHC portal search form has a **Side dropdown** that selects the court side:

| Side Value | When to use |
|------------|-------------|
| `AS` | Appellate Side — default for WP, PIL, APL, and most matters |
| `OS` | Original Side — for company/civil original matters |

Helper method:
```python
scraper._get_side_code("mumbai")          # → "AS"
scraper._get_side_code("mumbai_original") # → "OS"
```

## Stamp/Regn Field Determination

The BHC portal search form has a **Stamp/Regn. dropdown** with two options:

| Stamp/Regn. Value | When to use |
|-------------------|-------------|
| `Register` | Default — all regular case types (WP, PIL, APL, WPL, …) |
| `Stamp` | Case type ends with `(ST)` — e.g. `WP(ST)/294/2025` |

> **Note:** The new BHC portal uses `"Register"` (not `"Registration"`). The legacy
> eCourts helper `_get_stamp_regn_type()` still returns `"Registration"` for backward
> compatibility. Use `_get_stamp_regn_bhc()` for the new portal.

The `(ST)` suffix is part of the case reference as provided by the user. It is not passed to the Type dropdown; instead the base type (e.g. `WP`) is entered there, and the Stamp/Regn. dropdown is set to `Stamp`.

### Helper methods in `CourtScraper.py`

```python
scraper._get_stamp_regn_bhc("WP")        # → "Register"   (new BHC portal)
scraper._get_stamp_regn_bhc("WP(ST)")    # → "Stamp"
scraper._get_stamp_regn_type("WP")       # → "Registration" (legacy eCourts)
scraper._get_stamp_regn_type("WP(ST)")   # → "Stamp"
scraper._get_base_case_type("WP(ST)")    # → "WP"
scraper._get_base_case_type("WP")        # → "WP"
scraper._build_short_title("A Ltd", "State of MH")  # → "A Ltd against State of MH"
```

`parse_case_number()` accepts both formats:
```python
scraper.parse_case_number("WP/3373/2025")     # → {"case_type": "WP", ...}
scraper.parse_case_number("WP(ST)/294/2025")  # → {"case_type": "WP(ST)", ...}
```

## Playwright Integration (Primary)

Playwright is the primary scraping method, navigating the new BHC portal interactively.

### How it works

1. `_fetch_with_playwright()` launches a Chromium browser (headless by default).
2. Navigates to `https://bombayhighcourt.gov.in/bhc/casestatus/casenumber`.
3. `_playwright_fill_bhc_form()` fills the form with Side, Stamp/Regn., Type, Number, Year using prioritised selector lists.
4. `_playwright_click_search()` submits the form.
5. `_playwright_extract_parties()` and `_playwright_extract_case_summary()` read the case details page.
6. `_playwright_click_orders_tab()` clicks the Orders/Judgements tab.
7. `_playwright_extract_orders_from_table()` collects all order rows (date + download link).

### Environment Variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `COURT_PLAYWRIGHT_HEADLESS` | `true` | Run Chromium headless |
| `COURT_PLAYWRIGHT_TIMEOUT_SECONDS` | `25` | Per-navigation timeout |

## Firecrawl Integration

Firecrawl uses an AI agent that can navigate the browser and extract structured data.

### How it works

1. `_fetch_with_firecrawl()` initialises a `FirecrawlApp` with `FIRECRAWL_API_KEY`.
2. `agent_urls` is set with **the new BHC portal first**:
   ```python
   agent_urls = [
       "https://bombayhighcourt.gov.in/bhc/casestatus/casenumber",
       "https://bombayhighcourt.gov.in/*",
       "https://hcservices.ecourts.gov.in/ecourtindiaHC/cases/case_no.php",
       "https://hcservices.ecourts.gov.in/ecourtindiaHC/*",
   ]
   ```
3. The prompt (from `_build_firecrawl_prompt()`) instructs the agent step-by-step:
   - Step 1: Open `https://bombayhighcourt.gov.in/bhc/casestatus/casenumber`
   - Step 2: Fill form — Side (AS), Stamp/Regn. ("Register" or "Stamp"), Type, Number, Year → click Search
   - Step 3: On case details page — read case_summary, petitioner, respondent; click "Orders/Judgements"
   - Step 4: Collect ALL rows from the orders table (Date + order href)
4. Result is normalised via `_normalize_firecrawl_payload()` into the shared shape.

### Environment Variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `FIRECRAWL_API_KEY` | _(required)_ | Firecrawl API key |
| `FIRECRAWL_MODEL` | `spark-1-mini` | AI model used for extraction |

## Ollama Integration

The Ollama path uses HTTP requests to fetch page HTML and then calls a locally-hosted LLM to extract structured data.

### How it works

1. `_fetch_with_ollama_scraper()` builds candidate URLs starting with the BHC portal:
   ```python
   urls = [
       "https://bombayhighcourt.gov.in/bhc/casestatus/casenumber",  # primary portal
       "https://hcservices.ecourts.gov.in/.../case_no.php",          # legacy fallback
       "https://hcservices.ecourts.gov.in/.../case_detail.php?...",
       "https://hcservices.ecourts.gov.in/.../order_list.php?...",
   ]
   ```
2. For each URL, it fetches HTML, extracts direct order links, and extracts petitioner/respondent via regex.
3. All collected HTML chunks are sent to Ollama via `_call_ollama_for_orders()`.
4. The prompt describes the new BHC portal navigation so the LLM can correctly identify petitioner/respondent, case summary, and order links.

### Ollama Environment Variables

| Variable | Fallback Chain | Default | Purpose |
|----------|---------------|---------|---------|
| `COURT_OLLAMA_BASE_URL` | `OLLAMA_BASE_URL` → `LLM_BASE_URL` | `http://localhost:11434` | Ollama server URL |
| `COURT_OLLAMA_MODEL` | `ORDER_LLM_MODEL` → `LLM_MODEL` | `llama3.2` | Model for extraction |
| `COURT_OLLAMA_TIMEOUT_SECONDS` | — | `20` | Request timeout in seconds |

### Diagnosing Ollama Errors

If Ollama returns HTTP 5xx, `_call_ollama_for_orders()` logs the status code and returns `None` (no crash). The `get_case_orders()` endpoint then falls back to the `captcha_required` response.

To diagnose:
1. Call `GET /admin/ollama/health` — checks if the service is reachable.
2. Call `GET /admin/ollama/models` — lists available models; confirm the configured model is present.
3. Call `POST /admin/ollama/test-case` with `{"case_ref": "WP/NNNN/YYYY"}` — returns full HTTP trace, Ollama request/response, and final result for debugging.
4. If the model is missing, call `POST /admin/ollama-pull-model` to trigger a download.

## Provider Selection

The scraper provider is controlled by `COURT_SCRAPER_PROVIDER` (default: `playwright_first`):

| Provider | Attempt sequence | Behaviour |
|----------|-----------------|-----------|
| `playwright_first` *(default)* | playwright → ollama → firecrawl | Try Playwright; fall back to Ollama, then Firecrawl |
| `playwright_only` | playwright | Only use Playwright; return `captcha_required` if it fails |
| `playwright_then_ollama` | playwright → ollama | Try Playwright, then Ollama |
| `firecrawl_first` | playwright → firecrawl → ollama | Try Playwright first (as the best-effort browser path), then Firecrawl, then Ollama |
| `firecrawl_only` | firecrawl | Only use Firecrawl; return `captcha_required` if unavailable |
| `ollama_then_playwright` | ollama → playwright | Try Ollama first, then Playwright |
| `ollama_first` | ollama → playwright → firecrawl | Try Ollama first, fall back to Playwright, then Firecrawl |
| `ollama_only` | ollama | Only use Ollama; return `captcha_required` if extraction yields nothing |

> The sequences above reflect the actual implementation in `_provider_attempt_sequence()` in `CourtScraper.py`.

Change at runtime (admin only):
```
POST /scraper/configure
{ "provider": "playwright_first" }
```

## Expected Output Shape

`get_case_orders()` returns the following shape:

```json
{
  "status": "found",
  "source": "playwright_scraper" | "firecrawl" | "ollama_scraper",
  "case_summary": "Case No. WP/3373/2025 with CNR No. HCBM010116572025, was filed on 26/02/2025 at Bombay High Court by ... against ...",
  "petitioner": "MOTILAL OSWAL HOME FINANCE LTD THROUGH OFFICER",
  "respondent": "THE STATE OF MAHARASHTRA THROUGH G.P. AND ORS",
  "title": "MOTILAL OSWAL HOME FINANCE LTD THROUGH OFFICER against THE STATE OF MAHARASHTRA THROUGH G.P. AND ORS",
  "case_orders": [
    { "date": "09/04/2025", "download_link": "https://..." },
    { "date": "08/04/2025", "download_link": "https://..." }
  ],
  "case_details": {
    "petitioner_name": "...",
    "respondent_name": "...",
    "case_number": "WP/3373/2025",
    "case_status_url": "https://bombayhighcourt.gov.in/bhc/casestatus/casenumber",
    "case_summary": "...",
    "title": "..."
  },
  "court_orders": [
    { "listing_date": "09/04/2025", "download_url": "https://..." }
  ]
}
```

> `case_orders` (with `date` / `download_link`) is the new canonical format.
> `court_orders` (with `listing_date` / `download_url`) is kept for backward compatibility.

## Making Changes

### To update the Playwright navigation flow
1. Edit `_fetch_with_playwright()` or the helper methods `_playwright_fill_bhc_form()`,
   `_playwright_click_search()`, `_playwright_click_orders_tab()`,
   `_playwright_extract_case_summary()`, `_playwright_extract_parties()`,
   `_playwright_extract_orders_from_table()` in `CourtScraper.py`.
2. Add/update tests in `tests/unit/test_court_scraper.py`.

### To update the Firecrawl navigation prompt
1. Edit `_build_firecrawl_prompt()` in `CourtScraper.py`.
2. Update the unit test `test_firecrawl_prompt_includes_listing_navigation_steps` in `tests/unit/test_court_scraper.py` to assert the new step is present.

### To update the Ollama extraction prompt
1. Edit `_build_ollama_extraction_prompt()` in `CourtScraper.py`.
2. Update the unit test `test_ollama_extraction_prompt_describes_navigation_sequence` in `tests/unit/test_court_scraper.py`.

### To add a new field to the extraction output
1. Add the field to the appropriate Pydantic model (`FirecrawlCaseDetails` or `FirecrawlCourtOrder`).
2. Update `_build_firecrawl_prompt()`, `_build_ollama_extraction_prompt()`, and the Playwright extractors.
3. Update `_normalize_firecrawl_payload()` and `_enrich_case_orders_result()` to map the new field.
4. Add a unit test covering the normalisation.

### To change candidate URLs for the Ollama scraper
1. Edit `_build_candidate_urls()` in `CourtScraper.py`.
2. Update the unit test `test_build_candidate_urls_starts_with_bhc_portal` to assert the new ordering.

## Running Tests

```bash
cd billingonaire_backend
pytest tests/unit/test_court_scraper.py -v
```

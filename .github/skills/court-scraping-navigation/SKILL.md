---
name: court-scraping-navigation
description: Understand the sequence of navigation to fetch court order links from the Bombay High Court website, and make changes to Firecrawl and Ollama-based scraping to follow that sequence.
tags: [backend, scraping, firecrawl, ollama, court, orders]
---

## Overview

The Bombay High Court case search portal requires navigating through a menu system before filling a form and solving a CAPTCHA. Both the Firecrawl AI-agent path and the Ollama HTML-extraction path must follow the same logical navigation sequence to find petitioner/respondent names and court order links.

## Navigation Sequence

```
bombayhighcourt.nic.in (home)
        │
        ▼ click "Case Status" in navigation bar
        │
        ▼ click "Case Number Wise" in dropdown
        │
  [Case Number Search Form]
  ┌─────────────────────────────────────────────────────────────────────┐
  │ Case Type   : e.g. WP  (base type, without "(ST)")                  │
  │ Stamp/Regn  : Registration  ← default                               │
  │               Stamp         ← set when case type ends with "(ST)"   │
  │               (e.g. WP(ST)/294/2025 → Case Type=WP, Stamp/Regn=Stamp) │
  │ Case Number : e.g. 3373  (the numeric part only)                    │
  │ Year        : e.g. 2025                                             │
  │ CAPTCHA     : (solve manually)                                      │
  └─────────────────────────────────────────────────────────────────────┘
        │ submit
        ▼
  [Case Details Page]
  ┌──────────────────────────────────────────────┐
  │ Case: WP/3373/2025                           │
  │ Petitioner: <petitioner name>  ← extract    │
  │ Respondent: <respondent name>  ← extract    │
  │                                              │
  │ [ Listing Dates/Order ]  ← click this       │
  └──────────────────────────────────────────────┘
        │
        ▼
  [Listing Dates/Order Table]
  ┌──────────────────────────────────────────────────────────────────────┐
  │ Date        │ Coram       │ Action │ Order/Judgement                 │
  │─────────────┼─────────────┼────────┼─────────────────────────────── │
  │ 09/04/2025  │ Hon. X, Y   │  ...   │ <a href="…/order-1.pdf">       │ ← collect listing_date + href
  │ 08/04/2025  │ Hon. X, Y   │  ...   │ <a href="…/order-2.pdf">       │ ← collect listing_date + href
  └──────────────────────────────────────────────────────────────────────┘
        │
        ▼
  Return ALL rows — no date filtering
```

## Key Files

| File | Responsibility |
|------|----------------|
| `billingonaire_backend/CourtScraper.py` | All scraping logic: Firecrawl prompt, Ollama extraction, candidate URL building |
| `billingonaire_backend/tests/unit/test_court_scraper.py` | Unit tests for prompts, navigation URLs, extraction logic |
| `.github/skills/court-order-management/SKILL.md` | Order lifecycle and broader court order management |

## Stamp/Regn Field Determination

The Bombay HC search form has a **Stamp/Regn dropdown** with two options:

| Stamp/Regn Value | When to use |
|------------------|-------------|
| `Registration` | Default — all regular case types (WP, PIL, APL, WPL, …) |
| `Stamp` | Case type ends with `(ST)` — e.g. `WP(ST)/294/2025` |

The `(ST)` suffix is part of the case reference as provided by the user. It is not passed to the Case Type dropdown; instead the base type (e.g. `WP`) is entered there, and the Stamp/Regn dropdown is set to `Stamp`.

### Helper methods in `CourtScraper.py`

```python
scraper._get_stamp_regn_type("WP")        # → "Registration"
scraper._get_stamp_regn_type("WP(ST)")    # → "Stamp"
scraper._get_base_case_type("WP(ST)")     # → "WP"
scraper._get_base_case_type("WP")         # → "WP"
```

`parse_case_number()` accepts both formats:
```python
scraper.parse_case_number("WP/3373/2025")     # → {"case_type": "WP", ...}
scraper.parse_case_number("WP(ST)/294/2025")  # → {"case_type": "WP(ST)", ...}
```

## Firecrawl Integration

Firecrawl uses an AI agent that can navigate the browser, solve CAPTCHAs, and extract structured data. The key method is `_build_firecrawl_prompt()` in `CourtScraper.py`.

### How it works

1. `_fetch_with_firecrawl()` initialises a `FirecrawlApp` with `FIRECRAWL_API_KEY`.
2. `crawl_urls` is set with **the home page first** so the agent starts navigation from there:
   ```python
   crawl_urls = [
       "https://www.bombayhighcourt.nic.in/",
       "https://www.bombayhighcourt.nic.in/*",
       "https://hcservices.ecourts.gov.in/ecourtindiaHC/cases/case_no.php",
       "https://hcservices.ecourts.gov.in/ecourtindiaHC/*",
   ]
   ```
3. The prompt (from `_build_firecrawl_prompt()`) instructs the agent step-by-step:
   - Step 1: Open home page → click "Case Status" → "Case Number Wise"
   - Step 2: Fill form — Case Type (base type, without "(ST)"), Stamp/Regn ("Registration" or "Stamp"), Case Number, Year, Bench
   - Step 3: Handle CAPTCHA, re-submit
   - Step 4: On case details page — read petitioner/respondent; click "Listing Dates/Order"
   - Step 5: Collect ALL rows from the Listing Dates table (Date + Order/Judgement href)
4. Result is normalised via `_normalize_firecrawl_payload()` into the shared shape.

### Environment Variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `FIRECRAWL_API_KEY` | _(required)_ | Firecrawl API key |
| `FIRECRAWL_MODEL` | `spark-1-mini` | AI model used for extraction |

## Ollama Integration

The Ollama path uses HTTP requests to fetch page HTML and then calls a locally-hosted LLM to extract structured data. Because Ollama cannot navigate a real browser or solve a CAPTCHA, the HTML extraction is best-effort.

### How it works

1. `_fetch_with_ollama_scraper()` builds candidate URLs starting with the Bombay High Court home page:
   ```python
   urls = [
       "https://www.bombayhighcourt.nic.in/",           # home page
       "https://hcservices.ecourts.gov.in/.../case_no.php",  # search form
       "https://hcservices.ecourts.gov.in/.../case_detail.php?...",
       "https://hcservices.ecourts.gov.in/.../order_list.php?...",
   ]
   ```
2. For each URL, it fetches HTML, extracts direct order links (`_extract_links_from_html()`), and extracts petitioner/respondent via regex (`_extract_case_meta_from_html()`).
3. All collected HTML chunks are sent to Ollama via `_call_ollama_for_orders()` using the `_build_ollama_extraction_prompt()` prompt.
4. The prompt describes the navigation sequence and page structure so the LLM can correctly identify which parts of the HTML correspond to petitioner/respondent names and order links.
5. LLM results are merged with the directly-extracted links.

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

The scraper provider is controlled by `COURT_SCRAPER_PROVIDER` (default: `firecrawl_first`):

| Provider | Behaviour |
|----------|-----------|
| `firecrawl_first` | Try Firecrawl; fall back to Ollama if Firecrawl fails or is unconfigured |
| `firecrawl_only` | Only use Firecrawl; return `captcha_required` if unavailable |
| `ollama_first` | Try Ollama HTML scraping first; fall back to Firecrawl |
| `ollama_only` | Only use Ollama; return `captcha_required` if extraction yields nothing |

Change at runtime (admin only):
```
POST /scraper/configure
{ "provider": "ollama_first", "ollama_base_url": "http://my-ollama:11434", "ollama_model": "llama3.1:8b" }
```

## Expected Output Shape

Both Firecrawl and Ollama paths return the same normalised dict:

```json
{
  "status": "found",
  "source": "firecrawl" | "ollama_scraper",
  "case_details": {
    "petitioner_name": "ABC Ltd",
    "respondent_name": "State of Maharashtra",
    "case_number": "WP/3373/2025"
  },
  "court_orders": [
    { "listing_date": "09/04/2025", "download_url": "https://..." },
    { "listing_date": "08/04/2025", "download_url": "https://..." }
  ]
}
```

## Making Changes

### To update the Firecrawl navigation prompt
1. Edit `_build_firecrawl_prompt()` in `CourtScraper.py`.
2. Update the unit test `test_firecrawl_prompt_includes_listing_navigation_steps` in `tests/unit/test_court_scraper.py` to assert the new step is present.

### To update the Ollama extraction prompt
1. Edit `_build_ollama_extraction_prompt()` in `CourtScraper.py`.
2. Update the unit test `test_ollama_extraction_prompt_describes_navigation_sequence` in `tests/unit/test_court_scraper.py`.

### To add a new field to the extraction output
1. Add the field to the appropriate Pydantic model (`FirecrawlCaseDetails` or `FirecrawlCourtOrder`).
2. Update both `_build_firecrawl_prompt()` and `_build_ollama_extraction_prompt()` to instruct the model to extract the field.
3. Update `_normalize_firecrawl_payload()` to map the new field into the returned dict.
4. Add a unit test covering the normalisation.

### To change candidate URLs for the Ollama scraper
1. Edit `_build_candidate_urls()` in `CourtScraper.py`.
2. Update the unit test `test_build_candidate_urls_starts_with_home_page` to assert the new ordering.

## Running Tests

```bash
cd billingonaire_backend
pytest tests/unit/test_court_scraper.py -v
```

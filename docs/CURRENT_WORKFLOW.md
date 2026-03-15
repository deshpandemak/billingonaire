# Current Runtime Workflow (Fresh Start Model)

This document describes the active, non-legacy workflow for board ingestion, order retrieval, and order analysis.

## 1. Data Model

Primary collections used by runtime code:

- `daily-boards`: board rows and operational order status for each board listing.
- `case-details`: normalized per-case master record and order history.
- `board-assignments`: board-date assignment snapshots keyed by board document id.
- `order-search-index`: search-optimized projection for order lookup screens.

The active status flow is:

- `not_linked` -> `linked` -> `analysed`
- failure states: `order_failed`, `order_analysis_failed`

`order_linked` is no longer part of the active status model.

## 2. Board Ingestion Workflow

Entry point: `Board.readFile()` and `Board.saveData()`.

### Parsing strategy and fallbacks

1. Read PDF pages.
2. Prefer ML-enhanced parser when available.
3. Fallback to standard regex/text parsing when ML parsing is unavailable or fails.
4. Optional LLM enrichment can run when the local LLM extractor is available.

### Persistence

For each parsed row:

1. Write the board row to `daily-boards`.
2. Upsert normalized case data into `case-details` and `board-assignments` via `CaseDataStore.upsert_from_board_entry()`.

If normalized upsert fails, save operation now fails (no silent compatibility fallback path).

## 3. Board Read Workflow

Entry point: `Board.getData()`.

1. Query `daily-boards` with date/case/AGP filters.
2. Hydrate each result from `case-details` using case reference.
3. Use latest normalized order event (`latest_*` and `orders`) as source of truth for order fields returned to UI.

Hydrated fields include:

- `order_link`, `order_status`, `order_category`, `order_date`
- `order_petitioner`, `order_respondent`, `government_pleader`
- `assigned_government_pleaders`, `order_history`

## 4. Automated Order Retrieval Workflow

Entry point: `AutoOrderManager.get_orders_for_cases()` / `bulk_process_orders()`.

### Candidate selection

- Pull candidates from `daily-boards`.
- Process cases that are not fully analyzed or are in failure states.

### Download strategy and fallbacks

For each case (`_process_single_case`):

1. If status is `linked` and an order link exists:
   - Re-download and analyze existing link (`_analyze_existing_order`).
   - If link is invalid, fallback to fresh download.
2. Fresh download path:
   - First attempt structured scraper (`BombayHighCourtScraper`) once.
   - If unavailable/unsuccessful, fallback to legacy Bombay HC sequence retries.
3. For each successful PDF candidate:
   - quick date validation against board date.
   - accept first date-valid order.

### Post-download actions

1. Set `linked` status and order metadata on `daily-boards`.
2. Append order event to `case-details.orders`.
3. Run full order analysis.
4. On success, mark `analysed`, update search index, and try multi-case linking.
5. On analysis failure, mark `order_analysis_failed`.
6. If no candidate succeeds across retries, mark `order_failed`.

## 5. Order Analysis Workflow

Entry point: `OrderDocumentAnalyzer.analyze_order_document()` via `AutoOrderManager._analyze_order_with_date_validation()`.

### Analysis layers and fallbacks

1. Base extraction/classification via ML/rule pipeline.
2. Optional LLM-assisted enrichment when local LLM extractor is available.
3. Internal confidence-gated fallback merges to improve weak or missing fields.

### Persistence targets

- Flattened order fields on `daily-boards` for operational UI.
- Append/update normalized order event in `case-details`.
- Search projection in `order-search-index`.

## 6. Multi-Case Linking Workflow

When analysis reveals multiple cases in one order:

1. Resolve sibling case ids for same board date.
2. Skip cases already in `linked`/`analysed`/`manually_uploaded` states.
3. Reuse primary order link and persist case-specific flattened analysis.
4. Append sibling case order events to `case-details`.

## 7. Admin Bulk Workflow

Entry points:

- `/admin/order-status-overview`
- `/admin/bulk-order-processing`

These now operate on active statuses (`not_linked`, `linked`, `analysed`, `order_failed`, `order_analysis_failed`) and queue eligible cases for async order processing.

## 8. Manual Order Management Workflow

Entry points:

- `/orders/link`
- `/orders/update-status`
- `/orders/by-status`
- `/orders/case-details/{case_id}`

### Manual link flow

1. A user/admin stores an order link directly against a `daily-boards` case.
2. If the provided link resolves to a PDF, the backend immediately attempts analysis.
3. Successful analysis updates:
   - flattened order fields on `daily-boards`
   - normalized order history in `case-details`
   - `order-search-index`
4. If download or analysis fails, the link can still remain stored, but the case is marked with the relevant failure state.

### Manual status flow

Manual status updates should use the active status set only:

- `not_linked`
- `linked`
- `analysed`
- `order_failed`
- `order_analysis_failed`
- `manually_uploaded`

## 9. Search and Index Workflow

Entry points:

- `AutoOrderManager._create_search_index_entry()`
- `/orders/search`
- `/auto-orders/rebuild-search-index`

### Index source

The search index is derived from the flattened `daily-boards` representation after analysis.

### Rebuild behavior

Rebuild scans analyzed cases and recreates search-friendly projections, primarily for:

- petitioner/respondent lookup
- AGP name search
- order category and date filters

The index is derivative data and can be regenerated from operational collections.

## 10. Field Dictionary (Firestore Schema Reference)

This section documents the active field-level schema used by runtime code.

### 10.1 `daily-boards` (Operational Board Row Store)

Document id pattern:

- `{board_date}-{case_type}-{case_no}-{case_year}`

Core board fields:

- `file_name`: string
- `board_date`: timestamp/date string
- `case_type`: string
- `case_no`: string/number
- `case_year`: string/number
- `serial_number`: string/number
- `case_ref`: string (`TYPE/NO/YEAR`)
- `petitioner_lawyer`: string
- `respondent_lawyer`: string
- `additional_cases`: string[]
- `additional_respondent_lawyers`: string[]

Order tracking fields:

- `order_status`: one of `not_linked`, `linked`, `analysed`, `order_failed`, `order_analysis_failed`, `manually_uploaded`
- `order_status_updated_at`: ISO datetime
- `order_downloaded`: boolean
- `order_link`: string|null
- `order_filename`: string|null
- `order_source`: string|null
- `order_fetch_date`: ISO datetime|null
- `order_downloaded_at`: ISO datetime|null
- `order_created_at`: ISO datetime|null
- `order_updated_at`: ISO datetime|null

Analysis fields (set after successful analysis):

- `order_analysis_completed`: boolean
- `order_analysis_timestamp`: ISO datetime
- `order_last_updated`: ISO datetime
- `order_category`: string
- `order_category_confidence`: number
- `order_date`: `YYYY-MM-DD`|null
- `order_petitioner`: string
- `order_respondent`: string
- `government_pleader`: string[]
- `order_date_validation`: object
- `order_analysis_metadata`: object
- `order_analyzer_fallback_metrics`: object

Failure fields:

- `order_failure_reason`: string|null
- `order_analysis_error`: string|null

### 10.2 `case-details` (Normalized Case Master + Order History)

Document id pattern:

- `case_ref` with `/` replaced by `-`

Identity fields:

- `case_ref`: string (`TYPE/NO/YEAR`)
- `case_type`: string
- `case_no`: string/number
- `case_year`: string/number

Case-level normalized fields:

- `petitioner`: string
- `respondent`: string
- `government_pleader`: string[]
- `assigned_government_pleaders`: string[]
- `latest_board_date`: `YYYY-MM-DD`|null
- `board_assignment_ids`: string[]

Latest-order rollups:

- `latest_order_link`: string|null
- `latest_order_date`: `YYYY-MM-DD`|null
- `latest_order_status`: string|null
- `latest_order_category`: string|null

Order history array:

- `orders`: array of order event objects (capped to last 100)

Typical order event fields:

- `order_link`: string|null
- `order_status`: string|null
- `order_category`: string|null
- `order_date`: `YYYY-MM-DD`|null
- `board_date`: `YYYY-MM-DD`|null
- `order_category_confidence`: number|null
- `petitioner`: string|null
- `respondent`: string|null
- `government_pleader`: string[]|null
- `order_filename`: string|null
- `order_source`: string|null
- `order_fetch_date`: ISO datetime|null
- `order_analysis_timestamp`: ISO datetime|null
- `order_analysis_metadata`: object|null
- `order_date_validation`: object|null
- `created_at`: ISO datetime
- `updated_at`: ISO datetime

Timestamps:

- `created_at`: ISO datetime
- `updated_at`: ISO datetime

### 10.3 `board-assignments` (Board-Day Snapshot Layer)

Document id:

- same as `daily-boards` document id

Fields:

- `board_doc_id`: string
- `case_ref`: string
- `board_date`: `YYYY-MM-DD`|null
- `file_name`: string|null
- `serial_number`: string/number|null
- `assigned_government_pleaders`: string[]
- `petitioner_lawyer`: string|null
- `respondent_lawyer`: string|null
- `updated_at`: ISO datetime

### 10.4 `order-search-index` (Derived Search Projection)

Document id:

- `case_id` from `daily-boards`

Identity fields:

- `case_id`: string
- `case_ref`: string
- `case_type`: string
- `case_number`: string/number
- `case_year`: string/number
- `board_date`: timestamp/date string

Party/search fields:

- `petitioner`: string
- `respondent`: string
- `petitioner_text`: lowercase string for text search
- `respondent_text`: lowercase string for text search

Order/search fields:

- `order_category`: string|null
- `order_date`: `YYYY-MM-DD`|null
- `order_category_confidence`: number|null
- `agp_names`: string[]
- `key_phrases`: string[]
- `order_link`: string|null

Analysis/quality fields:

- `date_validation_valid`: boolean
- `order_analysis_completed`: boolean
- `order_analysis_timestamp`: ISO datetime|null

Timestamps:

- `created_at`: ISO datetime
- `last_updated`: ISO datetime

### 10.5 Lifecycle Summary (Pre vs Post Analysis)

Pre-analysis (after board ingestion):

1. `daily-boards` row exists with `order_status = not_linked`.
2. `case-details` exists/updated with normalized case fields and usually empty `orders`.
3. `board-assignments` snapshot is written.

Linked (downloaded but not analyzed):

1. `daily-boards` updated with `order_status = linked` and order link metadata.
2. `case-details.orders` gets a linked event.

Post-analysis success:

1. `daily-boards` updated with flattened analysis fields and `order_status = analysed`.
2. `case-details.orders` append/update; `latest_order_*` rollups refreshed.
3. `order-search-index` created/updated for search.

Failure states:

1. `order_failed` when download retries are exhausted.
2. `order_analysis_failed` when download succeeds but analysis fails.

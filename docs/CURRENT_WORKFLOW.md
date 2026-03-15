# Runtime Workflow (Asynchronous Reality Model)

This document describes the target workflow aligned to real court operations:

1. Board data arrives first.
2. Case details become richer over time.
3. Order links are often unavailable for future dates and many same-day matters.
4. Order analysis happens only after an order document is fetchable.

The system must therefore be stage-based, asynchronous, and transparent to users about data readiness.

## 1. High-Level Principles

- Separate concerns by domain:
1. Board Data: what is listed on board for a date.
2. Case Data: canonical case identity and accumulated party metadata.
3. Order Analysis: derived interpretation of fetched order documents.

- Never block board ingestion waiting for orders.
- Treat order fetch and order analysis as independent async jobs.
- Expose readiness and failure states explicitly in API and UI.

## 2. Data Domains and Ownership

### 2.1 daily-boards (Board Data Only)

Purpose:
- Immutable or lightly mutable board snapshot rows.

Contains:
- Board fields only, such as board_date, case_ref, serial_number, petitioner_lawyer, respondent_lawyer.

Does not contain:
- Order status, order link, analysis category, or analysis confidence.

### 2.2 case-details (Case Canonical Record)

Purpose:
- Single source of truth for case identity, latest state, and order lifecycle events.

Contains:
- Case identity fields and enriched party fields.
- Latest rollups for order lifecycle.
- Ordered event history for fetch and analysis attempts.

### 2.3 order-search-index (Derived Read Model)

Purpose:
- Fast UI search/filter across analyzed outcomes.

Contains:
- Flattened searchable attributes derived from case-details and board context.

## 3. Asynchronous Stage Model

Status model in case-details latest rollup:

- board_ingested
- fetch_not_due
- fetch_queued
- fetch_in_progress
- fetch_succeeded
- fetch_failed_retryable
- fetch_failed_terminal
- analysis_queued
- analysis_in_progress
- analysed
- analysis_failed_retryable
- analysis_failed_terminal
- manual_review_required

Notes:
- This status model replaces overloaded linked and analysed-only semantics.
- Existing statuses can be mapped during rollout, then removed.

## 4. Time and Availability Rules

Order fetch eligibility rules:

1. board_date greater than today: do not fetch, mark fetch_not_due with next_eligible_at.
2. board_date equals today: fetch allowed, but often delayed; retry policy should be conservative.
3. board_date less than today: fetch allowed with normal retry cadence.

Operational behavior:

- Future boards should display as onboarded, waiting for due date.
- Backdated boards should enter fetch queue according to policy.

## 5. Backend Changes (Complete)

### 5.1 Domain-Service Split

Create or refactor service layers:

1. BoardIngestionService:
- Parse and persist only board rows and board-assignment snapshots.
- Upsert baseline case record if absent.

2. CaseLifecycleService:
- Own state transitions and state validation.
- Enforce valid transitions and terminal states.

3. OrderFetchService:
- Own court fetch strategy and retries.
- Emit fetch events into case-details.

4. OrderAnalysisService:
- Analyze fetched PDF payloads.
- Emit analysis events and update latest rollup.

### 5.2 Job Queue Separation

Use two async queues:

1. order-fetch-jobs
2. order-analysis-jobs

Each job includes:
- case_ref
- board_date
- job_type
- priority
- attempt_count
- next_run_at
- correlation_id

### 5.3 Event Schema in case-details

Recommended event object fields:

- event_type: fetch_attempt, fetch_success, fetch_failure, analysis_attempt, analysis_success, analysis_failure, manual_override
- event_at
- source
- status
- reason_code
- reason_detail
- artifacts: order_link, order_hash, model_version, confidence, etc.

### 5.4 API Response Contract

For board list endpoints return three sections per row:

- board:
1. board_date, serial_number, lawyers, file_name

- case:
1. case_ref, petitioner, respondent, government_pleader, last_enriched_at

- order:
1. lifecycle_status
2. next_action
3. next_eligible_at
4. last_attempt_at
5. retry_count
6. order_link
7. analysis_summary: category, confidence, order_date, validation

Do not return legacy combined payload keys from old analyzed-orders style records.

### 5.5 Retry and Scheduling Policy

Fetch retry profile:

1. Same day: exponential backoff with caps.
2. Back date up to N days: moderate retry window.
3. Very old matters: low-frequency retry or manual-review bucket.

Analysis retry profile:

1. Retry for parser/network/model transient errors.
2. Route low-confidence ambiguous outputs to manual_review_required.

## 6. Frontend Changes (Complete)

### 6.1 UX by Stage

Board table should show clear stage chips:

- Board Uploaded
- Awaiting Fetch Window
- Fetch Queued
- Fetch In Progress
- Fetched, Awaiting Analysis
- Analysed
- Needs Review
- Failed with Retry ETA

### 6.2 User Actions

Per row actions:

1. Queue Fetch Now (if eligible)
2. Retry Fetch
3. Upload Manual Order
4. Queue Analysis
5. Mark for Review
6. View Event Timeline

### 6.3 Visibility and Trust

Add timeline drawer with:

- fetch attempts with timestamps
- analysis attempts with model version and confidence
- error reason codes
- next scheduled retry

### 6.4 Filters and Bulk Controls

Add filters:

- board date range
- lifecycle_status
- due today / future / overdue
- confidence band
- needs review

Add bulk actions:

- queue eligible fetches
- queue analysis for fetched items
- assign to review queue

## 7. Order Analysis Quality Improvements

Current pain point:
- Misclassification among DISPOSED_OFF, ADJOURNED, and HEARD_AND_ADJOURNED.

### 7.1 Hierarchical Classification

Switch to two-step model:

1. Step A: terminal vs non-terminal disposition.
2. Step B: if non-terminal, classify ADJOURNED vs HEARD_AND_ADJOURNED.

### 7.2 Rule-Augmented Signals

Add deterministic signal extraction before final label:

- disposal cues: disposed of, petition stands disposed, rule made absolute, dismissed as withdrawn, finally disposed
- hearing cues: heard learned counsel, heard finally, arguments heard
- adjournment cues: stand over, adjourned to, list on

Use weighted voting between model score and rule score.

### 7.3 Confidence and Human Review

Introduce confidence thresholds:

1. confidence greater than or equal to 0.80: auto-accept.
2. 0.55 to 0.79: accept with warning flag.
3. below 0.55 or conflicting rules: manual_review_required.

### 7.4 Evaluation Harness

Create golden dataset and track per-class metrics:

- precision/recall/F1 for DISPOSED_OFF, ADJOURNED, HEARD_AND_ADJOURNED
- confusion matrix trend by release
- false-terminal rate as key risk metric

## 8. Endpoint Adjustments (Implemented)

Implemented endpoints:

1. POST /jobs/fetch-orders
- queue fetch jobs for eligible cases.

2. POST /jobs/analyze-orders
- queue analysis jobs for fetched orders.

3. GET /cases/lifecycle
- unified board + case + order response contract.

4. GET /cases/{case_ref}/timeline
- full event timeline for transparency.

5. POST /cases/{case_ref}/manual-review
- move case to review workflow.

6. POST /cases/{case_ref}/manual-override
- store reviewed final outcome with audit metadata.

Status notes:

- Queue endpoints now run fetch and analysis as separate async stages.
- Manual review and override endpoints write lifecycle events for auditability.

## 9. Documentation and Contract Standards

All docs and API specs must consistently state:

1. Board upload does not imply order availability.
2. Future-dated board matters are expected to be fetch_not_due.
3. Order analysis only runs after successful fetch.
4. Low-confidence analysis may require manual review.

## 10. Migration and Rollout Plan

### Phase 1: Contract Stabilization

1. Stop producing any legacy analyzed-orders style payloads.
2. Serve unified board + case + order sections from API.
3. Keep compatibility adapter behind feature flag for one release only.

### Phase 2: Queue and Timeline

1. Introduce explicit fetch and analysis queues.
2. Persist event timeline records and expose in UI.

### Phase 3: Analysis Quality Upgrade

1. Deploy hierarchical classifier and rule weighting.
2. Add confidence thresholds and review queue.
3. Publish quality dashboard.

### Phase 4: Legacy Removal

1. Remove old status names and compatibility paths.
2. Remove deprecated fields from all docs and endpoints.

## 11. Operational SLOs

Track and alert on:

1. time_to_first_fetch_attempt
2. fetch_success_rate by board age bucket
3. analysis_success_rate
4. manual_review_rate
5. false-terminal-classification rate

## 12. Quick Reality Checklist

The workflow is correct if all of the following are true:

1. Uploading tomorrow board never triggers immediate failed fetch noise.
2. Today and backdated rows show accurate asynchronous progression.
3. Users always see what is missing, why it is missing, and what happens next.
4. Classification outcomes have confidence and review path, not silent mislabels.

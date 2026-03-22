# Skills Index

This directory contains the discoverable workspace skills for Billingonaire.

## Available Skills

| Skill | Use when | File |
|---|---|---|
| api-endpoint | Adding or modifying a FastAPI endpoint with auth, error handling, and tests | [.github/skills/api-endpoint/SKILL.md](.github/skills/api-endpoint/SKILL.md) |
| backend-spec-first | Implementing backend behavior using spec-first flow (Gherkin -> steps -> code -> validation) | [.github/skills/backend-spec-first/SKILL.md](.github/skills/backend-spec-first/SKILL.md) |
| bill-generation | Working on AGP billing report generation and Excel export behavior | [.github/skills/bill-generation/SKILL.md](.github/skills/bill-generation/SKILL.md) |
| board-pdf-parsing | Parsing board PDFs and persisting extracted records to Firestore | [.github/skills/board-pdf-parsing/SKILL.md](.github/skills/board-pdf-parsing/SKILL.md) |
| court-order-management | Managing order lifecycle, retries, linking, and overrides | [.github/skills/court-order-management/SKILL.md](.github/skills/court-order-management/SKILL.md) |
| dashboard-analytics | Building read-only analytics endpoints and aggregations | [.github/skills/dashboard-analytics/SKILL.md](.github/skills/dashboard-analytics/SKILL.md) |
| frontend-component | Adding or updating React components/pages with project conventions | [.github/skills/frontend-component/SKILL.md](.github/skills/frontend-component/SKILL.md) |
| order-analysis | Classifying court orders and updating lifecycle state | [.github/skills/order-analysis/SKILL.md](.github/skills/order-analysis/SKILL.md) |
| release-readiness-backend | Running pre-merge backend validation gates and risk review | [.github/skills/release-readiness-backend/SKILL.md](.github/skills/release-readiness-backend/SKILL.md) |
| spec-failure-triage | Diagnosing and fixing failing pytest-bdd scenarios | [.github/skills/spec-failure-triage/SKILL.md](.github/skills/spec-failure-triage/SKILL.md) |
| user-management | Managing Firebase users, profiles, and AGP role configuration | [.github/skills/user-management/SKILL.md](.github/skills/user-management/SKILL.md) |

## Recommended Skill Chains

1. New backend feature: backend-spec-first -> domain skill -> release-readiness-backend
2. Failing spec flow: spec-failure-triage -> backend-spec-first -> release-readiness-backend
3. Endpoint-only update: api-endpoint -> release-readiness-backend

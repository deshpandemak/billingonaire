---
name: spec-failure-triage
description: "Use when: debugging failing pytest-bdd specifications in Billingonaire backend, triaging red scenarios, applying minimal fixes, and adding regression coverage. Trigger phrases: failing spec, failing scenario, BDD failure, pytest-bdd error, red green refactor, step mismatch, broken feature test."
---

# Spec Failure Triage Workflow (Billingonaire)

Use this skill when a backend BDD scenario fails and you need fast, reliable triage through fix and verification.

## Scope

- Backend pytest-bdd failures under billingonaire_backend/specs
- Feature file and step definition mismatches
- Endpoint or domain logic bugs exposed by BDD scenarios

## Inputs To Collect First

- Exact failing command and failing scenario name
- Error type: step not found, assertion failure, fixture error, import error, endpoint regression
- Last known good behavior and expected behavior
- Whether this should be fixed in spec wording, step code, or backend implementation

## Files To Check First

- billingonaire_backend/specs/features/*.feature
- billingonaire_backend/specs/steps/*_steps.py
- billingonaire_backend/specs/conftest.py
- billingonaire_backend/main.py and related backend module
- billingonaire_backend/pytest.ini

## Triage Steps

1. Reproduce exactly
- Run only the failing step module first to reduce noise.

```bash
cd billingonaire_backend
pytest specs/steps/<failing_steps_file>.py -v --tb=short
```

2. Classify failure before editing
- Step binding issue: Gherkin sentence does not match step decorator text.
- Data fixture issue: missing or incorrect fixture setup in specs/conftest.py.
- Contract issue: status code or response schema changed.
- Business logic issue: endpoint or domain behavior is incorrect.

3. Apply smallest valid fix
- If wording drift: align feature text and step decorator parameters.
- If fixture gap: extend existing shared fixture rather than duplicate mock setup.
- If contract changed unintentionally: restore behavior in backend code.
- If intended behavior changed: update feature scenario and step assertions first, then code.

4. Validate impacted scope

```bash
cd billingonaire_backend
pytest specs/steps/<failing_steps_file>.py -v
pytest specs/ -v -k "<feature_or_behavior_keyword>"
```

5. Run broader regression checks

```bash
cd billingonaire_backend
pytest specs/ -v
pytest tests/unit -v
```

6. Add or strengthen regression signal
- Add one targeted scenario or assertion that would have caught the bug earlier.
- Keep it focused on the same behavior and failure mode.

## Done Criteria

- Original failing scenario now passes
- No new failures in related specs
- Unit tests still pass for touched modules
- Fix is minimal and traceable to one root cause
- Regression guard added when appropriate

## Guardrails

- Do not weaken assertions just to make tests green
- Do not broad-catch exceptions in endpoint code to hide failures
- Do not duplicate fixture logic already present in specs/conftest.py
- Do not edit unrelated scenarios during triage

## Output Format (when reporting completion)

- Root cause category
- Files changed and why
- Minimal fix summary
- Commands run
- Before and after test status
- Residual risk, if any

## Quick Prompt Template

Use the spec-failure-triage skill. Failing command: <command>. Failing scenario: <name>. Expected behavior: <expected>. Identify root cause, apply minimal fix, run impacted specs plus backend unit tests, and report before versus after results.

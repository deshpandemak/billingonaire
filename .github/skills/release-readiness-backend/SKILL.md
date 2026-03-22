---
name: release-readiness-backend
description: "Use when: preparing Billingonaire backend changes for merge or release by running specification checks, unit tests, coverage checks, and risk review. Trigger phrases: release readiness, pre PR checks, pre merge checks, CI parity, backend gate, ship checklist."
---

# Backend Release Readiness Workflow (Billingonaire)

Use this skill to standardize pre-merge backend validation and reduce CI surprises.

## Scope

- Backend changes under billingonaire_backend
- pytest-bdd specifications, unit tests, and coverage
- Merge readiness checks before opening or updating a pull request

## Inputs To Collect First

- Change summary in 1 to 2 sentences
- Touched backend modules
- Whether API contract was changed
- Whether new scenarios or tests were added
- Required confidence level: normal or strict

## Files To Review

- billingonaire_backend/pytest.ini
- docs/BDD_SPECIFICATIONS.md
- billingonaire_backend/specs/features/*.feature
- billingonaire_backend/specs/steps/*_steps.py
- billingonaire_backend/tests/unit/**/*.py

## Validation Sequence

1. Environment and dependency sanity

- Confirm backend dependencies are available.

Command:
cd billingonaire_backend
pip install -r requirements.txt -r requirements-test.txt

2. Fast targeted checks for touched behavior

- Run only impacted step files and related unit test modules first.

Command:
cd billingonaire_backend
pytest specs/steps/<impacted_steps_file>.py -v
pytest tests/unit/<related_test_file>.py -v

3. Full BDD specification pass

Command:
cd billingonaire_backend
pytest specs/ -v --tb=short

4. Full backend unit pass

Command:
cd billingonaire_backend
pytest tests/unit -v --tb=short

5. CI parity coverage pass

Command:
cd billingonaire_backend
pytest tests/unit -v --cov=. --cov-report=xml --cov-report=term
pytest specs/ -v --tb=short --cov=. --cov-append --cov-report=xml --cov-report=term

6. Optional strict mode quality checks

Command:
cd billingonaire_backend
black --check .
isort --check-only .
flake8 .

## Release Gate Criteria

- All impacted BDD scenarios pass
- All backend unit tests pass
- Coverage report generated successfully
- No unreviewed API response contract drift
- No unexplained new warnings or skipped tests in changed areas

## Risk Review Checklist

- Authentication and role checks remain correct
- Firestore interactions still use expected collections and keys
- Error paths return stable status codes and error payload shape
- Timeouts, retries, and background jobs keep expected behavior
- Existing feature files still express true product behavior

## Failure Handling Rules

- If targeted checks fail: use spec-failure-triage workflow before broader reruns
- If only strict mode fails: separate style fixes from functional fixes when possible
- If coverage drops in changed module: add focused unit or BDD scenario, not broad low-value tests

## Output Format (when reporting completion)

- Scope validated
- Commands run
- Pass and fail summary
- Coverage summary location
- Risks found and disposition
- Final release readiness verdict: ready or not ready

## Quick Prompt Template

Use the release-readiness-backend skill for this backend change: <summary>. Run targeted checks, full specs, full unit tests, CI parity coverage commands, and provide a final ready or not ready verdict with risks.

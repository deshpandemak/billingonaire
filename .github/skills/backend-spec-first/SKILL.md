---
name: backend-spec-first
description: "Use when: adding or changing a backend FastAPI endpoint with specification-first workflow, pytest-bdd feature/step updates, and backend test validation in Billingonaire. Trigger phrases: spec first, BDD, gherkin, feature file, step definitions, backend endpoint."
---

# Backend Spec-First Workflow (Billingonaire)

Use this skill for backend behavior changes that should start from specifications and end with passing tests.

## Scope

- Backend-only work under `billingonaire_backend/`
- Spec-first workflow using pytest-bdd
- FastAPI endpoint behavior, parsing logic, dashboard logic, order lifecycle logic

## Inputs To Collect First

- Business behavior to add/change in one sentence
- Target API endpoint(s) and HTTP method(s)
- Expected request/response contract (status code + key fields)
- Whether behavior is admin-only, authenticated-user, or public
- Any existing feature/scenario to extend vs new feature to create

## Files To Check First

- `docs/BDD_SPECIFICATIONS.md`
- `billingonaire_backend/specs/features/*.feature`
- `billingonaire_backend/specs/steps/*_steps.py`
- `billingonaire_backend/specs/conftest.py`
- `billingonaire_backend/main.py` and relevant domain modules
- `billingonaire_backend/pytest.ini`

## Execution Steps

1. **Define behavior in Gherkin first**
- Update an existing `.feature` file in `billingonaire_backend/specs/features/`.
- If behavior is new, add a new `.feature` file with clear `Feature` narrative.
- Keep one behavior per scenario; use `Background` for shared setup only.

2. **Bind/implement steps**
- Add or update a matching `*_steps.py` file in `billingonaire_backend/specs/steps/`.
- Ensure `scenarios("../features/<file>.feature")` points to the feature file.
- Reuse shared fixtures from `billingonaire_backend/specs/conftest.py`.
- Prefer explicit assertions on status and response body keys.

3. **Implement backend code**
- Modify endpoint logic in `billingonaire_backend/main.py` and related modules.
- Keep business logic out of route handlers where practical.
- Preserve existing auth/role checks (`require_active_user`, `require_admin`, etc.).

4. **Run focused validation first**
- Run only the impacted step module:
```bash
cd billingonaire_backend
pytest specs/steps/<target_steps_file>.py -v
```

5. **Run full backend validation**
```bash
cd billingonaire_backend
pytest specs/ -v
pytest tests/unit -v
```

6. **Coverage check (if change is substantial)**
```bash
cd billingonaire_backend
pytest tests/unit specs/ -v --cov=. --cov-report=term-missing
```

## Done Criteria

- Feature scenario clearly reflects expected behavior
- Step definitions are deterministic and readable
- Backend implementation matches scenario outcomes
- Impacted BDD specs pass locally
- No obvious regressions in backend unit tests

## Guardrails

- Do not silently change API response contract without updating Gherkin
- Do not duplicate fixtures that already exist in `specs/conftest.py`
- Do not add broad mocks that hide assertion value
- Do not mix multiple unrelated behaviors in one scenario

## Output Format (when reporting completion)

- Changed feature/scenario(s)
- Changed step definition file(s)
- Changed backend module(s)
- Test commands run
- Pass/fail summary and any known residual risk

## Quick Prompt Template

"Use the backend-spec-first skill. Implement: <behavior>. Update/extend: <feature file>. Endpoint: <method + path>. Expected result: <status + key response fields>. Then run impacted specs and backend unit tests and report results."
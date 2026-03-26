---
name: api-endpoint
description: Add a new FastAPI endpoint to the Billingonaire backend following project conventions for routing, authentication, Firestore access, error handling, and testing.
---

## Overview

This skill describes the standard pattern for adding a new API endpoint to the Billingonaire FastAPI backend. Follow every step to ensure the new endpoint is consistent with the rest of the codebase, passes CI, and is covered by both unit tests and BDD specifications.

## Project Conventions

| Convention | Detail |
|-----------|--------|
### 6. Code Quality & Linting
| Python version | 3.11 |
| Formatter | Black, line length 88 |
| Import sorting | isort |
| Linter | flake8 (config in `billingonaire_backend/.flake8`) |
| Type checker | mypy (config in `billingonaire_backend/mypy.ini`) |
| Type hints | Required on all public function signatures |
| Async | Use `async def` for all FastAPI route handlers. Firestore operations use the synchronous Firebase Admin SDK (`collection().document().get()/set()/stream()`); offload them to a threadpool if needed to avoid blocking the event loop. |
| Framework | FastAPI with Pydantic request/response models |
| Auth | Firebase ID token via `Authorization: Bearer <token>` header |

## Step-by-Step

### 1. Define Pydantic models

Add request and response models to `main.py` or a dedicated `models.py` file. Use `pydantic.BaseModel` with snake_case field names and explicit type annotations.

```python
from pydantic import BaseModel

class MyRequest(BaseModel):
    case_ref: str
    some_flag: bool = False

class MyResponse(BaseModel):
    case_ref: str
    result: str
```

### 2. Implement business logic in the appropriate module

- Board/PDF logic → `Board.py`
- Order lifecycle → `OrderManager.py`
- Analytics aggregations → `Dashboard.py`
- User/role operations → `UserManager.py`
- New concern → create a new module (e.g. `MyFeature.py`) and keep it single-purpose.

### 3. Add the route handler in `main.py`

```python
@app.post("/my-feature", response_model=MyResponse)
async def my_feature_endpoint(
    request: MyRequest,
    current_user: dict = Depends(get_current_user),
) -> MyResponse:
    result = await my_business_logic(request.case_ref, request.some_flag)
    return MyResponse(case_ref=request.case_ref, result=result)
```

Use `Depends(get_current_user)` for all authenticated routes. For admin-only routes use `Depends(require_admin)`.

### 4. Handle errors consistently

```python
from fastapi import HTTPException

if not record:
    raise HTTPException(status_code=404, detail="Case not found")
```

- 200 — success (even empty results)
- 400 — invalid input or unprocessable request
- 401/403 — auth failure
- 404 — resource not found
- 422 — FastAPI auto-handles missing required fields

### 5. Write a unit test

Create or extend a test file in `billingonaire_backend/tests/unit/`. Mock all external dependencies (Firestore, Firebase Auth, HTTP calls):

```python
import pytest
from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)

@pytest.mark.asyncio
async def test_my_feature_returns_expected_result(mock_firestore):
    with patch("main.my_business_logic", new_callable=AsyncMock) as mock_fn:
        mock_fn.return_value = "expected"
        response = client.post(
            "/my-feature",
            json={"case_ref": "WP/3373/2024"},
            headers={"Authorization": "Bearer test-token"},
        )
    assert response.status_code == 200
    assert response.json()["result"] == "expected"
```

### 6. Add a BDD scenario

Add a Gherkin scenario to the appropriate feature file in `billingonaire_backend/specs/features/`. Implement the steps in the corresponding `specs/steps/` file.

### 7. Run checks locally

```bash
cd billingonaire_backend
black .
isort .
flake8 . --config=.flake8
mypy --config-file mypy.ini CourtScraper.py main.py OrderManager.py
pytest tests/unit -v
```

All checks must pass before pushing.

## Common Pitfalls

- Forgetting `async def` on Firestore calls causes deadlocks under concurrent load.
- Returning a 4xx for an empty list response — use 200 with `[]` instead.
- Hardcoding secrets or Firebase project IDs — use environment variables.
- Importing at function scope to avoid circular imports is acceptable; module-level is preferred when safe.

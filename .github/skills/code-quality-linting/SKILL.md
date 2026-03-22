---
name: code-quality-linting
description: Check and enforce code quality standards (linting, formatting, type checking) on Python backend and React frontend before committing changes.
tags: [backend, frontend, linting, formatting, quality, python, javascript, testing]
---

## Overview

This skill covers all code quality checks required before merging changes to Billingonaire. It applies to:
- **Python Backend** (`billingonaire_backend/`) - Black, isort, flake8, mypy
- **React Frontend** (`billingonaire-ui/src/`) - ESLint

All changes must pass linting before being merged to main branch.

## Python Backend Quality Checks

### 1. Black (Code Formatter)

**Purpose**: Enforce consistent code formatting (line length, whitespace, indentation).

```bash
cd billingonaire_backend

# Check what would be reformatted (no changes)
python -m black --check .

# Auto-fix formatting issues
python -m black .
```

**Common Issues Fixed**:
- Line length exceeding 88 characters
- Inconsistent whitespace
- Trailing whitespace (W291)
- Blank lines with whitespace (W293)

### 2. isort (Import Sorter)

**Purpose**: Organize imports into groups: stdlib, third-party, local (alphabetically within each).

```bash
cd billingonaire_backend

# Check if imports need sorting
python -m isort --check-only .

# Auto-sort imports
python -m isort .
```

**Import Order Required**:
1. Standard library (`import os`, `from typing import ...`)
2. Third-party (`import requests`, `from fastapi import ...`)
3. Local (`from CourtScraper import ...`, `from . import ...`)

Each group separated by a blank line.

### 3. flake8 (Linter)

**Purpose**: Verify PEP 8 compliance and catch common errors.

```bash
cd billingonaire_backend

# Check all files
python -m flake8 . --config=.flake8

# Check specific file
python -m flake8 CourtScraper.py --config=.flake8
```

**Common Errors (Must Fix)**:
- `E501` - Line too long (but use Black instead of manual fixing)
- `F541` - f-string missing placeholders (use regular string instead)
- `W606` - `.has_key()` is deprecated
- `F841` - Local variable assigned but never used
- `E999` - Syntax errors

**Warnings to Address**:
- `W291` - Trailing whitespace (auto-fixed by Black)
- `W293` - Blank line contains whitespace (auto-fixed by Black)

### 4. mypy (Type Checker)

**Purpose**: Verify type hints are correct and catch type-related bugs.

```bash
cd billingonaire_backend

# Check specific module
python -m mypy CourtScraper.py --config-file=mypy.ini

# Run on critical files only
python -m mypy main.py OrderManager.py --config-file=mypy.ini
```

**Requirements**:
- All public function signatures must have type hints
- Return type must be specified
- Use `Optional[Type]` for nullable values
- Use `Dict`, `List` from `typing` for collections

**Example**:
```python
def get_case_details(case_ref: str) -> Dict[str, Any]:
    """Get case details from court scraper."""
    pass

async def process_order(order_id: str, timeout: int = 30) -> bool:
    """Process a court order asynchronously."""
    pass
```

---

## React Frontend Quality Checks

### 1. ESLint (JavaScript Linter)

**Purpose**: Verify React best practices, catch common JS errors, and enforce project code style.

```bash
cd billingonaire-ui

# Check all files
npx eslint . --no-fix

# Check specific file
npx eslint src/AdminOllamaManagement.jsx --no-fix

# Auto-fix fixable issues
npx eslint . --fix
```

**Common Issues**:
- Missing dependency in hooks (`exhaustive-deps`)
- Unused variables or imports
- Missing key prop in arrays
- Unreachable code after return
- Incorrect hook usage order

**Rules Enforced**:
- React Hooks rules (dependencies, order of operations)
- React Refresh rules (only export components)
- No `prop-types` required (using runtime validation only)
- Unused variables warnings are disabled (to avoid noise)

---

## Pre-Commit Quality Checklist

Before committing code, run this complete quality check:

```bash
# Backend Quality Check
cd billingonaire_backend && \
  echo "🔍 Checking Python code quality..." && \
  python -m black --check . && echo "✅ Black passed" && \
  python -m isort --check-only . && echo "✅ isort passed" && \
  python -m flake8 . --config=.flake8 && echo "✅ flake8 passed" && \
  echo "✅ Backend quality checks passed!"

# Frontend Quality Check  
cd ../billingonaire-ui && \
  echo "🔍 Checking frontend code quality..." && \
  npx eslint . --no-fix && \
  echo "✅ ESLint passed!"
```

## Pre-Merge Quality Requirements

**All of the following must pass:**

### Backend
- ✅ `black --check` exits with code 0 (no formatting issues)
- ✅ `isort --check-only` exits with code 0 (imports properly sorted)
- ✅ `flake8` exits with code 0 (zero lint violations)
- ✅ `mypy` on critical modules shows no errors
- ✅ All public functions have type hints

### Frontend
- ✅ `eslint . --no-fix` exits with code 0 (zero lint violations)
- ✅ No console warnings in ESLint output
- ✅ All imports are used
- ✅ All React hooks have proper dependencies

## Auto-Fix Workflow

If you fail linting checks, follow this order to fix:

1. **Format with Black** (auto-fixes most issues):
   ```bash
   cd billingonaire_backend && python -m black .
   ```

2. **Sort imports with isort**:
   ```bash
   python -m isort .
   ```

3. **Fix fixable ESLint issues**:
   ```bash
   cd ../billingonaire-ui && npx eslint . --fix
   ```

4. **Manually fix remaining flake8 errors**:
   ```bash
   cd ../billingonaire_backend && python -m flake8 . --config=.flake8
   ```

5. **Re-run all checks**:
   ```bash
   python -m black --check . && \
   python -m isort --check-only . && \
   python -m flake8 . --config=.flake8
   ```

---

## Common Errors & Fixes

### Python

| Error | Cause | Fix |
|-------|-------|-----|
| `W291` trailing whitespace | Spaces at end of line | `python -m black .` |
| `W293` blank line whitespace | Blank lines contain spaces | `python -m black .` |
| `F541` f-string missing placeholders | `f"no variables here"` | Change to `"no variables here"` |
| `E501` line too long | Line > 88 chars | Run Black to auto-wrap |
| `F841` variable assigned, never used | Unused local var | Delete variable or use it |

### JavaScript/React

| Error | Cause | Fix |
|-------|-------|-----|
| `no-unused-vars` | Import not used | Remove unused import |
| `exhaustive-deps` | Hook dependency missing | Add missing dependency to array |
| `react-hooks/rules-of-hooks` | Hook called conditionally | Move hook to top level |
| `no-undef` | Variable not defined | Check imports and spelling |

---

## Integration with CI/CD

These checks run automatically on all pull requests via GitHub Actions (`.github/workflows/ci.yml`):

```yaml
- Backend: black, isort, flake8
- Frontend: eslint
- Backend tests: pytest
- Frontend tests: vitest
- Security scan: Snyk
```

**PR will be blocked if any checks fail.** Fix all issues locally before pushing.

---

## Tools Configuration

### Black Configuration
File: `billingonaire_backend/pyproject.toml` or implicit defaults
```toml
[tool.black]
line-length = 88
target-version = ['py311']
```

### isort Configuration
File: `billingonaire_backend/pyproject.toml` or `.isort.cfg`
- Default profile: "black" compatible
- Alphabetic sorting within groups
- Std lib → Third-party → Local

### flake8 Configuration
File: `billingonaire_backend/.flake8`
- Ignores: W503, E203, E231
- Max line length: 88

### ESLint Configuration
File: `billingonaire-ui/eslint.config.js`
- React Hooks plugin with recommended rules
- React Refresh plugin
- Browser globals enabled

### mypy Configuration
File: `billingonaire_backend/mypy.ini`
- Python 3.11 target
- Strict mode enabled for critical modules

---

## Quick Reference

**Before every commit:**
```bash
# Backend
cd billingonaire_backend && black . && isort . && flake8 . --config=.flake8

# Frontend
cd ../billingonaire-ui && npx eslint . --fix
```

**Verify everything passes:**
```bash
# Backend
cd billingonaire_backend && \
  python -m black --check . && \
  python -m isort --check-only . && \
  python -m flake8 . --config=.flake8

# Frontend
cd ../billingonaire-ui && npx eslint . --no-fix
```

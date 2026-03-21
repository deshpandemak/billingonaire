---
name: frontend-component
description: Add a new React component or page to the Billingonaire frontend following project conventions for hooks, styling, API calls, and testing.
tags: [frontend, react, vite, javascript, testing, eslint]
---

## Overview

This skill describes the standard pattern for adding a new React component or page to the Billingonaire frontend. Follow every step to ensure consistency with the existing codebase, passing ESLint, and adequate test coverage.

## Project Conventions

| Convention | Detail |
|-----------|--------|
| Framework | React 19 |
| Build tool | Vite |
| Node version | 20 |
| Styling | React Bootstrap + component-level CSS |
| Routing | React Router DOM |
| HTTP client | `fetch` API or Axios (match existing component style) |
| Linter | ESLint (config in `billingonaire-ui/eslint.config.js`) |
| Unit tests | Vitest + React Testing Library |
| E2E tests | Playwright |
| Auth | Firebase Auth; ID token attached via `Authorization: Bearer` header |

## Component Structure

All components are **functional components** with hooks. No class components.

```jsx
import { useState, useEffect } from 'react';
import { Container, Row, Col, Card } from 'react-bootstrap';

function MyFeature() {
  const [data, setData] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    fetchData();
  }, []);

  async function fetchData() {
    try {
      const token = await getAuthToken();  // use existing auth helper
      const response = await fetch(`${API_BASE_URL}/my-feature`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!response.ok) throw new Error('Request failed');
      setData(await response.json());
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  if (loading) return <div>Loading...</div>;
  if (error) return <div role="alert" className="alert alert-danger">{error}</div>;

  return (
    <Container>
      <Row>
        <Col>
          <Card>
            <Card.Body>
              {/* component content */}
            </Card.Body>
          </Card>
        </Col>
      </Row>
    </Container>
  );
}

export default MyFeature;
```

## Step-by-Step

### 1. Create the component file

Place the new component in `billingonaire-ui/src/`. Use PascalCase for the filename matching the component name (e.g. `MyFeature.jsx`).

### 2. Add routing (for full pages)

Register the new page route in the router configuration in `billingonaire-ui/src/` (follow the existing `App.jsx` or router setup file pattern).

### 3. Add navigation link (if needed)

Add a navigation item to the sidebar or navbar component following the existing Bootstrap `Nav.Link` pattern.

### 4. Handle loading and error states

Every component that makes an API call must handle:
- `loading` state — show a spinner or "Loading..." message
- `error` state — show a Bootstrap alert with the error message
- Empty data — show an appropriate empty-state message (not an error)

### 5. Write a Vitest unit test

Create a test file at `billingonaire-ui/src/__tests__/MyFeature.test.jsx` (or matching the existing test file location pattern).

```jsx
import { render, screen, waitFor } from '@testing-library/react';
import { vi } from 'vitest';
import MyFeature from '../MyFeature';

// Mock Firebase auth
vi.mock('../firebase', () => ({
  auth: { currentUser: { getIdToken: async () => 'mock-token' } },
}));

// Mock fetch
global.fetch = vi.fn();

describe('MyFeature', () => {
  it('renders data from the API', async () => {
    fetch.mockResolvedValueOnce({
      ok: true,
      json: async () => [{ id: '1', label: 'Test Item' }],
    });

    render(<MyFeature />);

    await waitFor(() => {
      expect(screen.getByText('Test Item')).toBeInTheDocument();
    });
  });

  it('shows error message on fetch failure', async () => {
    fetch.mockResolvedValueOnce({ ok: false });
    render(<MyFeature />);
    await waitFor(() => {
      expect(screen.getByRole('alert')).toBeInTheDocument();
    });
  });
});
```

### 6. Run checks locally

```bash
cd billingonaire-ui
npm run lint -- src --max-warnings=6   # threshold matches .github/workflows/ci.yml
npm run test:unit:fast
npm run build
```

All checks must pass before pushing.

## Common Pitfalls

- Using class components — always use functional components with hooks.
- Calling `fetch` without attaching the Firebase auth token — all API calls require `Authorization: Bearer <token>`.
- Missing empty-state handling — always account for the case where the API returns an empty list.
- Importing Bootstrap CSS at component level unnecessarily — Bootstrap is already imported globally.
- Prop drilling more than two levels deep — use context or lift state when it becomes unwieldy.

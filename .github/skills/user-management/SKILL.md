---
name: user-management
description: Manage Firebase Auth users, their Firestore profiles, and their AGP role configuration including name-variation-based matter matching.
---

## Overview

User management covers Firebase Auth integration, Firestore user profiles, role-based access control (admin vs. user vs. AGP), and the AGP role configuration needed to match court board entries to specific users. Admin endpoints allow user creation, role assignment, and Firebase Auth→Firestore sync. Regular users manage their own profile, password, and AGP role configuration.

## Key Files

- `billingonaire_backend/UserManager.py` — Firebase Auth and Firestore user operations
- `billingonaire_backend/UserMatterMatcher.py` — AGP name variation generation and matter matching
- `billingonaire_backend/main.py` — `/user/*`, `/user-matters/*`, `/admin/*` route handlers
- `billingonaire_backend/specs/features/user_management.feature` — acceptance scenarios
- `billingonaire_backend/specs/steps/user_management_steps.py` — step implementations
- `billingonaire-ui/src/Login.jsx` — Firebase Auth login UI
- `billingonaire-ui/src/AdminUserManagement.jsx` — admin user management UI

## Firestore Collections Used

| Collection | Operation | Key Fields |
|-----------|-----------|-----------|
| `users` | read/write | `uid`, `email`, `full_name`, `role`, `legal_category`, `is_active`, ... |
| `user-roles` | read/write | `uid`, `agp_role`, `name_variations[]`, `active`, ... |
| `user-case-mappings` | read/write | `uid`, `case_id`, `source`, `match_score`, ... |

## Roles

The role model has two distinct layers:

| Layer | Storage | Values | Purpose |
|-------|---------|--------|---------|
| System role | `users.role` | `admin` or `user` | Controls API access (admin vs. regular user) |
| Legal role type | `user-roles` collection (`agp_role`) | `AGP`, `GP`, etc. | Identifies the legal professional category for court board matching |
| Legal category | `users.legal_category` | e.g. `assistant_government_pleader` | Categorises the user within the legal system |

Only users with `role = admin` can access admin endpoints. AGP/GP configuration and name variations are stored separately in `user-roles`, not in the `users` document.

## API Endpoints

| Endpoint | Method | Auth | Description |
|----------|--------|------|-------------|
| `/user/profile` | GET | Yes | Retrieve current user's profile |
| `/user/profile` | POST | Yes | Update `full_name` or other profile fields |
| `/user/change-password` | POST | Yes | Change password (min length enforced) |
| `/user-matters/configure-role` | POST | Yes | Set AGP role and `full_name` for matching |
| `/user-matters/role-config` | GET | Yes | Retrieve current role configuration |
| `/user-matters/generate-name-variations` | POST | Yes | Generate name variants for a given `name` |
| `/user-matters/my-matters` | GET | Yes | List court board matters matched to current user |
| `/admin/users` | GET | Admin | List all registered users |
| `/admin/user/{uid}/role` | POST | Admin | Set a user's role |
| `/admin/sync-firebase-users` | POST | Admin | Sync Firebase Auth users into Firestore |
| `/admin/create-user` | POST | Admin | Create user in Firebase Auth + Firestore |

## Business Rules

- Admin endpoints must return HTTP 403 for non-admin users — never 404.
- Password change must fail with a clear error when the new password is shorter than the minimum (6 characters).
- AGP name matching uses `name_variations` — a list of name permutations generated from `full_name` (e.g. initials, reversed order, title variations). Never hard-code a specific name format.
- `admin/sync-firebase-users` is idempotent: running it multiple times must not create duplicate Firestore documents.
- Firebase Auth is the source of truth for authentication; Firestore stores additional profile data.

## Name Variation Generation

`UserMatterMatcher.generate_name_variations(name)` accepts a full name string and returns a list of variations that cover common abbreviation and ordering patterns seen in court board PDFs. When implementing new variation logic:

1. Add the transformation function to `UserMatterMatcher.py`.
2. Keep transformations pure (no side effects).
3. Deduplicate the returned list.
4. Write a unit test covering at least three distinct name formats.

## Implementation Pattern

When adding a new admin or user endpoint:

1. Add the handler function in `UserManager.py` or a dedicated helper.
2. Register the route in `main.py` with the correct auth middleware (`require_admin` for admin routes).
3. Return HTTP 403 (not 401) when a valid but unprivileged user hits an admin route.
4. Add a Gherkin scenario in `specs/features/user_management.feature`.
5. Write a unit test mocking Firebase Admin SDK calls.

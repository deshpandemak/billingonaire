# GitHub Actions Deployment Fix Summary

## Issue Reported
**Error:** "Failed to load user profile: Unexpected token '<', "<!doctype "... is not valid JSON"

## Root Cause Analysis

### Problem 1: Frontend API URL Misconfiguration
The GitHub Actions workflow was NOT setting `VITE_API_URL` during the frontend build, causing the production frontend to use the wrong API endpoint.

**Failure Chain:**
1. GitHub Actions runs `npm run build` without `VITE_API_URL` env var
2. Vite defaults `import.meta.env.VITE_API_URL` to `undefined`
3. `api.js` uses fallback: `const API_BASE_URL = import.meta.env.VITE_API_URL || "/api"`
4. Frontend tries to fetch: `https://billingonaire.web.app/api/user/profile`
5. Firebase Hosting returns 404 HTML page (no `/api` route exists)
6. Frontend tries to parse HTML as JSON → **Error: Unexpected token '<', "<!doctype "..."**

### Problem 2: Backend Firebase Authentication (Resolved Previously)
Secret Manager was mounting credentials incorrectly, causing Firebase Admin SDK initialization failures.

## Solutions Implemented

### Fix 1: Explicit VITE_API_URL in GitHub Actions
**File:** `.github/workflows/cd.yml`

```yaml
- name: Build production bundle
  run: |
    cd billingonaire-ui
    npm run build
  env:
    NODE_ENV: production
    VITE_API_URL: https://billingonaire-backend-819125105651.asia-south1.run.app  # ADDED
```

### Fix 2: Manual Deployment Script Alignment
**File:** `firebase/deploy-all.sh`

```bash
# Deploy Frontend
echo "📦 Building frontend..."
cd billingonaire-ui
VITE_API_URL=https://billingonaire-backend-819125105651.asia-south1.run.app npm run build  # ADDED
```

### Fix 3: Backend Deployment (No Secret Manager)
**Files:** `.github/workflows/cd.yml`, `firebase/backend-cloudrun-deploy.sh`, `firebase/deploy-all.sh`

- Removed all Secret Manager creation/mounting steps
- Backend uses Application Default Credentials (ADC) exclusively
- Service account: `firebase-adminsdk-t0k85@billingonaire.iam.gserviceaccount.com`

## Verification

✅ **Local Build Check:**
```bash
$ grep "billingonaire-backend.*asia-south1.run.app" billingonaire-ui/dist/assets/*.js
Found 3 occurrences - API URL correctly embedded
```

✅ **Deployment Status:**
- Backend Revision: `billingonaire-backend-00097-wj6`
- Frontend: Deployed to Firebase Hosting
- API URL: Hardcoded in production bundle

## Why Replit Deployment Worked But GitHub Actions Failed

| Aspect | Replit | GitHub Actions (Before Fix) | GitHub Actions (After Fix) |
|--------|--------|------------------------------|----------------------------|
| **VITE_API_URL source** | Replit Secrets (auto-injected) | Not set (defaulted to "/api") | Explicitly set in workflow |
| **Build command** | `npm run build` (with env) | `npm run build` (no env) | `npm run build` (with env) |
| **Result** | ✅ Correct URL | ❌ Wrong URL ("/api") | ✅ Correct URL |

## Files Modified

1. `.github/workflows/cd.yml` - Added `VITE_API_URL` to frontend build step
2. `firebase/deploy-all.sh` - Added `VITE_API_URL` prefix to build command
3. `firebase/backend-cloudrun-deploy.sh` - Removed Secret Manager logic

## Testing Recommendations

1. **Verify frontend build:**
   ```bash
   grep -r "billingonaire-backend" billingonaire-ui/dist/
   ```

2. **Test production API calls:**
   - Visit https://billingonaire.web.app
   - Log in with valid credentials
   - Verify user profile loads without JSON parse errors

3. **Check browser console:**
   - Should see requests to `https://billingonaire-backend-819125105651.asia-south1.run.app/user/profile`
   - NOT to `https://billingonaire.web.app/api/user/profile`

## Deployment Completed

**Backend:** https://billingonaire-backend-819125105651.asia-south1.run.app  
**Frontend:** https://billingonaire.web.app  
**Status:** ✅ Live with fixes applied

---

**Date:** October 26, 2025  
**Deployed Revision:** Backend 00097, Frontend latest

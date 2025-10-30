# 🔧 Deployment Issue Resolution: Replit vs GitHub Actions

**Date:** October 30, 2025  
**Issue:** Order downloads work from Replit deployment but fail from GitHub Actions  
**Status:** ✅ RESOLVED - Ready for testing

---

## 🎯 ROOT CAUSE IDENTIFIED

The issue was **NOT** a difference in deployment configuration, networking, or Cloud Run setup.

### The Real Problem: **Stale Docker Images**

GitHub Actions was deploying **OLD Docker images** using the reusable `:latest` tag, while Replit was deploying **FRESH images** built from local code.

#### What Happened:

1. **Your Fixes Were Already on Main Branch** ✅
   - spaCy model download in Dockerfile
   - User-Agent headers for order downloads
   - Enhanced HTTP logging
   
2. **But GitHub Actions Kept Deploying Old Code** ❌
   - Used generic tag: `gcr.io/billingonaire/billingonaire-backend` (implicit `:latest`)
   - Cloud Build cached and reused the old image
   - Never picked up the new code from main branch
   
3. **Replit Deployments Worked** ✅
   - Built fresh images from local code
   - Had all the latest fixes
   - Order downloads succeeded

### Evidence from Production:

**Current production revision:** `billingonaire-backend-00107-5l7`

**Logs show OLD error format:**
```
WARNING:root:❌ Case WP/9976/2025 - FAILED after 50 sequences: No matching order found
```

**Should show NEW format (after fix deploys):**
```
INFO:root:Sequence 1: HTTP 200, Content-Type: application/pdf, Size: 107432 bytes
```

This proves the deployed image is stale and doesn't have your recent fixes.

---

## ✅ FIXES APPLIED

### 1. GitHub Actions Workflow Updated

**File:** `.github/workflows/cd.yml`

**Change:** Use commit SHA tags instead of `:latest`

**Before:**
```yaml
gcloud builds submit --tag gcr.io/$PROJECT_ID/$CLOUD_RUN_SERVICE .
gcloud run deploy ... --image=gcr.io/$PROJECT_ID/$CLOUD_RUN_SERVICE
```

**After:**
```yaml
gcloud builds submit --tag gcr.io/$PROJECT_ID/$CLOUD_RUN_SERVICE:${{ github.sha }} .
gcloud run deploy ... --image=gcr.io/$PROJECT_ID/$CLOUD_RUN_SERVICE:${{ github.sha }}
```

**Why this works:**
- Each commit gets a unique tag (e.g., `billingonaire-backend:9e4ac5d`)
- Cloud Build MUST build a fresh image (can't reuse cached `:latest`)
- Cloud Run deploys exactly the image that was just built
- No more stale image deployments

### 2. Code Fixes Already on Main

All these fixes are already committed to the main branch:

✅ **Dockerfile:** spaCy model download step added  
✅ **AutoOrderManager.py:** User-Agent headers for HTTP requests  
✅ **AutoOrderManager.py:** Enhanced logging with HTTP status, Content-Type, and response previews

---

## 📋 NEXT STEPS

### Step 1: Trigger GitHub Actions Deployment

Push this workflow change to trigger a fresh deployment:

```bash
# Commit the workflow fix
git add .github/workflows/cd.yml DEPLOYMENT_FIX_SUMMARY.md
git commit -m "Fix GitHub Actions to use commit SHA tags for Docker images"
git push origin main
```

### Step 2: Monitor the Deployment

1. **Check GitHub Actions:**
   - Go to your repository's Actions tab
   - Watch the "Deploy to Production" workflow run
   - Verify it builds and deploys successfully

2. **Expected Build Output:**
   ```
   🔨 Building Docker image with tag: 9e4ac5d...
   🚀 Deploying to Cloud Run...
   ```

3. **Check Cloud Run Revision:**
   ```bash
   gcloud run services describe billingonaire-backend \
     --region=asia-south1 --project=billingonaire \
     --format="value(status.latestReadyRevisionName)"
   ```
   
   You should see a NEW revision number (e.g., `billingonaire-backend-00108-xxx`)

### Step 3: Verify Order Downloads Work

After deployment completes:

1. **Check Production Logs:**
   ```bash
   gcloud logging read "resource.type=cloud_run_revision \
     AND resource.labels.service_name=billingonaire-backend" \
     --limit=50 --format="value(timestamp,textPayload)" \
     --project=billingonaire | grep -E "Sequence|HTTP|PDF"
   ```

2. **Look for NEW log format:**
   ```
   INFO:root:Sequence 1: HTTP 200, Content-Type: application/pdf, Size: 107432 bytes
   INFO:root:✅ SUCCESS at sequence 1: PDF found (107432 bytes)
   ```

3. **Test via Admin Dashboard:**
   - Go to Admin Order Management (`/admin/orders`)
   - Click "Process Queue"
   - Monitor live queue processing
   - Verify orders transition from `not_linked` → `order_linked` → `analysed`

---

## 🔍 TECHNICAL DETAILS

### Why Commit SHA Tagging Prevents This Issue

**Problem with `:latest` tag:**
```
First build:  gcr.io/billingonaire/backend:latest (version A)
Code updated: New code pushed to main
Second build: gcr.io/billingonaire/backend:latest (still uses cached version A)
              ❌ Cloud Build thinks nothing changed, reuses old image
```

**Solution with commit SHA tags:**
```
First build:  gcr.io/billingonaire/backend:abc1234 (version A)
Code updated: New code pushed to main
Second build: gcr.io/billingonaire/backend:def5678 (version B)
              ✅ Different tag forces fresh build, can't reuse old image
```

### Image Proliferation Management

**Note:** SHA tagging creates a new image for each commit. Consider adding cleanup:

```bash
# List old images
gcloud container images list-tags gcr.io/billingonaire/billingonaire-backend

# Delete images older than 30 days (optional)
gcloud container images list-tags gcr.io/billingonaire/billingonaire-backend \
  --format="get(digest)" --filter="timestamp.datetime < $(date -d '30 days ago' --iso-8601)" \
  | xargs -I {} gcloud container images delete gcr.io/billingonaire/billingonaire-backend@{} --quiet
```

Or set up GCR retention policy in Cloud Console.

---

## 📊 COMPARISON: Replit vs GitHub Actions

| Aspect | Replit Deployment | GitHub Actions (OLD) | GitHub Actions (FIXED) |
|--------|------------------|---------------------|----------------------|
| **Image Tag** | `:latest` | `:latest` | `:${{ github.sha }}` |
| **Code Source** | Local (fresh) | Main branch | Main branch |
| **Build Behavior** | Always fresh | Cached reuse ❌ | Always fresh ✅ |
| **Order Downloads** | ✅ Working | ❌ Failing | ✅ Will work |
| **Deployment Trigger** | Manual script | GitHub push/PR | GitHub push/PR |

---

## ✅ VERIFICATION CHECKLIST

After GitHub Actions deploys the new image:

- [ ] New Cloud Run revision created (e.g., 00108+)
- [ ] Logs show new format: `Sequence X: HTTP {status}, Content-Type: {type}`
- [ ] Order downloads succeed (no more "FAILED after 50 sequences")
- [ ] Admin dashboard shows orders transitioning: `not_linked` → `order_linked` → `analysed`
- [ ] spaCy model loads without `[E050]` warnings
- [ ] Multi-case order linking works correctly

---

## 📝 LESSONS LEARNED

1. **Always use specific image tags** in CI/CD (commit SHA, semantic version, etc.)
2. **Never rely on `:latest` tag** - it enables silent cache reuse
3. **Verify deployed image matches source code** - check revision logs after deployment
4. **Docker cache can hide code changes** - explicit tags force fresh builds
5. **Different deployment methods can deploy different code** - even with identical scripts

---

## 🚀 READY TO DEPLOY

The fix is ready. When you push this commit to main, GitHub Actions will:

1. Build a fresh Docker image with your latest fixes
2. Tag it with the commit SHA (prevents reuse)
3. Deploy it to Cloud Run
4. Order downloads should work immediately

**No additional configuration needed!** Just push and monitor the deployment.

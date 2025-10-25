# GitHub Actions Deployment Fix

## Issues Identified and Fixed

### 1. **Directory Navigation Problems**
**Problem**: GitHub Actions was not properly navigating to the backend directory for Docker builds.
**Fix**: Added explicit directory verification and changed to use the same approach as the Firebase script.

### 2. **Container Registry Configuration**
**Problem**: The GitHub Actions workflow mentioned Artifact Registry but was using Google Container Registry (GCR), with inconsistent tagging.
**Fix**: Simplified to use GCR consistently and removed complex tagging strategy that wasn't needed.

### 3. **Build Process Differences**
**Problem**: GitHub Actions was using a more complex build process with unnecessary steps.
**Fix**: Aligned the GitHub Actions workflow to match the working Firebase script approach:
- Removed unnecessary Python virtual environment setup
- Simplified the Cloud Build submission
- Used the same gcloud commands as the Firebase script

### 4. **Authentication Configuration**
**Problem**: Authentication was not fully configured with proper project settings.
**Fix**: Added explicit project configuration and Docker authentication steps.

### 5. **Error Handling**
**Problem**: Limited error handling and debugging information.
**Fix**: Added:
- Directory existence checks
- Better logging with emojis for clarity
- Verification steps before deployment
- More robust error handling in verification

### 6. **Frontend Deployment Configuration**
**Problem**: Firebase Hosting deployment wasn't specifying the correct entry point.
**Fix**: Removed the incorrect `entryPoint: './billingonaire-ui'` configuration. The Firebase Hosting action should use the root directory where `firebase.json` is located.

### 7. **Firebase Configuration Mismatch**
**Problem**: The GitHub Action was trying to find `firebase.json` in the `billingonaire-ui` directory due to the `entryPoint` setting, but `firebase.json` is in the root directory.
**Fix**: Removed the `entryPoint` parameter so the action uses the root directory by default, where `firebase.json` correctly configures the public directory as `billingonaire-ui/dist`.

## Key Changes Made

### Before (GitHub Actions):
```yaml
# Complex build with virtual environment
- name: Create and activate Python virtual environment
  run: |
    cd billingonaire_backend
    python -m venv venv
    source venv/bin/activate
    pip install --upgrade pip

# Complex tagging strategy
gcloud builds submit billingonaire_backend \
  --tag gcr.io/${{ env.GCP_PROJECT_ID }}/${{ env.CLOUD_RUN_SERVICE }}:${{ github.sha }} \
  --tag gcr.io/${{ env.GCP_PROJECT_ID }}/${{ env.CLOUD_RUN_SERVICE }}:latest
```

### After (GitHub Actions - matching Firebase script):
```yaml
# Simple build process matching Firebase script
cd billingonaire_backend
gcloud builds submit --tag gcr.io/${{ env.GCP_PROJECT_ID }}/${{ env.CLOUD_RUN_SERVICE }} .
```

## Firebase Script Approach (Working):
```bash
cd ../billingonaire_backend
gcloud builds submit --tag gcr.io/billingonaire/billingonaire-backend .
gcloud run deploy billingonaire-backend \
  --image=gcr.io/billingonaire/billingonaire-backend \
  --region=asia-south1 \
  # ... rest of configuration
```

## Verification Steps Added

1. **Dockerfile Verification**: Check that Dockerfile exists before attempting build
2. **Directory Listing**: Show contents of backend directory for debugging
3. **Project Configuration**: Explicitly set and verify GCP project
4. **Deployment Verification**: Wait for services to be ready before testing

## Environment Variables Aligned

Both GitHub Actions and Firebase scripts now use the same environment variables:
- `ORDER_PROCESSING_WORKERS=3`
- `ORDER_MAX_SEQUENCE_RETRIES=50`
- Same service account: `firebase-adminsdk-t0k85@billingonaire.iam.gserviceaccount.com`
- Same region: `asia-south1`
- Same resource configuration: 2Gi memory, 2 CPU

## Troubleshooting Guide

### If Deployment Still Fails:

1. **"firebase.json file not found" Error**:
   - This means the `entryPoint` is incorrectly set in the Firebase Hosting action
   - The `firebase.json` file should be in the root directory
   - Remove any `entryPoint` parameter to use the root directory by default
   - Ensure `firebase.json` has the correct `public` directory setting

2. **Check Secrets Configuration**:
   - Ensure `GCLOUD_SERVICE_ACCOUNT_KEY` is properly set in GitHub Secrets
   - Ensure `FIREBASE_SERVICE_ACCOUNT` is properly set in GitHub Secrets

2. **Check Service Account Permissions**:
   - Cloud Build Editor
   - Cloud Run Admin
   - Storage Admin
   - Firebase Admin

3. **Check GCP APIs**:
   ```bash
   gcloud services enable cloudbuild.googleapis.com
   gcloud services enable run.googleapis.com
   gcloud services enable containerregistry.googleapis.com
   ```

4. **Manual Testing**:
   - Test the Firebase script locally first
   - Verify Cloud Build and Cloud Run work manually
   - Check logs in GCP Console

### Debugging Commands:
```bash
# Check service account permissions
gcloud iam service-accounts get-iam-policy firebase-adminsdk-t0k85@billingonaire.iam.gserviceaccount.com

# Check existing Cloud Run services
gcloud run services list --region=asia-south1

# Check Container Registry images
gcloud container images list --repository=gcr.io/billingonaire
```

## Files Modified

1. `.github/workflows/cd.yml` - Main deployment workflow
2. This documentation file

## Next Steps

1. Test the updated GitHub Actions workflow
2. Monitor deployment logs for any remaining issues
3. Consider adding additional monitoring and alerts
4. Document any new issues that arise

The GitHub Actions deployment should now work the same way as the Firebase script that works locally.
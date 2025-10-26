# Cloud Run Secrets Management - Fix Documentation

## Issues Found and Fixed

### 1. **Inconsistent Secret Handling**
- **Problem**: Different deployment scripts handled secrets differently
- **Fix**: Standardized all scripts to use Secret Manager with fallback to ADC

### 2. **Missing Secret Manager Setup**
- **Problem**: CD pipeline tried to create secrets without proper error handling
- **Fix**: Created dedicated setup scripts and improved error handling

### 3. **Service Account Permissions**
- **Problem**: Missing or incomplete IAM permissions for secret access
- **Fix**: Added comprehensive permission setup

## Files Modified

### `/firebase/backend-cloudrun-deploy.sh`
- Added Secret Manager detection and mounting
- Improved secret handling logic
- Added GOOGLE_CLOUD_PROJECT environment variable

### `/firebase/setup-secrets.sh` (NEW)
- Simple script for basic secret setup
- Validates prerequisites
- Sets up secret and basic permissions

### `/firebase/setup-complete.sh` (NEW)
- Comprehensive setup script
- Enables all required APIs
- Sets up all IAM permissions
- Validates service account existence

### `/.github/workflows/cd.yml`
- Simplified secret creation logic
- Improved error handling
- Consistent Secret Manager usage
- Fixed Firebase service account reference

## Usage Instructions

### For Local/Manual Deployment

1. **First-time setup:**
   ```bash
   export GCLOUD_SERVICE_ACCOUNT_KEY='{"type":"service_account",...}'
   ./firebase/setup-complete.sh
   ```

2. **Deploy backend:**
   ```bash
   ./firebase/backend-cloudrun-deploy.sh
   ```

### For GitHub Actions

1. **Ensure these secrets are set in GitHub:**
   - `GCLOUD_SERVICE_ACCOUNT_KEY`: Firebase service account JSON
   - `GITHUB_TOKEN`: (automatically provided)

2. **The CD pipeline will:**
   - Automatically set up Secret Manager
   - Deploy using consistent configuration
   - Mount secrets properly to Cloud Run

## Security Improvements

1. **Secret Manager Integration**: Secrets are now stored securely in Google Secret Manager instead of just environment variables
2. **Least Privilege**: Service account only gets necessary permissions
3. **Fallback Support**: Application can still work with Application Default Credentials if secrets are unavailable
4. **Validation**: All scripts now validate prerequisites before proceeding

## Environment Variables Available to Cloud Run

After deployment, the following environment variables are available:
- `GCLOUD_SERVICE_ACCOUNT_KEY`: (via Secret Manager)
- `ORDER_PROCESSING_WORKERS`: 3
- `ORDER_MAX_SEQUENCE_RETRIES`: 50
- `GOOGLE_CLOUD_PROJECT`: billingonaire

## Testing the Fix

1. **Check secret exists:**
   ```bash
   gcloud secrets describe GCLOUD_SERVICE_ACCOUNT_KEY
   ```

2. **Verify service account permissions:**
   ```bash
   gcloud secrets get-iam-policy GCLOUD_SERVICE_ACCOUNT_KEY
   ```

3. **Test deployment:**
   ```bash
   ./firebase/backend-cloudrun-deploy.sh
   ```

4. **Verify Cloud Run service:**
   ```bash
   gcloud run services describe billingonaire-backend --region=asia-south1
   ```

## Rollback Plan

If issues occur, you can revert to environment variable approach by:
1. Removing `--update-secrets` from deployment commands
2. Adding `--set-env-vars="GCLOUD_SERVICE_ACCOUNT_KEY=$GCLOUD_SERVICE_ACCOUNT_KEY"`
3. The application code already supports both approaches
# GitHub Repository Secrets Setup

## Required Secrets

To fix the CD pipeline, you need to configure these secrets in your GitHub repository:

### 1. GCLOUD_SERVICE_ACCOUNT_KEY
**Value**: Your Firebase service account JSON key
**Purpose**: Authentication with Google Cloud Platform

**To get this value:**
1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Navigate to IAM & Admin → Service Accounts
3. Find `firebase-adminsdk-t0k85@billingonaire.iam.gserviceaccount.com`
4. Click on it, go to Keys tab
5. Create new key (JSON format)
6. Copy the entire JSON content

**To set in GitHub:**
1. Go to your repository on GitHub
2. Settings → Secrets and variables → Actions
3. Click "New repository secret"
4. Name: `GCLOUD_SERVICE_ACCOUNT_KEY`
5. Value: Paste the entire JSON (starting with `{` and ending with `}`)

### 2. GITHUB_TOKEN (Automatically Available)
This is automatically provided by GitHub Actions - no setup needed.

## Verification

After setting up the secrets, you can verify by:

1. **Check the CD pipeline runs without "Context access might be invalid" errors**
2. **Test a deployment by pushing to main branch**
3. **Check that the deployment succeeds in GitHub Actions**

## Alternative: Manual Deployment

If you prefer not to use GitHub Actions, you can deploy manually using:

```bash
# Set up your environment variable locally
export GCLOUD_SERVICE_ACCOUNT_KEY='{"type":"service_account",...}'

# Run the setup script
./firebase/setup-complete.sh

# Deploy backend
./firebase/backend-cloudrun-deploy.sh
```

## Firebase Service Account Permissions

Ensure your Firebase service account has these roles:
- Firebase Admin SDK Administrator Service Agent
- Cloud Datastore User
- Secret Manager Secret Accessor
- Cloud Run Admin (for deployment)
- Cloud Build Editor (for building images)

You can check and assign these in Google Cloud Console → IAM & Admin → IAM.
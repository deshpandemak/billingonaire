#!/bin/bash

# Script to set up Secret Manager for Cloud Run deployment
# This should be run once to configure secrets before deployment

set -e

PROJECT_ID="billingonaire"
SERVICE_ACCOUNT="firebase-adminsdk-t0k85@billingonaire.iam.gserviceaccount.com"

echo "🔐 Setting up Secret Manager for Cloud Run deployment"
echo "=================================================="

# Ensure we're authenticated and using the right project
gcloud config set project $PROJECT_ID

# Enable Secret Manager API if not already enabled
echo "📡 Enabling Secret Manager API..."
gcloud services enable secretmanager.googleapis.com

# Create or update GCLOUD_SERVICE_ACCOUNT_KEY secret from env var
if [ -z "$GCLOUD_SERVICE_ACCOUNT_KEY" ]; then
  echo "❌ Error: GCLOUD_SERVICE_ACCOUNT_KEY environment variable not set"
  echo "Please set it with your service account JSON key before running this script"
  exit 1
fi

if gcloud secrets describe GCLOUD_SERVICE_ACCOUNT_KEY >/dev/null 2>&1; then
  echo "🔄 Adding new version to GCLOUD_SERVICE_ACCOUNT_KEY"
  echo "$GCLOUD_SERVICE_ACCOUNT_KEY" | gcloud secrets versions add GCLOUD_SERVICE_ACCOUNT_KEY --data-file=-
else
  echo "🔑 Creating GCLOUD_SERVICE_ACCOUNT_KEY secret..."
  echo "$GCLOUD_SERVICE_ACCOUNT_KEY" | gcloud secrets create GCLOUD_SERVICE_ACCOUNT_KEY --data-file=-
fi

# Grant the Cloud Run service account access to the backend secret
echo "🔒 Granting secret access to service account..."
gcloud secrets add-iam-policy-binding GCLOUD_SERVICE_ACCOUNT_KEY \
  --member="serviceAccount:$SERVICE_ACCOUNT" \
  --role="roles/secretmanager.secretAccessor"

# Create or update GEMINI_API_KEY secret from env var. Optional: the
# review-copilot AI suggestion feature (POST /admin/orders/{id}/ai-suggestion)
# degrades gracefully without it -- the endpoint returns 501 and the manual
# review queue works exactly as before.
if [ -n "$GEMINI_API_KEY" ]; then
  if gcloud secrets describe GEMINI_API_KEY >/dev/null 2>&1; then
    echo "🔄 Adding new version to GEMINI_API_KEY"
    echo "$GEMINI_API_KEY" | gcloud secrets versions add GEMINI_API_KEY --data-file=-
  else
    echo "🔑 Creating GEMINI_API_KEY secret..."
    echo "$GEMINI_API_KEY" | gcloud secrets create GEMINI_API_KEY --data-file=-
  fi

  echo "🔒 Granting secret access to service account..."
  gcloud secrets add-iam-policy-binding GEMINI_API_KEY \
    --member="serviceAccount:$SERVICE_ACCOUNT" \
    --role="roles/secretmanager.secretAccessor"
else
  echo "ℹ️  GEMINI_API_KEY not set -- skipping (optional; the review-copilot"
  echo "    AI suggestion feature just won't be available until this is added)."
fi

echo "✅ Secret Manager setup complete!"
echo ""
echo "🚀 You can now deploy to Cloud Run with:"
echo "   ./firebase/backend-cloudrun-deploy.sh"

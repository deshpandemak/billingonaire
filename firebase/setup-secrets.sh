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

# Create or update FIRECRAWL_API_KEY secret from env var
if [ -z "$FIRECRAWL_API_KEY" ]; then
  echo "❌ Error: FIRECRAWL_API_KEY environment variable not set"
  echo "Please set it before running this script"
  exit 1
fi

if gcloud secrets describe FIRECRAWL_API_KEY >/dev/null 2>&1; then
  echo "🔄 Adding new version to FIRECRAWL_API_KEY"
  echo -n "$FIRECRAWL_API_KEY" | gcloud secrets versions add FIRECRAWL_API_KEY --data-file=-
else
  echo "🔑 Creating FIRECRAWL_API_KEY secret..."
  echo -n "$FIRECRAWL_API_KEY" | gcloud secrets create FIRECRAWL_API_KEY --data-file=-
fi

# Grant the Cloud Run service account access to both secrets
echo "🔒 Granting secret access to service account..."
gcloud secrets add-iam-policy-binding GCLOUD_SERVICE_ACCOUNT_KEY \
  --member="serviceAccount:$SERVICE_ACCOUNT" \
  --role="roles/secretmanager.secretAccessor"

gcloud secrets add-iam-policy-binding FIRECRAWL_API_KEY \
  --member="serviceAccount:$SERVICE_ACCOUNT" \
  --role="roles/secretmanager.secretAccessor"

echo "✅ Secret Manager setup complete!"
echo ""
echo "🚀 You can now deploy to Cloud Run with:"
echo "   ./firebase/backend-cloudrun-deploy.sh"

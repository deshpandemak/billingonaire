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

# Check if secret already exists
if gcloud secrets describe GCLOUD_SERVICE_ACCOUNT_KEY >/dev/null 2>&1; then
  echo "✅ Secret GCLOUD_SERVICE_ACCOUNT_KEY already exists"
else
  # Create the secret if it doesn't exist
  echo "🔑 Creating GCLOUD_SERVICE_ACCOUNT_KEY secret..."
  
  if [ -z "$GCLOUD_SERVICE_ACCOUNT_KEY" ]; then
    echo "❌ Error: GCLOUD_SERVICE_ACCOUNT_KEY environment variable not set"
    echo "Please set it with your service account JSON key before running this script"
    exit 1
  fi
  
  # Create secret from environment variable
  echo "$GCLOUD_SERVICE_ACCOUNT_KEY" | gcloud secrets create GCLOUD_SERVICE_ACCOUNT_KEY --data-file=-
  echo "✅ Secret created successfully"
fi

# Grant the Cloud Run service account access to the secret
echo "🔒 Granting secret access to service account..."
gcloud secrets add-iam-policy-binding GCLOUD_SERVICE_ACCOUNT_KEY \
  --member="serviceAccount:$SERVICE_ACCOUNT" \
  --role="roles/secretmanager.secretAccessor"

echo "✅ Secret Manager setup complete!"
echo ""
echo "🚀 You can now deploy to Cloud Run with:"
echo "   ./firebase/backend-cloudrun-deploy.sh"
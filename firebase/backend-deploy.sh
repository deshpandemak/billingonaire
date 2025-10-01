#!/bin/bash

# Exit on error
set -e

# Check if GCLOUD_SERVICE_ACCOUNT_KEY is set
if [ -z "$GCLOUD_SERVICE_ACCOUNT_KEY" ]; then
  echo "❌ Error: GCLOUD_SERVICE_ACCOUNT_KEY environment variable not set"
  echo "Please set it with your service account JSON key"
  exit 1
fi

# Authenticate with Google Cloud using service account
echo "🔐 Authenticating with Google Cloud..."
echo "$GCLOUD_SERVICE_ACCOUNT_KEY" > /tmp/gcloud-key.json
gcloud auth activate-service-account --key-file=/tmp/gcloud-key.json
gcloud config set project billingonaire

# Navigate to the backend directory
cd ../billingonaire-backend

# Deploy the backend to Google Cloud Functions
echo "🚀 Deploying backend to Google Cloud Functions..."
gcloud functions deploy billingonaire-backend \
  --gen2 \
  --runtime=python312 \
  --region=asia-south1 \
  --source=. \
  --entry-point=handler \
  --trigger-http \
  --allow-unauthenticated \
  --memory=1024MB \
  --timeout=540s \
  --env-vars-file=env.yaml \
  --service-account=firebase-adminsdk-t0k85@billingonaire.iam.gserviceaccount.com

# Clean up
rm /tmp/gcloud-key.json

echo "✅ Backend deployment complete!"

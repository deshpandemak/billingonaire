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

# Navigate to the backend directory (script is run from firebase dir)
cd ../billingonaire_backend

# Build and deploy using Dockerfile to avoid buildpacks permission issues
echo "🚀 Building and deploying backend to Google Cloud Run..."
gcloud builds submit --tag gcr.io/billingonaire/billingonaire-backend .

echo "🚀 Deploying to Cloud Run..."
echo "ℹ️  Backend will use Application Default Credentials (ADC) via service account"

# Deploy with Application Default Credentials (service account)
# No Secret Manager - ADC is more reliable for Firebase Admin SDK
gcloud run deploy billingonaire-backend \
  --image=gcr.io/billingonaire/billingonaire-backend \
  --region=asia-south1 \
  --platform=managed \
  --allow-unauthenticated \
  --memory=2Gi \
  --cpu=2 \
  --timeout=540s \
  --max-instances=10 \
  --min-instances=1 \
  --service-account=firebase-adminsdk-t0k85@billingonaire.iam.gserviceaccount.com \
  --set-env-vars="ORDER_PROCESSING_WORKERS=3,ORDER_MAX_SEQUENCE_RETRIES=50,GOOGLE_CLOUD_PROJECT=billingonaire"

# Clean up
rm /tmp/gcloud-key.json

echo "✅ Backend deployment to Cloud Run complete!"
echo "🌐 Your backend is now live!"

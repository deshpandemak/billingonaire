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

# Ensure the GCS bucket for court order PDFs exists and the Cloud Run service
# account has write permission to it.
GCS_BUCKET="billingonaire-court-orders"
SA_EMAIL="firebase-adminsdk-t0k85@billingonaire.iam.gserviceaccount.com"
echo "📦 Ensuring GCS bucket ${GCS_BUCKET} exists..."
if ! gsutil ls -b "gs://${GCS_BUCKET}" >/dev/null 2>&1; then
  gsutil mb -p billingonaire -l asia-south1 "gs://${GCS_BUCKET}"
  echo "✅ Created GCS bucket: gs://${GCS_BUCKET}"
else
  echo "✅ GCS bucket already exists: gs://${GCS_BUCKET}"
fi

echo "🔑 Granting objectAdmin on ${GCS_BUCKET} to ${SA_EMAIL}..."
gsutil iam ch "serviceAccount:${SA_EMAIL}:roles/storage.objectAdmin" "gs://${GCS_BUCKET}"
echo "✅ IAM binding applied."

# Navigate to the backend directory (script is run from firebase dir)
cd ../billingonaire_backend

# Build and deploy using Dockerfile to avoid buildpacks permission issues
echo "🚀 Building and deploying backend to Google Cloud Run..."
gcloud builds submit --tag gcr.io/billingonaire/billingonaire-backend .

echo "🚀 Deploying to Cloud Run..."
echo "ℹ️  Backend will use Application Default Credentials (ADC) via service account"

# --cpu-boost ensures full CPU during cold start so heavy Python/ML
# imports (spaCy, pandas, scikit-learn) complete before the startup probe times out
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
  --cpu-boost \
  --service-account=firebase-adminsdk-t0k85@billingonaire.iam.gserviceaccount.com \
  --set-env-vars="ORDER_PROCESSING_WORKERS=3,GOOGLE_CLOUD_PROJECT=billingonaire,ORDER_PDF_BUCKET=billingonaire-court-orders"

BACKEND_URL=$(gcloud run services describe billingonaire-backend --region=asia-south1 --format='value(status.url)')
echo "🔎 Backend health check: ${BACKEND_URL}/"

BACKEND_HEALTH_OK=false
for i in $(seq 1 20); do
  if curl -sSf "${BACKEND_URL}/" >/dev/null 2>&1; then
    BACKEND_HEALTH_OK=true
    break
  fi
  sleep 3
done

if [ "$BACKEND_HEALTH_OK" != "true" ]; then
  echo "⚠️ Backend health endpoint is not ready yet: ${BACKEND_URL}/"
else
  echo "✅ Backend is healthy: ${BACKEND_URL}/"
fi

# Clean up
rm /tmp/gcloud-key.json

echo "✅ Backend deployment to Cloud Run complete!"
echo "🌐 Your backend is now live: ${BACKEND_URL}"

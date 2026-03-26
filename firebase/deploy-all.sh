#!/bin/bash

# Deploy full stack to production
# Usage: ./firebase/deploy-all.sh

set -e

echo "🚀 Deploying Billingonaire to Production"
echo "========================================"

# Deploy Backend
echo ""
echo "📦 Building backend Docker image..."
cd billingonaire_backend
gcloud auth activate-service-account --key-file=<(echo "$GCLOUD_SERVICE_ACCOUNT_KEY")
gcloud config set project billingonaire
gcloud builds submit --tag gcr.io/billingonaire/billingonaire-backend .

echo ""
echo "🚀 Deploying backend to Cloud Run..."
echo "ℹ️  Backend will use Application Default Credentials (ADC) via service account"

gcloud run deploy billingonaire-backend \
  --image=gcr.io/billingonaire/billingonaire-backend:latest \
  --region=asia-south1 \
  --allow-unauthenticated \
  --platform=managed \
  --service-account=firebase-adminsdk-t0k85@billingonaire.iam.gserviceaccount.com \
  --timeout=540 \
  --cpu=2 \
  --memory=2Gi \
  --max-instances=10 \
  --min-instances=1 \
  --set-env-vars="ORDER_PROCESSING_WORKERS=3,ORDER_MAX_SEQUENCE_RETRIES=50,GOOGLE_CLOUD_PROJECT=billingonaire,COURT_SCRAPER_PROVIDER=direct_api"

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

cd ..

# Deploy Frontend
echo ""
echo "📦 Building frontend..."
cd billingonaire-ui
VITE_API_URL=https://billingonaire-backend-819125105651.asia-south1.run.app npm run build

echo ""
echo "🚀 Deploying frontend to Firebase Hosting..."
# Use service account key instead of deprecated FIREBASE_TOKEN
export GOOGLE_APPLICATION_CREDENTIALS=<(echo "$GCLOUD_SERVICE_ACCOUNT_KEY")
firebase use billingonaire
firebase deploy --only hosting

cd ..

echo ""
echo "✅ Deployment Complete!"
echo "========================================"
echo "Frontend: https://billingonaire.web.app"
echo "Backend: https://billingonaire-backend-819125105651.asia-south1.run.app"
echo "Scraper provider: direct_api"

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
  --set-env-vars="ORDER_PROCESSING_WORKERS=3,ORDER_MAX_SEQUENCE_RETRIES=50"

cd ..

# Deploy Frontend
echo ""
echo "📦 Building frontend..."
cd billingonaire-ui
npm run build

echo ""
echo "🚀 Deploying frontend to Firebase Hosting..."
firebase use billingonaire
firebase deploy --only hosting --token "$FIREBASE_TOKEN"

cd ..

echo ""
echo "✅ Deployment Complete!"
echo "========================================"
echo "Frontend: https://billingonaire.web.app"
echo "Backend: https://billingonaire-backend-819125105651.asia-south1.run.app"

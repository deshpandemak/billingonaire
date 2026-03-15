#!/bin/bash

# Deploy full stack to production
# Usage: ./firebase/deploy-all.sh

set -e

echo "🚀 Deploying Billingonaire to Production"
echo "========================================"

# Optional Ollama deployment (enabled by DEPLOY_OLLAMA=true)
if [ "${DEPLOY_OLLAMA:-false}" = "true" ]; then
  echo ""
  echo "🤖 Deploying Ollama service first..."
  ./firebase/ollama-cloudrun-deploy.sh
fi

# Optional dedicated GKE Ollama deployment (preferred for production)
if [ "${DEPLOY_OLLAMA_GKE:-false}" = "true" ]; then
  echo ""
  echo "🤖 Deploying Ollama on dedicated GKE..."
  ./firebase/ollama-gke-deploy.sh
fi

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

OLLAMA_BASE_URL_VALUE="${OLLAMA_BASE_URL:-}"
if [ -z "$OLLAMA_BASE_URL_VALUE" ]; then
  if [ -f /tmp/ollama-url.txt ]; then
    OLLAMA_BASE_URL_VALUE="$(cat /tmp/ollama-url.txt)"
  fi
fi
if [ -z "$OLLAMA_BASE_URL_VALUE" ]; then
  OLLAMA_BASE_URL_VALUE=$(gcloud run services describe billingonaire-ollama --region=asia-south1 --format='value(status.url)' 2>/dev/null || true)
fi
if [ -z "$OLLAMA_BASE_URL_VALUE" ]; then
  OLLAMA_BASE_URL_VALUE="http://localhost:11434"
fi

ORDER_ENABLE_LLM_FALLBACK_VALUE="${ORDER_ENABLE_LLM_FALLBACK:-false}"
ORDER_LLM_PROVIDER_VALUE="${ORDER_LLM_PROVIDER:-ollama}"
ORDER_LLM_MODEL_VALUE="${ORDER_LLM_MODEL:-llama3.1:8b}"
ORDER_LLM_TIMEOUT_SECONDS_VALUE="${ORDER_LLM_TIMEOUT_SECONDS:-60}"
ORDER_LLM_FALLBACK_MIN_QUALITY_VALUE="${ORDER_LLM_FALLBACK_MIN_QUALITY:-0.70}"
ORDER_LLM_FALLBACK_MIN_CATEGORY_CONFIDENCE_VALUE="${ORDER_LLM_FALLBACK_MIN_CATEGORY_CONFIDENCE:-0.70}"
ORDER_LLM_FALLBACK_MIN_CASES_VALUE="${ORDER_LLM_FALLBACK_MIN_CASES:-1}"

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
  --set-env-vars="ORDER_PROCESSING_WORKERS=3,ORDER_MAX_SEQUENCE_RETRIES=50,GOOGLE_CLOUD_PROJECT=billingonaire,FIRECRAWL_MODEL=spark-1-mini,ORDER_ENABLE_LLM_FALLBACK=${ORDER_ENABLE_LLM_FALLBACK_VALUE},ORDER_LLM_PROVIDER=${ORDER_LLM_PROVIDER_VALUE},ORDER_LLM_MODEL=${ORDER_LLM_MODEL_VALUE},OLLAMA_BASE_URL=${OLLAMA_BASE_URL_VALUE},ORDER_LLM_TIMEOUT_SECONDS=${ORDER_LLM_TIMEOUT_SECONDS_VALUE},ORDER_LLM_FALLBACK_MIN_QUALITY=${ORDER_LLM_FALLBACK_MIN_QUALITY_VALUE},ORDER_LLM_FALLBACK_MIN_CATEGORY_CONFIDENCE=${ORDER_LLM_FALLBACK_MIN_CATEGORY_CONFIDENCE_VALUE},ORDER_LLM_FALLBACK_MIN_CASES=${ORDER_LLM_FALLBACK_MIN_CASES_VALUE}" \
  --set-secrets="FIRECRAWL_API_KEY=FIRECRAWL_API_KEY:latest"

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

if [ -n "$OLLAMA_BASE_URL_VALUE" ] && [ "$OLLAMA_BASE_URL_VALUE" != "http://localhost:11434" ]; then
  echo "🔎 Ollama health check: ${OLLAMA_BASE_URL_VALUE}/api/tags"
  if curl -sSf "${OLLAMA_BASE_URL_VALUE}/api/tags" >/dev/null 2>&1; then
    echo "✅ Ollama is healthy"
  else
    echo "⚠️ Ollama health endpoint check failed: ${OLLAMA_BASE_URL_VALUE}/api/tags"
  fi
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
echo "Ollama: ${OLLAMA_BASE_URL_VALUE}"

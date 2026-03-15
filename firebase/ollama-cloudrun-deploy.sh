#!/bin/bash

# Deploy Ollama as a separate Cloud Run service for backend LLM fallback.
# Usage:
#   export GCLOUD_SERVICE_ACCOUNT_KEY='{"type":"service_account",...}'
#   export OLLAMA_MODEL='llama3.1:8b'   # optional, defaults to llama3.1:8b
#   ./firebase/ollama-cloudrun-deploy.sh

set -e

PROJECT_ID="billingonaire"
REGION="asia-south1"
SERVICE_NAME="billingonaire-ollama"
SERVICE_ACCOUNT="firebase-adminsdk-t0k85@billingonaire.iam.gserviceaccount.com"
OLLAMA_MODEL="${OLLAMA_MODEL:-llama3.1:8b}"

if [ -z "$GCLOUD_SERVICE_ACCOUNT_KEY" ]; then
  echo "❌ Error: GCLOUD_SERVICE_ACCOUNT_KEY environment variable not set"
  echo "Please set it with your service account JSON key"
  exit 1
fi

echo "🔐 Authenticating with Google Cloud..."
echo "$GCLOUD_SERVICE_ACCOUNT_KEY" > /tmp/gcloud-key.json
gcloud auth activate-service-account --key-file=/tmp/gcloud-key.json
gcloud config set project "$PROJECT_ID"

echo "🚀 Deploying Ollama service to Cloud Run..."
echo "ℹ️  Model to preload: $OLLAMA_MODEL"

gcloud run deploy "$SERVICE_NAME" \
  --image=ollama/ollama:latest \
  --region="$REGION" \
  --platform=managed \
  --allow-unauthenticated \
  --memory=8Gi \
  --cpu=4 \
  --timeout=900s \
  --max-instances=1 \
  --min-instances=1 \
  --service-account="$SERVICE_ACCOUNT" \
  --set-env-vars="OLLAMA_MODEL=$OLLAMA_MODEL" \
  --command="/bin/sh" \
  --args="-c,ollama serve & sleep 5; ollama pull ${OLLAMA_MODEL}; wait"

OLLAMA_URL=$(gcloud run services describe "$SERVICE_NAME" --region="$REGION" --format='value(status.url)')

rm /tmp/gcloud-key.json

echo "✅ Ollama deployment complete"
echo "🌐 Ollama URL: $OLLAMA_URL"
echo "➡️  Set backend OLLAMA_BASE_URL=$OLLAMA_URL (backend deploy script now auto-detects this service)."

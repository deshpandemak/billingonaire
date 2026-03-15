#!/bin/bash

# Deploy Ollama as a separate Cloud Run service for backend LLM fallback.
# Usage:
#   export GCLOUD_SERVICE_ACCOUNT_KEY='{"type":"service_account",...}'
#   export OLLAMA_MODEL='llama3.1:8b'   # optional, defaults to llama3.1:8b
#   ./firebase/ollama-cloudrun-deploy.sh

set -e

PROJECT_ID="${PROJECT_ID:-billingonaire}"
REGION="${REGION:-asia-south1}"
SERVICE_NAME="${OLLAMA_SERVICE_NAME:-billingonaire-ollama}"
SERVICE_ACCOUNT="${OLLAMA_SERVICE_ACCOUNT:-firebase-adminsdk-t0k85@billingonaire.iam.gserviceaccount.com}"
OLLAMA_MODEL="${OLLAMA_MODEL:-llama3.1:8b}"

echo "ℹ️  Deploy target: project=$PROJECT_ID region=$REGION service=$SERVICE_NAME"

if [ -n "$GCLOUD_SERVICE_ACCOUNT_KEY" ]; then
  echo "🔐 Authenticating with Google Cloud using provided service account key..."
  echo "$GCLOUD_SERVICE_ACCOUNT_KEY" > /tmp/gcloud-key.json
  gcloud auth activate-service-account --key-file=/tmp/gcloud-key.json
else
  echo "ℹ️  GCLOUD_SERVICE_ACCOUNT_KEY not provided; using existing gcloud auth context"
fi

gcloud config set project "$PROJECT_ID"

echo "🚀 Deploying Ollama service to Cloud Run..."
echo "ℹ️  Model to preload: $OLLAMA_MODEL"

gcloud run deploy "$SERVICE_NAME" \
  --image=ollama/ollama:latest \
  --region="$REGION" \
  --platform=managed \
  --port=11434 \
  --allow-unauthenticated \
  --memory=8Gi \
  --cpu=4 \
  --timeout=900s \
  --max-instances=1 \
  --min-instances=1 \
  --service-account="$SERVICE_ACCOUNT" \
  --set-env-vars="OLLAMA_MODEL=$OLLAMA_MODEL,OLLAMA_HOST=0.0.0.0:11434" \
  --command="/bin/sh" \
  --args="-c,ollama serve"

OLLAMA_URL=$(gcloud run services describe "$SERVICE_NAME" --region="$REGION" --format='value(status.url)')

# Best-effort model warm-up after service is reachable.
echo "⏳ Waiting for Ollama API readiness at $OLLAMA_URL/api/tags"
READY=false
for i in $(seq 1 40); do
  if curl -sSf "$OLLAMA_URL/api/tags" >/dev/null 2>&1; then
    READY=true
    break
  fi
  sleep 3
done

if [ "$READY" = "true" ]; then
  echo "📦 Triggering best-effort model pull for $OLLAMA_MODEL"
  curl -sS -X POST "$OLLAMA_URL/api/pull" \
    -H "Content-Type: application/json" \
    -d "{\"model\":\"$OLLAMA_MODEL\",\"stream\":false}" \
    >/tmp/ollama-pull-response.json || true
else
  echo "⚠️ Ollama API readiness timed out; model pull skipped"
fi

if [ -f /tmp/gcloud-key.json ]; then
  rm /tmp/gcloud-key.json
fi

echo "✅ Ollama deployment complete"
echo "🌐 Ollama URL: $OLLAMA_URL"
echo "➡️  Set backend OLLAMA_BASE_URL=$OLLAMA_URL (backend deploy script now auto-detects this service)."

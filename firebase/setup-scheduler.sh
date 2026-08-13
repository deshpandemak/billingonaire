#!/bin/bash

# One-time setup for the Cloud Scheduler keep-alive tick.
#
# Why this exists: the backend deploys with --min-instances=0, and the
# fetch/analyse poll loops (main.py's fetch_poll_loop/analysis_poll_loop)
# only run while a Cloud Run instance is alive. /queue/status already
# opportunistically wakes the loops on every request it handles, which
# covers "someone has the Dashboard open" -- but with --min-instances=0 and
# no other traffic, Cloud Run scales to zero and the backlog stops draining
# entirely, no matter how full the queue is or how good the auto-refill
# logic (_query_claim_candidates's backlog tier) is once an instance is
# actually up to run it.
#
# This script creates:
#   1. A SCHEDULER_SHARED_SECRET in Secret Manager (generated if not
#      supplied), granted to the Cloud Run runtime service account.
#   2. A Cloud Scheduler job that POSTs to /internal/queue/tick every 5
#      minutes with that secret in the X-Scheduler-Secret header.
#
# /internal/queue/tick is deliberately NOT gated by the app's normal
# require_admin dependency -- Cloud Scheduler has no way to hold an
# application user's Firebase ID token, only a service-account identity --
# so it uses a shared-secret header instead (main.py's
# _SCHEDULER_SHARED_SECRET / scheduler_queue_tick).
#
# Run once, then redeploy the backend (./firebase/backend-cloudrun-deploy.sh)
# so the secret actually gets mounted into the running service.
#
# Usage:
#   ./firebase/setup-scheduler.sh
#   SCHEDULER_SHARED_SECRET=<your-own-secret> ./firebase/setup-scheduler.sh
#   TICK_INTERVAL_MINUTES=10 ./firebase/setup-scheduler.sh

set -e

PROJECT_ID="billingonaire"
REGION="asia-south1"
SERVICE_ACCOUNT="firebase-adminsdk-t0k85@billingonaire.iam.gserviceaccount.com"
CLOUD_RUN_SERVICE="billingonaire-backend"
SCHEDULER_JOB="billingonaire-queue-tick"
TICK_INTERVAL_MINUTES="${TICK_INTERVAL_MINUTES:-5}"

echo "🕐 Setting up the Cloud Scheduler keep-alive tick"
echo "=================================================="

gcloud config set project "$PROJECT_ID"

echo "📡 Enabling Cloud Scheduler API..."
gcloud services enable cloudscheduler.googleapis.com

# Generate a secret if the caller didn't supply one.
if [ -z "$SCHEDULER_SHARED_SECRET" ]; then
  echo "🎲 No SCHEDULER_SHARED_SECRET supplied -- generating one."
  SCHEDULER_SHARED_SECRET="$(openssl rand -hex 32)"
fi

if gcloud secrets describe SCHEDULER_SHARED_SECRET >/dev/null 2>&1; then
  echo "🔄 Adding new version to SCHEDULER_SHARED_SECRET"
  echo "$SCHEDULER_SHARED_SECRET" | gcloud secrets versions add SCHEDULER_SHARED_SECRET --data-file=-
else
  echo "🔑 Creating SCHEDULER_SHARED_SECRET secret..."
  echo "$SCHEDULER_SHARED_SECRET" | gcloud secrets create SCHEDULER_SHARED_SECRET --data-file=-
fi

echo "🔒 Granting secret access to service account..."
gcloud secrets add-iam-policy-binding SCHEDULER_SHARED_SECRET \
  --member="serviceAccount:$SERVICE_ACCOUNT" \
  --role="roles/secretmanager.secretAccessor"

BACKEND_URL=$(gcloud run services describe "$CLOUD_RUN_SERVICE" --region="$REGION" --format='value(status.url)')
if [ -z "$BACKEND_URL" ]; then
  echo "❌ Error: could not resolve the Cloud Run service URL. Deploy the"
  echo "   backend first with ./firebase/backend-cloudrun-deploy.sh"
  exit 1
fi

echo "⏱  Creating/updating the Cloud Scheduler job (every ${TICK_INTERVAL_MINUTES} min)..."
if gcloud scheduler jobs describe "$SCHEDULER_JOB" --location="$REGION" >/dev/null 2>&1; then
  gcloud scheduler jobs update http "$SCHEDULER_JOB" \
    --location="$REGION" \
    --schedule="*/${TICK_INTERVAL_MINUTES} * * * *" \
    --uri="${BACKEND_URL}/internal/queue/tick" \
    --http-method=POST \
    --update-headers="X-Scheduler-Secret=${SCHEDULER_SHARED_SECRET}"
else
  gcloud scheduler jobs create http "$SCHEDULER_JOB" \
    --location="$REGION" \
    --schedule="*/${TICK_INTERVAL_MINUTES} * * * *" \
    --uri="${BACKEND_URL}/internal/queue/tick" \
    --http-method=POST \
    --headers="X-Scheduler-Secret=${SCHEDULER_SHARED_SECRET}" \
    --attempt-deadline=30s
fi

echo ""
echo "✅ Cloud Scheduler keep-alive tick configured!"
echo ""
echo "⚠️  IMPORTANT: the secret is created, but the running Cloud Run service"
echo "   doesn't have it yet. Redeploy the backend so it gets mounted:"
echo "   ./firebase/backend-cloudrun-deploy.sh"
echo ""
echo "   Verify afterwards with:"
echo "   gcloud scheduler jobs run $SCHEDULER_JOB --location=$REGION"

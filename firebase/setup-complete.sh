#!/bin/bash

# Comprehensive setup for secrets and deployment configuration
# Run this script to set up all necessary secrets and permissions

set -e

PROJECT_ID="billingonaire"
SERVICE_ACCOUNT="firebase-adminsdk-t0k85@billingonaire.iam.gserviceaccount.com"
REGION="asia-south1"

echo "🔧 Billingonaire Cloud Run Setup & Configuration"
echo "==============================================="

# Check prerequisites
if [ -z "$GCLOUD_SERVICE_ACCOUNT_KEY" ]; then
  echo "❌ Error: GCLOUD_SERVICE_ACCOUNT_KEY environment variable not set"
  echo "Please set it with your Firebase service account JSON key"
  exit 1
fi

# Set project
gcloud config set project $PROJECT_ID

# Enable required APIs
echo "📡 Enabling required Google Cloud APIs..."
gcloud services enable cloudbuild.googleapis.com
gcloud services enable run.googleapis.com
gcloud services enable secretmanager.googleapis.com

# Verify service account exists
echo "🔍 Verifying service account..."
if ! gcloud iam service-accounts describe $SERVICE_ACCOUNT >/dev/null 2>&1; then
  echo "❌ Service account $SERVICE_ACCOUNT not found"
  echo "Please ensure the Firebase service account is created"
  exit 1
fi

# Create secret if it doesn't exist
echo "🔐 Setting up Secret Manager..."
if ! gcloud secrets describe GCLOUD_SERVICE_ACCOUNT_KEY >/dev/null 2>&1; then
  echo "🔑 Creating GCLOUD_SERVICE_ACCOUNT_KEY secret..."
  echo "$GCLOUD_SERVICE_ACCOUNT_KEY" | gcloud secrets create GCLOUD_SERVICE_ACCOUNT_KEY --data-file=-
  echo "✅ Secret created successfully"
else
  echo "✅ GCLOUD_SERVICE_ACCOUNT_KEY secret already exists"
fi

# Grant permissions
echo "🔒 Setting up IAM permissions..."

# Grant secret access
gcloud secrets add-iam-policy-binding GCLOUD_SERVICE_ACCOUNT_KEY \
  --member="serviceAccount:$SERVICE_ACCOUNT" \
  --role="roles/secretmanager.secretAccessor" || echo "⚠️ Secret access binding may already exist"

# Ensure service account has necessary roles
echo "🛡️ Ensuring service account has required roles..."

# Required roles for Cloud Run and Firebase
REQUIRED_ROLES=(
  "roles/firebase.admin"
  "roles/datastore.user"
  "roles/secretmanager.secretAccessor"
)

for role in "${REQUIRED_ROLES[@]}"; do
  gcloud projects add-iam-policy-binding $PROJECT_ID \
    --member="serviceAccount:$SERVICE_ACCOUNT" \
    --role="$role" || echo "⚠️ Role $role may already be assigned"
done

echo ""
echo "✅ Setup complete!"
echo ""
echo "🚀 Next steps:"
echo "1. Deploy using: ./firebase/backend-cloudrun-deploy.sh"
echo "2. Or use GitHub Actions CD pipeline"
echo ""
echo "📋 Configuration summary:"
echo "   Project: $PROJECT_ID"
echo "   Region: $REGION" 
echo "   Service Account: $SERVICE_ACCOUNT"
echo "   Secret: GCLOUD_SERVICE_ACCOUNT_KEY (configured)"
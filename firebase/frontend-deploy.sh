#!/bin/bash

# Exit on error
set -e

# Get Firebase token from environment or file
FIREBASE_TOKEN="${FIREBASE_TOKEN:-$(cat firebase/firebasetoken 2>/dev/null)}"

if [ -z "$FIREBASE_TOKEN" ]; then
  echo "❌ Error: FIREBASE_TOKEN not found"
  echo "Please set FIREBASE_TOKEN environment variable or ensure firebase/firebasetoken exists"
  exit 1
fi

# Navigate to the frontend directory
cd ../billingonaire-ui

# Install dependencies
echo "📦 Installing dependencies..."
npm ci || npm install

# Build the frontend
echo "🔨 Building frontend..."
npm run build

# Navigate back to root for Firebase deployment
cd ..

# Deploy the frontend to Firebase hosting
echo "🚀 Deploying frontend to Firebase Hosting..."
firebase deploy --only hosting --token "$FIREBASE_TOKEN"

echo "✅ Frontend deployment complete!"

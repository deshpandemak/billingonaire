#!/bin/bash

# Navigate to the frontend directory
cd ../billingonaire-ui

# Build the frontend
npm run build

# Navigate back to root for Firebase deployment
cd ..

# Deploy the frontend to Firebase hosting
firebase deploy --only hosting

#!/bin/bash

# Navigate to the frontend directory
cd ../billingonaire-ui

# Build the frontend
npm run build

# Deploy the frontend to Firebase
firebase deploy --only hosting:frontend

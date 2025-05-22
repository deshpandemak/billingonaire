#!/bin/bash

# Navigate to the backend directory
cd ../billingonaire-backend

# Deploy the backend to Firebase
# firebase deploy --only functions:backend
gcloud functions deploy billingonaire-backend \
  --gen2 \
  --runtime=python312 \
  --region=asia-south1 \
  --source=. \
  --entry-point=handler \
  --trigger-http \
  --allow-unauthenticated \
  --memory=1024MB \
  --timeout=540s \
  --env-vars-file=env.yaml \
  --service-account=firebase-adminsdk-t0k85@billingonaire.iam.gserviceaccount.com

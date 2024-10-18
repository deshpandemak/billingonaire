#!/bin/bash

# Navigate to the backend directory
cd ../billingonaire-backend

# Deploy the backend to Firebase
firebase deploy --only functions:backend

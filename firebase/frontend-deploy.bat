@echo off

REM Navigate to the billingonaire-ui directory
cd ../billingonaire-ui

REM Build the frontend
npm run build

REM Deploy the frontend to Firebase
firebase deploy --only hosting:frontend

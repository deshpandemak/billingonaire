@echo off
REM Navigate to the backend directory
cd ../billingonaire-backend

REM Deploy the backend to Firebase
firebase deploy --only functions:backend

# Billingonaire - Professional Legal Billing Management System

## Overview
Billingonaire is a professional legal billing management system that processes daily board PDF files, extracts AGP assignments, fetches court orders, and generates comprehensive billing analytics. The application now features a beautiful, modern UI with a complete React frontend and FastAPI backend.

## Project Structure
- **Backend**: Python FastAPI application in `billingonaire-backend/`
- **Frontend**: Professional React application in `billingonaire-ui/` with modern design system
- **Database**: Firebase Firestore
- **Authentication**: Firebase Auth with ID token verification

## Professional UI Features
- **Landing Page**: Beautiful gradient hero section with feature showcase
- **Modern Design System**: Professional CSS theme with legal-themed colors and typography
- **Responsive Navigation**: Clean navigation with active states and user-friendly UX
- **Professional Login**: Modern login page with enhanced styling and loading states
- **Dashboard**: Cards-based layout with professional tables and data visualization
- **Consistent Theming**: Professional color palette and spacing throughout

## Current Setup
- **Frontend**: Professional React app running on port 5000 with Vite
- **Backend**: FastAPI server running on port 8000 with Uvicorn
- **Language**: Python 3.11 and Node.js installed
- **Package Manager**: npm for frontend, pip for backend

## Workflows
1. **Frontend**: `cd billingonaire-ui && npm run dev` (port 5000)
2. **Backend**: `cd billingonaire-backend && uvicorn main:app --host localhost --port 8000 --reload` (port 8000)

## Configuration Applied
- ✅ Vite configured with proper API proxy and rewrite rules
- ✅ CORS configured for cross-origin requests
- ✅ Professional CSS design system with modern components
- ✅ API routing fixed for proper frontend-backend communication
- ✅ Firebase authentication with ID token verification
- ✅ Responsive design for all screen sizes

## Key Features
- **PDF Processing**: Upload and parse daily court board files
- **AGP Management**: Track Assistant Government Pleader assignments
- **Unified Search & Order Management**: Search cases, download court orders, and analyze them all from one interface
- **Court Order Integration**: Automated order download from Bombay High Court with ML-powered analysis
- **Analytics Dashboard**: Weekly status, AGP statistics, and monthly averages
- **Professional Authentication**: Secure Firebase-based user management
- **Modern UI/UX**: Beautiful, responsive interface designed for legal professionals

## Technology Stack
- **Frontend**: React 18, Vite, React Router, React Bootstrap, Custom CSS
- **Backend**: FastAPI, Python 3.11, Firebase Admin SDK
- **Database**: Firebase Firestore
- **Authentication**: Firebase Auth
- **Styling**: Professional CSS design system with legal theme

## Production Deployment ✅
**Application is live and deployed to production!**

### Production URLs
- **Frontend**: https://billingonaire.web.app (Firebase Hosting)
- **Backend**: https://billingonaire-backend-819125105651.asia-south1.run.app (Google Cloud Run)

### Deployment Architecture
- **Frontend**: React app built with Vite and deployed to Firebase Hosting
- **Backend**: FastAPI server containerized and deployed to Google Cloud Run
- **Database**: Firebase Firestore (shared between dev and production)
- **Authentication**: Firebase Auth with ID token verification

### Deployment Commands
```bash
# Deploy Backend to Cloud Run
cd billingonaire-backend
gcloud builds submit --tag gcr.io/billingonaire/billingonaire-backend .
gcloud run deploy billingonaire-backend \
  --image=gcr.io/billingonaire/billingonaire-backend:latest \
  --region=asia-south1 \
  --allow-unauthenticated \
  --platform=managed \
  --service-account=firebase-adminsdk-t0k85@billingonaire.iam.gserviceaccount.com \
  --timeout=300 \
  --cpu=1 \
  --memory=1Gi \
  --port=8080

# Deploy Frontend to Firebase Hosting
cd billingonaire-ui
npm run build
firebase deploy --only hosting --token "$FIREBASE_TOKEN"
```

### Environment Configuration
- **Development**: Uses `/api` proxy (Vite dev server) pointing to localhost:8000
- **Production**: Uses `VITE_API_URL` environment variable pointing to Cloud Run backend
- **Environment Files**:
  - `.env.development`: `VITE_API_URL=/api`
  - `.env.production`: `VITE_API_URL=https://billingonaire-backend-819125105651.asia-south1.run.app`

## API Integration
- **Development**: Vite proxy configured to handle `/api/*` requests to localhost:8000
- **Production**: Direct HTTPS calls to Cloud Run backend URL
- **Authentication**: Firebase ID tokens passed in Authorization header
- **RESTful API**: Endpoints for dashboard data, file processing, order management, and bill generation

## Recent Updates (Sept 30, 2025)
### Order Management Consolidation
- **Unified Interface**: Consolidated separate order management screens into single "Search & Orders" interface
- **Inline Actions**: Users can now download orders, view PDFs, analyze, all from search results table
- **Enhanced UX**: Eliminated need to navigate between multiple screens for order operations
- **Backend Endpoints**: Added `/auto-orders/process-case` and `/auto-orders/analyze-case/{case_id}` for single-case operations
- **Navigation**: Redirect `/order-center` → `/table` for seamless user experience

### Batch Operations Toolbar (Latest)
- **Toolbar Buttons**: Added "Download Selected Orders" and "Delete Selected" buttons above the AG Grid table
- **Multi-Select**: Users can now select multiple rows and perform batch operations
- **Space Optimization**: Removed individual delete button column, freeing up horizontal space for data columns
- **Better UX**: Toolbar shows selection count and enables/disables buttons based on selection
- **Confirmation Prompts**: Safe batch operations with confirmation dialogs showing operation summary

### ML Order Analysis Improvements (Sept 30, 2025)
- **Enhanced "HEARD & ADJOURNED" Detection**: Added 15+ new patterns for detecting hearings including:
  - "On hearing", "Upon hearing", "Having heard" phrases
  - Counsel submission/appearance patterns (e.g., "learned counsel submits", "AGP appears")
  - Court observations (e.g., "court observes that", "considering the submissions")
  - Document review indicators (e.g., "perused the papers")
- **Improved Scoring Logic**: Weighted scoring gives higher priority to hearing indicators (2.0x-2.5x weight)
- **Lower Classification Threshold**: Reduced from 70% to 50% for preferring "HEARD & ADJOURNED" over "ADJOURNED"
- **Better Accuracy**: System now correctly identifies hearings even without explicit "heard and adjourned" text
- **AGP + Standover Rule (Oct 2, 2025)**: When AGP names are present AND order contains "stand over", automatically categorizes as "HEARD & ADJOURNED" instead of "ADJOURNED" (business logic enhancement)

### Order Date Validation & Retry Logic (Sept 30, 2025)
- **Intelligent Retry System**: Automatically tries up to 50 sequence numbers (1-50) to find order with matching date
- **Date Matching Enforcement**: Orders are only linked to cases when order date matches board date
- **Pre-Link Validation**: Order date is validated BEFORE creating the order link in database
- **Smart Date Extraction**: Enhanced date parsing handles formats like "DATE : 24 JULY 2024" and returns YYYY-MM-DD
- **Comprehensive Logging**: Tracks each retry attempt with status (download_failed, date_mismatch, success)
- **Clear Failure Messages**: Reports "No matching order found after 50 attempts" when no match exists
- **Process Flow**: For each sequence (1-50): Download → Extract Date → Validate → Link if Match → Stop, else Continue
- **Auto Cleanup on Failure**: If a case has existing order data and download fails after 50 attempts, automatically removes old order data to keep database clean

### Data Display Optimization (Sept 30, 2025)
- **AGP Names from Board Data**: Shows all AGPs from board data (respondent_lawyer + additional_respondent_lawyers)
- **Existing Columns Enhanced**: Court Order, Petitioner, and Respondent columns now display order analysis data
- **Smart Fallback**: Shows ML-extracted party names when available, falls back to board data otherwise
- **Clickable Order Links**: Court Order column displays "View Order" link when order is available
- **No New Columns**: Maximized table space by reusing existing columns for additional data

### Critical Fixes
- ✅ Fixed Firestore serialization error with CaseInfo dataclass objects
- ✅ Fixed order link visibility by updating both case-orders and daily-boards collections
- ✅ Fixed filtering logic to properly check order_downloaded flag in case documents
- ✅ AG Grid framework components properly registered for custom cell renderers
- ✅ Fixed backend search index serialization error with party name dictionaries
- ✅ Enhanced error handling with detailed user feedback for order operations
- ✅ AG Grid row height and column width optimizations for better button display
- ✅ Fixed AG Grid SetFilter error by using TextColumnFilter for Court Order column

## Latest Updates (Sept 30, 2025 - Final)
### Automatic Cleanup on Download Failure
- **Cleanup Triggers on Any Failure**: When order download fails and case has existing order data, automatically removes all stale data
- **Database Consistency**: Deletes order document, clears all order fields from daily-boards, removes search index
- **Smart Detection**: Identifies cases with existing orders and cleans them up after 50 failed download attempts

### Enhanced Data Display
- **Dual Source Petitioner/Respondent**: Columns check both `order_cases` (from order table) and `order_petitioners/order_respondents` (from ML text extraction)
- **Fallback Logic**: If case table extraction is empty, displays names extracted from order body text
- **Analyze Button**: For orders downloaded before auto-analysis, manual "Analyze" button appears to trigger analysis

### Production Deployment (Oct 2, 2025)
- ✅ Backend successfully deployed to Google Cloud Run
- ✅ Frontend successfully deployed to Firebase Hosting
- ✅ Environment variables configured for production API endpoint
- ✅ Lazy loading pattern implemented for all heavy objects to prevent startup timeouts
- ✅ Direct Docker image deployment (avoiding Cloud Functions wrapper)
- ✅ CORS and authentication properly configured for cross-origin requests

## Status
✅ Professional UI transformation completed with modern design
✅ Unified order management interface fully operational
✅ All components successfully configured and running in Replit environment
✅ API routing and authentication working correctly
✅ Responsive design optimized for legal professionals
✅ **Successfully deployed to production and live!**
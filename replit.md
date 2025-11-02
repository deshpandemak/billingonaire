# Billingonaire - Professional Legal Billing Management System

## Overview
Billingonaire is a professional legal billing management system for the legal industry. It automates the processing of daily court board PDF files, extracts AGP (Assistant Government Pleader) assignments, fetches relevant court orders, and generates comprehensive billing analytics. The system aims to streamline legal billing and case management through advanced automation and a user-friendly interface, enhancing efficiency and accuracy for legal professionals.

## User Preferences
I prefer detailed explanations.
I want iterative development.
Ask before making major changes.
I like clean, readable code with good comments.
I prefer to be informed about the implications of changes.
Do not make changes to the folder `Z`.
Do not make changes to the file `Y`.

## System Architecture
Billingonaire features a modern web application architecture with a React frontend and a FastAPI backend.

- **UI/UX Decisions**: Professional UI with a modern design system, legal-themed colors, typography, a responsive landing page, navigation, login, and a cards-based dashboard.
- **Technical Implementations**:
    - **PDF Processing**: Upload and parsing of daily court board files.
    - **AGP Management**: Tracking and management of Assistant Government Pleader assignments with AI/ML fuzzy name matching for consolidation and normalization of AGP names across dashboards and statistics.
    - **Unified Search & Order Management**: Single interface for searching cases, downloading court orders, and analysis. Includes an intelligent retry system for order date validation and automatic cleanup for failed downloads. Enhanced search filtering supports order category (ADJOURNED, HEARD_AND_ADJOURNED, DISPOSED_OFF) and status, utilizing hybrid server-side and client-side filtering to optimize for Firestore index limitations.
    - **Court Order Integration**: Automated order download from the Bombay High Court with ML-powered analysis, including enhanced "HEARD & ADJOURNED" detection and improved scoring.
    - **Multi-Case Order Linking**: Automatic detection and linking of orders to multiple clubbed cases.
    - **Analytics Dashboard**: Provides weekly status, AGP statistics, and monthly averages, utilizing fuzzy name matching for consistent AGP reporting.
    - **Authentication**: Secure Firebase-based user management with ID token verification.
    - **Admin Order Management System**: Dashboard (`/admin/orders`) for tracking the 5-state lifecycle of orders (`not_linked`, `order_linked`, `analysed`, `order_failed`, `order_analysis_failed`), with real-time status, live queue monitoring, and bulk processing controls.
    - **Async Background Processing**: Concurrent order processing with configurable worker pools using ThreadPoolExecutor for blocking operations. Queue processing is optimized to prevent premature timeouts.
    - **Data Display Optimization**: AGP names from board data, enhanced columns for order analysis, and petitioner/respondent names derived from dual extraction from order case tables and body text.
    - **Bill Generation with Role-Based Access Control & Enhanced Fuzzy Name Matching**: Comprehensive bill generation workflow with role-based access. Non-admins generate bills for their cases; admins for any user. Intelligent AI/ML fuzzy name matching (50% confidence threshold) maps user names to AGP names from board data, supporting initials, spelling variations, compound names, and title removal. Fee calculation based on order analysis categories. Includes a unique, transaction-safe bill numbering system (BILL/YEAR/SEQUENCE) and an AGP-compliant Excel export format with detailed headers, specific column structure (Case Type, Case No, Case Year), and styling. User management exclusively uses full_name with fuzzy matching.
- **System Design Choices**:
    - **Frontend**: React 18, Vite, React Router, React Bootstrap, Custom CSS (port 5000).
    - **Backend**: Python 3.11 FastAPI server, Uvicorn (port 8000).
    - **Database**: Firebase Firestore.
    - **Authentication**: Firebase Auth.
    - **Deployment**: Frontend on Firebase Hosting, backend containerized on Google Cloud Run. Lazy loading for heavy objects.
    - **API Integration**: RESTful API with Vite proxy for development, direct HTTPS calls to Cloud Run for production. Firebase ID tokens for authorization.
    - **Testing Infrastructure**: CI/CD with flake8 and ESLint. Playwright e2e tests exist (require Firebase emulator setup).

## External Dependencies
- **Firebase**: Firestore (database), Firebase Auth (authentication), Firebase Admin SDK (backend integration), Firebase Hosting (frontend deployment).
- **Google Cloud Run**: Backend deployment and hosting.
- **Bombay High Court Website**: Source for automated court order downloads.

## Recent Changes

### November 2, 2025 - Flattened Order Data Structure
- **Restructured Order Analysis Storage**: Changed from array-based `order_cases[]` to **flattened structure** where each case's order analysis data is stored directly in its daily-board document
- **Field Naming Standardization**: Renamed `order_agp_names` to `government_pleader` throughout the entire codebase for consistency
- **Multi-Case Order Handling**: When processing orders with multiple clubbed cases, each case now gets its own flattened data (order_petitioner, order_respondent, government_pleader) in its respective daily-board entry
- **Data Structure Changes**:
  - OLD: `order_cases: [{petitioner, respondent, government_pleader}, ...]`
  - NEW: Direct fields `order_petitioner` (string), `order_respondent` (string), `government_pleader` (array)
- **Bill Generation Priority**: `government_pleader` (order analysis) → `respondent_lawyer` (board data) → `additional_respondent_lawyers` (board data)
- **Files Updated**: AutoOrderManager.py, main.py, UserMatterMatcher.py

### October 31, 2025 - ML Categorization Enhancements
- **Absolute DISPOSED_OFF Priority**: Any disposal indicators now trigger immediate DISPOSED_OFF classification
- **Enhanced Disposal Patterns**: Added detection for "case is closed", "contempt case closed", "petition allowed/granted", "relief granted"
- **Aggressive HEARD_AND_ADJOURNED Detection**: Lowered threshold to 30% of ADJOURNED score for better hearing detection
- **Comprehensive Diagnostic Logging**: Added detailed pattern matching logs showing scores, matched patterns, and classification decisions
- **Bug Fix**: Fixed AttributeError in AutoOrderManager (case_number.zfill() without str() conversion)
- **Bug Fix**: Fixed IA(ST) case parsing by moving (ST) suffix stripping before regex parsing

### Production Deployment Status
**Last Deployed**: October 31, 2025  
**Production URLs**:
- Frontend: https://billingonaire.web.app
- Backend: https://billingonaire-backend-819125105651.asia-south1.run.app

**Deployment Method**: Manual deployment via `firebase/deploy-all.sh` script (updated to use service account authentication instead of deprecated FIREBASE_TOKEN)
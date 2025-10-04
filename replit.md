# Billingonaire - Professional Legal Billing Management System

## Overview
Billingonaire is a professional legal billing management system designed for the legal industry. It automates the processing of daily court board PDF files, extracts AGP (Assistant Government Pleader) assignments, fetches relevant court orders, and generates comprehensive billing analytics. The system aims to streamline legal billing and case management through advanced automation and a user-friendly interface, enhancing efficiency and accuracy for legal professionals.

## User Preferences
I prefer detailed explanations.
I want iterative development.
Ask before making major changes.
I like clean, readable code with good comments.
I prefer to be informed about the implications of changes.
Do not make changes to the folder `Z`.
Do not make changes to the file `Y`.

## System Architecture
Billingonaire features a modern web application architecture consisting of a React frontend and a FastAPI backend.
- **UI/UX Decisions**: The application boasts a professional UI with a modern design system, legal-themed colors, and typography. It includes a beautiful landing page, responsive navigation, a modern login page, and a cards-based dashboard layout. The theming is consistent throughout, optimized for legal professionals.
- **Technical Implementations**:
    - **PDF Processing**: Upload and parsing of daily court board files.
    - **AGP Management**: Tracking and management of Assistant Government Pleader assignments.
    - **Unified Search & Order Management**: A single interface for searching cases, downloading court orders, and conducting analysis. This includes an intelligent retry system for order date validation and an automatic cleanup mechanism for failed downloads. **Enhanced Search Filtering (October 4, 2025)**: Added order category filtering (ADJOURNED, HEARD_AND_ADJOURNED, DISPOSED_OFF) and fixed order status filtering by implementing hybrid filtering to work around Firestore's composite index limitations. All filters (advocate name, order status, order category) use intelligent server-side filtering when possible (no date range), and automatically switch to client-side filtering when combined with date ranges to avoid Firestore index requirements. This ensures all filter combinations work correctly without requiring database index creation.
    - **Court Order Integration**: Automated order download from the Bombay High Court with ML-powered analysis, including enhanced "HEARD & ADJOURNED" detection and improved scoring logic.
    - **Multi-Case Order Linking**: Automatic detection and linking of orders to multiple clubbed cases based on extracted case numbers and normalized formats.
    - **Analytics Dashboard**: Provides weekly status, AGP statistics, and monthly averages. **AI/ML Fuzzy Name Matching (October 4, 2025)**: Implemented intelligent fuzzy name matching with 85% similarity threshold to automatically group and consolidate similar AGP name variations in all dashboard statistics. The system normalizes names (removes titles like SHRI, SMT, AGP, ADDL, GP), uses SequenceMatcher for similarity scoring, and selects the most frequent variant as the canonical name. Applied across all aggregation functions: AGP stats, monthly averages, and matter distributions.
    - **Authentication**: Secure Firebase-based user management with ID token verification.
    - **Admin Order Management System**: A dedicated admin dashboard (`/admin/orders`) for tracking the 5-state lifecycle of orders (`not_linked`, `order_linked`, `analysed`, `order_failed`, `order_analysis_failed`). It includes real-time status overview, live queue monitoring, and bulk processing controls with customizable filters (status, date range, limits).
    - **Async Background Processing**: Concurrent order processing with configurable worker pool (default 3 workers, configurable via ORDER_PROCESSING_WORKERS env var). Uses ThreadPoolExecutor for blocking HTTP operations to prevent event loop blocking. Multiple worker tasks process cases in parallel for improved throughput. **Queue Processing Optimization (October 4, 2025)**: Removed 30-second timeout from order_processing_queue.get() to prevent queue appearing empty instantly. Background worker now blocks indefinitely until work arrives, while maintaining 5-minute timeout only for individual case processing to prevent hanging on problematic cases.
    - **Data Display Optimization**: AGP names are sourced from board data, and existing columns are enhanced to display order analysis data. Petitioner and respondent party names are always derived from order analysis, utilizing dual extraction from both order case tables and body text.
    - **Bill Generation with Role-Based Access Control & Enhanced Fuzzy Name Matching**: Comprehensive bill generation workflow where non-admin users can only generate bills for their own assigned cases, while admins can generate bills for any user. The system features an intelligent AI/ML-powered fuzzy name matching system with 50% confidence threshold that maps user names from the system to AGP names in board data. The enhanced matching algorithm handles: (1) Initials and permutations (e.g., "Pooja Makarand Joshi Deshpande" matches "SMT.P.M.JOSHI,AGP"), (2) Spelling variations in last names (e.g., "Pabale" matches "PABLE" with 83% similarity), (3) Compound last names (checks AGP last name against all user name words), (4) Removes common titles (SHRI, SMT, AGP, ADDL, GP) for better matching. Scoring weights: last name 35%, initials 25%, full words 25%, sequence 15%. When confidence is below 50%, returns detailed error with best match candidate. User dropdown shows active system users (from users collection). Fee calculation based on order analysis (ADJOURNED: ₹1,250, HEARD & ADJN.: ₹1,875, DISPOSED: ₹2,500). **User Management Refactoring (October 4, 2025)**: Removed deprecated agp_names field from entire system. User management now exclusively uses full_name with fuzzy matching. Role display updated from "AGP user" to "User". Bill generation uses user_name parameter. New /admin/active-users endpoint provides user list. Frontend uses user-centric state (userList, selectedUser). Legacy agp_names fields in database are ignored.
- **System Design Choices**:
    - **Frontend**: React 18, Vite, React Router, React Bootstrap, Custom CSS. Runs on port 5000.
    - **Backend**: Python 3.11 FastAPI server, Uvicorn. Runs on port 8000.
    - **Database**: Firebase Firestore.
    - **Authentication**: Firebase Auth.
    - **Deployment**: Frontend is deployed to Firebase Hosting, and the backend is containerized and deployed to Google Cloud Run. Lazy loading is implemented for heavy objects to prevent startup timeouts.
    - **API Integration**: RESTful API with Vite proxy for development and direct HTTPS calls to Cloud Run for production. Firebase ID tokens are used for authorization.
    - **Testing Infrastructure (October 4, 2025)**: Comprehensive CI/CD testing pipeline with frontend unit tests (Vitest) and backend unit tests (pytest). Frontend tests use simplified smoke tests to avoid React hook conflicts. Backend tests cover AutoOrderManager functionality including date validation and case reference parsing. Test configuration excludes Playwright e2e tests from Vitest runs to prevent conflicts.

## External Dependencies
- **Firebase**: Firestore (database), Firebase Auth (authentication), Firebase Admin SDK (backend integration), Firebase Hosting (frontend deployment).
- **Google Cloud Run**: Backend deployment and hosting.
- **Bombay High Court Website**: Source for automated court order downloads.
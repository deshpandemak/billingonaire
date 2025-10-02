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
    - **Unified Search & Order Management**: A single interface for searching cases, downloading court orders, and conducting analysis. This includes an intelligent retry system for order date validation and an automatic cleanup mechanism for failed downloads.
    - **Court Order Integration**: Automated order download from the Bombay High Court with ML-powered analysis, including enhanced "HEARD & ADJOURNED" detection and improved scoring logic.
    - **Multi-Case Order Linking**: Automatic detection and linking of orders to multiple clubbed cases based on extracted case numbers and normalized formats.
    - **Analytics Dashboard**: Provides weekly status, AGP statistics, and monthly averages.
    - **Authentication**: Secure Firebase-based user management with ID token verification.
    - **Admin Order Management System**: A dedicated admin dashboard (`/admin/orders`) for tracking the 5-state lifecycle of orders (`not_linked`, `order_linked`, `analysed`, `order_failed`, `order_analysis_failed`). It includes real-time status overview, live queue monitoring, and bulk processing controls with customizable filters (status, date range, limits).
    - **Async Background Processing**: Concurrent order processing with configurable worker pool (default 3 workers, configurable via ORDER_PROCESSING_WORKERS env var). Uses ThreadPoolExecutor for blocking HTTP operations to prevent event loop blocking. Multiple worker tasks process cases in parallel for improved throughput.
    - **Data Display Optimization**: AGP names are sourced from board data, and existing columns are enhanced to display order analysis data. Petitioner and respondent party names are always derived from order analysis, utilizing dual extraction from both order case tables and body text.
- **System Design Choices**:
    - **Frontend**: React 18, Vite, React Router, React Bootstrap, Custom CSS. Runs on port 5000.
    - **Backend**: Python 3.11 FastAPI server, Uvicorn. Runs on port 8000.
    - **Database**: Firebase Firestore.
    - **Authentication**: Firebase Auth.
    - **Deployment**: Frontend is deployed to Firebase Hosting, and the backend is containerized and deployed to Google Cloud Run. Lazy loading is implemented for heavy objects to prevent startup timeouts.
    - **API Integration**: RESTful API with Vite proxy for development and direct HTTPS calls to Cloud Run for production. Firebase ID tokens are used for authorization.

## External Dependencies
- **Firebase**: Firestore (database), Firebase Auth (authentication), Firebase Admin SDK (backend integration), Firebase Hosting (frontend deployment).
- **Google Cloud Run**: Backend deployment and hosting.
- **Bombay High Court Website**: Source for automated court order downloads.
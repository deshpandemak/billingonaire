# Billingonaire - Replit Project Documentation

## Overview
Billingonaire is a billing management system that consists of a FastAPI backend with Firebase integration and a SvelteKit frontend. The application enables PDF document processing, data management, and user authentication through Firebase.

## Project Structure
- **Backend**: Python FastAPI application in `billingonaire-backend/`
- **Frontend**: SvelteKit application in `billingonaire-ui/` (also has React alternative in `src-react/`)
- **Database**: Firebase Firestore
- **Authentication**: Firebase Auth

## Current Setup
- **Frontend**: Running on port 5000 with Svelte/Vite
- **Backend**: Running on port 8000 with FastAPI/Uvicorn
- **Language**: Python 3.11 installed
- **Package Manager**: npm for frontend, pip for backend

## Workflows
1. **Frontend**: `cd billingonaire-ui && npm run dev` (port 5000)
2. **Backend**: `cd billingonaire-backend && uvicorn main:app --host localhost --port 8000 --reload` (port 8000)

## Configuration Applied
- Vite configured to allow all hosts (0.0.0.0:5000) for Replit proxy
- CORS configured to allow Replit domain and localhost connections
- CSS import order fixed for Tailwind and font imports
- Missing root route created for SvelteKit

## Features
- User authentication with Firebase
- PDF upload and processing
- Data visualization and management
- Dashboard with statistics
- Responsive web interface

## Deployment
Configured for VM deployment with both frontend and backend running simultaneously.

## Environment Variables
- `VITE_BACKEND_URL`: Set to http://localhost:8000

## Status
✅ All components successfully configured and running in Replit environment
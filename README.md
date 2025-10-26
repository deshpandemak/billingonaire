# Billingonaire - Legal Billing Management System

A professional legal billing management system designed for the legal industry. Automates processing of daily court board PDF files, extracts AGP assignments, fetches court orders, and generates comprehensive billing analytics.

## 🚀 Production URLs

- **Frontend**: https://billingonaire.web.app
- **Backend API**: https://billingonaire-backend-819125105651.asia-south1.run.app

## 📁 Project Structure

```
billingonaire/
├── billingonaire_backend/     # FastAPI backend
│   ├── main.py               # Main API server
│   ├── Board.py              # PDF parsing and board management
│   ├── requirements.txt      # Python dependencies
│   └── tests/               # Backend tests
├── billingonaire-ui/         # React frontend (Vite)
│   ├── src/                 # React components
│   ├── package.json         # Node dependencies
│   └── vite.config.js       # Vite configuration
├── firebase/                # Deployment scripts
│   ├── deploy-all.sh        # Deploy both frontend and backend
│   ├── backend-cloudrun-deploy.sh
│   └── frontend-deploy.sh
└── .github/workflows/       # CI/CD pipelines
```

## 🛠️ Local Development

### Backend Setup

1. Navigate to backend directory:
```bash
cd billingonaire_backend
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Run development server:
```bash
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

4. Access API documentation:
- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

### Frontend Setup

1. Navigate to frontend directory:
```bash
cd billingonaire-ui
```

2. Install dependencies:
```bash
npm install
```

3. Run development server:
```bash
npm run dev
```

4. Access application: http://localhost:5000

## 🚢 Production Deployment

### Deploy Both (Recommended)

```bash
./firebase/deploy-all.sh
```

This script:
- Builds and deploys backend to Google Cloud Run
- Builds and deploys frontend to Firebase Hosting

### Deploy Backend Only

```bash
./firebase/backend-cloudrun-deploy.sh
```

### Deploy Frontend Only

```bash
./firebase/frontend-deploy.sh
```

### Environment Variables Required

- `GCLOUD_SERVICE_ACCOUNT_KEY`: Google Cloud service account credentials
- `FIREBASE_TOKEN`: Firebase deployment token

## 🧪 Testing

### Backend Tests

```bash
cd billingonaire_backend
pytest tests/
```

### Frontend Tests

```bash
cd billingonaire-ui
npm run test:unit
```

## 🔑 Key Features

- **PDF Processing**: Automated parsing of daily court board files
- **Order Management**: Download and analysis of court orders with ML
- **Bill Generation**: Professional AGP-compliant Excel bill export
- **Analytics Dashboard**: Weekly status, AGP statistics, monthly averages
- **Role-Based Access**: Admin and user permissions
- **Firebase Authentication**: Secure user management

## 📚 Tech Stack

- **Frontend**: React 18, Vite, React Bootstrap
- **Backend**: Python 3.11, FastAPI, Uvicorn
- **Database**: Firebase Firestore
- **Authentication**: Firebase Auth
- **Deployment**: Google Cloud Run (backend), Firebase Hosting (frontend)
- **CI/CD**: GitHub Actions

## 📝 Documentation

For detailed project architecture and recent changes, see `replit.md`.

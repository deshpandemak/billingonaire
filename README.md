# billingonaire

## Repository Structure

The repository is structured as follows:

```
billingonaire/
├── billingonaire-backend/
│   ├── main.py
│   ├── requirements.txt
│   ├── .gitignore
├── billingonaire-ui/
│   ├── <frontend files and directories>
├── .gitignore
├── README.md
```

## Running the FastAPI Application

To run the FastAPI application, follow these steps:

1. Navigate to the `billingonaire-backend` directory:

```bash
cd billingonaire-backend
```

2. Install the required dependencies:

```bash
pip install -r requirements.txt
```

3. Start the FastAPI application using Uvicorn:

```bash
uvicorn main:app --reload
```

The FastAPI application will be running at `http://127.0.0.1:8000`.

## Backend Deployment

To deploy the backend, follow these steps:

1. Navigate to the `billingonaire-backend` directory:

```bash
cd billingonaire-backend
```

2. Install the required dependencies:

```bash
pip install -r requirements.txt
```

3. Deploy the backend using the deployment script:

```bash
../firebase/backend-deploy.sh
```

## Frontend Deployment

To deploy the frontend, follow these steps:

1. Navigate to the `billingonaire-ui` directory:

```bash
cd billingonaire-ui
```

2. Install the required dependencies:

```bash
npm install
```

3. Build the frontend:

```bash
npm run build
```

4. Deploy the frontend using the deployment script:

```bash
../firebase/frontend-deploy.sh
```

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
import functions_framework
from fastapi import FastAPI, File, UploadFile, Depends, Request, HTTPException, Form, Query
import pandas as pd
from fastapi.responses import RedirectResponse, JSONResponse
import logging
from fastapi.middleware.cors import CORSMiddleware
from Board import Board
from Dashboard import DashboardData
from firebase_admin import auth, firestore, credentials
import firebase_admin
import re
import asyncio
import socket
from mangum import Mangum
from fastapi.testclient import TestClient
from typing import List

app = FastAPI(
    title="Billingonaire API",
    description="API for Billingonaire application",
    version="1.0.0",
    openapi_tags=[
        {"name": "Root", "description": "Root endpoint"},
        {"name": "PDF Upload", "description": "Upload PDF and extract data"},
        {"name": "Data Retrieval", "description": "Retrieve stored data"},
        {"name": "Authentication", "description": "User authentication"},
        {"name": "Case Status", "description": "Retrieve case status from Bombay High Court"},
        {"name": "Case Orders", "description": "Retrieve case orders from Bombay High Court"}
    ]
)

cred = credentials.Certificate("./firebase/credentials.json")
firebase_admin.initialize_app(cred)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://billingonaire.web.app",
        "http://localhost:5173",
        "http://localhost:5174"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def get_session(request: Request):
    session_token = request.cookies.get("session")
    if not session_token:
        return None
    return session_token

def require_login(session_token: str = Depends(get_session)):
    if not session_token:
        return RedirectResponse(url="/login")

@app.post("/login", tags=["Authentication"])
async def login(request: Request):
    data = await request.json()
    email = data.get("email")
    password = data.get("password")

    logging.debug(f"Login attempt for email: {email}")

    try:
        user = auth.get_user_by_email(email)
        auth.verify_password(password, user.password_hash)
        
        db = firestore.client()
        doc_ref = db.collection("roles").document(user.uid)
        doc = doc_ref.get()
        if doc.exists:
            user_role = doc.to_dict().get("role")
        else:
            user_role = "user"
        
        auth.set_custom_user_claims(user.uid, {"role": user_role})
        
        session_cookie = auth.create_session_cookie(user.uid)
        response = JSONResponse(content={"message": "Login successful"})
        response.set_cookie(key="session", value=session_cookie, httponly=True)
        logging.info(f"Login successful for email: {email}")
        return response
    except Exception as e:
        logging.error(f"Login failed for email: {email}, error: {str(e)}")
        raise HTTPException(status_code=400, detail="Invalid credentials")

@app.post("/logout", tags=["Authentication"])
async def logout(request: Request):
    response = JSONResponse(content={"message": "Logout successful"})
    response.delete_cookie("session")
    return response

@app.get("/", tags=["Root"], dependencies=[Depends(require_login)])
async def read_root():
    return {"message": "Hello, World!"}

@app.post("/upload-pdf", tags=["PDF Upload"], dependencies=[Depends(require_login)])
async def upload_pdf(files: List[UploadFile] = File(...)):
    results = []
    for file in files:
        if file.content_type != "application/pdf":
            results.append({"filename": file.filename, "error": "Invalid file type. Only PDF files are allowed."})
            continue
        max_retries = 3
        for attempt in range(max_retries):
            try:
                board = Board()
                df = board.readFile(file.filename, file.file)
                record_count = len(df) if df is not None else 0
                board.saveData(df)
                results.append({
                    "filename": file.filename,
                    "message": "Data saved successfully",
                    "records_processed": record_count
                })
                break
            except ConnectionResetError as e:
                logging.error(f"ConnectionResetError on attempt {attempt + 1}: {str(e)}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(1)
                    continue
                else:
                    results.append({"filename": file.filename, "error": "Connection was reset by the remote host. Please try again later."})
                    break
            except Exception as e:
                results.append({"filename": file.filename, "error": str(e)})
                break
    return {"results": results}

@app.post("/save-data", tags=["PDF Upload"], dependencies=[Depends(require_login)])
async def save_data(data: dict):
    try:
        board = Board()
        df = pd.DataFrame(data['data'])
        board.saveData(df)
        return {"message": "Data saved successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/get-data", tags=["Data Retrieval"], dependencies=[Depends(require_login)])
async def get_data(request: Request):
    try:
        search_criteria = await request.json()
        board = Board()
        data = board.getData(search_criteria)
        return data
    except Exception as e:
        raise HTTPException(status_code=500, detail=(str(e)))

client = TestClient(app)

app.include_router(dashboard_router)

@functions_framework.http
def handler(request):
    # Map the incoming request to FastAPI using TestClient
    method = request.method
    path = request.path
    headers = dict(request.headers)
    data = request.get_data()
    # Forward the request to FastAPI app
    response = client.request(method, path, headers=headers, data=data)
    return (response.content, response.status_code, response.headers.items())

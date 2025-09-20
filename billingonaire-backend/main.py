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
from CourtScraper import BombayHighCourtScraper
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
        "http://localhost:5000",
        "http://localhost:5173",
        "http://localhost:5174",
        "https://2856c3cf-582f-4f2b-a0f3-cae6a5c3b647-00-5mlgokfyfmx.pike.replit.dev",
        "http://2856c3cf-582f-4f2b-a0f3-cae6a5c3b647-00-5mlgokfyfmx.pike.replit.dev"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def get_current_user(request: Request):
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid authentication token")
    
    id_token = auth_header.split("Bearer ")[1]
    
    try:
        # Verify the Firebase ID token
        decoded_token = auth.verify_id_token(id_token)
        return decoded_token
    except Exception as e:
        raise HTTPException(status_code=401, detail="Invalid authentication token")

# Login/logout endpoints removed - using Firebase client-side authentication

@app.get("/", tags=["Root"])
async def read_root():
    return {"message": "Hello, World!"}

@app.post("/upload-pdf", tags=["PDF Upload"])
async def upload_pdf(files: List[UploadFile] = File(...), current_user = Depends(get_current_user)):
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

@app.post("/save-data", tags=["PDF Upload"])
async def save_data(data: dict, current_user = Depends(get_current_user)):
    try:
        board = Board()
        df = pd.DataFrame(data['data'])
        board.saveData(df)
        return {"message": "Data saved successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/get-data", tags=["Data Retrieval"])
async def get_data(request: Request, current_user = Depends(get_current_user)):
    try:
        search_criteria = await request.json()
        board = Board()
        data = board.getData(search_criteria)
        return data
    except Exception as e:
        raise HTTPException(status_code=500, detail=(str(e)))

@app.get("/debug/simple-db-check")
async def simple_database_check():
    try:
        board = Board()
        
        # Get all documents
        all_docs = list(board.db.collection("daily-boards").limit(10).stream())
        
        # Get sample documents
        sample_docs = []
        case_years_found = []
        
        for doc in all_docs:
            doc_data = doc.to_dict()
            case_year = doc_data.get('case_year')
            case_years_found.append(case_year)
            
            # Convert datetime to string for JSON serialization
            if 'board_date' in doc_data and hasattr(doc_data['board_date'], 'strftime'):
                doc_data['board_date'] = doc_data['board_date'].strftime('%Y-%m-%d')
            
            sample_docs.append({
                "document_id": doc.id,
                "case_year": case_year,
                "case_year_type": str(type(case_year)),
                "board_date": doc_data.get('board_date'),
                "all_fields": list(doc_data.keys())
            })
        
        # Test query for case_year = "2025"
        test_query = board.db.collection("daily-boards").where(filter=firestore.FieldFilter("case_year", "==", "2025"))
        test_results = list(test_query.stream())
        
        return {
            "total_documents": len(all_docs),
            "case_years_found": case_years_found,
            "test_query_for_2025_results": len(test_results),
            "sample_documents": sample_docs[:3],
            "database_status": "connected" if all_docs else "empty"
        }
    except Exception as e:
        return {"error": str(e), "database_status": "error"}

# Dashboard endpoints (with authentication)
dashboard_data = DashboardData()

@app.get("/dashboard/weekly-status")
async def dashboard_weekly_status(start_date: str = Query(None), end_date: str = Query(None), current_user = Depends(get_current_user)):
    data = await dashboard_data.get_weekly_status(start_date, end_date)
    return JSONResponse(content=data)

@app.get("/dashboard/agp-stats")
async def dashboard_agp_stats(agp_name: str = Query(None), current_user = Depends(get_current_user)):
    data = await dashboard_data.get_agp_stats(agp_name)
    return JSONResponse(content=data)

@app.get("/dashboard/monthly-avg")
async def dashboard_monthly_avg(year: str = Query(None), current_user = Depends(get_current_user)):
    data = await dashboard_data.get_monthly_avg(year)
    return JSONResponse(content=data)

# Court integration endpoints
court_scraper = BombayHighCourtScraper()

@app.get("/court/case-details", tags=["Case Status"])
async def get_case_details(
    case_ref: str = Query(..., description="Case reference like 'WP/294/2025'"),
    bench: str = Query("mumbai", description="Court bench: mumbai, aurangabad, nagpur, goa"),
    current_user = Depends(get_current_user)
):
    """
    Fetch case details from Bombay High Court
    Example: /court/case-details?case_ref=WP/294/2025&bench=mumbai
    """
    try:
        case_details = court_scraper.get_case_details(case_ref, bench)
        return JSONResponse(content=case_details)
    except Exception as e:
        logging.error(f"Error fetching case details for {case_ref}: {e}")
        return JSONResponse(
            status_code=500,
            content={"error": f"Failed to fetch case details: {str(e)}", "case_ref": case_ref}
        )

@app.get("/court/case-orders", tags=["Case Orders"])
async def get_case_orders(
    case_ref: str = Query(..., description="Case reference like 'WP/294/2025'"),
    date: str = Query(None, description="Specific date in YYYY-MM-DD format"),
    bench: str = Query("mumbai", description="Court bench: mumbai, aurangabad, nagpur, goa"),
    current_user = Depends(get_current_user)
):
    """
    Fetch case orders from Bombay High Court for a specific case and date
    Example: /court/case-orders?case_ref=WP/294/2025&date=2025-01-03
    """
    try:
        case_orders = court_scraper.get_case_orders(case_ref, date, bench)
        return JSONResponse(content={"case_ref": case_ref, "date": date, "orders": case_orders})
    except Exception as e:
        logging.error(f"Error fetching case orders for {case_ref}: {e}")
        return JSONResponse(
            status_code=500,
            content={"error": f"Failed to fetch case orders: {str(e)}", "case_ref": case_ref}
        )

@app.post("/court/batch-case-lookup", tags=["Case Status"])
async def batch_case_lookup(
    case_refs: List[str],
    bench: str = Query("mumbai", description="Court bench: mumbai, aurangabad, nagpur, goa"),
    current_user = Depends(get_current_user)
):
    """
    Fetch case details for multiple cases in batch
    Useful for getting court data for multiple cases from your billing records
    """
    try:
        results = []
        for case_ref in case_refs:
            case_details = court_scraper.get_case_details(case_ref, bench)
            results.append({
                "case_ref": case_ref,
                "details": case_details,
                "timestamp": pd.Timestamp.now().isoformat()
            })
        
        return JSONResponse(content={
            "total_cases": len(case_refs),
            "results": results,
            "bench": bench
        })
    except Exception as e:
        logging.error(f"Error in batch case lookup: {e}")
        return JSONResponse(
            status_code=500,
            content={"error": f"Batch lookup failed: {str(e)}", "total_cases": len(case_refs)}
        )

client = TestClient(app)

@functions_framework.http
def handler(request):
    # Map the incoming request to FastAPI using TestClient
    method = request.method
    path = request.path
    
    # Preserve query string for serverless deployment
    if request.query_string:
        path = f"{path}?{request.query_string.decode()}"
    
    headers = dict(request.headers)
    data = request.get_data()
    # Forward the request to FastAPI app
    response = client.request(method, path, headers=headers, data=data)
    return (response.content, response.status_code, response.headers.items())

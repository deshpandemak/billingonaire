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
from OrderManager import OrderManager
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
        {"name": "Case Orders", "description": "Retrieve case orders from Bombay High Court"},
        {"name": "Order Management", "description": "Manage court order linking and states"}
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
        # Verify the Firebase ID token with more detailed error logging
        logging.info(f"Attempting to verify ID token: {id_token[:20]}...")
        decoded_token = auth.verify_id_token(id_token)
        logging.info(f"Token verified successfully for user: {decoded_token.get('uid')}")
        return decoded_token
    except Exception as e:
        logging.error(f"Token verification failed: {str(e)}")
        logging.error(f"Token details: {id_token[:50]}...")
        raise HTTPException(status_code=401, detail=f"Invalid authentication token: {str(e)}")

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
                logging.info(f"Starting upload processing for file: {file.filename}")
                board = Board()
                df = board.readFile(file.filename, file.file)
                record_count = len(df) if df is not None else 0
                logging.info(f"PDF processed successfully. Records found: {record_count}")
                
                if record_count > 0:
                    board.saveData(df)
                    logging.info(f"Data saved successfully for {file.filename}")
                    results.append({
                        "filename": file.filename,
                        "message": "Data saved successfully",
                        "records_processed": record_count
                    })
                else:
                    logging.warning(f"No records found in {file.filename}")
                    results.append({
                        "filename": file.filename,
                        "message": "No records found in PDF",
                        "records_processed": 0
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
                logging.error(f"Error processing {file.filename}: {str(e)}")
                logging.error("Stack trace:", exc_info=True)
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

@app.get("/debug/auth-test")
async def auth_test(current_user = Depends(get_current_user)):
    return {"message": "Authentication successful", "user_id": current_user.get('uid')}

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
        test_query = board.db.collection("daily-boards").where("case_year", "==", "2025")
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
order_manager = OrderManager()

@app.get("/court/case-details", tags=["Case Status"])
async def get_case_details(
    case_ref: str = Query(..., description="Case reference like 'WP/294/2025'"),
    bench: str = Query("mumbai", description="Court bench: mumbai, mumbai_appellate, aurangabad, nagpur, goa"),
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
    bench: str = Query("mumbai", description="Court bench: mumbai, mumbai_appellate, aurangabad, nagpur, goa"),
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
    bench: str = Query("mumbai", description="Court bench: mumbai, mumbai_appellate, aurangabad, nagpur, goa"),
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

# Order Management endpoints
@app.get("/orders/cases-without-orders", tags=["Order Management"])
async def get_cases_without_orders(
    limit: int = Query(100, description="Number of cases to return"),
    offset: int = Query(0, description="Pagination offset"),
    current_user = Depends(get_current_user)
):
    """
    Get cases from board data that don't have linked orders
    Used for order management interface
    """
    try:
        result = order_manager.get_cases_without_orders(limit, offset)
        return JSONResponse(content=result)
    except Exception as e:
        logging.error(f"Error fetching cases without orders: {e}")
        return JSONResponse(
            status_code=500,
            content={"error": f"Failed to fetch cases: {str(e)}"}
        )

@app.post("/orders/create-link", tags=["Order Management"])
async def create_order_link(
    request: Request,
    current_user = Depends(get_current_user)
):
    """
    Create or update an order link for a case
    Body should contain: case_id, status, order_link, order_text, court_bench, notes
    """
    try:
        order_data = await request.json()
        case_id = order_data.get("case_id")
        
        if not case_id:
            return JSONResponse(
                status_code=400,
                content={"error": "case_id is required"}
            )
        
        result = order_manager.create_order_link(case_id, order_data)
        return JSONResponse(content=result)
    except Exception as e:
        logging.error(f"Error creating order link: {e}")
        return JSONResponse(
            status_code=500,
            content={"error": f"Failed to create order link: {str(e)}"}
        )

@app.put("/orders/update-status", tags=["Order Management"])
async def update_order_status(
    case_id: str = Query(..., description="Case document ID"),
    status: str = Query(..., description="Order status: linked, failed, manually_uploaded, not_present"),
    notes: str = Query("", description="Optional notes"),
    current_user = Depends(get_current_user)
):
    """Update the status of an order"""
    try:
        result = order_manager.update_order_status(case_id, status, notes)
        return JSONResponse(content=result)
    except Exception as e:
        logging.error(f"Error updating order status: {e}")
        return JSONResponse(
            status_code=500,
            content={"error": f"Failed to update status: {str(e)}"}
        )

@app.get("/orders/by-status", tags=["Order Management"])
async def get_orders_by_status(
    status: str = Query(..., description="Order status to filter by"),
    limit: int = Query(100, description="Maximum number of orders"),
    current_user = Depends(get_current_user)
):
    """Get all orders with a specific status"""
    try:
        orders = order_manager.get_orders_by_status(status, limit)
        return JSONResponse(content={"orders": orders, "count": len(orders)})
    except Exception as e:
        logging.error(f"Error fetching orders by status: {e}")
        return JSONResponse(
            status_code=500,
            content={"error": f"Failed to fetch orders: {str(e)}"}
        )

@app.get("/orders/case-details/{case_id}", tags=["Order Management"])
async def get_case_with_order_info(
    case_id: str,
    current_user = Depends(get_current_user)
):
    """Get complete case information including order status"""
    try:
        result = order_manager.get_case_with_order_info(case_id)
        return JSONResponse(content=result)
    except Exception as e:
        logging.error(f"Error fetching case with order info: {e}")
        return JSONResponse(
            status_code=500,
            content={"error": f"Failed to fetch case details: {str(e)}"}
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

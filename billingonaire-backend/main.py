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
from UserManager import UserManager
from order_analyzer import OrderDocumentAnalyzer
from AutoOrderManager import AutoOrderManager
from UserMatterMatcher import UserMatterMatcher, UserRole, MatterMatch
from firebase_admin import auth, firestore, credentials
import firebase_admin
import re
import asyncio
import socket
from mangum import Mangum
from fastapi.testclient import TestClient
from typing import List, Dict
from datetime import datetime
from asyncio import Queue
import json

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
        {"name": "Order Management", "description": "Manage court order linking and states"},
        {"name": "Order Analysis", "description": "ML-powered analysis of court order documents"},
        {"name": "Queue Management", "description": "Monitor async order processing queue"},
        {"name": "User Matter Mapping", "description": "Link users to their legal matters using AI-powered name matching"}
    ]
)

# Startup event to initialize background processing
@app.on_event("startup")
async def startup_event():
    """Initialize background order processing on app startup"""
    logging.info("🚀 Billingonaire API starting up...")
    try:
        await ensure_background_processing_active()
        logging.info("✅ Background order processing initialized")
    except Exception as e:
        logging.error(f"❌ Failed to initialize background processing: {e}")

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

user_manager = UserManager()
order_analyzer = OrderDocumentAnalyzer()
auto_order_manager = AutoOrderManager()
user_matter_matcher = UserMatterMatcher()

# In-memory queue for async order processing
order_processing_queue = Queue()
processing_active = False

def get_current_user(request: Request):
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid authentication token")
    
    id_token = auth_header.split("Bearer ")[1]
    
    try:
        # Verify the Firebase ID token with more detailed error logging
        logging.info(f"Attempting to verify ID token for authentication")
        decoded_token = auth.verify_id_token(id_token)
        logging.info(f"Token verified successfully for user: {decoded_token.get('uid')}")
        return decoded_token
    except Exception as e:
        logging.error(f"Token verification failed: {str(e)}")
        # SECURITY: Do not log token details to prevent leakage
        raise HTTPException(status_code=401, detail="Invalid authentication token")

def require_active_user(current_user: dict = Depends(get_current_user)):
    """Dependency to require active user account"""
    uid = current_user.get('uid')
    profile = user_manager.get_user_profile(uid)
    
    if not profile.get('is_active', True):
        raise HTTPException(status_code=403, detail="Account is disabled. Contact administrator.")
    
    return {**current_user, 'profile': profile}

def get_user_with_profile(current_user: dict = Depends(require_active_user)):
    """Dependency to get current user with profile (active users only)"""
    return current_user

def require_admin(current_user: dict = Depends(get_current_user)):
    """Dependency to require admin role"""
    if not user_manager.is_admin(current_user.get('uid')):
        raise HTTPException(status_code=403, detail="Admin access required")
    return current_user

def require_admin_active(current_user: dict = Depends(require_active_user)):
    """Dependency to require active admin user"""
    if not user_manager.is_admin(current_user.get('uid')):
        raise HTTPException(status_code=403, detail="Admin access required")
    return current_user

# Async Order Processing Functions
async def trigger_async_order_processing(df: pd.DataFrame):
    """Add uploaded cases to async order processing queue"""
    try:
        # Extract case information from uploaded board data
        records = df.to_dict(orient="records")
        case_list = []
        
        for record in records:
            # Create document ID using same scheme as Board.saveData
            formatted_date = record['board_date']
            if isinstance(formatted_date, str):
                formatted_date = datetime.strptime(formatted_date, '%Y-%m-%d').strftime('%Y-%m-%d')
            else:
                formatted_date = formatted_date.strftime('%Y-%m-%d')
            
            document_id = f"{formatted_date}-{record['case_type']}-{record['case_no']}-{record['case_year']}"
            
            # Create case info for queue processing - include 'id' field for AutoOrderManager
            case_info = {
                "id": document_id,  # Firestore document ID that AutoOrderManager expects
                "case_id": document_id,  # For backward compatibility
                "case_ref": f"{record['case_type']}/{record['case_no']}/{record['case_year']}",
                "case_type": record['case_type'],
                "case_no": record['case_no'],
                "case_year": record['case_year'],
                "board_date": record['board_date'],
                "petitioner_lawyer": record.get('petitioner_lawyer'),
                "respondent_lawyer": record.get('respondent_lawyer')
            }
            case_list.append(case_info)
        
        # Add cases to processing queue
        for case_info in case_list:
            await order_processing_queue.put(case_info)
            logging.info(f"Added case {case_info['case_ref']} to order processing queue")
        
        # Start background processing if not already active
        await ensure_background_processing_active()
        
    except Exception as e:
        logging.error(f"Error adding cases to processing queue: {e}")

async def process_order_queue():
    """Background worker to process order queue"""
    global processing_active
    processing_active = True
    
    logging.info("🚀 Order processing background worker started")
    
    while True:
        try:
            # Get case from queue (wait up to 30 seconds)
            case_info = await asyncio.wait_for(order_processing_queue.get(), timeout=30.0)
            
            logging.info(f"📋 Processing order for case: {case_info['case_ref']} (ID: {case_info.get('id', 'unknown')})")
            
            # Use AutoOrderManager to process single case
            try:
                result = auto_order_manager._process_single_case(case_info)
                
                if result.get("analysis_success"):
                    logging.info(f"✅ Successfully processed order for {case_info['case_ref']} - Analysis completed and data updated in daily-boards")
                    
                    # Automatically map case to users after successful analysis
                    try:
                        await auto_map_case_to_users(case_info.get('id'), case_info)
                        logging.info(f"✅ Successfully mapped case {case_info['case_ref']} to users")
                    except Exception as mapping_error:
                        logging.error(f"❌ Error mapping case {case_info['case_ref']} to users: {mapping_error}")
                        
                elif result.get("download_success"):
                    logging.warning(f"⚠️ Order downloaded but analysis failed for {case_info['case_ref']}: {result.get('error', 'Unknown error')}")
                else:
                    logging.warning(f"⚠️ Order processing failed for {case_info['case_ref']}: {result.get('error', 'Unknown error')}")
            
            except Exception as e:
                logging.error(f"❌ Error processing order for {case_info['case_ref']}: {e}")
                import traceback
                logging.error(f"Full traceback: {traceback.format_exc()}")
            
            # Mark task as done
            order_processing_queue.task_done()
            
        except asyncio.TimeoutError:
            # No more items in queue, continue waiting
            logging.debug("Queue timeout - waiting for more cases...")
            continue
        except Exception as e:
            logging.error(f"Background order processing error: {e}")
            await asyncio.sleep(5)  # Wait before retrying

async def auto_map_case_to_users(case_id: str, case_info: Dict):
    """Automatically map case to users after order analysis completion"""
    try:
        # Get all users who have configured roles
        users_ref = db.collection('user-roles')
        user_docs = users_ref.stream()
        
        mapped_users = []
        
        for user_doc in user_docs:
            try:
                user_id = user_doc.id
                user_data = user_doc.to_dict()
                
                # Create UserRole object from stored data
                user_role = UserRole(
                    role_type=user_data.get('role_type'),
                    full_name=user_data.get('full_name'),
                    name_variations=user_data.get('name_variations', []),
                    pattern_keywords=user_data.get('pattern_keywords', []),
                    confidence_threshold=user_data.get('confidence_threshold', 0.75)
                )
                
                # Check if this case matches the user
                user_matches = user_matter_matcher.find_user_matters_for_case(user_id, user_role, case_id)
                
                if user_matches:
                    # Store the mapping in user-case-mappings collection
                    for match in user_matches:
                        mapping_data = {
                            'user_id': user_id,
                            'case_id': case_id,
                            'case_ref': case_info.get('case_ref'),
                            'match_source': match.match_source,
                            'match_field': match.match_field,
                            'matched_text': match.matched_text,
                            'confidence_score': match.confidence_score,
                            'role_type': match.role_type,
                            'board_date': match.board_date,
                            'mapped_at': firestore.SERVER_TIMESTAMP,
                            'auto_mapped': True
                        }
                        
                        # Use composite key to prevent duplicates
                        mapping_key = f"{user_id}_{case_id}_{match.match_source}_{match.match_field}"
                        db.collection('user-case-mappings').document(mapping_key).set(mapping_data, merge=True)
                        
                        mapped_users.append({
                            'user_id': user_id,
                            'role_type': user_role.role_type,
                            'confidence': match.confidence_score
                        })
                        
            except Exception as user_error:
                logging.error(f"Error processing user {user_doc.id} for case mapping: {user_error}")
                continue
        
        if mapped_users:
            logging.info(f"Case {case_info.get('case_ref')} mapped to {len(mapped_users)} users: {[u['user_id'] for u in mapped_users]}")
        else:
            logging.info(f"No user matches found for case {case_info.get('case_ref')}")
            
    except Exception as e:
        logging.error(f"Error in auto_map_case_to_users: {e}")
        raise

async def ensure_background_processing_active():
    """Ensure background order processing is running"""
    global processing_active
    
    if not processing_active:
        # Start background task
        asyncio.create_task(process_order_queue())
        logging.info("Started background order processing task")

# Login/logout endpoints removed - using Firebase client-side authentication

@app.get("/", tags=["Root"])
async def read_root():
    return {"message": "Hello, World! 🚀 Billingonaire API is running with async order processing."}

@app.post("/upload-pdf", tags=["PDF Upload"])
async def upload_pdf(files: List[UploadFile] = File(...), current_user = Depends(require_admin)):
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
                    
                    # Trigger async order processing for uploaded cases
                    await trigger_async_order_processing(df)
                    
                    results.append({
                        "filename": file.filename,
                        "message": "Data saved successfully - Order processing started in background",
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
async def save_data(data: dict, current_user = Depends(require_admin)):
    try:
        board = Board()
        df = pd.DataFrame(data['data'])
        board.saveData(df)
        return {"message": "Data saved successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/get-data", tags=["Data Retrieval"])
async def get_data(
    request: Request, 
    current_user_with_profile = Depends(get_user_with_profile)
):
    try:
        search_criteria = await request.json()
        
        
        board = Board()
        
        # SECURITY: Apply AGP filter for non-admin users - strict enforcement
        uid = current_user_with_profile.get('uid')
        agp_filter = user_manager.get_user_agp_filter(uid)  # This will raise 403 if invalid
        
        data = board.getData(search_criteria, agp_filter)
        return data
    except Exception as e:
        logging.error(f"Error in data retrieval: {str(e)}")
        raise HTTPException(status_code=500, detail="Error retrieving data")

@app.get("/debug/auth-test")
async def auth_test(current_user = Depends(get_current_user)):
    return {"message": "Authentication successful", "user_id": current_user.get('uid')}

@app.get("/debug/simple-db-check", tags=["Admin"])
async def simple_database_check(current_user = Depends(require_admin)):
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

# User management endpoints
@app.get("/user/profile", tags=["User Management"])
async def get_user_profile(current_user_with_profile = Depends(get_user_with_profile)):
    """Get current user's profile"""
    return current_user_with_profile['profile']

@app.post("/user/profile", tags=["User Management"])
async def create_or_update_profile(
    profile_data: dict,
    current_user = Depends(get_current_user)
):
    """Create or update user profile (self-service - no role changes)"""
    uid = current_user.get('uid')
    email = current_user.get('email')
    
    # Check if this is the initial admin user
    if email == "deshpande.mak@gmail.com":
        # Create admin profile directly
        return user_manager.create_user_profile(
            uid=uid,
            email=email,
            role='admin',
            agp_names=[],
            full_name=profile_data.get('full_name')
        )
    
    # SECURITY: Remove role and agp_names from self-service updates to prevent privilege escalation
    safe_updates = {
        'full_name': profile_data.get('full_name')
    }
    
    # Check if profile exists
    try:
        existing_profile = user_manager.get_user_profile(uid)
        if existing_profile.get('needs_setup'):
            # For new profiles, create user with legal category (admin will assign AGP later)
            return user_manager.create_user_profile(
                uid=uid,
                email=email,
                role='user',
                legal_category='assistant_government_pleader',
                agp_names=[],  # Start with empty AGP names - admin will assign
                full_name=profile_data.get('full_name')
            )
        else:
            # Update existing profile with safe fields only
            return user_manager.update_user_profile(uid, safe_updates)
    except:
        # Create new profile with user role and legal category
        return user_manager.create_user_profile(
            uid=uid,
            email=email,
            role='user',
            legal_category='assistant_government_pleader',
            agp_names=[],
            full_name=profile_data.get('full_name')
        )

@app.post("/user/change-password", tags=["User Management"])
async def change_password(
    password_data: dict,
    current_user = Depends(get_current_user)
):
    """Change user password"""
    try:
        uid = current_user.get('uid')
        new_password = password_data.get('new_password')
        
        if not new_password or len(new_password) < 6:
            raise HTTPException(status_code=400, detail="Password must be at least 6 characters")
        
        # Update password in Firebase Auth
        auth.update_user(uid, password=new_password)
        
        logging.info(f"Password changed for user {uid}")
        return {"message": "Password changed successfully"}
        
    except Exception as e:
        logging.error(f"Error changing password: {str(e)}")
        raise HTTPException(status_code=500, detail="Error changing password")

@app.get("/admin/users", tags=["Admin"])
async def list_users(
    role_filter: str = Query(None, description="Filter by role: admin or agp"),
    current_user = Depends(require_admin_active)
):
    """List all users (admin only)"""
    return user_manager.list_users(role_filter)


@app.post("/admin/user/{target_uid}/role", tags=["Admin"])
async def update_user_role(
    target_uid: str,
    role_data: dict,
    current_user = Depends(require_admin_active)
):
    """Update user role and AGP assignment (admin only)"""
    admin_uid = current_user.get('uid')
    return user_manager.admin_update_user_profile(target_uid, role_data, admin_uid)

@app.post("/admin/user/{target_uid}/agp-names", tags=["Admin"])
async def assign_agp_names(
    target_uid: str,
    agp_data: dict,
    current_user = Depends(require_admin_active)
):
    """Assign multiple AGP names to a user (admin only)"""
    admin_uid = current_user.get('uid')
    agp_names = agp_data.get('agp_names', [])
    
    # Ensure agp_names is a list
    if isinstance(agp_names, str):
        agp_names = [agp_names]
    
    updates = {'agp_names': agp_names}
    return user_manager.admin_update_user_profile(target_uid, updates, admin_uid)

@app.post("/admin/setup-initial-admin", tags=["Admin"])
async def setup_initial_admin():
    """Set up deshpande.mak@gmail.com as initial administrator"""
    return user_manager.setup_initial_admin()

@app.get("/admin/agp-names", tags=["Admin"])
async def get_all_agp_names_admin(current_user = Depends(require_admin_active)):
    """Get all AGP names in the system (admin only)"""
    return {"agp_names": user_manager.get_agp_names_list()}

@app.get("/admin/available-roles", tags=["Admin"])
async def get_available_roles(current_user = Depends(require_admin_active)):
    """Get available user roles for admin interface"""
    return {"roles": user_manager.get_available_roles()}

@app.get("/admin/available-legal-categories", tags=["Admin"])
async def get_available_legal_categories(current_user = Depends(require_admin_active)):
    """Get available legal categories for admin interface"""
    return {"legal_categories": user_manager.get_available_legal_categories()}

@app.get("/admin/firebase-users", tags=["Admin"])
async def list_firebase_auth_users(current_user = Depends(require_admin_active)):
    """List all users from Firebase Authentication"""
    return user_manager.list_firebase_auth_users()

@app.get("/admin/unsynced-users", tags=["Admin"])
async def get_unsynced_firebase_users(current_user = Depends(require_admin_active)):
    """Get Firebase Auth users that don't have Firestore profiles"""
    return user_manager.get_firebase_auth_users_not_in_firestore()

@app.post("/admin/sync-firebase-users", tags=["Admin"])
async def sync_firebase_users(current_user = Depends(require_admin_active)):
    """Sync Firebase Auth users to Firestore database"""
    uid = current_user.get('uid')
    return user_manager.sync_firebase_users_to_firestore(uid)

@app.post("/admin/create-user", tags=["Admin"])
async def create_new_user(
    user_data: dict,
    current_user = Depends(require_admin_active)
):
    """Create a new user with default password (admin only)"""
    try:
        admin_uid = current_user.get('uid')
        email = user_data.get('email')
        role = user_data.get('role', 'user')
        legal_category = user_data.get('legal_category', 'assistant_government_pleader')
        full_name = user_data.get('full_name', '')
        agp_names = user_data.get('agp_names', [])
        
        if not email:
            raise HTTPException(status_code=400, detail="Email is required")
        
        # Create user in Firebase Auth with default password
        try:
            firebase_user = auth.create_user(
                email=email,
                password="password123",  # Default password
                email_verified=False
            )
            
            # Create user profile in Firestore
            user_profile = user_manager.create_user_profile(
                uid=firebase_user.uid,
                email=email,
                role=role,
                legal_category=legal_category if user_manager.is_legal_professional(role) else None,
                agp_names=agp_names if user_manager.is_legal_professional(role) else [],
                full_name=full_name
            )
            
            logging.info(f"Admin {admin_uid} created new user {email} with role {role}")
            
            return {
                "message": "User created successfully",
                "user": user_profile,
                "default_password": "password123",
                "note": "User should change password on first login"
            }
            
        except auth.EmailAlreadyExistsError:
            raise HTTPException(status_code=400, detail="Email already exists in the system")
        except Exception as e:
            logging.error(f"Error creating Firebase user: {str(e)}")
            raise HTTPException(status_code=500, detail=f"Error creating user account: {str(e)}")
            
    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Error in create_new_user: {str(e)}")
        raise HTTPException(status_code=500, detail="Error creating user")

@app.get("/user/agp-names", tags=["User Management"])
async def get_agp_names(current_user = Depends(get_current_user)):
    """Get list of available AGP names"""
    return {"agp_names": user_manager.get_all_agp_names()}

# Dashboard endpoints (with authentication)
dashboard_data = DashboardData()

@app.get("/dashboard/weekly-status")
async def dashboard_weekly_status(
    start_date: str = Query(None), 
    end_date: str = Query(None), 
    current_user_with_profile = Depends(get_user_with_profile)
):
    # SECURITY: Get AGP filter for the user - strict enforcement
    uid = current_user_with_profile.get('uid')
    agp_filter = user_manager.get_user_agp_filter(uid)  # This will raise 403 if invalid
    
    data = await dashboard_data.get_weekly_status(start_date, end_date, agp_filter)
    return JSONResponse(content=data)

@app.get("/dashboard/agp-stats")
async def dashboard_agp_stats(
    agp_name: str = Query(None), 
    current_user_with_profile = Depends(get_user_with_profile)
):
    # SECURITY: Get AGP filter for the user - strict enforcement
    uid = current_user_with_profile.get('uid')
    agp_filter = user_manager.get_user_agp_filter(uid)  # This will raise 403 if invalid
    
    # For AGP users, use their assigned AGP name; for admins, use query parameter
    target_agp = agp_filter or agp_name
    
    data = await dashboard_data.get_agp_stats(target_agp, agp_filter)
    return JSONResponse(content=data)

@app.get("/dashboard/monthly-avg")
async def dashboard_monthly_avg(
    year: str = Query(None), 
    current_user_with_profile = Depends(get_user_with_profile)
):
    # SECURITY: Get AGP filter for the user - strict enforcement
    uid = current_user_with_profile.get('uid')
    agp_filter = user_manager.get_user_agp_filter(uid)  # This will raise 403 if invalid
    
    data = await dashboard_data.get_monthly_avg(year, agp_filter)
    return JSONResponse(content=data)

@app.get("/dashboard/matters-by-date-range")
async def dashboard_matters_by_date_range(
    start_date: str = Query(None, description="Start date (YYYY-MM-DD) - defaults to last 5 days"),
    end_date: str = Query(None, description="End date (YYYY-MM-DD) - defaults to today"),
    current_user_with_profile = Depends(get_user_with_profile)
):
    """Get total matters by date range with average for bar chart + line visualization"""
    # SECURITY: Get AGP filter for the user - strict enforcement
    uid = current_user_with_profile.get('uid')
    agp_filter = user_manager.get_user_agp_filter(uid)  # This will raise 403 if invalid
    
    data = await dashboard_data.get_matters_by_date_range(start_date, end_date, agp_filter)
    return JSONResponse(content=data)

@app.get("/dashboard/agp-distribution-weekly")
async def dashboard_agp_distribution_weekly(
    current_user_with_profile = Depends(get_user_with_profile)
):
    """Get AGP distribution for current week (Monday to current date)"""
    # SECURITY: Get AGP filter for the user - strict enforcement
    uid = current_user_with_profile.get('uid')
    agp_filter = user_manager.get_user_agp_filter(uid)  # This will raise 403 if invalid
    
    data = await dashboard_data.get_agp_distribution_weekly(agp_filter)
    return JSONResponse(content=data)

@app.get("/dashboard/agp-distribution-monthly")
async def dashboard_agp_distribution_monthly(
    current_user_with_profile = Depends(get_user_with_profile)
):
    """Get AGP distribution for current month to date"""
    # SECURITY: Get AGP filter for the user - strict enforcement
    uid = current_user_with_profile.get('uid')
    agp_filter = user_manager.get_user_agp_filter(uid)  # This will raise 403 if invalid
    
    data = await dashboard_data.get_agp_distribution_monthly(agp_filter)
    return JSONResponse(content=data)

@app.get("/dashboard/agp-distribution-yearly")
async def dashboard_agp_distribution_yearly(
    current_user_with_profile = Depends(get_user_with_profile)
):
    """Get AGP distribution for current year to date"""
    # SECURITY: Get AGP filter for the user - strict enforcement
    uid = current_user_with_profile.get('uid')
    agp_filter = user_manager.get_user_agp_filter(uid)  # This will raise 403 if invalid
    
    data = await dashboard_data.get_agp_distribution_yearly(agp_filter)
    return JSONResponse(content=data)

# ML Enhancement endpoints
@app.get("/ml/status")
async def get_ml_enhancement_status(
    current_user = Depends(get_current_user)
):
    """Get status of ML enhancement capabilities"""
    try:
        board = Board()
        if hasattr(board, 'ml_parser') and board.ml_parser:
            status = board.ml_parser.get_enhancement_status()
            status['ml_parser_available'] = True
            status['message'] = "ML Enhanced Parser is active and improving PDF processing quality"
        else:
            status = {
                'ml_parser_available': False,
                'capabilities': {
                    'enhanced_preprocessing': False,
                    'ner': False,
                    'fuzzy_matching': False,
                    'learning': False,
                    'advanced_fuzzy': False
                },
                'message': "ML Enhanced Parser not available - using standard PDF processing"
            }
        return JSONResponse(content=status)
    except Exception as e:
        logging.error(f"Error fetching ML status: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch ML enhancement status")

@app.post("/ml/learn-from-correction")
async def learn_from_correction(
    correction_data: dict,
    current_user = Depends(get_current_user)
):
    """Allow users to provide corrections for ML learning"""
    try:
        board = Board()
        if hasattr(board, 'ml_parser') and board.ml_parser:
            board.ml_parser.learn_from_correction(
                filename=correction_data.get('filename', ''),
                original_extraction=correction_data.get('original_extraction', ''),
                corrected_extraction=correction_data.get('corrected_extraction', ''),
                user_feedback=correction_data.get('user_feedback', {})
            )
            return JSONResponse(content={"message": "Learning data stored successfully"})
        else:
            return JSONResponse(content={"message": "ML Enhanced Parser not available for learning"})
    except Exception as e:
        logging.error(f"Error storing learning data: {e}")
        raise HTTPException(status_code=500, detail="Failed to store learning data")

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

# ============================================
# ORDER DOCUMENT ANALYSIS ENDPOINTS
# ============================================

@app.post("/analyze-order", tags=["Order Analysis"])
async def analyze_order_document(
    file: UploadFile = File(...),
    current_user = Depends(get_current_user)
):
    """
    Analyze a court order document to extract:
    - Order category (ADJOURNED/HEARD & ADJOURNED/DISPOSED OFF)
    - Petitioner and respondent names
    - AGP names and dates
    - Key phrases and next hearing dates
    """
    try:
        # Validate file type
        if not file.filename.lower().endswith('.pdf'):
            return JSONResponse(
                status_code=400,
                content={"error": "Only PDF files are supported for order analysis"}
            )
        
        # Read file content
        file_content = await file.read()
        
        if len(file_content) == 0:
            return JSONResponse(
                status_code=400,
                content={"error": "Uploaded file is empty"}
            )
        
        logging.info(f"Starting order analysis for file: {file.filename}")
        
        # Analyze the order document
        analysis_result = order_analyzer.analyze_order_document(file.filename, file_content)
        
        # DEBUG: Log the actual category being returned
        logging.info(f"🔍 CATEGORY DEBUG for {file.filename}:")
        logging.info(f"   order_category: '{analysis_result.order_category}'")
        logging.info(f"   category_confidence: {analysis_result.category_confidence}")
        
        # Save analysis result to database
        doc_id = order_analyzer.save_analysis_result(file.filename, analysis_result)
        
        # Prepare enhanced response with structured case information and tabular data
        response_data = {
            "analysis_id": doc_id,
            "filename": file.filename,
            "order_category": analysis_result.order_category,
            "category_confidence": round(analysis_result.category_confidence, 3),
            "order_date": analysis_result.order_date,
            "cases": [
                {
                    "case_number": case.case_number,
                    "petitioners": case.petitioners,
                    "respondents": case.respondents,
                    "agp_names": case.agp_names,
                    "advocates": case.advocates
                }
                for case in analysis_result.cases
            ],
            "document_structure": {
                "type": analysis_result.document_structure.get('document_type', 'UNKNOWN'),
                "has_case_numbers": analysis_result.document_structure.get('has_case_numbers', False),
                "has_parties": analysis_result.document_structure.get('has_parties', False),
                "has_advocates": analysis_result.document_structure.get('has_advocates', False),
                "has_order_date": analysis_result.document_structure.get('has_order_date', False)
            },
            # New tabular format data
            "tabular_data": analysis_result.tabular_data or [],
            # Legacy format for compatibility
            "petitioners": analysis_result.petitioners,
            "respondents": analysis_result.respondents,
            "agp_names": analysis_result.agp_names,
            "dates": analysis_result.dates,
            "key_phrases": analysis_result.key_phrases,
            "next_hearing_date": analysis_result.next_hearing_date,
            "disposal_reason": analysis_result.disposal_reason,
            "summary": {
                "total_cases": len(analysis_result.cases),
                "total_petitioners": len(analysis_result.petitioners),
                "total_respondents": len(analysis_result.respondents),
                "total_agp_names": len(analysis_result.agp_names),
                "total_dates": len(analysis_result.dates)
            }
        }
        
        logging.info(f"Order analysis completed successfully for {file.filename}")
        return JSONResponse(content=response_data)
        
    except HTTPException as he:
        logging.error(f"HTTP error in order analysis: {he.detail}")
        return JSONResponse(
            status_code=he.status_code,
            content={"error": he.detail}
        )
    except Exception as e:
        logging.error(f"Unexpected error in order analysis: {str(e)}")
        return JSONResponse(
            status_code=500,
            content={"error": f"Order analysis failed: {str(e)}"}
        )

@app.get("/analysis-history", tags=["Order Analysis"])
async def get_analysis_history(
    limit: int = Query(50, description="Maximum number of analyses to return"),
    current_user = Depends(get_current_user)
):
    """Get history of order document analyses from consolidated daily-boards"""
    try:
        db = firestore.client()
        
        # Get cases with completed order analysis from daily-boards
        analyses_ref = db.collection('daily-boards').where('order_analysis_completed', '==', True).order_by('order_analysis_timestamp', direction=firestore.Query.DESCENDING).limit(limit)
        docs = analyses_ref.stream()
        
        analyses = []
        for doc in docs:
            board_data = doc.to_dict()
            
            # Extract order analysis data from the board document
            analysis_data = {
                'id': doc.id,
                'case_id': doc.id,
                'case_ref': f"{board_data.get('case_type', '')}/{board_data.get('case_no', '')}/{board_data.get('case_year', '')}",
                'case_type': board_data.get('case_type'),
                'case_no': board_data.get('case_no'),
                'case_year': board_data.get('case_year'),
                'board_date': board_data.get('board_date'),
                'petitioner_lawyer': board_data.get('petitioner_lawyer'),
                'respondent_lawyer': board_data.get('respondent_lawyer'),
                
                # Order analysis results
                'order_category': board_data.get('order_category'),
                'category_confidence': board_data.get('order_category_confidence'),
                'order_date': board_data.get('order_date'),
                'order_petitioners': board_data.get('order_petitioners', []),
                'order_respondents': board_data.get('order_respondents', []),
                'order_agp_names': board_data.get('order_agp_names', []),
                'order_key_phrases': board_data.get('order_key_phrases', []),
                'next_hearing_date': board_data.get('order_next_hearing_date'),
                'disposal_reason': board_data.get('order_disposal_reason'),
                'date_validation': board_data.get('order_date_validation'),
                'order_link': board_data.get('order_link'),
                'analysis_timestamp': board_data.get('order_analysis_timestamp'),
                'order_tabular_data': board_data.get('order_tabular_data', [])
            }
            
            analyses.append(analysis_data)
        
        return JSONResponse(content={
            "analyses": analyses,
            "count": len(analyses),
            "total_fetched": len(analyses)
        })
        
    except Exception as e:
        logging.error(f"Error fetching analysis history: {e}")
        return JSONResponse(
            status_code=500,
            content={"error": f"Failed to fetch analysis history: {str(e)}"}
        )

@app.get("/analysis/{analysis_id}", tags=["Order Analysis"])
async def get_analysis_details(
    analysis_id: str,
    current_user = Depends(get_current_user)
):
    """Get detailed analysis results for a specific case from daily-boards"""
    try:
        db = firestore.client()
        
        # Get board document with analysis data
        doc_ref = db.collection('daily-boards').document(analysis_id)
        doc = doc_ref.get()
        
        if not doc.exists:
            return JSONResponse(
                status_code=404,
                content={"error": "Case not found"}
            )
        
        board_data = doc.to_dict()
        
        # Check if analysis is completed
        if not board_data.get('order_analysis_completed', False):
            return JSONResponse(
                status_code=404,
                content={"error": "Order analysis not completed for this case"}
            )
        
        # Combine board data with analysis data
        analysis_data = {
            'id': doc.id,
            'case_id': doc.id,
            'case_ref': f"{board_data.get('case_type', '')}/{board_data.get('case_no', '')}/{board_data.get('case_year', '')}",
            
            # Original board data
            'case_type': board_data.get('case_type'),
            'case_no': board_data.get('case_no'),
            'case_year': board_data.get('case_year'),
            'board_date': board_data.get('board_date'),
            'petitioner_lawyer': board_data.get('petitioner_lawyer'),
            'respondent_lawyer': board_data.get('respondent_lawyer'),
            'serial_number': board_data.get('serial_number'),
            'additional_cases': board_data.get('additional_cases'),
            
            # Complete order analysis results
            'order_category': board_data.get('order_category'),
            'category_confidence': board_data.get('order_category_confidence'),
            'order_date': board_data.get('order_date'),
            'order_petitioners': board_data.get('order_petitioners', []),
            'order_respondents': board_data.get('order_respondents', []),
            'order_agp_names': board_data.get('order_agp_names', []),
            'order_tabular_data': board_data.get('order_tabular_data', []),
            'order_key_phrases': board_data.get('order_key_phrases', []),
            'next_hearing_date': board_data.get('order_next_hearing_date'),
            'disposal_reason': board_data.get('order_disposal_reason'),
            'order_text': board_data.get('order_text'),
            'order_cases': board_data.get('order_cases', []),
            'date_validation': board_data.get('order_date_validation'),
            'order_link': board_data.get('order_link'),
            'analysis_timestamp': board_data.get('order_analysis_timestamp'),
            'last_updated': board_data.get('order_last_updated')
        }
        
        return JSONResponse(content=analysis_data)
        
    except Exception as e:
        logging.error(f"Error fetching analysis details: {e}")
        return JSONResponse(
            status_code=500,
            content={"error": f"Failed to fetch analysis details: {str(e)}"}
        )

@app.get("/analysis-stats", tags=["Order Analysis"])
async def get_analysis_statistics(
    current_user = Depends(get_current_user)
):
    """Get statistics about order document analyses from daily-boards"""
    try:
        db = firestore.client()
        
        # Get all cases with completed order analysis from daily-boards
        analyses_ref = db.collection('daily-boards').where('order_analysis_completed', '==', True)
        docs = analyses_ref.stream()
        
        stats = {
            "total_analyses": 0,
            "category_distribution": {
                "ADJOURNED": 0,
                "HEARD_AND_ADJOURNED": 0,
                "DISPOSED_OFF": 0
            },
            "avg_confidence": 0.0,
            "recent_analyses": 0  # Last 30 days
        }
        
        confidences = []
        recent_cutoff = datetime.now().timestamp() - (30 * 24 * 60 * 60)  # 30 days ago
        
        for doc in docs:
            data = doc.to_dict()
            stats["total_analyses"] += 1
            
            # Category distribution
            category = data.get("order_category", "UNKNOWN")
            if category in stats["category_distribution"]:
                stats["category_distribution"][category] += 1
            
            # Confidence scores
            confidence = data.get("order_category_confidence", 0)
            if confidence > 0:
                confidences.append(confidence)
            
            # Recent analyses - use order_analysis_timestamp
            timestamp_str = data.get("order_analysis_timestamp", "")
            if timestamp_str:
                try:
                    timestamp = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00')).timestamp()
                    if timestamp > recent_cutoff:
                        stats["recent_analyses"] += 1
                except:
                    pass
        
        # Calculate average confidence
        if confidences:
            stats["avg_confidence"] = round(sum(confidences) / len(confidences), 3)
        
        return JSONResponse(content=stats)
        
    except Exception as e:
        logging.error(f"Error fetching analysis statistics: {e}")
        return JSONResponse(
            status_code=500,
            content={"error": f"Failed to fetch statistics: {str(e)}"}
        )

# Auto Order Management Endpoints
@app.post("/auto-orders/process-cases", tags=["Auto Order Management"])
async def auto_process_orders(
    request: Request,
    current_user=Depends(get_current_user)
):
    """Automatically process cases for order download and analysis"""
    try:
        body = await request.json()
        filters = body.get("filters", {})
        limit = body.get("limit", 50)
        
        result = auto_order_manager.get_orders_for_cases(filters, limit)
        
        if result.get("success"):
            return JSONResponse(content=result)
        else:
            return JSONResponse(
                status_code=500,
                content={"error": result.get("error", "Unknown error")}
            )
            
    except Exception as e:
        logging.error(f"Error in auto-process-orders: {e}")
        return JSONResponse(
            status_code=500,
            content={"error": f"Failed to process orders: {str(e)}"}
        )

@app.post("/auto-orders/bulk-process", tags=["Auto Order Management"])
async def bulk_process_orders(
    request: Request,
    current_user=Depends(get_current_user)
):
    """Bulk process specific cases by IDs"""
    try:
        body = await request.json()
        case_ids = body.get("case_ids", [])
        
        if not case_ids:
            return JSONResponse(
                status_code=400,
                content={"error": "No case IDs provided"}
            )
        
        result = auto_order_manager.bulk_process_orders(case_ids)
        
        if result.get("success"):
            return JSONResponse(content=result)
        else:
            return JSONResponse(
                status_code=500,
                content={"error": result.get("error", "Unknown error")}
            )
            
    except Exception as e:
        logging.error(f"Error in bulk-process-orders: {e}")
        return JSONResponse(
            status_code=500,
            content={"error": f"Failed to bulk process orders: {str(e)}"}
        )

# Queue Management Endpoints
@app.get("/queue/status", tags=["Queue Management"])
async def get_queue_status(
    current_user=Depends(get_current_user)
):
    """Get status of async order processing queue"""
    try:
        queue_size = order_processing_queue.qsize()
        
        return JSONResponse(content={
            "queue_size": queue_size,
            "processing_active": processing_active,
            "status": "active" if processing_active else "inactive",
            "message": f"Queue has {queue_size} pending cases" if queue_size > 0 else "Queue is empty"
        })
        
    except Exception as e:
        logging.error(f"Error getting queue status: {e}")
        return JSONResponse(
            status_code=500,
            content={"error": f"Failed to get queue status: {str(e)}"}
        )

@app.post("/queue/restart", tags=["Queue Management"])
async def restart_queue_processing(
    current_user=Depends(require_admin)
):
    """Restart the background order processing (admin only)"""
    try:
        global processing_active
        processing_active = False
        await asyncio.sleep(1)  # Allow current processing to finish
        await ensure_background_processing_active()
        
        return JSONResponse(content={
            "success": True,
            "message": "Background order processing restarted",
            "processing_active": processing_active
        })
        
    except Exception as e:
        logging.error(f"Error restarting queue processing: {e}")
        return JSONResponse(
            status_code=500,
            content={"error": f"Failed to restart queue processing: {str(e)}"}
        )

# User Matter Mapping Endpoints
@app.get("/user-matters/my-matters", tags=["User Matter Mapping"])
async def get_my_matters(
    limit: int = Query(100, description="Maximum number of matters to return"),
    current_user=Depends(get_current_user)
):
    """Get matters linked to the current logged-in user"""
    try:
        user_id = current_user.get('uid')
        matches = user_matter_matcher.find_user_matters(user_id, limit)
        
        # Convert dataclass objects to dictionaries
        matters_data = []
        for match in matches:
            matters_data.append({
                'case_id': match.case_id,
                'case_ref': match.case_ref,
                'match_source': match.match_source,
                'match_field': match.match_field,
                'matched_text': match.matched_text,
                'confidence_score': match.confidence_score,
                'role_type': match.role_type,
                'board_date': match.board_date
            })
        
        return JSONResponse(content={
            "user_id": user_id,
            "total_matches": len(matters_data),
            "matters": matters_data
        })
        
    except Exception as e:
        logging.error(f"Error getting user matters: {e}")
        return JSONResponse(
            status_code=500,
            content={"error": f"Failed to get user matters: {str(e)}"}
        )

@app.get("/user-matters/summary", tags=["User Matter Mapping"])
async def get_my_matters_summary(
    current_user=Depends(get_current_user)
):
    """Get summary statistics of matters for the current user"""
    try:
        user_id = current_user.get('uid')
        summary = user_matter_matcher.get_matters_summary(user_id)
        
        return JSONResponse(content={
            "user_id": user_id,
            "summary": summary
        })
        
    except Exception as e:
        logging.error(f"Error getting matters summary: {e}")
        return JSONResponse(
            status_code=500,
            content={"error": f"Failed to get matters summary: {str(e)}"}
        )

@app.get("/user-matters/role-config", tags=["User Matter Mapping"])
async def get_user_role_config(
    current_user=Depends(get_current_user)
):
    """Get current user's role configuration"""
    try:
        user_id = current_user.get('uid')
        user_role = user_matter_matcher.get_user_role_config(user_id)
        
        if not user_role:
            return JSONResponse(content={
                "user_id": user_id,
                "role_configured": False,
                "message": "No role configuration found. Please configure your legal role and name variations."
            })
        
        return JSONResponse(content={
            "user_id": user_id,
            "role_configured": True,
            "role_config": {
                "role_type": user_role.role_type,
                "full_name": user_role.full_name,
                "name_variations": user_role.name_variations,
                "pattern_keywords": user_role.pattern_keywords,
                "confidence_threshold": user_role.confidence_threshold
            }
        })
        
    except Exception as e:
        logging.error(f"Error getting user role config: {e}")
        return JSONResponse(
            status_code=500,
            content={"error": f"Failed to get role config: {str(e)}"}
        )

@app.post("/user-matters/configure-role", tags=["User Matter Mapping"])
async def configure_user_role(
    request: Request,
    current_user=Depends(get_current_user)
):
    """Configure user's legal role and name variations for matter matching"""
    try:
        user_id = current_user.get('uid')
        body = await request.json()
        
        # Validate required fields
        role_type = body.get('role_type')
        full_name = body.get('full_name')
        
        if not role_type or not full_name:
            return JSONResponse(
                status_code=400,
                content={"error": "role_type and full_name are required"}
            )
        
        # Valid role types
        valid_roles = ['AGP', 'GP', 'Addl_GP', 'B_Pnl', 'State_Advocate', 'AG']
        if role_type not in valid_roles:
            return JSONResponse(
                status_code=400,
                content={"error": f"Invalid role_type. Must be one of: {', '.join(valid_roles)}"}
            )
        
        # Generate name variations if not provided
        name_variations = body.get('name_variations', [])
        if not name_variations:
            name_variations = user_matter_matcher.generate_name_variations(full_name)
        
        # Create user role configuration
        user_role = UserRole(
            role_type=role_type,
            full_name=full_name,
            name_variations=name_variations,
            pattern_keywords=body.get('pattern_keywords', []),
            confidence_threshold=body.get('confidence_threshold', 0.75)
        )
        
        # Save configuration
        success = user_matter_matcher.save_user_role_config(user_id, user_role)
        
        if success:
            return JSONResponse(content={
                "success": True,
                "message": "Role configuration saved successfully",
                "user_id": user_id,
                "role_config": {
                    "role_type": user_role.role_type,
                    "full_name": user_role.full_name,
                    "name_variations": user_role.name_variations,
                    "pattern_keywords": user_role.pattern_keywords,
                    "confidence_threshold": user_role.confidence_threshold
                }
            })
        else:
            return JSONResponse(
                status_code=500,
                content={"error": "Failed to save role configuration"}
            )
        
    except Exception as e:
        logging.error(f"Error configuring user role: {e}")
        return JSONResponse(
            status_code=500,
            content={"error": f"Failed to configure role: {str(e)}"}
        )

@app.post("/user-matters/generate-name-variations", tags=["User Matter Mapping"])
async def generate_name_variations(
    request: Request,
    current_user=Depends(get_current_user)
):
    """Generate name variations for a given full name (helper endpoint)"""
    try:
        body = await request.json()
        full_name = body.get('full_name')
        
        if not full_name:
            return JSONResponse(
                status_code=400,
                content={"error": "full_name is required"}
            )
        
        variations = user_matter_matcher.generate_name_variations(full_name)
        
        return JSONResponse(content={
            "full_name": full_name,
            "name_variations": variations,
            "total_variations": len(variations)
        })
        
    except Exception as e:
        logging.error(f"Error generating name variations: {e}")
        return JSONResponse(
            status_code=500,
            content={"error": f"Failed to generate name variations: {str(e)}"}
        )

# Bill Generation Endpoints
@app.get("/bills/generate", tags=["Bill Generation"])
async def generate_bill_data(
    start_date: str = Query(..., description="Start date in YYYY-MM-DD format"),
    end_date: str = Query(..., description="End date in YYYY-MM-DD format"),
    current_user=Depends(get_current_user)
):
    """Generate bill data for logged-in user based on date range"""
    try:
        user_id = current_user.get('uid')
        
        # Parse dates
        from datetime import datetime
        start_dt = datetime.strptime(start_date, '%Y-%m-%d')
        end_dt = datetime.strptime(end_date, '%Y-%m-%d')
        
        # Get user's mapped cases within date range
        mappings_ref = db.collection('user-case-mappings')
        query = mappings_ref.where('user_id', '==', user_id)
        mappings = query.stream()
        
        bill_entries = []
        case_ids = set()
        
        for mapping_doc in mappings:
            mapping_data = mapping_doc.to_dict()
            case_id = mapping_data.get('case_id')
            
            # Get case details from daily-boards
            case_ref = db.collection('daily-boards').document(case_id)
            case_doc = case_ref.get()
            
            if case_doc.exists:
                case_data = case_doc.to_dict()
                board_date_str = case_data.get('board_date')
                
                if board_date_str:
                    try:
                        board_date = datetime.strptime(board_date_str, '%Y-%m-%d')
                        
                        # Check if case falls within date range
                        if start_dt <= board_date <= end_dt and case_id not in case_ids:
                            case_ids.add(case_id)
                            
                            # Determine fee and result based on order analysis
                            fee_info = calculate_case_fee(case_data)
                            
                            # Extract parties information
                            parties = extract_parties_info(case_data)
                            
                            bill_entry = {
                                'id': case_id,
                                'date': board_date_str,
                                'case_detail': f"{case_data.get('case_type')}/{case_data.get('case_no')}/{case_data.get('case_year')}",
                                'parties_name': parties,
                                'results': fee_info['result'],
                                'fees_rs': fee_info['fee'],
                                'confidence_score': mapping_data.get('confidence_score', 0.0),
                                'match_source': mapping_data.get('match_source'),
                                'editable': True
                            }
                            bill_entries.append(bill_entry)
                            
                    except ValueError as date_error:
                        logging.warning(f"Invalid date format for case {case_id}: {board_date_str}")
                        continue
        
        # Sort by date
        bill_entries.sort(key=lambda x: x['date'])
        
        return JSONResponse(content={
            "user_id": user_id,
            "date_range": {"start": start_date, "end": end_date},
            "total_entries": len(bill_entries),
            "total_fees": sum(entry['fees_rs'] for entry in bill_entries),
            "bill_entries": bill_entries
        })
        
    except Exception as e:
        logging.error(f"Error generating bill data: {e}")
        return JSONResponse(
            status_code=500,
            content={"error": f"Failed to generate bill data: {str(e)}"}
        )

@app.post("/bills/save", tags=["Bill Generation"])
async def save_bill_entries(
    request: Request,
    current_user=Depends(get_current_user)
):
    """Save/update bill entries for logged-in user"""
    try:
        user_id = current_user.get('uid')
        body = await request.json()
        
        bill_entries = body.get('bill_entries', [])
        bill_metadata = body.get('metadata', {})
        
        # Create a bill document
        bill_data = {
            'user_id': user_id,
            'created_at': firestore.SERVER_TIMESTAMP,
            'updated_at': firestore.SERVER_TIMESTAMP,
            'metadata': bill_metadata,
            'entries': bill_entries,
            'total_entries': len(bill_entries),
            'total_fees': sum(entry.get('fees_rs', 0) for entry in bill_entries)
        }
        
        # Save to user-bills collection
        bill_ref = db.collection('user-bills').document()
        bill_ref.set(bill_data)
        bill_id = bill_ref.id
        
        return JSONResponse(content={
            "success": True,
            "bill_id": bill_id,
            "total_entries": len(bill_entries),
            "total_fees": bill_data['total_fees']
        })
        
    except Exception as e:
        logging.error(f"Error saving bill entries: {e}")
        return JSONResponse(
            status_code=500,
            content={"error": f"Failed to save bill entries: {str(e)}"}
        )

@app.get("/bills/my-bills", tags=["Bill Generation"])
async def get_my_bills(
    limit: int = Query(20, description="Maximum number of bills to return"),
    current_user=Depends(get_current_user)
):
    """Get saved bills for logged-in user"""
    try:
        user_id = current_user.get('uid')
        
        bills_ref = db.collection('user-bills')
        query = bills_ref.where('user_id', '==', user_id).order_by('created_at', direction=firestore.Query.DESCENDING).limit(limit)
        bills = query.stream()
        
        bills_list = []
        for bill_doc in bills:
            bill_data = bill_doc.to_dict()
            bill_data['id'] = bill_doc.id
            
            # Convert timestamps
            if 'created_at' in bill_data and bill_data['created_at']:
                bill_data['created_at'] = bill_data['created_at'].isoformat()
            if 'updated_at' in bill_data and bill_data['updated_at']:
                bill_data['updated_at'] = bill_data['updated_at'].isoformat()
                
            bills_list.append(bill_data)
        
        return JSONResponse(content={
            "user_id": user_id,
            "bills": bills_list,
            "total_bills": len(bills_list)
        })
        
    except Exception as e:
        logging.error(f"Error getting user bills: {e}")
        return JSONResponse(
            status_code=500,
            content={"error": f"Failed to get user bills: {str(e)}"}
        )

def calculate_case_fee(case_data: Dict) -> Dict:
    """Calculate fee and result based on order analysis"""
    try:
        # Check if order analysis is available
        if not case_data.get('order_analysis_completed'):
            return {'result': '*ADJOURNED*', 'fee': 1250}
        
        # Get order analysis data
        order_result = case_data.get('order_result', '').lower()
        order_type = case_data.get('order_type', '').lower()
        order_text = case_data.get('order_summary', '').lower()
        
        # Fee calculation logic based on order content
        if 'due to paucity of time' in order_text or 'adjourned' in order_result:
            return {'result': 'ADJOURNED', 'fee': 1250}
        elif 'dispose' in order_result or 'disposal' in order_result or 'disposed' in order_text:
            return {'result': 'WP DISPOSED OF', 'fee': 2500}
        elif 'heard' in order_result or order_type == 'heard_adjourned':
            return {'result': 'HEARD & ADJN.', 'fee': 1875}
        else:
            # Default case
            return {'result': 'HEARD & ADJN.', 'fee': 1875}
            
    except Exception as e:
        logging.error(f"Error calculating case fee: {e}")
        return {'result': '*ADJOURNED*', 'fee': 1250}

def extract_parties_info(case_data: Dict) -> str:
    """Extract parties information from case data"""
    try:
        # Try to get from order analysis first
        if case_data.get('order_analysis_completed'):
            petitioners = case_data.get('order_petitioners', [])
            respondents = case_data.get('order_respondents', [])
            
            if petitioners and respondents:
                if isinstance(petitioners, list):
                    petitioner_str = ', '.join(petitioners[:2])  # Take first 2
                else:
                    petitioner_str = str(petitioners)
                    
                if isinstance(respondents, list):
                    respondent_str = ', '.join(respondents[:2])  # Take first 2
                else:
                    respondent_str = str(respondents)
                    
                return f"{petitioner_str} V/S {respondent_str}"
        
        # Fallback to case reference
        case_ref = f"{case_data.get('case_type')}/{case_data.get('case_no')}/{case_data.get('case_year')}"
        return f"Matter in {case_ref}"
        
    except Exception as e:
        logging.error(f"Error extracting parties info: {e}")
        return "Parties information not available"

@app.get("/bills/export/excel", tags=["Bill Generation"])
async def export_bill_excel(
    bill_id: str = Query(None, description="Bill ID to export"),
    start_date: str = Query(None, description="Start date for generating fresh export"),
    end_date: str = Query(None, description="End date for generating fresh export"),
    current_user=Depends(get_current_user)
):
    """Export bill data as Excel format"""
    try:
        user_id = current_user.get('uid')
        
        # Get bill data - either from saved bill or generate fresh
        if bill_id:
            # Export saved bill
            bill_ref = db.collection('user-bills').document(bill_id)
            bill_doc = bill_ref.get()
            
            if not bill_doc.exists:
                return JSONResponse(
                    status_code=404,
                    content={"error": "Bill not found"}
                )
            
            bill_data = bill_doc.to_dict()
            if bill_data.get('user_id') != user_id:
                return JSONResponse(
                    status_code=403,
                    content={"error": "Access denied"}
                )
            
            entries = bill_data.get('entries', [])
            metadata = bill_data.get('metadata', {})
            filename = f"bill_{bill_id}.csv"
            
        elif start_date and end_date:
            # Generate fresh export
            response = await generate_bill_data(start_date, end_date, current_user)
            if response.status_code != 200:
                return response
            
            response_data = json.loads(response.body.decode())
            entries = response_data.get('bill_entries', [])
            metadata = {"date_range": {"start": start_date, "end": end_date}}
            filename = f"bill_{start_date}_to_{end_date}.csv"
            
        else:
            return JSONResponse(
                status_code=400,
                content={"error": "Either bill_id or both start_date and end_date are required"}
            )
        
        if not entries:
            return JSONResponse(
                status_code=404,
                content={"error": "No bill entries found"}
            )
        
        # Create CSV content
        import io
        output = io.StringIO()
        
        # Write headers
        headers = ['DATE', 'CASE DETAIL', 'PARTIES NAME', 'RESULTS', 'FEES (RS.)']
        output.write(','.join(headers) + '\n')
        
        # Write data rows
        total_fees = 0
        for entry in entries:
            row = [
                entry.get('date', ''),
                f'"{entry.get("case_detail", "")}"',
                f'"{entry.get("parties_name", "")}"',
                f'"{entry.get("results", "")}"',
                str(entry.get('fees_rs', 0))
            ]
            output.write(','.join(row) + '\n')
            total_fees += entry.get('fees_rs', 0)
        
        # Add summary row
        output.write('\n')
        output.write(f',,,"TOTAL:",{total_fees}\n')
        
        csv_content = output.getvalue()
        output.close()
        
        # Return as downloadable file
        from fastapi.responses import StreamingResponse
        import io
        
        def generate():
            yield csv_content.encode('utf-8')
        
        return StreamingResponse(
            io.BytesIO(csv_content.encode('utf-8')),
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )
        
    except Exception as e:
        logging.error(f"Error exporting bill to Excel: {e}")
        return JSONResponse(
            status_code=500,
            content={"error": f"Failed to export bill: {str(e)}"}
        )

@app.get("/bills/{bill_id}", tags=["Bill Generation"])
async def get_bill_details(
    bill_id: str,
    current_user=Depends(get_current_user)
):
    """Get details of a specific saved bill"""
    try:
        user_id = current_user.get('uid')
        
        bill_ref = db.collection('user-bills').document(bill_id)
        bill_doc = bill_ref.get()
        
        if not bill_doc.exists:
            return JSONResponse(
                status_code=404,
                content={"error": "Bill not found"}
            )
        
        bill_data = bill_doc.to_dict()
        
        # Check ownership
        if bill_data.get('user_id') != user_id:
            return JSONResponse(
                status_code=403,
                content={"error": "Access denied"}
            )
        
        bill_data['id'] = bill_doc.id
        
        # Convert timestamps
        if 'created_at' in bill_data and bill_data['created_at']:
            bill_data['created_at'] = bill_data['created_at'].isoformat()
        if 'updated_at' in bill_data and bill_data['updated_at']:
            bill_data['updated_at'] = bill_data['updated_at'].isoformat()
        
        return JSONResponse(content=bill_data)
        
    except Exception as e:
        logging.error(f"Error getting bill details: {e}")
        return JSONResponse(
            status_code=500,
            content={"error": f"Failed to get bill details: {str(e)}"}
        )

@app.delete("/bills/{bill_id}", tags=["Bill Generation"])
async def delete_bill(
    bill_id: str,
    current_user=Depends(get_current_user)
):
    """Delete a saved bill"""
    try:
        user_id = current_user.get('uid')
        
        bill_ref = db.collection('user-bills').document(bill_id)
        bill_doc = bill_ref.get()
        
        if not bill_doc.exists:
            return JSONResponse(
                status_code=404,
                content={"error": "Bill not found"}
            )
        
        bill_data = bill_doc.to_dict()
        
        # Check ownership
        if bill_data.get('user_id') != user_id:
            return JSONResponse(
                status_code=403,
                content={"error": "Access denied"}
            )
        
        # Delete the bill
        bill_ref.delete()
        
        return JSONResponse(content={
            "success": True,
            "message": "Bill deleted successfully"
        })
        
    except Exception as e:
        logging.error(f"Error deleting bill: {e}")
        return JSONResponse(
            status_code=500,
            content={"error": f"Failed to delete bill: {str(e)}"}
        )

@app.get("/auto-orders/search", tags=["Auto Order Management"])
async def search_orders(
    petitioner_search: str = Query(None, description="Search in petitioner names"),
    respondent_search: str = Query(None, description="Search in respondent names"),
    case_type: str = Query(None, description="Filter by case type"),
    case_year: str = Query(None, description="Filter by case year"),
    order_category: str = Query(None, description="Filter by order category"),
    limit: int = Query(100, description="Maximum results to return"),
    current_user=Depends(get_current_user)
):
    """Search orders with petitioner, respondent, and order links"""
    try:
        search_params = {}
        
        if petitioner_search:
            search_params["petitioner_search"] = petitioner_search
        if respondent_search:
            search_params["respondent_search"] = respondent_search
        if case_type:
            search_params["case_type"] = case_type
        if case_year:
            search_params["case_year"] = case_year
        if order_category:
            search_params["order_category"] = order_category
        
        search_params["limit"] = limit
        
        result = auto_order_manager.search_orders(search_params)
        
        if result.get("success"):
            return JSONResponse(content=result)
        else:
            return JSONResponse(
                status_code=500,
                content={"error": result.get("error", "Unknown error")}
            )
            
    except Exception as e:
        logging.error(f"Error in search-orders: {e}")
        return JSONResponse(
            status_code=500,
            content={"error": f"Failed to search orders: {str(e)}"}
        )

@app.get("/auto-orders/search-index-stats", tags=["Auto Order Management"])
async def get_search_index_stats(current_user=Depends(get_current_user)):
    """Get statistics about the search index"""
    try:
        db = firestore.client()
        
        # Count total indexed orders
        search_docs = list(db.collection("order-search-index").stream())
        total_indexed = len(search_docs)
        
        # Count by categories
        categories = {}
        case_types = {}
        years = {}
        
        for doc in search_docs:
            data = doc.to_dict()
            
            # Count categories
            category = data.get("order_category", "UNKNOWN")
            categories[category] = categories.get(category, 0) + 1
            
            # Count case types
            case_type = data.get("case_type", "UNKNOWN")
            case_types[case_type] = case_types.get(case_type, 0) + 1
            
            # Count years
            year = data.get("case_year", "UNKNOWN")
            years[year] = years.get(year, 0) + 1
        
        return JSONResponse(content={
            "total_indexed_orders": total_indexed,
            "category_distribution": categories,
            "case_type_distribution": case_types,
            "year_distribution": years
        })
        
    except Exception as e:
        logging.error(f"Error getting search index stats: {e}")
        return JSONResponse(
            status_code=500,
            content={"error": f"Failed to get search stats: {str(e)}"}
        )

@app.get("/auto-orders/tabular-data", tags=["Auto Order Management"])
async def get_order_tabular_data(
    petitioner_search: str = Query(None),
    respondent_search: str = Query(None),
    case_type: str = Query(None),
    case_year: str = Query(None),
    order_category: str = Query(None),
    date_validation_valid: bool = Query(None),
    limit: int = Query(100, le=1000),
    current_user=Depends(get_current_user)
):
    """Get structured tabular data from analyzed-orders collection with Order Date, Petitioner, Respondent, AGP/GP list, Category, and order links"""
    try:
        db = firestore.client()
        query_ref = db.collection("analyzed-orders")
        
        # Apply filters - only filter on indexed fields
        if order_category:
            query_ref = query_ref.where("order_category", "==", order_category)
        if date_validation_valid is not None:
            query_ref = query_ref.where("date_validation.valid", "==", date_validation_valid)
        
        # Execute query with limit
        docs = query_ref.limit(limit).stream()
        
        results = []
        for doc in docs:
            data = doc.to_dict()
            
            # Apply text-based filters (post-query)
            if petitioner_search:
                petitioners = data.get("petitioners", [])
                if not any(petitioner_search.lower() in pet.lower() for pet in petitioners):
                    continue
                    
            if respondent_search:
                respondents = data.get("respondents", [])
                if not any(respondent_search.lower() in resp.lower() for resp in respondents):
                    continue
            
            # Apply additional filters (post-query)
            if case_type and data.get("case_ref", "").split("-")[0] != case_type:
                continue
            if case_year and data.get("case_ref", "").split("-")[-1] != case_year:
                continue
            
            # Format result for frontend consumption with comprehensive tabular data
            result = {
                "case_id": data.get("case_id"),
                "case_ref": data.get("case_ref"),
                "case_type": data.get("case_ref", "").split("-")[0] if data.get("case_ref") else None,
                "case_number": data.get("case_ref", "").split("-")[1] if data.get("case_ref") and len(data.get("case_ref", "").split("-")) > 1 else None,
                "case_year": data.get("case_ref", "").split("-")[-1] if data.get("case_ref") else None,
                "board_date": data.get("expected_board_date"),
                
                # Core tabular data from order_analyzer (exactly what user requested)
                "order_date": data.get("order_date"),
                "order_category": data.get("order_category"),
                "category_confidence": data.get("category_confidence"),
                
                # Parties (cleaned by order_analyzer)
                "petitioners": data.get("petitioners", []),
                "respondents": data.get("respondents", []),
                
                # AGP/GP/State advocates list (cleaned by order_analyzer)
                "agp_names": data.get("agp_names", []),
                
                # Complete structured tabular data from order_analyzer
                "tabular_data": data.get("tabular_data", []),
                
                # Additional details
                "next_hearing_date": data.get("next_hearing_date"),
                "disposal_reason": data.get("disposal_reason"),
                "key_phrases": data.get("key_phrases", []),
                
                # Date validation info
                "date_validation": data.get("date_validation", {}),
                
                # Order link (fetched and stored with analysis)
                "order_link": data.get("order_link"),
                
                # Timestamps
                "analysis_timestamp": data.get("analysis_timestamp"),
                "created_at": data.get("created_at")
            }
            
            results.append(result)
        
        return JSONResponse(content={
            "success": True,
            "results": results,
            "count": len(results),
            "filters_applied": {
                "petitioner_search": petitioner_search,
                "respondent_search": respondent_search,
                "case_type": case_type,
                "case_year": case_year,
                "order_category": order_category,
                "date_validation_valid": date_validation_valid,
                "limit": limit
            }
        })
        
    except Exception as e:
        logging.error(f"Error getting tabular data: {e}")
        return JSONResponse(
            status_code=500,
            content={"error": f"Failed to get tabular data: {str(e)}"}
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

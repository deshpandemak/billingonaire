import os
import sys

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
import asyncio
import json
import logging
import re
import socket
from asyncio import Queue
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from typing import Dict, List, Optional

import firebase_admin
import pandas as pd
from fastapi import (
    Depends,
    FastAPI,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from firebase_admin import auth, credentials, firestore

from AutoOrderManager import AutoOrderManager
from Board import Board
from CourtScraper import BombayHighCourtScraper
from Dashboard import DashboardData
from order_analyzer import OrderDocumentAnalyzer
from OrderManager import OrderManager
from UserManager import UserManager
from UserMatterMatcher import MatterMatch, UserMatterMatcher, UserRole

app = FastAPI(
    title="Billingonaire API",
    description="API for Billingonaire application",
    version="1.0.0",
    openapi_tags=[
        {"name": "Root", "description": "Root endpoint"},
        {"name": "PDF Upload", "description": "Upload PDF and extract data"},
        {"name": "Data Retrieval", "description": "Retrieve stored data"},
        {"name": "Authentication", "description": "User authentication"},
        {
            "name": "Case Status",
            "description": "Retrieve case status from Bombay High Court",
        },
        {
            "name": "Case Orders",
            "description": "Retrieve case orders from Bombay High Court",
        },
        {
            "name": "Order Management",
            "description": "Manage court order linking and states",
        },
        {
            "name": "Order Analysis",
            "description": "ML-powered analysis of court order documents",
        },
        {
            "name": "Queue Management",
            "description": "Monitor async order processing queue",
        },
        {
            "name": "User Matter Mapping",
            "description": "Link users to their legal matters using AI-powered name matching",
        },
    ],
)

# Startup event to initialize background processing
# Temporarily disabled for Cloud Run - background processing can be initialized on first use
# @app.on_event("startup")
# async def startup_event():
#     """Initialize background order processing on app startup"""
#     logging.info("🚀 Billingonaire API starting up...")
#     try:
#         await ensure_background_processing_active()
#         logging.info("✅ Background order processing initialized")
#     except Exception as e:
#         logging.error(f"❌ Failed to initialize background processing: {e}")

# Lazy Firebase initialization - deferred until first use to avoid blocking port binding
_firebase_initialized = False


def ensure_firebase():
    """Initialize Firebase Admin SDK on first use"""
    global _firebase_initialized
    if not _firebase_initialized:
        if not firebase_admin._apps:
            import json

            gcloud_key = os.environ.get("GCLOUD_SERVICE_ACCOUNT_KEY")
            if gcloud_key:
                # Local/Replit environment with service account key
                cred_dict = json.loads(gcloud_key)
                cred = credentials.Certificate(cred_dict)
                firebase_admin.initialize_app(cred)
            else:
                # Cloud Run with ADC
                firebase_admin.initialize_app()
        _firebase_initialized = True


app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://billingonaire.web.app",
        "http://localhost:5000",
        "http://localhost:5173",
        "http://localhost:5174",
        "https://2856c3cf-582f-4f2b-a0f3-cae6a5c3b647-00-5mlgokfyfmx.pike.replit.dev",
        "http://2856c3cf-582f-4f2b-a0f3-cae6a5c3b647-00-5mlgokfyfmx.pike.replit.dev",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Lazy initialization of heavy objects to avoid blocking Cloud Run startup
user_manager = None
order_analyzer = None
auto_order_manager = None
user_matter_matcher = None


def get_user_manager():
    global user_manager
    if user_manager is None:
        user_manager = UserManager()
    return user_manager


def get_order_analyzer():
    global order_analyzer
    if order_analyzer is None:
        from order_analyzer import OrderDocumentAnalyzer

        order_analyzer = OrderDocumentAnalyzer()
    return order_analyzer


def get_auto_order_manager():
    global auto_order_manager
    if auto_order_manager is None:
        from AutoOrderManager import AutoOrderManager

        auto_order_manager = AutoOrderManager()
    return auto_order_manager


def get_user_matter_matcher():
    global user_matter_matcher
    if user_matter_matcher is None:
        from UserMatterMatcher import UserMatterMatcher

        user_matter_matcher = UserMatterMatcher()
    return user_matter_matcher


# In-memory queue for async order processing
order_processing_queue = Queue()
processing_active = False
# Thread pool executor for blocking operations (configurable via env var)
try:
    MAX_WORKERS = max(1, int(os.environ.get("ORDER_PROCESSING_WORKERS", "3")))
except (ValueError, TypeError):
    logging.warning("Invalid ORDER_PROCESSING_WORKERS value, using default of 3")
    MAX_WORKERS = 3
executor = ThreadPoolExecutor(max_workers=MAX_WORKERS)


def get_current_user(request: Request):
    ensure_firebase()  # Initialize Firebase before auth operations
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=401, detail="Missing or invalid authentication token"
        )

    id_token = auth_header.split("Bearer ")[1]

    try:
        # Verify the Firebase ID token with more detailed error logging
        logging.info(f"Attempting to verify ID token for authentication")
        decoded_token = auth.verify_id_token(id_token)
        logging.info(
            f"Token verified successfully for user: {decoded_token.get('uid')}"
        )
        return decoded_token
    except Exception as e:
        logging.error(f"Token verification failed: {str(e)}")
        # SECURITY: Do not log token details to prevent leakage
        raise HTTPException(status_code=401, detail="Invalid authentication token")


def require_active_user(current_user: dict = Depends(get_current_user)):
    """Dependency to require active user account"""
    uid = current_user.get("uid")
    profile = get_user_manager().get_user_profile(uid)

    if not profile.get("is_active", True):
        raise HTTPException(
            status_code=403, detail="Account is disabled. Contact administrator."
        )

    return {**current_user, "profile": profile}


def get_user_with_profile(current_user: dict = Depends(require_active_user)):
    """Dependency to get current user with profile (active users only)"""
    return current_user


def require_admin(current_user: dict = Depends(get_current_user)):
    """Dependency to require admin role"""
    if not get_user_manager().is_admin(current_user.get("uid")):
        raise HTTPException(status_code=403, detail="Admin access required")
    return current_user


def require_admin_active(current_user: dict = Depends(require_active_user)):
    """Dependency to require active admin user"""
    if not get_user_manager().is_admin(current_user.get("uid")):
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
            formatted_date = record["board_date"]
            if isinstance(formatted_date, str):
                formatted_date = datetime.strptime(formatted_date, "%Y-%m-%d").strftime(
                    "%Y-%m-%d"
                )
            else:
                formatted_date = formatted_date.strftime("%Y-%m-%d")

            document_id = f"{formatted_date}-{record['case_type']}-{record['case_no']}-{record['case_year']}"

            # Create case info for queue processing - include 'id' field for AutoOrderManager
            case_info = {
                "id": document_id,  # Firestore document ID that AutoOrderManager expects
                "case_id": document_id,  # For backward compatibility
                "case_ref": f"{record['case_type']}/{record['case_no']}/{record['case_year']}",
                "case_type": record["case_type"],
                "case_no": record["case_no"],
                "case_year": record["case_year"],
                "board_date": record["board_date"],
                "petitioner_lawyer": record.get("petitioner_lawyer"),
                "respondent_lawyer": record.get("respondent_lawyer"),
            }
            case_list.append(case_info)

        # Add cases to processing queue
        for case_info in case_list:
            await order_processing_queue.put(case_info)
            logging.info(
                f"Added case {case_info['case_ref']} to order processing queue"
            )

        # Start background processing if not already active
        await ensure_background_processing_active()

    except Exception as e:
        logging.error(f"Error adding cases to processing queue: {e}")


async def process_order_queue_worker(worker_id: int):
    """Background worker to process order queue - one task per worker"""
    logging.info(f"🚀 Order processing worker {worker_id} started")

    while True:
        try:
            # Get case from queue (wait indefinitely for new items)
            case_info = await order_processing_queue.get()

            logging.info(
                f"[Worker {worker_id}] 📋 Processing order for case: {case_info['case_ref']} (ID: {case_info.get('id', 'unknown')})"
            )

            # Use AutoOrderManager to process single case
            # Run blocking operation in thread pool to avoid blocking event loop
            # Set timeout to 5 minutes (300 seconds) to prevent hanging
            try:
                loop = asyncio.get_event_loop()
                result = await asyncio.wait_for(
                    loop.run_in_executor(
                        executor,
                        get_auto_order_manager()._process_single_case,
                        case_info,
                    ),
                    timeout=300.0,  # 5 minutes timeout per case
                )

                if result.get("analysis_success"):
                    logging.info(
                        f"[Worker {worker_id}] ✅ Successfully processed order for {case_info['case_ref']} - Status should be 'analysed' in database"
                    )

                    # Automatically map case to users after successful analysis
                    try:
                        await auto_map_case_to_users(case_info.get("id"), case_info)
                        logging.info(
                            f"✅ Successfully mapped case {case_info['case_ref']} to users"
                        )
                    except Exception as mapping_error:
                        logging.error(
                            f"❌ Error mapping case {case_info['case_ref']} to users: {mapping_error}"
                        )

                elif result.get("download_success"):
                    logging.warning(
                        f"⚠️ Order downloaded but analysis failed for {case_info['case_ref']}: {result.get('error', 'Unknown error')}"
                    )
                else:
                    logging.warning(
                        f"⚠️ Order processing failed for {case_info['case_ref']}: {result.get('error', 'Unknown error')}"
                    )

            except asyncio.TimeoutError:
                logging.error(
                    f"❌ [Worker {worker_id}] TIMEOUT after 5 minutes processing {case_info['case_ref']} - moving to next case"
                )
            except Exception as e:
                logging.error(
                    f"❌ Error processing order for {case_info['case_ref']}: {e}"
                )
                import traceback

                logging.error(f"Full traceback: {traceback.format_exc()}")

            # Mark task as done
            order_processing_queue.task_done()

        except Exception as e:
            logging.error(f"Background order processing error: {e}")
            await asyncio.sleep(5)  # Wait before retrying


async def auto_map_case_to_users(case_id: str, case_info: Dict):
    """Automatically map case to users after order analysis completion"""
    try:
        # Initialize Firestore client
        db = firestore.client()

        # Get all users who have configured roles
        users_ref = db.collection("user-roles")
        user_docs = users_ref.stream()

        mapped_users = []

        for user_doc in user_docs:
            try:
                user_id = user_doc.id
                user_data = user_doc.to_dict()

                # Create UserRole object from stored data
                user_role = UserRole(
                    role_type=user_data.get("role_type"),
                    full_name=user_data.get("full_name"),
                    name_variations=user_data.get("name_variations", []),
                    pattern_keywords=user_data.get("pattern_keywords", []),
                    confidence_threshold=user_data.get("confidence_threshold", 0.75),
                )

                # Check if this case matches the user
                user_matches = get_user_matter_matcher().find_user_matters_for_case(
                    user_id, user_role, case_id
                )

                if user_matches:
                    # Store the mapping in user-case-mappings collection
                    for match in user_matches:
                        mapping_data = {
                            "user_id": user_id,
                            "case_id": case_id,
                            "case_ref": case_info.get("case_ref"),
                            "match_source": match.match_source,
                            "match_field": match.match_field,
                            "matched_text": match.matched_text,
                            "confidence_score": match.confidence_score,
                            "role_type": match.role_type,
                            "board_date": match.board_date,
                            "mapped_at": firestore.SERVER_TIMESTAMP,
                            "auto_mapped": True,
                        }

                        # Use composite key to prevent duplicates
                        mapping_key = f"{user_id}_{case_id}_{match.match_source}_{match.match_field}"
                        db.collection("user-case-mappings").document(mapping_key).set(
                            mapping_data, merge=True
                        )

                        mapped_users.append(
                            {
                                "user_id": user_id,
                                "role_type": user_role.role_type,
                                "confidence": match.confidence_score,
                            }
                        )

            except Exception as user_error:
                logging.error(
                    f"Error processing user {user_doc.id} for case mapping: {user_error}"
                )
                continue

        if mapped_users:
            logging.info(
                f"Case {case_info.get('case_ref')} mapped to {len(mapped_users)} users: {[u['user_id'] for u in mapped_users]}"
            )
        else:
            logging.info(f"No user matches found for case {case_info.get('case_ref')}")

    except Exception as e:
        logging.error(f"Error in auto_map_case_to_users: {e}")
        raise


async def ensure_background_processing_active():
    """Ensure background order processing is running with multiple workers"""
    global processing_active

    if not processing_active:
        processing_active = True
        # Start multiple worker tasks (one per thread pool worker)
        for worker_id in range(MAX_WORKERS):
            asyncio.create_task(process_order_queue_worker(worker_id))
        logging.info(f"🚀 Started {MAX_WORKERS} background order processing worker(s)")
    else:
        logging.info(
            f"✅ Background processing already active with {MAX_WORKERS} workers"
        )


# Login/logout endpoints removed - using Firebase client-side authentication


@app.get("/", tags=["Root"])
async def read_root():
    return {
        "message": "Hello, World! 🚀 Billingonaire API is running with async order processing."
    }


@app.post("/upload-pdf", tags=["PDF Upload"])
async def upload_pdf(
    files: List[UploadFile] = File(...), current_user=Depends(require_admin)
):
    results = []
    for file in files:
        if file.content_type != "application/pdf":
            results.append(
                {
                    "filename": file.filename,
                    "error": "Invalid file type. Only PDF files are allowed.",
                }
            )
            continue
        max_retries = 3
        for attempt in range(max_retries):
            try:
                logging.info(f"Starting upload processing for file: {file.filename}")
                board = Board()
                df = board.readFile(file.filename, file.file)
                record_count = len(df) if df is not None else 0
                logging.info(
                    f"PDF processed successfully. Records found: {record_count}"
                )

                if record_count > 0:
                    board.saveData(df)
                    logging.info(f"Data saved successfully for {file.filename}")

                    # Trigger async order processing for uploaded cases
                    await trigger_async_order_processing(df)

                    results.append(
                        {
                            "filename": file.filename,
                            "message": "Data saved successfully - Order processing started in background",
                            "records_processed": record_count,
                        }
                    )
                else:
                    logging.warning(f"No records found in {file.filename}")
                    results.append(
                        {
                            "filename": file.filename,
                            "message": "No records found in PDF",
                            "records_processed": 0,
                        }
                    )
                break
            except ConnectionResetError as e:
                logging.error(
                    f"ConnectionResetError on attempt {attempt + 1}: {str(e)}"
                )
                if attempt < max_retries - 1:
                    await asyncio.sleep(1)
                    continue
                else:
                    results.append(
                        {
                            "filename": file.filename,
                            "error": "Connection was reset by the remote host. Please try again later.",
                        }
                    )
                    break
            except Exception as e:
                logging.error(f"Error processing {file.filename}: {str(e)}")
                logging.error("Stack trace:", exc_info=True)
                results.append({"filename": file.filename, "error": str(e)})
                break
    return {"results": results}


@app.post("/save-data", tags=["PDF Upload"])
async def save_data(data: dict, current_user=Depends(require_admin)):
    try:
        board = Board()
        df = pd.DataFrame(data["data"])
        board.saveData(df)
        return {"message": "Data saved successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/get-data", tags=["Data Retrieval"])
async def get_data(
    request: Request, current_user_with_profile=Depends(get_user_with_profile)
):
    try:
        search_criteria = await request.json()

        board = Board()

        # SECURITY: Apply AGP filter for non-admin users - strict enforcement
        uid = current_user_with_profile.get("uid")
        agp_filter = get_user_manager().get_user_agp_filter(
            uid
        )  # This will raise 403 if invalid

        data = board.getData(search_criteria, agp_filter)
        return data
    except Exception as e:
        logging.error(f"Error in data retrieval: {str(e)}")
        raise HTTPException(status_code=500, detail="Error retrieving data")


@app.get("/debug/auth-test")
async def auth_test(current_user=Depends(get_current_user)):
    return {"message": "Authentication successful", "user_id": current_user.get("uid")}


@app.get("/debug/simple-db-check", tags=["Admin"])
async def simple_database_check(current_user=Depends(require_admin)):
    try:
        board = Board()

        # Get all documents
        all_docs = list(board.db.collection("daily-boards").limit(10).stream())

        # Get sample documents
        sample_docs = []
        case_years_found = []

        for doc in all_docs:
            doc_data = doc.to_dict()
            case_year = doc_data.get("case_year")
            case_years_found.append(case_year)

            # Convert datetime to string for JSON serialization
            if "board_date" in doc_data and hasattr(doc_data["board_date"], "strftime"):
                doc_data["board_date"] = doc_data["board_date"].strftime("%Y-%m-%d")

            sample_docs.append(
                {
                    "document_id": doc.id,
                    "case_year": case_year,
                    "case_year_type": str(type(case_year)),
                    "board_date": doc_data.get("board_date"),
                    "all_fields": list(doc_data.keys()),
                }
            )

        # Test query for case_year = "2025"
        test_query = board.db.collection("daily-boards").where(
            "case_year", "==", "2025"
        )
        test_results = list(test_query.stream())

        return {
            "total_documents": len(all_docs),
            "case_years_found": case_years_found,
            "test_query_for_2025_results": len(test_results),
            "sample_documents": sample_docs[:3],
            "database_status": "connected" if all_docs else "empty",
        }
    except Exception as e:
        return {"error": str(e), "database_status": "error"}


# User management endpoints
@app.get("/user/profile", tags=["User Management"])
async def get_user_profile(current_user_with_profile=Depends(get_user_with_profile)):
    """Get current user's profile"""
    return current_user_with_profile["profile"]


@app.post("/user/profile", tags=["User Management"])
async def create_or_update_profile(
    profile_data: dict, current_user=Depends(get_current_user)
):
    """Create or update user profile (self-service - no role changes)"""
    uid = current_user.get("uid")
    email = current_user.get("email")

    # Check if this is the initial admin user
    if email == "deshpande.mak@gmail.com":
        # Create admin profile directly
        return get_user_manager().create_user_profile(
            uid=uid, email=email, role="admin", full_name=profile_data.get("full_name")
        )

    # SECURITY: Remove role from self-service updates to prevent privilege escalation
    safe_updates = {"full_name": profile_data.get("full_name")}

    # Check if profile exists
    try:
        existing_profile = get_user_manager().get_user_profile(uid)
        if existing_profile.get("needs_setup"):
            # For new profiles, create user with legal category
            return get_user_manager().create_user_profile(
                uid=uid,
                email=email,
                role="user",
                legal_category="assistant_government_pleader",
                full_name=profile_data.get("full_name"),
            )
        else:
            # Update existing profile with safe fields only
            return get_user_manager().update_user_profile(uid, safe_updates)
    except:
        # Create new profile with user role and legal category
        return get_user_manager().create_user_profile(
            uid=uid,
            email=email,
            role="user",
            legal_category="assistant_government_pleader",
            full_name=profile_data.get("full_name"),
        )


@app.post("/user/change-password", tags=["User Management"])
async def change_password(password_data: dict, current_user=Depends(get_current_user)):
    """Change user password"""
    try:
        uid = current_user.get("uid")
        new_password = password_data.get("new_password")

        if not new_password or len(new_password) < 6:
            raise HTTPException(
                status_code=400, detail="Password must be at least 6 characters"
            )

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
    current_user=Depends(require_admin_active),
):
    """List all users (admin only)"""
    return get_user_manager().list_users(role_filter)


@app.post("/admin/user/{target_uid}/role", tags=["Admin"])
async def update_user_role(
    target_uid: str, role_data: dict, current_user=Depends(require_admin_active)
):
    """Update user role and profile information (admin only)"""
    admin_uid = current_user.get("uid")
    return get_user_manager().admin_update_user_profile(
        target_uid, role_data, admin_uid
    )


@app.post("/admin/setup-initial-admin", tags=["Admin"])
async def setup_initial_admin():
    """Set up deshpande.mak@gmail.com as initial administrator"""
    return get_user_manager().setup_initial_admin()


@app.get("/admin/active-users", tags=["Admin"])
async def get_active_users_for_bills(current_user=Depends(require_admin_active)):
    """Get list of active user names for bill generation (admin only)"""
    return {"user_names": get_user_manager().get_active_user_names()}


@app.get("/admin/available-roles", tags=["Admin"])
async def get_available_roles(current_user=Depends(require_admin_active)):
    """Get available user roles for admin interface"""
    return {"roles": get_user_manager().get_available_roles()}


@app.get("/admin/available-legal-categories", tags=["Admin"])
async def get_available_legal_categories(current_user=Depends(require_admin_active)):
    """Get available legal categories for admin interface"""
    return {"legal_categories": get_user_manager().get_available_legal_categories()}


@app.get("/admin/firebase-users", tags=["Admin"])
async def list_firebase_auth_users(current_user=Depends(require_admin_active)):
    """List all users from Firebase Authentication"""
    return get_user_manager().list_firebase_auth_users()


@app.get("/admin/unsynced-users", tags=["Admin"])
async def get_unsynced_firebase_users(current_user=Depends(require_admin_active)):
    """Get Firebase Auth users that don't have Firestore profiles"""
    return get_user_manager().get_firebase_auth_users_not_in_firestore()


@app.post("/admin/sync-firebase-users", tags=["Admin"])
async def sync_firebase_users(current_user=Depends(require_admin_active)):
    """Sync Firebase Auth users to Firestore database"""
    uid = current_user.get("uid")
    return get_user_manager().sync_firebase_users_to_firestore(uid)


@app.post("/admin/create-user", tags=["Admin"])
async def create_new_user(user_data: dict, current_user=Depends(require_admin_active)):
    """Create a new user with default password (admin only)"""
    try:
        admin_uid = current_user.get("uid")
        email = user_data.get("email")
        role = user_data.get("role", "user")
        legal_category = user_data.get("legal_category", "assistant_government_pleader")
        full_name = user_data.get("full_name", "")

        if not email:
            raise HTTPException(status_code=400, detail="Email is required")

        # Create user in Firebase Auth with default password
        try:
            firebase_user = auth.create_user(
                email=email,
                password="password123",  # Default password
                email_verified=False,
            )

            # Create user profile in Firestore
            user_profile = get_user_manager().create_user_profile(
                uid=firebase_user.uid,
                email=email,
                role=role,
                legal_category=(
                    legal_category
                    if get_user_manager().is_legal_professional(role)
                    else None
                ),
                full_name=full_name,
            )

            logging.info(f"Admin {admin_uid} created new user {email} with role {role}")

            return {
                "message": "User created successfully",
                "user": user_profile,
                "default_password": "password123",
                "note": "User should change password on first login",
            }

        except auth.EmailAlreadyExistsError:
            raise HTTPException(
                status_code=400, detail="Email already exists in the system"
            )
        except Exception as e:
            logging.error(f"Error creating Firebase user: {str(e)}")
            raise HTTPException(
                status_code=500, detail=f"Error creating user account: {str(e)}"
            )

    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Error in create_new_user: {str(e)}")
        raise HTTPException(status_code=500, detail="Error creating user")


# Dashboard endpoints (with authentication)
dashboard_data = None


def get_dashboard_data():
    global dashboard_data
    if dashboard_data is None:
        ensure_firebase()  # Ensure Firebase is initialized before creating DashboardData
        dashboard_data = DashboardData()
    return dashboard_data


@app.get("/dashboard/weekly-status")
async def dashboard_weekly_status(
    start_date: str = Query(None),
    end_date: str = Query(None),
    current_user_with_profile=Depends(get_user_with_profile),
):
    # SECURITY: Get AGP filter for the user - strict enforcement
    uid = current_user_with_profile.get("uid")
    agp_filter = get_user_manager().get_user_agp_filter(
        uid
    )  # This will raise 403 if invalid

    data = await get_dashboard_data().get_weekly_status(
        start_date, end_date, agp_filter
    )
    return JSONResponse(content=data)


@app.get("/dashboard/agp-stats")
async def dashboard_agp_stats(
    agp_name: str = Query(None),
    current_user_with_profile=Depends(get_user_with_profile),
):
    # SECURITY: Get AGP filter for the user - strict enforcement
    uid = current_user_with_profile.get("uid")
    agp_filter = get_user_manager().get_user_agp_filter(
        uid
    )  # This will raise 403 if invalid

    # For AGP users, use their assigned AGP name; for admins, use query parameter
    target_agp = agp_filter or agp_name

    data = await get_dashboard_data().get_agp_stats(target_agp, agp_filter)
    return JSONResponse(content=data)


@app.get("/dashboard/monthly-avg")
async def dashboard_monthly_avg(
    year: str = Query(None), current_user_with_profile=Depends(get_user_with_profile)
):
    # SECURITY: Get AGP filter for the user - strict enforcement
    uid = current_user_with_profile.get("uid")
    agp_filter = get_user_manager().get_user_agp_filter(
        uid
    )  # This will raise 403 if invalid

    data = await get_dashboard_data().get_monthly_avg(year, agp_filter)
    return JSONResponse(content=data)


@app.get("/dashboard/matters-by-date-range")
async def dashboard_matters_by_date_range(
    start_date: str = Query(
        None, description="Start date (YYYY-MM-DD) - defaults to last 5 days"
    ),
    end_date: str = Query(
        None, description="End date (YYYY-MM-DD) - defaults to today"
    ),
    current_user_with_profile=Depends(get_user_with_profile),
):
    """Get total matters by date range with average for bar chart + line visualization"""
    # SECURITY: Get AGP filter for the user - strict enforcement
    uid = current_user_with_profile.get("uid")
    agp_filter = get_user_manager().get_user_agp_filter(
        uid
    )  # This will raise 403 if invalid

    data = await get_dashboard_data().get_matters_by_date_range(
        start_date, end_date, agp_filter
    )
    return JSONResponse(content=data)


@app.get("/dashboard/agp-distribution-weekly")
async def dashboard_agp_distribution_weekly(
    current_user_with_profile=Depends(get_user_with_profile),
):
    """Get AGP distribution for current week (Monday to current date)"""
    # SECURITY: Get AGP filter for the user - strict enforcement
    uid = current_user_with_profile.get("uid")
    agp_filter = get_user_manager().get_user_agp_filter(
        uid
    )  # This will raise 403 if invalid

    data = await get_dashboard_data().get_agp_distribution_weekly(agp_filter)
    return JSONResponse(content=data)


@app.get("/dashboard/agp-distribution-monthly")
async def dashboard_agp_distribution_monthly(
    current_user_with_profile=Depends(get_user_with_profile),
):
    """Get AGP distribution for current month to date"""
    # SECURITY: Get AGP filter for the user - strict enforcement
    uid = current_user_with_profile.get("uid")
    agp_filter = get_user_manager().get_user_agp_filter(
        uid
    )  # This will raise 403 if invalid

    data = await get_dashboard_data().get_agp_distribution_monthly(agp_filter)
    return JSONResponse(content=data)


@app.get("/dashboard/agp-distribution-yearly")
async def dashboard_agp_distribution_yearly(
    current_user_with_profile=Depends(get_user_with_profile),
):
    """Get AGP distribution for current year to date"""
    # SECURITY: Get AGP filter for the user - strict enforcement
    uid = current_user_with_profile.get("uid")
    agp_filter = get_user_manager().get_user_agp_filter(
        uid
    )  # This will raise 403 if invalid

    data = await get_dashboard_data().get_agp_distribution_yearly(agp_filter)
    return JSONResponse(content=data)


# ML Enhancement endpoints
@app.get("/ml/status")
async def get_ml_enhancement_status(current_user=Depends(get_current_user)):
    """Get status of ML enhancement capabilities"""
    try:
        board = Board()
        if hasattr(board, "ml_parser") and board.ml_parser:
            status = board.ml_parser.get_enhancement_status()
            status["ml_parser_available"] = True
            status["message"] = (
                "ML Enhanced Parser is active and improving PDF processing quality"
            )
        else:
            status = {
                "ml_parser_available": False,
                "capabilities": {
                    "enhanced_preprocessing": False,
                    "ner": False,
                    "fuzzy_matching": False,
                    "learning": False,
                    "advanced_fuzzy": False,
                },
                "message": "ML Enhanced Parser not available - using standard PDF processing",
            }
        return JSONResponse(content=status)
    except Exception as e:
        logging.error(f"Error fetching ML status: {e}")
        raise HTTPException(
            status_code=500, detail="Failed to fetch ML enhancement status"
        )


@app.post("/ml/learn-from-correction")
async def learn_from_correction(
    correction_data: dict, current_user=Depends(get_current_user)
):
    """Allow users to provide corrections for ML learning"""
    try:
        board = Board()
        if hasattr(board, "ml_parser") and board.ml_parser:
            board.ml_parser.learn_from_correction(
                filename=correction_data.get("filename", ""),
                original_extraction=correction_data.get("original_extraction", ""),
                corrected_extraction=correction_data.get("corrected_extraction", ""),
                user_feedback=correction_data.get("user_feedback", {}),
            )
            return JSONResponse(
                content={"message": "Learning data stored successfully"}
            )
        else:
            return JSONResponse(
                content={"message": "ML Enhanced Parser not available for learning"}
            )
    except Exception as e:
        logging.error(f"Error storing learning data: {e}")
        raise HTTPException(status_code=500, detail="Failed to store learning data")


# Court integration endpoints
court_scraper = None
order_manager = None


def get_court_scraper():
    global court_scraper
    if court_scraper is None:
        court_scraper = BombayHighCourtScraper()
    return court_scraper


def get_order_manager():
    global order_manager
    if order_manager is None:
        ensure_firebase()  # Ensure Firebase is initialized before creating OrderManager
        order_manager = OrderManager()
    return order_manager


@app.get("/court/case-details", tags=["Case Status"])
async def get_case_details(
    case_ref: str = Query(..., description="Case reference like 'WP/294/2025'"),
    bench: str = Query(
        "mumbai",
        description="Court bench: mumbai, mumbai_appellate, aurangabad, nagpur, goa",
    ),
    current_user=Depends(get_current_user),
):
    """
    Fetch case details from Bombay High Court
    Example: /court/case-details?case_ref=WP/294/2025&bench=mumbai
    """
    try:
        case_details = get_court_scraper().get_case_details(case_ref, bench)
        return JSONResponse(content=case_details)
    except Exception as e:
        logging.error(f"Error fetching case details for {case_ref}: {e}")
        return JSONResponse(
            status_code=500,
            content={
                "error": f"Failed to fetch case details: {str(e)}",
                "case_ref": case_ref,
            },
        )


@app.get("/court/case-orders", tags=["Case Orders"])
async def get_case_orders(
    case_ref: str = Query(..., description="Case reference like 'WP/294/2025'"),
    date: str = Query(None, description="Specific date in YYYY-MM-DD format"),
    bench: str = Query(
        "mumbai",
        description="Court bench: mumbai, mumbai_appellate, aurangabad, nagpur, goa",
    ),
    current_user=Depends(get_current_user),
):
    """
    Fetch case orders from Bombay High Court for a specific case and date
    Example: /court/case-orders?case_ref=WP/294/2025&date=2025-01-03
    """
    try:
        case_orders = get_court_scraper().get_case_orders(case_ref, date, bench)
        return JSONResponse(
            content={"case_ref": case_ref, "date": date, "orders": case_orders}
        )
    except Exception as e:
        logging.error(f"Error fetching case orders for {case_ref}: {e}")
        return JSONResponse(
            status_code=500,
            content={
                "error": f"Failed to fetch case orders: {str(e)}",
                "case_ref": case_ref,
            },
        )


@app.post("/court/batch-case-lookup", tags=["Case Status"])
async def batch_case_lookup(
    case_refs: List[str],
    bench: str = Query(
        "mumbai",
        description="Court bench: mumbai, mumbai_appellate, aurangabad, nagpur, goa",
    ),
    current_user=Depends(get_current_user),
):
    """
    Fetch case details for multiple cases in batch
    Useful for getting court data for multiple cases from your billing records
    """
    try:
        results = []
        for case_ref in case_refs:
            case_details = get_court_scraper().get_case_details(case_ref, bench)
            results.append(
                {
                    "case_ref": case_ref,
                    "details": case_details,
                    "timestamp": pd.Timestamp.now().isoformat(),
                }
            )

        return JSONResponse(
            content={"total_cases": len(case_refs), "results": results, "bench": bench}
        )
    except Exception as e:
        logging.error(f"Error in batch case lookup: {e}")
        return JSONResponse(
            status_code=500,
            content={
                "error": f"Batch lookup failed: {str(e)}",
                "total_cases": len(case_refs),
            },
        )


# Order Management endpoints
@app.get("/orders/cases-without-orders", tags=["Order Management"])
async def get_cases_without_orders(
    limit: int = Query(100, description="Number of cases to return"),
    offset: int = Query(0, description="Pagination offset"),
    current_user=Depends(get_current_user),
):
    """
    Get cases from board data that don't have linked orders
    Used for order management interface
    """
    try:
        result = get_order_manager().get_cases_without_orders(limit, offset)
        return JSONResponse(content=result)
    except Exception as e:
        logging.error(f"Error fetching cases without orders: {e}")
        return JSONResponse(
            status_code=500, content={"error": f"Failed to fetch cases: {str(e)}"}
        )


@app.post("/orders/create-link", tags=["Order Management"])
async def create_order_link(request: Request, current_user=Depends(get_current_user)):
    """
    Create or update an order link for a case
    Body should contain: case_id, status, order_link, order_text, court_bench, notes
    When manual linking is done, automatically triggers order analysis
    """
    try:
        order_data = await request.json()
        case_id = order_data.get("case_id")

        if not case_id:
            return JSONResponse(
                status_code=400, content={"error": "case_id is required"}
            )

        result = get_order_manager().create_order_link(case_id, order_data)

        # AUTO-ANALYSIS: If order link is provided, automatically analyze the order
        if result.get("success") and order_data.get("order_link"):
            try:
                db = firestore.client()
                # Get case data for analysis
                case_doc = db.collection("daily-boards").document(case_id).get()
                if case_doc.exists:
                    case_data = case_doc.to_dict()
                    case_ref = f"{case_data.get('case_type')}/{case_data.get('case_no')}/{case_data.get('case_year')}"

                    # Download and analyze the order
                    import requests

                    order_link = order_data.get("order_link")
                    response = requests.get(order_link, timeout=30)

                    if (
                        response.status_code == 200
                        and response.headers.get("Content-Type") == "application/pdf"
                    ):
                        analysis_result = get_auto_order_manager()._analyze_order_with_date_validation(
                            case_id,
                            case_ref,
                            response.content,
                            case_data.get("board_date"),
                            order_link,
                        )

                        if analysis_result.get("success"):
                            result["analysis_completed"] = True
                            result["analysis_message"] = (
                                "Order linked and analyzed successfully"
                            )
                            logging.info(
                                f"Auto-analysis completed for manually linked order: {case_id}"
                            )
                        else:
                            result["analysis_completed"] = False
                            result["analysis_error"] = analysis_result.get("error")
                    else:
                        result["analysis_completed"] = False
                        result["analysis_error"] = "Could not download PDF from link"

            except Exception as analysis_error:
                logging.error(
                    f"Auto-analysis failed for manual link {case_id}: {analysis_error}"
                )
                result["analysis_completed"] = False
                result["analysis_error"] = str(analysis_error)

        return JSONResponse(content=result)
    except Exception as e:
        logging.error(f"Error creating order link: {e}")
        return JSONResponse(
            status_code=500, content={"error": f"Failed to create order link: {str(e)}"}
        )


@app.put("/orders/update-status", tags=["Order Management"])
async def update_order_status(
    case_id: str = Query(..., description="Case document ID"),
    status: str = Query(
        ..., description="Order status: linked, failed, manually_uploaded, not_present"
    ),
    notes: str = Query("", description="Optional notes"),
    current_user=Depends(get_current_user),
):
    """Update the status of an order"""
    try:
        result = get_order_manager().update_order_status(case_id, status, notes)
        return JSONResponse(content=result)
    except Exception as e:
        logging.error(f"Error updating order status: {e}")
        return JSONResponse(
            status_code=500, content={"error": f"Failed to update status: {str(e)}"}
        )


@app.get("/orders/by-status", tags=["Order Management"])
async def get_orders_by_status(
    status: str = Query(..., description="Order status to filter by"),
    limit: int = Query(100, description="Maximum number of orders"),
    current_user=Depends(get_current_user),
):
    """Get all orders with a specific status"""
    try:
        orders = get_order_manager().get_orders_by_status(status, limit)
        return JSONResponse(content={"orders": orders, "count": len(orders)})
    except Exception as e:
        logging.error(f"Error fetching orders by status: {e}")
        return JSONResponse(
            status_code=500, content={"error": f"Failed to fetch orders: {str(e)}"}
        )


@app.get("/orders/case-details/{case_id}", tags=["Order Management"])
async def get_case_with_order_info(
    case_id: str, current_user=Depends(get_current_user)
):
    """Get complete case information including order status"""
    try:
        result = get_order_manager().get_case_with_order_info(case_id)
        return JSONResponse(content=result)
    except Exception as e:
        logging.error(f"Error fetching case with order info: {e}")
        return JSONResponse(
            status_code=500,
            content={"error": f"Failed to fetch case details: {str(e)}"},
        )


# ============================================
# ORDER DOCUMENT ANALYSIS ENDPOINTS
# ============================================


@app.post("/analyze-order", tags=["Order Analysis"])
async def analyze_order_document(
    file: UploadFile = File(...), current_user=Depends(get_current_user)
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
        if not file.filename.lower().endswith(".pdf"):
            return JSONResponse(
                status_code=400,
                content={"error": "Only PDF files are supported for order analysis"},
            )

        # Read file content
        file_content = await file.read()

        if len(file_content) == 0:
            return JSONResponse(
                status_code=400, content={"error": "Uploaded file is empty"}
            )

        logging.info(f"Starting order analysis for file: {file.filename}")

        # Analyze the order document
        analysis_result = get_order_analyzer().analyze_order_document(
            file.filename, file_content
        )

        # DEBUG: Log the actual category being returned
        logging.info(f"🔍 CATEGORY DEBUG for {file.filename}:")
        logging.info(f"   order_category: '{analysis_result.order_category}'")
        logging.info(f"   category_confidence: {analysis_result.category_confidence}")

        # Save analysis result to database
        doc_id = get_order_analyzer().save_analysis_result(
            file.filename, analysis_result
        )

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
                    "advocates": case.advocates,
                }
                for case in analysis_result.cases
            ],
            "document_structure": {
                "type": analysis_result.document_structure.get(
                    "document_type", "UNKNOWN"
                ),
                "has_case_numbers": analysis_result.document_structure.get(
                    "has_case_numbers", False
                ),
                "has_parties": analysis_result.document_structure.get(
                    "has_parties", False
                ),
                "has_advocates": analysis_result.document_structure.get(
                    "has_advocates", False
                ),
                "has_order_date": analysis_result.document_structure.get(
                    "has_order_date", False
                ),
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
                "total_dates": len(analysis_result.dates),
            },
        }

        logging.info(f"Order analysis completed successfully for {file.filename}")
        return JSONResponse(content=response_data)

    except HTTPException as he:
        logging.error(f"HTTP error in order analysis: {he.detail}")
        return JSONResponse(status_code=he.status_code, content={"error": he.detail})
    except Exception as e:
        logging.error(f"Unexpected error in order analysis: {str(e)}")
        return JSONResponse(
            status_code=500, content={"error": f"Order analysis failed: {str(e)}"}
        )


@app.get("/analysis-history", tags=["Order Analysis"])
async def get_analysis_history(
    limit: int = Query(50, description="Maximum number of analyses to return"),
    current_user=Depends(get_current_user),
):
    """Get history of order document analyses from consolidated daily-boards"""
    try:
        db = firestore.client()

        # Get cases with completed order analysis from daily-boards
        analyses_ref = (
            db.collection("daily-boards")
            .where("order_analysis_completed", "==", True)
            .order_by("order_analysis_timestamp", direction=firestore.Query.DESCENDING)
            .limit(limit)
        )
        docs = analyses_ref.stream()

        analyses = []
        for doc in docs:
            board_data = doc.to_dict()

            # Extract order analysis data from the board document
            analysis_data = {
                "id": doc.id,
                "case_id": doc.id,
                "case_ref": f"{board_data.get('case_type', '')}/{board_data.get('case_no', '')}/{board_data.get('case_year', '')}",
                "case_type": board_data.get("case_type"),
                "case_no": board_data.get("case_no"),
                "case_year": board_data.get("case_year"),
                "board_date": board_data.get("board_date"),
                "petitioner_lawyer": board_data.get("petitioner_lawyer"),
                "respondent_lawyer": board_data.get("respondent_lawyer"),
                # Order analysis results
                "order_category": board_data.get("order_category"),
                "category_confidence": board_data.get("order_category_confidence"),
                "order_date": board_data.get("order_date"),
                "order_petitioners": board_data.get("order_petitioners", []),
                "order_respondents": board_data.get("order_respondents", []),
                "order_agp_names": board_data.get("order_agp_names", []),
                "order_key_phrases": board_data.get("order_key_phrases", []),
                "next_hearing_date": board_data.get("order_next_hearing_date"),
                "disposal_reason": board_data.get("order_disposal_reason"),
                "date_validation": board_data.get("order_date_validation"),
                "order_link": board_data.get("order_link"),
                "analysis_timestamp": board_data.get("order_analysis_timestamp"),
                "order_tabular_data": board_data.get("order_tabular_data", []),
            }

            analyses.append(analysis_data)

        return JSONResponse(
            content={
                "analyses": analyses,
                "count": len(analyses),
                "total_fetched": len(analyses),
            }
        )

    except Exception as e:
        logging.error(f"Error fetching analysis history: {e}")
        return JSONResponse(
            status_code=500,
            content={"error": f"Failed to fetch analysis history: {str(e)}"},
        )


@app.get("/analysis/{analysis_id}", tags=["Order Analysis"])
async def get_analysis_details(
    analysis_id: str, current_user=Depends(get_current_user)
):
    """Get detailed analysis results for a specific case from daily-boards"""
    try:
        db = firestore.client()

        # Get board document with analysis data
        doc_ref = db.collection("daily-boards").document(analysis_id)
        doc = doc_ref.get()

        if not doc.exists:
            return JSONResponse(status_code=404, content={"error": "Case not found"})

        board_data = doc.to_dict()

        # Check if analysis is completed
        if not board_data.get("order_analysis_completed", False):
            return JSONResponse(
                status_code=404,
                content={"error": "Order analysis not completed for this case"},
            )

        # Combine board data with analysis data
        analysis_data = {
            "id": doc.id,
            "case_id": doc.id,
            "case_ref": f"{board_data.get('case_type', '')}/{board_data.get('case_no', '')}/{board_data.get('case_year', '')}",
            # Original board data
            "case_type": board_data.get("case_type"),
            "case_no": board_data.get("case_no"),
            "case_year": board_data.get("case_year"),
            "board_date": board_data.get("board_date"),
            "petitioner_lawyer": board_data.get("petitioner_lawyer"),
            "respondent_lawyer": board_data.get("respondent_lawyer"),
            "serial_number": board_data.get("serial_number"),
            "additional_cases": board_data.get("additional_cases"),
            # Complete order analysis results
            "order_category": board_data.get("order_category"),
            "category_confidence": board_data.get("order_category_confidence"),
            "order_date": board_data.get("order_date"),
            "order_petitioners": board_data.get("order_petitioners", []),
            "order_respondents": board_data.get("order_respondents", []),
            "order_agp_names": board_data.get("order_agp_names", []),
            "order_tabular_data": board_data.get("order_tabular_data", []),
            "order_key_phrases": board_data.get("order_key_phrases", []),
            "next_hearing_date": board_data.get("order_next_hearing_date"),
            "disposal_reason": board_data.get("order_disposal_reason"),
            "order_text": board_data.get("order_text"),
            "order_cases": board_data.get("order_cases", []),
            "date_validation": board_data.get("order_date_validation"),
            "order_link": board_data.get("order_link"),
            "analysis_timestamp": board_data.get("order_analysis_timestamp"),
            "last_updated": board_data.get("order_last_updated"),
        }

        return JSONResponse(content=analysis_data)

    except Exception as e:
        logging.error(f"Error fetching analysis details: {e}")
        return JSONResponse(
            status_code=500,
            content={"error": f"Failed to fetch analysis details: {str(e)}"},
        )


@app.get("/analysis-stats", tags=["Order Analysis"])
async def get_analysis_statistics(current_user=Depends(get_current_user)):
    """Get statistics about order document analyses from daily-boards"""
    try:
        db = firestore.client()

        # Get all cases with completed order analysis from daily-boards
        analyses_ref = db.collection("daily-boards").where(
            "order_analysis_completed", "==", True
        )
        docs = analyses_ref.stream()

        stats = {
            "total_analyses": 0,
            "category_distribution": {
                "ADJOURNED": 0,
                "HEARD_AND_ADJOURNED": 0,
                "DISPOSED_OFF": 0,
            },
            "avg_confidence": 0.0,
            "recent_analyses": 0,  # Last 30 days
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
                    timestamp = datetime.fromisoformat(
                        timestamp_str.replace("Z", "+00:00")
                    ).timestamp()
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
            status_code=500, content={"error": f"Failed to fetch statistics: {str(e)}"}
        )


# Auto Order Management Endpoints
@app.post("/auto-orders/process-cases", tags=["Auto Order Management"])
async def auto_process_orders(request: Request, current_user=Depends(get_current_user)):
    """Automatically process cases for order download and analysis"""
    try:
        body = await request.json()
        filters = body.get("filters", {})
        limit = body.get("limit", 50)

        result = get_auto_order_manager().get_orders_for_cases(filters, limit)

        if result.get("success"):
            return JSONResponse(content=result)
        else:
            return JSONResponse(
                status_code=500, content={"error": result.get("error", "Unknown error")}
            )

    except Exception as e:
        logging.error(f"Error in auto-process-orders: {e}")
        return JSONResponse(
            status_code=500, content={"error": f"Failed to process orders: {str(e)}"}
        )


@app.post("/auto-orders/process-case", tags=["Auto Order Management"])
async def process_single_case(request: Request, current_user=Depends(get_current_user)):
    """Process a single case for order download and analysis"""
    try:
        db = firestore.client()

        body = await request.json()
        case_id = body.get("case_id")
        case_ref = body.get("case_ref")
        board_date = body.get("board_date")

        if not case_id or not case_ref:
            return JSONResponse(
                status_code=400, content={"error": "case_id and case_ref are required"}
            )

        # Fetch existing case data from database to check order status
        case_doc = db.collection("daily-boards").document(case_id).get()

        if not case_doc.exists:
            return JSONResponse(status_code=404, content={"error": "Case not found"})

        # Get full case data including order status
        case_data = case_doc.to_dict()
        case_data["id"] = case_id
        case_data["case_ref"] = case_ref
        case_data["board_date"] = board_date

        # Process the single case
        result = get_auto_order_manager()._process_single_case(case_data)

        return JSONResponse(content=result)

    except Exception as e:
        logging.error(f"Error processing single case: {e}")
        return JSONResponse(
            status_code=500, content={"error": f"Failed to process case: {str(e)}"}
        )


@app.post("/auto-orders/analyze-case/{case_id}", tags=["Auto Order Management"])
async def analyze_single_case(case_id: str, current_user=Depends(get_current_user)):
    """Analyze an already downloaded order for a case"""
    try:
        db = firestore.client()
        # Get case data from database
        case_doc = db.collection("daily-boards").document(case_id).get()
        if not case_doc.exists:
            return JSONResponse(status_code=404, content={"error": "Case not found"})

        case_data = case_doc.to_dict()

        # Check if order is downloaded
        if not case_data.get("order_link"):
            return JSONResponse(
                status_code=400,
                content={
                    "error": "No order available to analyze. Please download the order first."
                },
            )

        # If already analyzed, return existing analysis
        if case_data.get("order_analysis_completed"):
            return JSONResponse(
                content={
                    "success": True,
                    "message": "Order already analyzed",
                    "data": {
                        "order_category": case_data.get("order_category"),
                        "order_date": case_data.get("order_date"),
                        "order_petitioners": case_data.get("order_petitioners"),
                        "order_respondents": case_data.get("order_respondents"),
                    },
                }
            )

        # Download the PDF from the link and analyze
        # If stored link fails, fallback to fresh download from court website
        try:
            import requests

            order_link = case_data.get("order_link")
            logging.info(f"Downloading order from: {order_link}")

            try:
                response = requests.get(order_link, timeout=30)

                # More lenient Content-Type check (handles variations like 'application/pdf;charset=UTF-8')
                content_type = response.headers.get("Content-Type", "").lower()
                is_pdf = "application/pdf" in content_type

                # Check if stored link is valid
                if (
                    response.status_code != 200
                    or not is_pdf
                    or len(response.content) < 100
                ):
                    # Stored link failed - fallback to fresh download
                    reason = f"Stored link failed: status={response.status_code}, content_type={content_type}, size={len(response.content) if response.content else 0}"
                    logging.warning(
                        f"⚠️ {reason}. Attempting fresh download from court website..."
                    )

                    # Prepare case_data for fresh download (same as Download Order button)
                    case_ref = f"{case_data.get('case_type')}/{case_data.get('case_no')}/{case_data.get('case_year')}"
                    case_data_with_refs = {
                        **case_data,
                        "id": case_id,
                        "case_ref": case_ref,
                    }

                    # Use the same fallback logic as Download Order button
                    result = {
                        "case_id": case_id,
                        "case_ref": case_ref,
                        "download_success": False,
                        "analysis_success": False,
                    }
                    fresh_result = get_auto_order_manager()._fallback_to_fresh_download(
                        case_data_with_refs, result, reason
                    )

                    if fresh_result.get("analysis_success"):
                        return JSONResponse(
                            content={
                                "success": True,
                                "data": fresh_result.get("analysis_data"),
                                "message": "Order re-downloaded and analyzed successfully",
                            }
                        )
                    else:
                        return JSONResponse(
                            status_code=500,
                            content={
                                "error": fresh_result.get(
                                    "error", "Failed to re-download and analyze order"
                                )
                            },
                        )

                # Stored link is valid - proceed with analysis
                case_ref = f"{case_data.get('case_type')}/{case_data.get('case_no')}/{case_data.get('case_year')}"
                logging.info(f"Analyzing order for case: {case_ref}")

                analysis_result = (
                    get_auto_order_manager()._analyze_order_with_date_validation(
                        case_id,
                        case_ref,
                        response.content,
                        case_data.get("board_date"),
                        order_link,
                    )
                )

                return JSONResponse(content=analysis_result)

            except requests.RequestException as req_error:
                # Network error accessing stored link - try fresh download
                logging.warning(
                    f"Network error accessing stored link: {req_error}. Attempting fresh download..."
                )

                case_ref = f"{case_data.get('case_type')}/{case_data.get('case_no')}/{case_data.get('case_year')}"
                case_data_with_refs = {**case_data, "id": case_id, "case_ref": case_ref}

                result = {
                    "case_id": case_id,
                    "case_ref": case_ref,
                    "download_success": False,
                    "analysis_success": False,
                }
                fresh_result = get_auto_order_manager()._fallback_to_fresh_download(
                    case_data_with_refs, result, f"Network error: {str(req_error)}"
                )

                if fresh_result.get("analysis_success"):
                    return JSONResponse(
                        content={
                            "success": True,
                            "data": fresh_result.get("analysis_data"),
                            "message": "Order re-downloaded and analyzed successfully",
                        }
                    )
                else:
                    return JSONResponse(
                        status_code=500,
                        content={
                            "error": fresh_result.get(
                                "error", "Failed to re-download and analyze order"
                            )
                        },
                    )

        except Exception as e:
            logging.error(f"Unexpected error in download/analyze: {e}", exc_info=True)
            return JSONResponse(
                status_code=500, content={"error": f"Failed to analyze order: {str(e)}"}
            )

    except Exception as e:
        logging.error(f"Error in analyze-case: {e}")
        return JSONResponse(
            status_code=500, content={"error": f"Failed to analyze case: {str(e)}"}
        )


@app.post("/auto-orders/bulk-process", tags=["Auto Order Management"])
async def bulk_process_orders(request: Request, current_user=Depends(get_current_user)):
    """Bulk process specific cases by IDs"""
    try:
        body = await request.json()
        case_ids = body.get("case_ids", [])

        if not case_ids:
            return JSONResponse(
                status_code=400, content={"error": "No case IDs provided"}
            )

        result = get_auto_order_manager().bulk_process_orders(case_ids)

        if result.get("success"):
            return JSONResponse(content=result)
        else:
            return JSONResponse(
                status_code=500, content={"error": result.get("error", "Unknown error")}
            )

    except Exception as e:
        logging.error(f"Error in bulk-process-orders: {e}")
        return JSONResponse(
            status_code=500,
            content={"error": f"Failed to bulk process orders: {str(e)}"},
        )


@app.post("/auto-orders/upload-manual-order/{case_id}", tags=["Auto Order Management"])
async def upload_manual_order(
    case_id: str, file: UploadFile = File(...), current_user=Depends(get_current_user)
):
    """
    Upload a manual order PDF for a case and automatically analyze it
    This allows users to upload order PDFs when automatic download isn't available
    """
    try:
        db = firestore.client()
        # Verify it's a PDF
        if file.content_type != "application/pdf":
            return JSONResponse(
                status_code=400, content={"error": "File must be a PDF"}
            )

        # Get case data
        case_doc = db.collection("daily-boards").document(case_id).get()
        if not case_doc.exists:
            return JSONResponse(status_code=404, content={"error": "Case not found"})

        case_data = case_doc.to_dict()
        case_ref = f"{case_data.get('case_type')}/{case_data.get('case_no')}/{case_data.get('case_year')}"

        # Read PDF content
        pdf_content = await file.read()

        # Store the PDF (you might want to upload to Firebase Storage or similar)
        # For now, we'll just analyze it directly

        # Create a temporary order link (or upload to storage)
        order_link = f"manual_upload_{case_id}_{file.filename}"

        # Update case document with manual order link
        update_data = {
            "order_downloaded": True,
            "order_link": order_link,
            "order_filename": file.filename,
            "order_source": "manual_upload",
            "order_downloaded_at": datetime.now().isoformat(),
        }
        db.collection("daily-boards").document(case_id).update(update_data)

        # Create order document
        order_doc = {
            "case_id": case_id,
            "status": "linked",
            "order_link": order_link,
            "fetch_date": datetime.now().isoformat(),
            "source": "manual_upload",
            "filename": file.filename,
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
        }
        db.collection("case-orders").document(case_id).set(order_doc)

        # AUTOMATICALLY ANALYZE THE UPLOADED ORDER
        analysis_result = get_auto_order_manager()._analyze_order_with_date_validation(
            case_id, case_ref, pdf_content, case_data.get("board_date"), order_link
        )

        if analysis_result.get("success"):
            # Create search index
            try:
                get_auto_order_manager()._create_search_index_entry(
                    case_id, case_data, analysis_result["data"]
                )
            except Exception as index_error:
                logging.warning(f"Failed to create search index: {index_error}")

            return JSONResponse(
                content={
                    "success": True,
                    "message": "Order uploaded and analyzed successfully",
                    "case_id": case_id,
                    "case_ref": case_ref,
                    "filename": file.filename,
                    "analysis": {
                        "order_category": analysis_result["data"].get("order_category"),
                        "order_date": analysis_result["data"].get("order_date"),
                        "petitioners_count": len(
                            analysis_result["data"].get("order_petitioners", [])
                        ),
                        "respondents_count": len(
                            analysis_result["data"].get("order_respondents", [])
                        ),
                    },
                }
            )
        else:
            return JSONResponse(
                status_code=500,
                content={
                    "success": False,
                    "message": "Order uploaded but analysis failed",
                    "error": analysis_result.get("error"),
                },
            )

    except Exception as e:
        logging.error(f"Error uploading manual order: {e}")
        return JSONResponse(
            status_code=500, content={"error": f"Failed to upload order: {str(e)}"}
        )


@app.post("/auto-orders/scheduled-retry", tags=["Auto Order Management"])
async def scheduled_retry_orders(
    days_back: int = Query(7, description="Number of days to look back"),
    limit: int = Query(100, description="Maximum cases to process"),
    current_user=Depends(get_current_user),
):
    """
    Scheduled endpoint for automatic retry of order downloads
    Can be called by Cloud Scheduler or cron job to automatically process cases without orders

    Use Case: After board upload, orders may not be available yet. This endpoint
    retries downloading orders for recent cases that don't have orders yet.
    """
    try:
        db = firestore.client()
        # Calculate date range
        end_date = datetime.now()
        start_date = end_date - timedelta(days=days_back)

        # Query cases without orders from recent boards
        query = (
            db.collection("daily-boards")
            .where("board_date", ">=", start_date.strftime("%Y-%m-%d"))
            .where("board_date", "<=", end_date.strftime("%Y-%m-%d"))
            .where("order_downloaded", "==", False)
            .limit(limit)
        )

        cases = query.get()

        case_list = []
        for case_doc in cases:
            case_data = case_doc.to_dict()
            case_info = {
                "id": case_doc.id,
                "case_ref": f"{case_data.get('case_type')}/{case_data.get('case_no')}/{case_data.get('case_year')}",
                "board_date": case_data.get("board_date"),
            }
            case_list.append(case_info)

        if not case_list:
            return JSONResponse(
                content={
                    "success": True,
                    "message": f"No cases without orders found in the last {days_back} days",
                    "cases_found": 0,
                }
            )

        # Add cases to processing queue for async processing
        for case_info in case_list:
            await order_processing_queue.put(case_info)

        # Ensure background processing is active
        await ensure_background_processing_active()

        logging.info(
            f"Scheduled retry: Added {len(case_list)} cases to processing queue"
        )

        return JSONResponse(
            content={
                "success": True,
                "message": f"Added {len(case_list)} cases to background processing queue",
                "cases_queued": len(case_list),
                "date_range": {
                    "start": start_date.strftime("%Y-%m-%d"),
                    "end": end_date.strftime("%Y-%m-%d"),
                },
            }
        )

    except Exception as e:
        logging.error(f"Error in scheduled retry: {e}")
        return JSONResponse(
            status_code=500, content={"error": f"Scheduled retry failed: {str(e)}"}
        )


@app.get("/admin/order-status-overview", tags=["Admin Order Management"])
async def get_order_status_overview(current_user=Depends(require_admin)):
    """
    Get overview of order statuses for admin dashboard
    Shows counts for each order status
    """
    try:
        db = firestore.client()

        # Query all cases grouped by order_status
        cases = db.collection("daily-boards").stream()

        status_counts = {
            "not_linked": 0,
            "order_linked": 0,
            "analysed": 0,
            "order_failed": 0,
            "order_analysis_failed": 0,
        }

        for case_doc in cases:
            case_data = case_doc.to_dict()
            status = case_data.get("order_status", "not_linked")

            # Normalize: treat "unknown", empty, or missing status as "not_linked"
            if (
                status == "unknown"
                or status is None
                or status == ""
                or status not in status_counts
            ):
                status = "not_linked"

            status_counts[status] += 1

        total_cases = sum(status_counts.values())

        return JSONResponse(
            content={
                "success": True,
                "total_cases": total_cases,
                "status_counts": status_counts,
                "pending_processing": status_counts["not_linked"]
                + status_counts["order_failed"],
            }
        )

    except Exception as e:
        logging.error(f"Error getting order status overview: {e}")
        return JSONResponse(
            status_code=500,
            content={"error": f"Failed to get order status overview: {str(e)}"},
        )


@app.post("/admin/bulk-order-processing", tags=["Admin Order Management"])
async def admin_bulk_order_processing(
    request: Request, current_user=Depends(require_admin)
):
    """
    Admin endpoint to trigger bulk order processing for cases with specific order status
    Adds cases to async processing queue and returns immediately

    Request body:
    {
        "order_statuses": ["not_linked", "order_failed"],  // Which statuses to process
        "limit": 100,  // Maximum cases to process
        "days_back": 30  // Only process cases from last N days (optional)
    }

    Note: Cases with "unknown" or missing status are automatically normalized to "not_linked"
    """
    try:
        db = firestore.client()

        body = await request.json()
        order_statuses = body.get(
            "order_statuses", ["not_linked", "order_linked", "order_failed"]
        )
        limit = body.get("limit", 100)
        days_back = body.get("days_back")

        # Build query
        query = db.collection("daily-boards")

        # Filter by date if specified (board_date is stored as datetime object)
        if days_back:
            start_date = datetime.now() - timedelta(days=days_back)
            # Convert to datetime object to match database storage format
            start_datetime = datetime(
                start_date.year, start_date.month, start_date.day, 0, 0, 0
            )
            query = query.where("board_date", ">=", start_datetime)

        # Get all cases and filter by status (since Firestore doesn't support 'in' for all types)
        all_cases = query.limit(limit * 3).stream()

        case_list = []
        for case_doc in all_cases:
            case_data = case_doc.to_dict()
            case_status = case_data.get("order_status", "not_linked")

            # Normalize: treat "unknown" or missing status as "not_linked"
            if case_status == "unknown" or case_status is None or case_status == "":
                case_status = "not_linked"

            if case_status in order_statuses:
                case_info = {
                    "id": case_doc.id,
                    "case_ref": f"{case_data.get('case_type')}/{case_data.get('case_no')}/{case_data.get('case_year')}",
                    "board_date": case_data.get("board_date"),
                    "current_status": case_status,
                }
                case_list.append(case_info)

                if len(case_list) >= limit:
                    break

        if not case_list:
            return JSONResponse(
                content={
                    "success": True,
                    "message": f"No cases found with statuses {order_statuses}",
                    "cases_queued": 0,
                }
            )

        # Ensure background processing is active BEFORE adding to queue
        await ensure_background_processing_active()

        # Add cases to processing queue for async processing
        for case_info in case_list:
            await order_processing_queue.put(case_info)

        queue_size_after = order_processing_queue.qsize()
        logging.info(
            f"Admin bulk processing: Added {len(case_list)} cases to queue, current queue size: {queue_size_after}"
        )

        return JSONResponse(
            content={
                "success": True,
                "message": f"Added {len(case_list)} cases to background processing queue",
                "cases_queued": len(case_list),
                "statuses_processed": order_statuses,
                "queue_size": queue_size_after,
            }
        )

    except Exception as e:
        logging.error(f"Error in admin bulk order processing: {e}")
        return JSONResponse(
            status_code=500,
            content={"error": f"Admin bulk processing failed: {str(e)}"},
        )


# Queue Management Endpoints
@app.get("/queue/status", tags=["Queue Management"])
async def get_queue_status(current_user=Depends(get_current_user)):
    """Get status of async order processing queue"""
    try:
        queue_size = order_processing_queue.qsize()

        return JSONResponse(
            content={
                "queue_size": queue_size,
                "processing_active": processing_active,
                "status": "active" if processing_active else "inactive",
                "message": (
                    f"Queue has {queue_size} pending cases"
                    if queue_size > 0
                    else "Queue is empty"
                ),
            }
        )

    except Exception as e:
        logging.error(f"Error getting queue status: {e}")
        return JSONResponse(
            status_code=500, content={"error": f"Failed to get queue status: {str(e)}"}
        )


@app.post("/queue/restart", tags=["Queue Management"])
async def restart_queue_processing(current_user=Depends(require_admin)):
    """Restart the background order processing (admin only)"""
    try:
        global processing_active
        processing_active = False
        await asyncio.sleep(1)  # Allow current processing to finish
        await ensure_background_processing_active()

        return JSONResponse(
            content={
                "success": True,
                "message": "Background order processing restarted",
                "processing_active": processing_active,
            }
        )

    except Exception as e:
        logging.error(f"Error restarting queue processing: {e}")
        return JSONResponse(
            status_code=500,
            content={"error": f"Failed to restart queue processing: {str(e)}"},
        )


# User Matter Mapping Endpoints
@app.get("/user-matters/my-matters", tags=["User Matter Mapping"])
async def get_my_matters(
    limit: int = Query(100, description="Maximum number of matters to return"),
    current_user=Depends(get_current_user),
):
    """Get matters linked to the current logged-in user"""
    try:
        user_id = current_user.get("uid")
        matches = get_user_matter_matcher().find_user_matters(user_id, limit)

        # Convert dataclass objects to dictionaries
        matters_data = []
        for match in matches:
            matters_data.append(
                {
                    "case_id": match.case_id,
                    "case_ref": match.case_ref,
                    "match_source": match.match_source,
                    "match_field": match.match_field,
                    "matched_text": match.matched_text,
                    "confidence_score": match.confidence_score,
                    "role_type": match.role_type,
                    "board_date": match.board_date,
                }
            )

        return JSONResponse(
            content={
                "user_id": user_id,
                "total_matches": len(matters_data),
                "matters": matters_data,
            }
        )

    except Exception as e:
        logging.error(f"Error getting user matters: {e}")
        return JSONResponse(
            status_code=500, content={"error": f"Failed to get user matters: {str(e)}"}
        )


@app.get("/user-matters/summary", tags=["User Matter Mapping"])
async def get_my_matters_summary(current_user=Depends(get_current_user)):
    """Get summary statistics of matters for the current user"""
    try:
        user_id = current_user.get("uid")
        summary = get_user_matter_matcher().get_matters_summary(user_id)

        return JSONResponse(content={"user_id": user_id, "summary": summary})

    except Exception as e:
        logging.error(f"Error getting matters summary: {e}")
        return JSONResponse(
            status_code=500,
            content={"error": f"Failed to get matters summary: {str(e)}"},
        )


@app.get("/user-matters/role-config", tags=["User Matter Mapping"])
async def get_user_role_config(current_user=Depends(get_current_user)):
    """Get current user's role configuration"""
    try:
        user_id = current_user.get("uid")
        user_role = get_user_matter_matcher().get_user_role_config(user_id)

        if not user_role:
            return JSONResponse(
                content={
                    "user_id": user_id,
                    "role_configured": False,
                    "message": "No role configuration found. Please configure your legal role and name variations.",
                }
            )

        return JSONResponse(
            content={
                "user_id": user_id,
                "role_configured": True,
                "role_config": {
                    "role_type": user_role.role_type,
                    "full_name": user_role.full_name,
                    "name_variations": user_role.name_variations,
                    "pattern_keywords": user_role.pattern_keywords,
                    "confidence_threshold": user_role.confidence_threshold,
                },
            }
        )

    except Exception as e:
        logging.error(f"Error getting user role config: {e}")
        return JSONResponse(
            status_code=500, content={"error": f"Failed to get role config: {str(e)}"}
        )


@app.post("/user-matters/configure-role", tags=["User Matter Mapping"])
async def configure_user_role(request: Request, current_user=Depends(get_current_user)):
    """Configure user's legal role and name variations for matter matching"""
    try:
        user_id = current_user.get("uid")
        body = await request.json()

        # Validate required fields
        role_type = body.get("role_type")
        full_name = body.get("full_name")

        if not role_type or not full_name:
            return JSONResponse(
                status_code=400,
                content={"error": "role_type and full_name are required"},
            )

        # Valid role types
        valid_roles = ["AGP", "GP", "Addl_GP", "B_Pnl", "State_Advocate", "AG"]
        if role_type not in valid_roles:
            return JSONResponse(
                status_code=400,
                content={
                    "error": f"Invalid role_type. Must be one of: {', '.join(valid_roles)}"
                },
            )

        # Generate name variations if not provided
        name_variations = body.get("name_variations", [])
        if not name_variations:
            name_variations = get_user_matter_matcher().generate_name_variations(
                full_name
            )

        # Create user role configuration
        user_role = UserRole(
            role_type=role_type,
            full_name=full_name,
            name_variations=name_variations,
            pattern_keywords=body.get("pattern_keywords", []),
            confidence_threshold=body.get("confidence_threshold", 0.75),
        )

        # Save configuration
        success = get_user_matter_matcher().save_user_role_config(user_id, user_role)

        if success:
            return JSONResponse(
                content={
                    "success": True,
                    "message": "Role configuration saved successfully",
                    "user_id": user_id,
                    "role_config": {
                        "role_type": user_role.role_type,
                        "full_name": user_role.full_name,
                        "name_variations": user_role.name_variations,
                        "pattern_keywords": user_role.pattern_keywords,
                        "confidence_threshold": user_role.confidence_threshold,
                    },
                }
            )
        else:
            return JSONResponse(
                status_code=500, content={"error": "Failed to save role configuration"}
            )

    except Exception as e:
        logging.error(f"Error configuring user role: {e}")
        return JSONResponse(
            status_code=500, content={"error": f"Failed to configure role: {str(e)}"}
        )


@app.post("/user-matters/generate-name-variations", tags=["User Matter Mapping"])
async def generate_name_variations(
    request: Request, current_user=Depends(get_current_user)
):
    """Generate name variations for a given full name (helper endpoint)"""
    try:
        body = await request.json()
        full_name = body.get("full_name")

        if not full_name:
            return JSONResponse(
                status_code=400, content={"error": "full_name is required"}
            )

        variations = get_user_matter_matcher().generate_name_variations(full_name)

        return JSONResponse(
            content={
                "full_name": full_name,
                "name_variations": variations,
                "total_variations": len(variations),
            }
        )

    except Exception as e:
        logging.error(f"Error generating name variations: {e}")
        return JSONResponse(
            status_code=500,
            content={"error": f"Failed to generate name variations: {str(e)}"},
        )


# Order Management Center Endpoints
@app.get("/orders/overview-stats", tags=["Order Management"])
async def get_order_overview_stats(current_user=Depends(get_current_user)):
    """Get comprehensive overview statistics for Order Management Center"""
    try:
        db = firestore.client()
        # Get total cases count
        boards_ref = db.collection("daily-boards")
        total_cases_query = boards_ref.limit(10000)  # Reasonable limit for counting
        total_cases_docs = list(total_cases_query.stream())
        total_cases = len(total_cases_docs)

        # Count cases with orders (orders collection exists)
        orders_ref = db.collection("case-orders")
        orders_docs = list(orders_ref.limit(10000).stream())
        cases_with_orders = len(orders_docs)

        # Calculate cases without orders
        cases_without_orders = total_cases - cases_with_orders

        # Calculate analysis completion rate
        analysis_completion_rate = round(
            (cases_with_orders / total_cases * 100) if total_cases > 0 else 0, 1
        )

        # Get recent processing statistics
        recent_successful = 0
        recent_failed = 0

        # Count recent successful analyses from board data with analysis results
        for doc in total_cases_docs[:100]:  # Check recent 100 cases
            case_data = doc.to_dict()
            if case_data.get("order_analysis_result"):
                recent_successful += 1

        return JSONResponse(
            content={
                "total_cases": total_cases,
                "cases_with_orders": cases_with_orders,
                "cases_without_orders": cases_without_orders,
                "analysis_completion_rate": analysis_completion_rate,
                "recent_successful_analyses": recent_successful,
                "recent_failed_analyses": recent_failed,
                "last_updated": datetime.now().isoformat(),
            }
        )

    except Exception as e:
        logging.error(f"Error getting order overview stats: {e}")
        return JSONResponse(
            status_code=500,
            content={"error": f"Failed to get overview stats: {str(e)}"},
        )


@app.get("/orders/queue-status", tags=["Order Management"])
async def get_queue_status(current_user=Depends(get_current_user)):
    """Get current processing queue status"""
    try:
        # Get approximate queue size (this is in-memory, so basic check)
        pending_items = order_processing_queue.qsize() if order_processing_queue else 0

        return JSONResponse(
            content={
                "active": processing_active,
                "pending": pending_items,
                "last_checked": datetime.now().isoformat(),
            }
        )

    except Exception as e:
        logging.error(f"Error getting queue status: {e}")
        return JSONResponse(content={"active": False, "pending": 0, "error": str(e)})


@app.get("/orders/recent-activity", tags=["Order Management"])
async def get_recent_activity(
    limit: int = Query(10, description="Number of recent activities to return"),
    current_user=Depends(get_current_user),
):
    """Get recent order processing activity"""
    try:
        # This would typically come from a dedicated activity log collection
        # For now, we'll return a mock structure that can be implemented later
        recent_activity = [
            {
                "timestamp": datetime.now().isoformat(),
                "action": "Auto Download",
                "case_ref": "WP/123/2025",
                "status": "success",
            },
            {
                "timestamp": (datetime.now() - timedelta(minutes=5)).isoformat(),
                "action": "Analysis Complete",
                "case_ref": "WP/124/2025",
                "status": "success",
            },
            {
                "timestamp": (datetime.now() - timedelta(minutes=10)).isoformat(),
                "action": "Manual Link",
                "case_ref": "CP/125/2024",
                "status": "success",
            },
        ]

        return JSONResponse(content=recent_activity[:limit])

    except Exception as e:
        logging.error(f"Error getting recent activity: {e}")
        return JSONResponse(
            status_code=500,
            content={"error": f"Failed to get recent activity: {str(e)}"},
        )


# Bill Generation Endpoints
@app.get("/bills/generate", tags=["Bill Generation"])
async def generate_bill_data(
    start_date: str = Query(..., description="Start date in YYYY-MM-DD format"),
    end_date: str = Query(..., description="End date in YYYY-MM-DD format"),
    user_name: Optional[str] = Query(
        None, description="User's full name to generate bill for (admin only)"
    ),
    current_user=Depends(get_current_user),
):
    """Generate bill data for logged-in user or specific user (admin only) based on date range"""
    try:
        user_id = current_user.get("uid")
        is_admin = get_user_manager().is_admin(user_id)

        # Initialize Firestore client
        db = firestore.client()

        # Parse dates
        from datetime import datetime, timedelta

        start_dt = datetime.strptime(start_date, "%Y-%m-%d")
        end_dt = datetime.strptime(end_date, "%Y-%m-%d")

        bill_entries = []
        case_ids = set()

        # Admin can generate bill for any user, non-admin only for themselves
        if user_name and not is_admin:
            return JSONResponse(
                status_code=403,
                content={
                    "error": "Only administrators can generate bills for other users"
                },
            )

        # Determine which cases to include
        if user_name:
            # Admin generating bill for specific user - use ENHANCED fuzzy matching
            logging.info(f"Admin {user_id} generating bill for user: {user_name}")

            # Step 1: Collect all unique AGP names from MULTIPLE sources in board data
            boards_ref = db.collection("daily-boards")
            all_cases = boards_ref.stream()

            unique_agp_names = set()
            cases_by_agp = {}  # Map AGP names to their cases for efficient lookup

            for case_doc in all_cases:
                case_data = case_doc.to_dict()
                case_id = case_doc.id
                
                # Source 1: respondent_lawyer (primary field)
                respondent_lawyer = case_data.get("respondent_lawyer", "").strip()
                if respondent_lawyer:
                    unique_agp_names.add(respondent_lawyer)
                    if respondent_lawyer not in cases_by_agp:
                        cases_by_agp[respondent_lawyer] = []
                    cases_by_agp[respondent_lawyer].append((case_id, case_data))
                
                # Source 2: additional_respondent_lawyers (comma-separated from daily board)
                # Parse properly to keep name+designation pairs intact (e.g., "SHRI A.B.SHARMA,AGP")
                additional_lawyers = case_data.get("additional_respondent_lawyers", "").strip()
                if additional_lawyers:
                    # Split on patterns that indicate separate advocates
                    # Look for patterns like "AGP," or "GP," followed by space and new name
                    import re
                    # Split on AGP/GP followed by comma and space, but keep AGP/GP with the name
                    lawyer_names = re.split(r'(?:,\s*(?=(?:SHRI|SMT|MS|MR|DR|PROF)\.?\s+))', additional_lawyers)
                    for lawyer_name in lawyer_names:
                        lawyer_name = lawyer_name.strip().rstrip(',')
                        if lawyer_name:
                            unique_agp_names.add(lawyer_name)
                            if lawyer_name not in cases_by_agp:
                                cases_by_agp[lawyer_name] = []
                            cases_by_agp[lawyer_name].append((case_id, case_data))
                
                # Source 3: order_agp_names (can be list OR single string from order analysis)
                order_agp_names = case_data.get("order_agp_names")
                if order_agp_names:
                    # Handle both string and list formats
                    if isinstance(order_agp_names, str):
                        # Single string - treat as one name
                        agp_name = order_agp_names.strip()
                        if agp_name:
                            unique_agp_names.add(agp_name)
                            if agp_name not in cases_by_agp:
                                cases_by_agp[agp_name] = []
                            cases_by_agp[agp_name].append((case_id, case_data))
                    elif isinstance(order_agp_names, list):
                        # List of names
                        for agp_name in order_agp_names:
                            agp_name = str(agp_name).strip() if agp_name else ""
                            if agp_name:
                                unique_agp_names.add(agp_name)
                                if agp_name not in cases_by_agp:
                                    cases_by_agp[agp_name] = []
                                cases_by_agp[agp_name].append((case_id, case_data))
            
            logging.info(f"📚 Collected {len(unique_agp_names)} unique AGP names from all sources (respondent_lawyer, additional_respondent_lawyers, order_agp_names)")

            # Step 2: Use ENHANCED fuzzy matching with initials support
            matched_agp, confidence = get_user_manager().match_user_name_to_agp(
                user_name, list(unique_agp_names)
            )

            logging.info(
                f"🤖 Enhanced Fuzzy Matching: '{user_name}' → '{matched_agp}' (confidence: {confidence:.2%})"
            )

            if (
                matched_agp and confidence >= 0.50
            ):  # Lowered threshold to 50% for initial-based matching
                # Step 3: Find ALL similar AGP name variants (handle formatting inconsistencies)
                # Normalize the matched AGP name for comparison
                from UserMatterMatcher import UserMatterMatcher

                matcher = UserMatterMatcher()
                matched_normalized = matcher.normalize_name(matched_agp)

                # Collect cases from all variants that normalize to the same name
                matched_cases = []
                matched_variants = []
                for agp_variant, variant_cases in cases_by_agp.items():
                    if matcher.normalize_name(agp_variant) == matched_normalized:
                        matched_cases.extend(variant_cases)
                        matched_variants.append(agp_variant)

                logging.info(
                    f"📊 Found {len(matched_variants)} AGP variants for '{matched_agp}': {matched_variants[:5]}..."
                )
                logging.info(
                    f"📁 Total cases across all variants: {len(matched_cases)}"
                )

                for case_id, case_data in matched_cases:
                    board_date_raw = case_data.get("board_date")

                    if board_date_raw:
                        try:
                            # Handle both Firestore Timestamp and string formats
                            if isinstance(board_date_raw, str):
                                board_date = datetime.strptime(
                                    board_date_raw, "%Y-%m-%d"
                                )
                                board_date_str = board_date_raw
                            else:
                                # Firestore DatetimeWithNanoseconds object - convert to naive datetime
                                board_date = board_date_raw.replace(tzinfo=None)
                                board_date_str = board_date.strftime("%Y-%m-%d")

                            # Check if case falls within date range
                            if (
                                start_dt <= board_date <= end_dt
                                and case_id not in case_ids
                            ):
                                case_ids.add(case_id)

                                # Determine fee and result based on order analysis
                                fee_info = calculate_case_fee(case_data)

                                # Extract parties information
                                parties = extract_parties_info(case_data)

                                bill_entry = {
                                    "id": case_id,
                                    "date": board_date_str,
                                    "case_detail": f"{case_data.get('case_type')}/{case_data.get('case_no')}/{case_data.get('case_year')}",
                                    "case_type": case_data.get('case_type', ''),
                                    "case_no": case_data.get('case_no', ''),
                                    "case_year": case_data.get('case_year', ''),
                                    "parties_name": parties,
                                    "results": fee_info["result"],
                                    "fees_rs": fee_info["fee"],
                                    "agp_name": matched_agp,  # Show the actual AGP name from data
                                    "user_name": user_name,  # Show the selected user name
                                    "name_match_confidence": round(
                                        confidence, 3
                                    ),  # Include confidence score
                                    "editable": True,
                                }
                                bill_entries.append(bill_entry)
                        except ValueError as date_error:
                            logging.warning(
                                f"Invalid date format for case {case_id}: {board_date_str}"
                            )
                            continue

                logging.info(
                    f"✅ Found {len(bill_entries)} bill entries for user '{user_name}'"
                )
            else:
                error_msg = f"No matching AGP found for user '{user_name}' with sufficient confidence (best match: '{matched_agp}' at {confidence:.1%}). Need at least 50%."
                logging.warning(f"⚠️ {error_msg}")
                return JSONResponse(
                    status_code=400,
                    content={
                        "error": error_msg,
                        "user_name": user_name,
                        "best_match": matched_agp,
                        "confidence": round(confidence, 3),
                        "threshold_required": 0.50,
                        "suggestion": "Try using a different name format or configure the user's name to match board data format",
                    },
                )
        else:
            # Non-admin or admin generating their own bill - use user-case-mappings
            mappings_ref = db.collection("user-case-mappings")
            query = mappings_ref.where("user_id", "==", user_id)
            mappings = query.stream()

            for mapping_doc in mappings:
                mapping_data = mapping_doc.to_dict()
                case_id = mapping_data.get("case_id")

                # Get case details from daily-boards
                case_ref = db.collection("daily-boards").document(case_id)
                case_doc = case_ref.get()

                if case_doc.exists:
                    case_data = case_doc.to_dict()
                    board_date_raw = case_data.get("board_date")

                    if board_date_raw:
                        try:
                            # Handle both Firestore Timestamp and string formats
                            if isinstance(board_date_raw, str):
                                board_date = datetime.strptime(
                                    board_date_raw, "%Y-%m-%d"
                                )
                                board_date_str = board_date_raw
                            else:
                                # Firestore DatetimeWithNanoseconds object - convert to naive datetime
                                board_date = board_date_raw.replace(tzinfo=None)
                                board_date_str = board_date.strftime("%Y-%m-%d")

                            # Check if case falls within date range
                            if (
                                start_dt <= board_date <= end_dt
                                and case_id not in case_ids
                            ):
                                case_ids.add(case_id)

                                # Determine fee and result based on order analysis
                                fee_info = calculate_case_fee(case_data)

                                # Extract parties information
                                parties = extract_parties_info(case_data)

                                bill_entry = {
                                    "id": case_id,
                                    "date": board_date_str,
                                    "case_detail": f"{case_data.get('case_type')}/{case_data.get('case_no')}/{case_data.get('case_year')}",
                                    "case_type": case_data.get('case_type', ''),
                                    "case_no": case_data.get('case_no', ''),
                                    "case_year": case_data.get('case_year', ''),
                                    "parties_name": parties,
                                    "results": fee_info["result"],
                                    "fees_rs": fee_info["fee"],
                                    "confidence_score": mapping_data.get(
                                        "confidence_score", 0.0
                                    ),
                                    "match_source": mapping_data.get("match_source"),
                                    "agp_name": case_data.get("agp_name", "N/A"),
                                    "editable": True,
                                }
                                bill_entries.append(bill_entry)

                        except ValueError as date_error:
                            logging.warning(
                                f"Invalid date format for case {case_id}: {board_date_str}"
                            )
                            continue

        # Sort by date
        bill_entries.sort(key=lambda x: x["date"])

        # Add debug information
        response_data = {
            "user_id": user_id,
            "user_name": user_name if user_name else "self",
            "date_range": {"start": start_date, "end": end_date},
            "total_entries": len(bill_entries),
            "total_fees": sum(entry["fees_rs"] for entry in bill_entries),
            "bill_entries": bill_entries,
        }

        # Add matching debug info for admin fuzzy matching
        if user_name and "matched_agp" in locals():
            response_data["debug_info"] = {
                "requested_name": user_name,
                "matched_agp_name": matched_agp,
                "match_confidence": round(confidence, 3),
                "total_cases_for_agp": len(cases_by_agp.get(matched_agp, [])),
                "cases_in_date_range": len(bill_entries),
            }

        return JSONResponse(content=response_data)

    except Exception as e:
        logging.error(f"Error generating bill data: {e}")
        return JSONResponse(
            status_code=500,
            content={"error": f"Failed to generate bill data: {str(e)}"},
        )


def generate_bill_number_safe(db, user_id: str, year: int) -> tuple:
    """Generate unique bill number with year and sequence for a user (transaction-safe)"""
    try:
        # Use a counter document per user per year to ensure atomic increments
        counter_id = f"{user_id}_{year}"
        counter_ref = db.collection("bill-counters").document(counter_id)
        
        # Use Firestore transaction to atomically increment counter
        @firestore.transactional
        def increment_counter(transaction):
            counter_doc = counter_ref.get(transaction=transaction)
            
            if counter_doc.exists:
                current_seq = counter_doc.to_dict().get("sequence", 0)
                next_sequence = current_seq + 1
            else:
                # First bill for this user in this year
                next_sequence = 1
            
            # Update counter atomically
            transaction.set(counter_ref, {
                "user_id": user_id,
                "year": year,
                "sequence": next_sequence,
                "last_updated": firestore.SERVER_TIMESTAMP
            })
            
            return next_sequence
        
        # Execute transaction
        transaction = db.transaction()
        next_sequence = increment_counter(transaction)
        
        # Format: BILL/YEAR/SEQUENCE (e.g., BILL/2025/001)
        bill_number = f"BILL/{year}/{next_sequence:03d}"
        
        logging.info(f"✨ Generated bill number: {bill_number} for user {user_id}")
        return bill_number, next_sequence
        
    except Exception as e:
        logging.error(f"Error generating bill number: {e}")
        # Fallback to timestamp-based number (should rarely happen)
        import time
        timestamp_seq = int(time.time()) % 10000
        return f"BILL/{year}/{timestamp_seq:04d}", timestamp_seq


def generate_month_description(start_date: str, end_date: str) -> str:
    """Generate month description from date range (e.g., 'January 2025 - March 2025')"""
    try:
        start_dt = datetime.strptime(start_date, "%Y-%m-%d")
        end_dt = datetime.strptime(end_date, "%Y-%m-%d")
        
        # Same month
        if start_dt.month == end_dt.month and start_dt.year == end_dt.year:
            return start_dt.strftime("%B %Y")
        
        # Different months, same year
        if start_dt.year == end_dt.year:
            return f"{start_dt.strftime('%B')} - {end_dt.strftime('%B %Y')}"
        
        # Different years
        return f"{start_dt.strftime('%B %Y')} - {end_dt.strftime('%B %Y')}"
    except Exception as e:
        logging.error(f"Error generating month description: {e}")
        return f"{start_date} to {end_date}"


@app.post("/bills/save", tags=["Bill Generation"])
async def save_bill_entries(request: Request, current_user=Depends(get_current_user)):
    """Save bill entries with unique bill number and year for logged-in user"""
    try:
        db = firestore.client()
        user_id = current_user.get("uid")
        body = await request.json()

        bill_entries = body.get("bill_entries", [])
        bill_metadata = body.get("metadata", {})
        
        # Get date range from metadata (frontend sends startDate/endDate)
        date_range = bill_metadata.get("date_range", {})
        start_date = date_range.get("startDate", date_range.get("start", ""))
        end_date = date_range.get("endDate", date_range.get("end", ""))
        
        # Determine bill year from date range (use end date year)
        current_year = datetime.now().year
        if end_date:
            try:
                end_dt = datetime.strptime(end_date, "%Y-%m-%d")
                current_year = end_dt.year
            except:
                pass
        
        # Generate unique bill number (transaction-safe to prevent duplicates)
        bill_number, bill_sequence = generate_bill_number_safe(db, user_id, current_year)
        
        # Generate month description
        month_description = generate_month_description(start_date, end_date) if start_date and end_date else ""

        # Create a bill document with bill number and year
        bill_data = {
            "user_id": user_id,
            "bill_number": bill_number,
            "bill_year": current_year,
            "bill_sequence": bill_sequence,
            "month_description": month_description,
            "created_at": firestore.SERVER_TIMESTAMP,
            "updated_at": firestore.SERVER_TIMESTAMP,
            "metadata": bill_metadata,
            "entries": bill_entries,
            "total_entries": len(bill_entries),
            "total_fees": sum(entry.get("fees_rs", 0) for entry in bill_entries),
        }

        # Save to user-bills collection
        bill_ref = db.collection("user-bills").document()
        bill_ref.set(bill_data)
        bill_id = bill_ref.id

        logging.info(f"✅ Bill saved: {bill_number} for user {user_id}, {month_description}")

        return JSONResponse(
            content={
                "success": True,
                "bill_id": bill_id,
                "bill_number": bill_number,
                "bill_year": current_year,
                "month_description": month_description,
                "total_entries": len(bill_entries),
                "total_fees": bill_data["total_fees"],
            }
        )

    except Exception as e:
        logging.error(f"Error saving bill entries: {e}")
        import traceback
        traceback.print_exc()
        return JSONResponse(
            status_code=500, content={"error": f"Failed to save bill entries: {str(e)}"}
        )


@app.get("/bills/my-bills", tags=["Bill Generation"])
async def get_my_bills(
    limit: int = Query(20, description="Maximum number of bills to return"),
    user_id_filter: Optional[str] = Query(None, description="Filter by user ID (admin only)"),
    current_user=Depends(get_current_user),
):
    """Get saved bills - logged-in user's bills or all bills (admin only)"""
    try:
        db = firestore.client()
        user_id = current_user.get("uid")
        is_admin = get_user_manager().is_admin(user_id)

        bills_ref = db.collection("user-bills")
        
        # Admin can view all bills or filter by specific user
        if is_admin and user_id_filter:
            # Admin viewing specific user's bills
            query = (
                bills_ref.where("user_id", "==", user_id_filter)
                .order_by("created_at", direction=firestore.Query.DESCENDING)
                .limit(limit)
            )
            target_user_id = user_id_filter
        elif is_admin and not user_id_filter:
            # Admin viewing all bills
            query = bills_ref.order_by("created_at", direction=firestore.Query.DESCENDING).limit(limit)
            target_user_id = "all"
        else:
            # Regular user - only their own bills
            query = (
                bills_ref.where("user_id", "==", user_id)
                .order_by("created_at", direction=firestore.Query.DESCENDING)
                .limit(limit)
            )
            target_user_id = user_id

        bills = query.stream()

        bills_list = []
        for bill_doc in bills:
            bill_data = bill_doc.to_dict()
            bill_data["id"] = bill_doc.id

            # Convert timestamps
            if "created_at" in bill_data and bill_data["created_at"]:
                bill_data["created_at"] = bill_data["created_at"].isoformat()
            if "updated_at" in bill_data and bill_data["updated_at"]:
                bill_data["updated_at"] = bill_data["updated_at"].isoformat()

            bills_list.append(bill_data)

        return JSONResponse(
            content={
                "user_id": target_user_id,
                "is_admin": is_admin,
                "bills": bills_list,
                "total_bills": len(bills_list),
            }
        )

    except Exception as e:
        logging.error(f"Error getting user bills: {e}")
        return JSONResponse(
            status_code=500, content={"error": f"Failed to get user bills: {str(e)}"}
        )


def calculate_case_fee(case_data: Dict) -> Dict:
    """Calculate fee and result based on order analysis"""
    try:
        # Check if order analysis is available
        if not case_data.get("order_analysis_completed"):
            return {"result": "*ADJOURNED*", "fee": 1250}

        # Get order analysis data - use correct field names from order_analyzer
        order_category = case_data.get("order_category", "").upper()
        order_text = case_data.get("order_text", "").lower()
        order_disposal_reason = case_data.get("order_disposal_reason", "").lower()

        # Fee calculation logic based on order category and content
        # Check for disposal first (highest fee)
        if (
            "DISPOSED" in order_category
            or "disposed" in order_text
            or "disposed" in order_disposal_reason
        ):
            return {"result": "WP DISPOSED OF", "fee": 2500}

        # Check for heard & adjourned (middle fee)
        elif "HEARD" in order_category and "ADJOURNED" in order_category:
            return {"result": "HEARD & ADJN.", "fee": 1875}

        # Check for simple adjournment (lowest fee)
        elif "ADJOURNED" in order_category or "adjourned" in order_text:
            # Check if it's due to paucity of time
            if "paucity of time" in order_text or "due to paucity" in order_text:
                return {"result": "ADJOURNED", "fee": 1250}
            else:
                return {"result": "ADJOURNED", "fee": 1250}

        # Default case based on order category
        else:
            # If category indicates any hearing, use heard & adjourned
            if "HEARD" in order_category:
                return {"result": "HEARD & ADJN.", "fee": 1875}
            else:
                # Default to adjourned if category is unclear
                return {"result": "*ADJOURNED*", "fee": 1250}

    except Exception as e:
        logging.error(f"Error calculating case fee for case: {e}")
        return {"result": "*ADJOURNED*", "fee": 1250}


def extract_parties_info(case_data: Dict) -> str:
    """Extract parties information from case data"""
    try:
        # Try to get from order analysis first
        if case_data.get("order_analysis_completed"):
            petitioners = case_data.get("order_petitioners", [])
            respondents = case_data.get("order_respondents", [])

            if petitioners and respondents:
                if isinstance(petitioners, list):
                    petitioner_str = ", ".join(petitioners[:2])  # Take first 2
                else:
                    petitioner_str = str(petitioners)

                if isinstance(respondents, list):
                    respondent_str = ", ".join(respondents[:2])  # Take first 2
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
    user_name: Optional[str] = Query(None, description="User name for bill header (admin only)"),
    current_user=Depends(get_current_user),
):
    """Export bill data as Excel format matching AGP bill specification"""
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Font, Alignment, Border, Side
        from datetime import datetime
        import io
        from fastapi.responses import StreamingResponse
        
        db = firestore.client()
        user_id = current_user.get("uid")
        is_admin = get_user_manager().is_admin(user_id)

        # Get bill data - either from saved bill or generate fresh
        agp_name = "ASSISTANT GOVERNMENT PLEADER"
        bill_number = f"BILL/{datetime.now().strftime('%m')}/{datetime.now().year}"
        
        if bill_id:
            # Export saved bill
            bill_ref = db.collection("user-bills").document(bill_id)
            bill_doc = bill_ref.get()

            if not bill_doc.exists:
                return JSONResponse(
                    status_code=404, content={"error": "Bill not found"}
                )

            bill_data = bill_doc.to_dict()
            if bill_data.get("user_id") != user_id and not is_admin:
                return JSONResponse(status_code=403, content={"error": "Access denied"})

            entries = bill_data.get("entries", [])
            metadata = bill_data.get("metadata", {})
            agp_name = entries[0].get("agp_name", agp_name) if entries else agp_name
            filename = f"bill_{bill_id}.xlsx"

        elif start_date and end_date:
            # Generate fresh export
            response = await generate_bill_data(start_date, end_date, user_name, current_user)
            if response.status_code != 200:
                return response

            response_data = json.loads(response.body.decode())
            entries = response_data.get("bill_entries", [])
            metadata = {"date_range": {"start": start_date, "end": end_date}}
            
            # Get AGP name from entries or debug info
            if entries and entries[0].get("agp_name"):
                agp_name = entries[0].get("agp_name")
            elif "debug_info" in response_data and response_data["debug_info"].get("matched_agp_name"):
                agp_name = response_data["debug_info"]["matched_agp_name"]
            
            filename = f"AGP_Bill_{start_date}_to_{end_date}.xlsx"

        else:
            return JSONResponse(
                status_code=400,
                content={
                    "error": "Either bill_id or both start_date and end_date are required"
                },
            )

        if not entries:
            return JSONResponse(
                status_code=404, content={"error": "No bill entries found"}
            )

        # Create Excel workbook
        wb = Workbook()
        ws = wb.active
        ws.title = "Bill"

        # Define styles
        title_font = Font(bold=True, size=12)
        header_font = Font(bold=True, size=11)
        border_thin = Border(
            left=Side(style='thin'), 
            right=Side(style='thin'), 
            top=Side(style='thin'), 
            bottom=Side(style='thin')
        )
        center_align = Alignment(horizontal='center', vertical='center', wrap_text=True)
        left_align = Alignment(horizontal='left', vertical='center', wrap_text=True)

        # Parse dates for header
        date_range = metadata.get("date_range", {})
        start_dt = datetime.strptime(date_range.get("start", start_date), "%Y-%m-%d")
        end_dt = datetime.strptime(date_range.get("end", end_date), "%Y-%m-%d")
        period_str = f"{start_dt.strftime('%B %Y').upper()} - {end_dt.strftime('%B %Y').upper()}"

        # Row counter
        current_row = 1

        # Header Section
        # Title
        ws.merge_cells(f'A{current_row}:H{current_row}')
        ws[f'A{current_row}'] = f"STATEMENT OF PROFESSIONAL FEES BILL OF {agp_name.upper()}"
        ws[f'A{current_row}'].font = title_font
        ws[f'A{current_row}'].alignment = center_align
        current_row += 1

        # Subtitle
        ws.merge_cells(f'A{current_row}:H{current_row}')
        ws[f'A{current_row}'] = "A.S.(WRIT CELL),HIGH COURT, MUMBAI FOR CONDUCTING WRIT MATTERS ETC."
        ws[f'A{current_row}'].alignment = center_align
        current_row += 1

        # Government Resolution
        ws.merge_cells(f'A{current_row}:H{current_row}')
        ws[f'A{current_row}'] = "SANCTIONED VIDE:- GOVERNMENT OF MAHARASHTRA\nLAW AND JUDICIARY DEPARTMENT,\nGOVERNMENT RESOLUTION NO. MEETING-GPH-2023/C.R.29/D-14,\nDATED-30TH OCTOBER, 2023"
        ws[f'A{current_row}'].alignment = center_align
        current_row += 1

        # Period and Bill Number
        ws.merge_cells(f'A{current_row}:D{current_row}')
        ws[f'A{current_row}'] = f"MONTHS :- {period_str}"
        ws.merge_cells(f'E{current_row}:H{current_row}')
        ws[f'E{current_row}'] = f"BILL NO:- {bill_number}"
        ws[f'E{current_row}'].alignment = Alignment(horizontal='right', vertical='center')
        current_row += 1

        # Declaration
        ws.merge_cells(f'A{current_row}:H{current_row}')
        declaration_text = (
            f"DECLARATION : I hereby certify that the below mentioned matters were allotted to me by the Government Pleader, "
            f"I personally appeared in the below mentioned matters. The below mentioned entries/information given in above columns "
            f"are true and correct to the best of my knowledge and belief. I further certify that nothing is suppressed by me. "
            f"Also, the fees which is claimed in bill no. {bill_number} has not been claimed by me earlier."
        )
        ws[f'A{current_row}'] = declaration_text
        ws[f'A{current_row}'].alignment = left_align
        ws.row_dimensions[current_row].height = 60
        current_row += 1

        # Column Headers
        headers = ["SR. NO.", "DATE", "CASE TYPE", "CASE NO", "CASE YEAR", "RESULTS", "PARTIES NAME", "FEES (RS.)"]
        for col_num, header in enumerate(headers, 1):
            cell = ws.cell(row=current_row, column=col_num, value=header)
            cell.font = header_font
            cell.alignment = center_align
            cell.border = border_thin
        current_row += 1

        # Data rows
        total_fees = 0
        for idx, entry in enumerate(entries, 1):
            # Parse case_detail to extract case type, number, year
            case_detail = entry.get("case_detail", "")
            case_parts = case_detail.split("/")
            case_type = case_parts[0] if len(case_parts) > 0 else ""
            case_no = case_parts[1] if len(case_parts) > 1 else ""
            case_year = case_parts[2] if len(case_parts) > 2 else ""

            # Format date
            date_str = entry.get("date", "")
            try:
                date_obj = datetime.strptime(date_str, "%Y-%m-%d")
                formatted_date = date_obj.strftime("%d-%m-%Y")
            except:
                formatted_date = date_str

            row_data = [
                idx,  # SR. NO.
                formatted_date,  # DATE
                case_type,  # CASE TYPE
                case_no,  # CASE NO
                case_year,  # CASE YEAR
                entry.get("results", ""),  # RESULTS
                entry.get("parties_name", ""),  # PARTIES NAME
                entry.get("fees_rs", 0),  # FEES (RS.)
            ]

            for col_num, value in enumerate(row_data, 1):
                cell = ws.cell(row=current_row, column=col_num, value=value)
                cell.border = border_thin
                if col_num == 1 or col_num == 8:  # SR. NO. and FEES
                    cell.alignment = center_align
                elif col_num == 7:  # PARTIES NAME
                    cell.alignment = left_align
                else:
                    cell.alignment = center_align

            total_fees += entry.get("fees_rs", 0)
            current_row += 1

        # Total row
        ws.merge_cells(f'A{current_row}:G{current_row}')
        ws[f'A{current_row}'] = "TOTAL:"
        ws[f'A{current_row}'].font = header_font
        ws[f'A{current_row}'].alignment = Alignment(horizontal='right', vertical='center')
        ws[f'A{current_row}'].border = border_thin
        
        cell = ws.cell(row=current_row, column=8, value=total_fees)
        cell.font = header_font
        cell.alignment = center_align
        cell.border = border_thin

        # Adjust column widths
        ws.column_dimensions['A'].width = 10  # SR. NO.
        ws.column_dimensions['B'].width = 15  # DATE
        ws.column_dimensions['C'].width = 12  # CASE TYPE
        ws.column_dimensions['D'].width = 12  # CASE NO
        ws.column_dimensions['E'].width = 12  # CASE YEAR
        ws.column_dimensions['F'].width = 18  # RESULTS
        ws.column_dimensions['G'].width = 50  # PARTIES NAME
        ws.column_dimensions['H'].width = 15  # FEES (RS.)

        # Save to BytesIO
        output = io.BytesIO()
        wb.save(output)
        output.seek(0)

        # Return as downloadable file
        return StreamingResponse(
            output,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )

    except Exception as e:
        logging.error(f"Error exporting bill to Excel: {e}")
        import traceback
        traceback.print_exc()
        return JSONResponse(
            status_code=500, content={"error": f"Failed to export bill: {str(e)}"}
        )


@app.get("/bills/{bill_id}", tags=["Bill Generation"])
async def get_bill_details(bill_id: str, current_user=Depends(get_current_user)):
    """Get details of a specific saved bill - admin can view any bill"""
    try:
        db = firestore.client()
        user_id = current_user.get("uid")
        is_admin = get_user_manager().is_admin(user_id)

        bill_ref = db.collection("user-bills").document(bill_id)
        bill_doc = bill_ref.get()

        if not bill_doc.exists:
            return JSONResponse(status_code=404, content={"error": "Bill not found"})

        bill_data = bill_doc.to_dict()

        # Check ownership - admin can view any bill, regular user only their own
        if not is_admin and bill_data.get("user_id") != user_id:
            return JSONResponse(status_code=403, content={"error": "Access denied"})

        bill_data["id"] = bill_doc.id

        # Convert timestamps
        if "created_at" in bill_data and bill_data["created_at"]:
            bill_data["created_at"] = bill_data["created_at"].isoformat()
        if "updated_at" in bill_data and bill_data["updated_at"]:
            bill_data["updated_at"] = bill_data["updated_at"].isoformat()

        return JSONResponse(content=bill_data)

    except Exception as e:
        logging.error(f"Error getting bill details: {e}")
        return JSONResponse(
            status_code=500, content={"error": f"Failed to get bill details: {str(e)}"}
        )


@app.delete("/bills/{bill_id}", tags=["Bill Generation"])
async def delete_bill(bill_id: str, current_user=Depends(get_current_user)):
    """Delete a saved bill - admin can delete any bill"""
    try:
        db = firestore.client()
        user_id = current_user.get("uid")
        is_admin = get_user_manager().is_admin(user_id)

        bill_ref = db.collection("user-bills").document(bill_id)
        bill_doc = bill_ref.get()

        if not bill_doc.exists:
            return JSONResponse(status_code=404, content={"error": "Bill not found"})

        bill_data = bill_doc.to_dict()

        # Check ownership - admin can delete any bill, regular user only their own
        if not is_admin and bill_data.get("user_id") != user_id:
            return JSONResponse(status_code=403, content={"error": "Access denied"})

        # Delete the bill
        bill_ref.delete()

        return JSONResponse(
            content={"success": True, "message": "Bill deleted successfully"}
        )

    except Exception as e:
        logging.error(f"Error deleting bill: {e}")
        return JSONResponse(
            status_code=500, content={"error": f"Failed to delete bill: {str(e)}"}
        )


@app.get("/auto-orders/search", tags=["Auto Order Management"])
async def search_orders(
    petitioner_search: str = Query(None, description="Search in petitioner names"),
    respondent_search: str = Query(None, description="Search in respondent names"),
    case_type: str = Query(None, description="Filter by case type"),
    case_year: str = Query(None, description="Filter by case year"),
    order_category: str = Query(None, description="Filter by order category"),
    limit: int = Query(100, description="Maximum results to return"),
    current_user=Depends(get_current_user),
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

        result = get_auto_order_manager().search_orders(search_params)

        if result.get("success"):
            return JSONResponse(content=result)
        else:
            return JSONResponse(
                status_code=500, content={"error": result.get("error", "Unknown error")}
            )

    except Exception as e:
        logging.error(f"Error in search-orders: {e}")
        return JSONResponse(
            status_code=500, content={"error": f"Failed to search orders: {str(e)}"}
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

        return JSONResponse(
            content={
                "total_indexed_orders": total_indexed,
                "category_distribution": categories,
                "case_type_distribution": case_types,
                "year_distribution": years,
            }
        )

    except Exception as e:
        logging.error(f"Error getting search index stats: {e}")
        return JSONResponse(
            status_code=500, content={"error": f"Failed to get search stats: {str(e)}"}
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
    current_user=Depends(get_current_user),
):
    """Get structured tabular data from analyzed-orders collection with Order Date, Petitioner, Respondent, AGP/GP list, Category, and order links"""
    try:
        db = firestore.client()
        query_ref = db.collection("analyzed-orders")

        # Apply filters - only filter on indexed fields
        if order_category:
            query_ref = query_ref.where("order_category", "==", order_category)
        if date_validation_valid is not None:
            query_ref = query_ref.where(
                "date_validation.valid", "==", date_validation_valid
            )

        # Execute query with limit
        docs = query_ref.limit(limit).stream()

        results = []
        for doc in docs:
            data = doc.to_dict()

            # Apply text-based filters (post-query)
            if petitioner_search:
                petitioners = data.get("petitioners", [])
                if not any(
                    petitioner_search.lower() in pet.lower() for pet in petitioners
                ):
                    continue

            if respondent_search:
                respondents = data.get("respondents", [])
                if not any(
                    respondent_search.lower() in resp.lower() for resp in respondents
                ):
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
                "case_type": (
                    data.get("case_ref", "").split("-")[0]
                    if data.get("case_ref")
                    else None
                ),
                "case_number": (
                    data.get("case_ref", "").split("-")[1]
                    if data.get("case_ref")
                    and len(data.get("case_ref", "").split("-")) > 1
                    else None
                ),
                "case_year": (
                    data.get("case_ref", "").split("-")[-1]
                    if data.get("case_ref")
                    else None
                ),
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
                "created_at": data.get("created_at"),
            }

            results.append(result)

        return JSONResponse(
            content={
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
                    "limit": limit,
                },
            }
        )

    except Exception as e:
        logging.error(f"Error getting tabular data: {e}")
        return JSONResponse(
            status_code=500, content={"error": f"Failed to get tabular data: {str(e)}"}
        )


# Cloud Run entry point - uvicorn will run the app directly
# For Cloud Functions deployment, use a separate functions_entry.py file

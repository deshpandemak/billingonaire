import asyncio
import json
import logging
import os
import posixpath
import sys
from asyncio import Queue
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import firebase_admin
import pandas as pd
import requests
from fastapi import Depends, FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from firebase_admin import auth, credentials, firestore
from pydantic import BaseModel

# Configure logging to show INFO level messages with timestamps for Cloud Log Viewer
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S%z",
)
logger = logging.getLogger(__name__)

_overview_stats_cache: Dict[str, Any] = {"ts": 0.0, "data": None}
_queue_status_cache: Dict[str, Any] = {"ts": 0.0, "data": None}

# Integrate with Google Cloud Logging when running on GCP (Cloud Run sets K_SERVICE)
if os.getenv("K_SERVICE"):
    try:
        import google.cloud.logging as gcp_logging
    except ImportError:
        logger.info(
            "google-cloud-logging not installed; using standard logging only.",
        )
    else:
        try:
            _gcp_log_client = gcp_logging.Client()
            _gcp_log_client.setup_logging(log_level=logging.INFO)
            logger.info("Google Cloud Logging integration enabled")
        except Exception:
            logger.warning(
                "Failed to initialize Google Cloud Logging; falling back to standard logging.",
                exc_info=True,
            )

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from Board import Board  # noqa: E402
from CourtScraper import BombayHighCourtScraper  # noqa: E402
from Dashboard import DashboardData  # noqa: E402
from OrderManager import OrderManager  # noqa: E402
from UserManager import UserManager  # noqa: E402
from UserMatterMatcher import UserRole  # noqa: E402

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

# Lazy Firebase initialization - deferred until first use to avoid blocking port binding
_firebase_initialized = False
_firebase_init_error = None


def ensure_firebase():
    """Initialize Firebase Admin SDK on first use"""
    global _firebase_initialized, _firebase_init_error
    if not _firebase_initialized:
        if not firebase_admin._apps:
            import json

            # Log environment info for debugging
            logger.info("🔍 Firebase initialization - Environment check:")
            logger.info(
                f"   - Running in Cloud: {os.environ.get('K_SERVICE') is not None}"
            )
            logger.info(
                f"   - Service account key available: {bool(os.environ.get('GCLOUD_SERVICE_ACCOUNT_KEY'))}"
            )
            logger.info(
                f"   - Google credentials env: {bool(os.environ.get('GOOGLE_APPLICATION_CREDENTIALS'))}"
            )

            gcloud_key = os.environ.get("GCLOUD_SERVICE_ACCOUNT_KEY")
            if gcloud_key:
                try:
                    # Environment with service account key (local/Replit/Cloud Run with secret)
                    cred_dict = json.loads(gcloud_key)
                    cred = credentials.Certificate(cred_dict)
                    firebase_admin.initialize_app(cred)
                    logger.info(
                        "✅ Firebase Admin SDK initialized with service account key"
                    )
                except json.JSONDecodeError as e:
                    _firebase_init_error = (
                        f"Invalid JSON in GCLOUD_SERVICE_ACCOUNT_KEY: {str(e)}"
                    )
                    logger.error(f"❌ {_firebase_init_error}")
                    raise HTTPException(
                        status_code=500,
                        detail="Server configuration error: Invalid Firebase service account JSON. Contact administrator.",
                    )
                except Exception as e:
                    _firebase_init_error = f"Failed to initialize Firebase with service account key: {str(e)}"
                    logger.error(f"❌ {_firebase_init_error}")
                    raise HTTPException(
                        status_code=500,
                        detail="Server configuration error: Firebase credentials invalid. Contact administrator.",
                    )
            else:
                # Try Application Default Credentials (Cloud Run, Compute Engine, etc.)
                try:
                    logger.info(
                        "🔄 Attempting to initialize with Application Default Credentials..."
                    )
                    firebase_admin.initialize_app()
                    logger.info(
                        "✅ Firebase Admin SDK initialized with Application Default Credentials"
                    )
                except Exception as e:
                    # Final attempt: try with explicit project ID
                    try:
                        logger.info("🔄 Retrying with explicit project configuration...")
                        project_id = os.environ.get(
                            "GCP_PROJECT",
                            os.environ.get("GOOGLE_CLOUD_PROJECT", "billingonaire"),
                        )
                        config = {
                            "projectId": project_id,
                        }
                        firebase_admin.initialize_app(config)
                        logger.info(
                            f"✅ Firebase Admin SDK initialized with project ID: {project_id}"
                        )
                    except Exception as e2:
                        _firebase_init_error = (
                            f"Firebase Admin SDK initialization failed. "
                            f"ADC Error: {str(e)}. Project Config Error: {str(e2)}. "
                            f"Missing GCLOUD_SERVICE_ACCOUNT_KEY environment variable."
                        )
                        logger.error(f"❌ {_firebase_init_error}")
                        logger.error(
                            "💡 To fix: Set GCLOUD_SERVICE_ACCOUNT_KEY environment variable with Firebase service account JSON"
                        )
                        logger.error(
                            "💡 Or ensure Cloud Run service account has Firebase Admin permissions"
                        )
                        raise HTTPException(
                            status_code=500,
                            detail="Server configuration error: Firebase credentials not configured. Contact administrator.",
                        )
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
order_processing_queue: Queue[Any] = Queue()
order_processing_queue: Queue[Any] = Queue()
processing_active = False
analysis_processing_queue: Queue[Any] = Queue()
analysis_processing_queue: Queue[Any] = Queue()
analysis_processing_active = False
# Thread pool executor for blocking operations (configurable via env var)
try:
    MAX_WORKERS = max(1, int(os.environ.get("ORDER_PROCESSING_WORKERS", "5")))
except (ValueError, TypeError):
    logger.warning("Invalid ORDER_PROCESSING_WORKERS value, using default of 5")
    MAX_WORKERS = 5
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
        logger.info("Attempting to verify ID token for authentication")
        decoded_token = auth.verify_id_token(id_token)
        logger.info(f"Token verified successfully for user: {decoded_token.get('uid')}")
        return decoded_token
    except Exception as e:
        logger.error(f"Token verification failed: {str(e)}")
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
            logger.info(f"Added case {case_info['case_ref']} to order processing queue")

        # Start background processing if not already active
        await ensure_background_processing_active()

    except Exception as e:
        logger.error(f"Error adding cases to processing queue: {e}")


async def process_order_queue_worker(worker_id: int):
    """Background worker to process order queue - one task per worker"""
    logger.info(f"🚀 Order processing worker {worker_id} started")

    while True:
        try:
            # Get case from queue (wait indefinitely for new items)
            case_info = await order_processing_queue.get()

            logger.info(
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
                    logger.info(
                        f"[Worker {worker_id}] ✅ Successfully processed order for {case_info['case_ref']} - Status should be 'analysed' in database"
                    )

                    # Automatically map case to users after successful analysis
                    try:
                        await auto_map_case_to_users(case_info.get("id"), case_info)
                        logger.info(
                            f"✅ Successfully mapped case {case_info['case_ref']} to users"
                        )
                    except Exception as mapping_error:
                        logger.error(
                            f"❌ Error mapping case {case_info['case_ref']} to users: {mapping_error}"
                        )

                elif result.get("download_success"):
                    # Order was downloaded (or already linked) but analysis failed.
                    # Auto-queue for the analysis worker so it will be retried without
                    # admin intervention — this prevents cases from getting stuck at
                    # "linked" status indefinitely.
                    logger.warning(
                        f"⚠️ Order downloaded but analysis failed for {case_info['case_ref']}: {result.get('error', 'Unknown error')} — auto-queuing for analysis retry"
                    )
                    try:
                        await analysis_processing_queue.put(
                            {
                                "id": case_info.get("id"),
                                "case_ref": case_info["case_ref"],
                                "board_date": case_info.get("board_date"),
                            }
                        )
                        await ensure_background_analysis_processing_active()
                        logger.info(
                            f"📋 Auto-queued {case_info['case_ref']} for analysis retry"
                        )
                    except Exception as queue_error:
                        logger.error(
                            f"❌ Failed to auto-queue {case_info['case_ref']} for analysis: {queue_error}"
                        )
                else:
                    logger.warning(
                        f"⚠️ Order processing failed for {case_info['case_ref']}: {result.get('error', 'Unknown error')}"
                    )

            except asyncio.TimeoutError:
                logger.error(
                    f"❌ [Worker {worker_id}] TIMEOUT after 5 minutes processing {case_info['case_ref']} - moving to next case"
                )
                try:
                    get_auto_order_manager().case_store.transition_lifecycle(
                        case_info["case_ref"],
                        "fetch_failed_terminal",
                        reason="Worker timeout after 5 minutes",
                        force=True,
                        metadata={"source": "worker_timeout"},
                        event_type="fetch_timeout",
                    )
                except Exception as lc_err:
                    logger.error(
                        f"Failed to mark lifecycle failed after timeout: {lc_err}"
                    )
            except Exception as e:
                logger.error(
                    f"❌ Error processing order for {case_info['case_ref']}: {e}"
                )
                import traceback

                logger.error(f"Full traceback: {traceback.format_exc()}")
                try:
                    get_auto_order_manager().case_store.transition_lifecycle(
                        case_info["case_ref"],
                        "fetch_failed_terminal",
                        reason=f"Worker error: {str(e)[:200]}",
                        force=True,
                        metadata={"source": "worker_exception"},
                        event_type="fetch_error",
                    )
                except Exception as lc_err:
                    logger.error(
                        f"Failed to mark lifecycle failed after exception: {lc_err}"
                    )

            # Mark task as done
            order_processing_queue.task_done()

        except Exception as e:
            logger.error(f"Background order processing error: {e}")
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
                logger.error(
                    f"Error processing user {user_doc.id} for case mapping: {user_error}"
                )
                continue

        if mapped_users:
            logger.info(
                f"Case {case_info.get('case_ref')} mapped to {len(mapped_users)} users: {[u['user_id'] for u in mapped_users]}"
            )
        else:
            logger.info(f"No user matches found for case {case_info.get('case_ref')}")

    except Exception as e:
        logger.error(f"Error in auto_map_case_to_users: {e}")
        raise


async def ensure_background_processing_active():
    """Ensure background order processing is running with multiple workers"""
    global processing_active

    if not processing_active:
        processing_active = True
        # Start multiple worker tasks (one per thread pool worker)
        for worker_id in range(MAX_WORKERS):
            asyncio.create_task(process_order_queue_worker(worker_id))
        logger.info(f"🚀 Started {MAX_WORKERS} background order processing worker(s)")
    else:
        logger.info(
            f"✅ Background processing already active with {MAX_WORKERS} workers"
        )


def _run_case_analysis_job(case_info: Dict) -> Dict:
    """Blocking analysis job used by async worker executor."""
    manager = get_auto_order_manager()
    case_ref = case_info.get("case_ref")
    case_id = case_info.get("id")
    board_date = case_info.get("board_date")

    order_context = manager._get_case_order_context(case_ref)
    order_link = order_context.get("order_link")

    if not order_link:
        manager.case_store.transition_lifecycle(
            case_ref,
            "analysis_failed_retryable",
            reason="No order link available for analysis",
            metadata={"source": "analysis_queue", "case_id": case_id},
            event_type="analysis_queue_no_link",
        )
        return {
            "case_ref": case_ref,
            "analysis_success": False,
            "error": "No order link available for analysis",
        }

    case_data = {
        "id": case_id,
        "case_ref": case_ref,
        "order_link": order_link,
        "board_date": board_date,
        "order_status": "linked",
    }
    result_template = {
        "case_id": case_id,
        "case_ref": case_ref,
        "download_success": True,
        "analysis_success": False,
        "order_link": order_link,
        "analysis_data": None,
        "error": None,
        "retry_attempts": [],
        "has_existing_order": True,
    }
    return manager._analyze_existing_order(case_data, result_template)


async def process_analysis_queue_worker(worker_id: int):
    """Background worker to process analysis queue."""
    logger.info(f"🚀 Analysis queue worker {worker_id} started")

    while True:
        try:
            case_info = await analysis_processing_queue.get()
            case_ref = case_info.get("case_ref")
            case_id = case_info.get("id")

            logger.info(
                f"[Analysis Worker {worker_id}] 🔎 Processing analysis for {case_ref}"
            )

            try:
                get_auto_order_manager().case_store.transition_lifecycle(
                    case_ref,
                    "analysis_in_progress",
                    metadata={"source": "analysis_queue", "case_id": case_id},
                    event_type="analysis_queue_started",
                )

                loop = asyncio.get_event_loop()
                result = await asyncio.wait_for(
                    loop.run_in_executor(executor, _run_case_analysis_job, case_info),
                    timeout=300.0,
                )

                if result.get("analysis_success"):
                    logger.info(
                        f"[Analysis Worker {worker_id}] ✅ Analysis completed for {case_ref}"
                    )
                    try:
                        await auto_map_case_to_users(case_id, case_info)
                    except Exception as mapping_error:
                        logger.error(
                            f"Error mapping users after analysis for {case_ref}: {mapping_error}"
                        )
                else:
                    error_msg = result.get("error") or "Analysis failed"
                    get_auto_order_manager().case_store.transition_lifecycle(
                        case_ref,
                        "analysis_failed_retryable",
                        reason=error_msg,
                        metadata={"source": "analysis_queue", "case_id": case_id},
                        event_type="analysis_queue_failed",
                    )
                    logger.warning(
                        f"[Analysis Worker {worker_id}] ⚠️ Analysis failed for {case_ref}: {error_msg}"
                    )

            except asyncio.TimeoutError:
                get_auto_order_manager().case_store.transition_lifecycle(
                    case_ref,
                    "analysis_failed_retryable",
                    reason="Analysis worker timeout after 5 minutes",
                    metadata={"source": "analysis_queue", "case_id": case_id},
                    event_type="analysis_queue_timeout",
                )
                logger.error(
                    f"[Analysis Worker {worker_id}] ❌ Timeout while analyzing {case_ref}"
                )
            except Exception as e:
                get_auto_order_manager().case_store.transition_lifecycle(
                    case_ref,
                    "analysis_failed_retryable",
                    reason=str(e),
                    metadata={"source": "analysis_queue", "case_id": case_id},
                    event_type="analysis_queue_exception",
                )
                logger.error(
                    f"[Analysis Worker {worker_id}] ❌ Error analyzing {case_ref}: {e}"
                )

            analysis_processing_queue.task_done()

        except Exception as e:
            logger.error(f"Analysis queue worker error: {e}")
            await asyncio.sleep(5)


async def ensure_background_analysis_processing_active():
    """Ensure background analysis processing is running."""
    global analysis_processing_active

    if not analysis_processing_active:
        analysis_processing_active = True
        for worker_id in range(MAX_WORKERS):
            asyncio.create_task(process_analysis_queue_worker(worker_id))
        logger.info(f"🚀 Started {MAX_WORKERS} background analysis worker(s)")
    else:
        logger.info(
            f"✅ Background analysis processing already active with {MAX_WORKERS} workers"
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
    results: List[Dict[str, Any]] = []
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
                logger.info(f"Starting upload processing for file: {file.filename}")
                board = Board()
                df = board.readFile(file.filename, file.file)
                record_count = len(df) if df is not None else 0
                logger.info(
                    f"PDF processed successfully. Records found: {record_count}"
                )

                if record_count > 0:
                    board.saveData(df)
                    logger.info(f"Data saved successfully for {file.filename}")

                    # Trigger async order processing for uploaded cases
                    await trigger_async_order_processing(df)

                    board_date = None
                    try:
                        board_date = (
                            str(df["board_date"].iloc[0])
                            if "board_date" in df.columns and len(df) > 0
                            else None
                        )
                    except Exception:
                        pass

                    results.append(
                        {
                            "filename": file.filename,
                            "message": "Data saved successfully - Order processing started in background",
                            "records_processed": record_count,
                            "board_date": board_date,
                        }
                    )
                else:
                    logger.warning(f"No records found in {file.filename}")
                    results.append(
                        {
                            "filename": file.filename,
                            "message": "No records found in PDF",
                            "records_processed": 0,
                        }
                    )
                break
            except ConnectionResetError as e:
                logger.error(f"ConnectionResetError on attempt {attempt + 1}: {str(e)}")
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
                logger.error(f"Error processing {file.filename}: {str(e)}")
                logger.error("Stack trace:", exc_info=True)
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

        # Compute name variations so the search screen uses the same
        # case-matching algorithm as bill generation (checks
        # government_pleader, respondent_lawyer and
        # additional_respondent_lawyers with name-variation matching).
        agp_name_variations = None
        if agp_filter and isinstance(agp_filter, str):
            agp_name_variations = get_user_matter_matcher().generate_name_variations(
                agp_filter
            )

        # Generate name variations for the advocate name search field too, so
        # that "Pooja Deshpande" matches "SMT. P.M.J.DESHPANDE, AGP" etc. —
        # the same fuzzy logic used in bill generation.
        advocate_name_variations = None
        advocate_name_raw = search_criteria.get("advocateName") or search_criteria.get(
            "advocate_name"
        )
        if advocate_name_raw and advocate_name_raw.strip():
            advocate_name_variations = (
                get_user_matter_matcher().generate_name_variations(
                    advocate_name_raw.strip()
                )
            )

        data = board.getData(
            search_criteria,
            agp_filter,
            agp_name_variations,
            advocate_name_variations=advocate_name_variations,
        )
        return data
    except Exception as e:
        logger.error(f"Error in data retrieval: {str(e)}")
        raise HTTPException(status_code=500, detail="Error retrieving data")


@app.get("/cases/lifecycle", tags=["Data Retrieval"])
async def get_cases_lifecycle(
    case_type: Optional[str] = Query(None),
    case_number: Optional[str] = Query(None),
    case_year: Optional[str] = Query(None),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    advocate_name: Optional[str] = Query(None),
    order_status: Optional[str] = Query(None),
    order_category: Optional[str] = Query(None),
    lifecycle_status: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    timeline_limit: int = Query(5, ge=0, le=50),
    current_user_with_profile=Depends(get_user_with_profile),
):
    """Return unified board, case, order, and lifecycle sections for each matter."""
    try:
        board = Board()
        search_criteria = {
            "caseType": case_type,
            "caseNumber": case_number,
            "caseYear": case_year,
            "startDate": start_date,
            "endDate": end_date,
            "advocateName": advocate_name,
            "orderStatus": order_status,
            "orderCategory": order_category,
        }

        uid = current_user_with_profile.get("uid")
        agp_filter = get_user_manager().get_user_agp_filter(uid)

        # Use the same name-variation algorithm as bill generation
        agp_name_variations = None
        if agp_filter and isinstance(agp_filter, str):
            agp_name_variations = get_user_matter_matcher().generate_name_variations(
                agp_filter
            )

        rows = board.getData(search_criteria, agp_filter, agp_name_variations)

        case_store = get_auto_order_manager().case_store
        items = []
        for row in rows:
            case_ref = row.get("case_ref")
            if not case_ref:
                case_ref = case_store.build_case_ref(
                    row.get("case_type"), row.get("case_no"), row.get("case_year")
                )

            case_details = case_store.get_case_details(case_ref) or {}
            resolved_lifecycle_status = (
                case_details.get("lifecycle_status")
                or case_store.map_legacy_order_status(
                    case_details.get("latest_order_status") or row.get("order_status")
                )
                or "board_ingested"
            )

            if lifecycle_status and resolved_lifecycle_status != lifecycle_status:
                continue

            timeline = list(case_details.get("lifecycle_events") or [])
            timeline_preview = timeline[-timeline_limit:] if timeline_limit else []

            items.append(
                {
                    "board": {
                        "id": row.get("id"),
                        "board_date": row.get("board_date"),
                        "serial_number": row.get("serial_number"),
                        "file_name": row.get("file_name"),
                        "petitioner_lawyer": row.get("petitioner_lawyer"),
                        "respondent_lawyer": row.get("respondent_lawyer"),
                    },
                    "case": {
                        "case_ref": case_ref,
                        "case_type": row.get("case_type"),
                        "case_no": row.get("case_no"),
                        "case_year": row.get("case_year"),
                        "petitioner": case_details.get("petitioner")
                        or row.get("order_petitioner"),
                        "respondent": case_details.get("respondent")
                        or row.get("order_respondent"),
                        "government_pleader": case_details.get("government_pleader")
                        or row.get("government_pleader")
                        or [],
                    },
                    "order": {
                        "status": case_details.get("latest_order_status")
                        or row.get("order_status")
                        or "not_linked",
                        "link": case_details.get("latest_order_link")
                        or row.get("order_link"),
                        "category": case_details.get("latest_order_category")
                        or row.get("order_category"),
                        "date": case_details.get("latest_order_date")
                        or row.get("order_date"),
                    },
                    "lifecycle": {
                        "status": resolved_lifecycle_status,
                        "updated_at": case_details.get("lifecycle_status_updated_at")
                        or row.get("lifecycle_status_updated_at"),
                        "timeline_preview": timeline_preview,
                        "event_count": len(timeline),
                    },
                }
            )

            if len(items) >= limit:
                break

        return {
            "items": items,
            "count": len(items),
            "filters": {
                "case_type": case_type,
                "case_number": case_number,
                "case_year": case_year,
                "order_status": order_status,
                "order_category": order_category,
                "lifecycle_status": lifecycle_status,
            },
        }

    except Exception as e:
        logger.error(f"Error building lifecycle view: {e}")
        raise HTTPException(status_code=500, detail="Error retrieving lifecycle data")


@app.get("/cases/{case_ref:path}/timeline", tags=["Data Retrieval"])
async def get_case_timeline(
    case_ref: str,
    limit: int = Query(50, ge=1, le=500),
    current_user=Depends(get_current_user),
):
    """Return full case details + lifecycle timeline for the case detail modal.

    Returns petitioner, respondent, orders, board_dates, and lifecycle_events
    so the frontend CaseDetailModal can display all sections without additional
    API calls.
    """
    try:
        normalized_case_ref = str(case_ref or "").strip().upper()
        if not normalized_case_ref:
            raise HTTPException(status_code=400, detail="case_ref is required")

        ensure_firebase()
        db = firestore.client()
        case_store = get_auto_order_manager().case_store
        case_details = case_store.get_case_details(normalized_case_ref)
        if not case_details:
            raise HTTPException(status_code=404, detail="Case not found")

        # Lifecycle events (paginated)
        all_events = list(case_details.get("lifecycle_events") or [])
        lifecycle_events = all_events[-limit:] if limit and limit > 0 else all_events

        # Board date records — batch-fetch from daily-boards using stored assignment IDs
        board_dates: list = []
        board_ids = case_details.get("board_assignment_ids") or []
        if board_ids:
            try:
                doc_refs = [
                    db.collection("daily-boards").document(bid)
                    for bid in board_ids[:50]
                ]
                for snap in db.get_all(doc_refs):
                    if snap.exists:
                        d = snap.to_dict() or {}
                        raw_bd = d.get("board_date")
                        if hasattr(raw_bd, "strftime"):
                            # Firestore Timestamp / DatetimeWithNanoseconds
                            bd = raw_bd.strftime("%Y-%m-%d")
                        else:
                            bd = str(raw_bd or "")
                            # Handle both ISO ("T") and space-separated formats
                            if "T" in bd:
                                bd = bd.split("T", 1)[0]
                            elif " " in bd:
                                bd = bd.split(" ", 1)[0]
                        board_dates.append(
                            {
                                "board_date": bd,
                                "board_doc_id": snap.id,
                                "respondent_lawyer": d.get("respondent_lawyer") or "",
                                "additional_respondent_lawyers": d.get(
                                    "additional_respondent_lawyers"
                                )
                                or [],
                                "petitioner_lawyer": d.get("petitioner_lawyer") or "",
                            }
                        )
            except Exception as _bd_err:
                logger.warning(
                    "get_case_timeline: board_dates fetch failed for %s: %s",
                    normalized_case_ref,
                    _bd_err,
                )

        lifecycle_status = (
            case_details.get("lifecycle_status")
            or case_store.map_legacy_order_status(
                case_details.get("latest_order_status")
            )
            or "board_ingested"
        )

        # Normalise each order's board_date field (may be a Timestamp from old data)
        raw_orders = case_details.get("orders") or []
        orders_out = []
        for o in raw_orders:
            if not isinstance(o, dict):
                continue
            o = dict(o)
            # Skip status-only entries that have neither an order_date nor an
            # order_link — these are internal tracking markers (e.g. order_failed
            # after exhausting sequence retries) that should not appear as rows
            # in the modal's appearances table.
            if not o.get("order_date") and not o.get("order_link"):
                continue
            raw_bd = o.get("board_date")
            if raw_bd is not None:
                if hasattr(raw_bd, "strftime"):
                    o["board_date"] = raw_bd.strftime("%Y-%m-%d")
                else:
                    bd_str = str(raw_bd)
                    if "T" in bd_str:
                        bd_str = bd_str.split("T", 1)[0]
                    elif " " in bd_str:
                        bd_str = bd_str.split(" ", 1)[0]
                    o["board_date"] = bd_str
            orders_out.append(o)

        return {
            "case_ref": normalized_case_ref,
            "lifecycle_status": lifecycle_status,
            "petitioner": case_details.get("petitioner") or "",
            "respondent": case_details.get("respondent") or "",
            "government_pleader": case_details.get("government_pleader") or [],
            "orders": orders_out,
            "board_dates": board_dates,
            "lifecycle_events": lifecycle_events,
            # backward-compat aliases kept for any callers expecting the old shape
            "timeline": lifecycle_events,
            "count": len(lifecycle_events),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error fetching case timeline for %s: %s", case_ref, e)
        raise HTTPException(status_code=500, detail="Error retrieving case timeline")


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
    except Exception as e:
        logger.warning(f"Profile update failed, creating new profile: {e}")
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

        logger.info(f"Password changed for user {uid}")
        return {"message": "Password changed successfully"}

    except Exception as e:
        logger.error(f"Error changing password: {str(e)}")
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

            logger.info(f"Admin {admin_uid} created new user {email} with role {role}")

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
            logger.error(f"Error creating Firebase user: {str(e)}")
            raise HTTPException(
                status_code=500, detail=f"Error creating user account: {str(e)}"
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in create_new_user: {str(e)}")
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
    response: Response = None,
):
    # SECURITY: Get AGP filter for the user - strict enforcement
    uid = current_user_with_profile.get("uid")
    agp_filter = get_user_manager().get_user_agp_filter(
        uid
    )  # This will raise 403 if invalid

    data = await get_dashboard_data().get_weekly_status(
        start_date, end_date, agp_filter
    )
    if response is not None:
        response.headers["Cache-Control"] = "public, max-age=120"
    return JSONResponse(content=data)


@app.get("/dashboard/agp-stats")
async def dashboard_agp_stats(
    agp_name: str = Query(None),
    current_user_with_profile=Depends(get_user_with_profile),
    response: Response = None,
):
    # SECURITY: Get AGP filter for the user - strict enforcement
    uid = current_user_with_profile.get("uid")
    agp_filter = get_user_manager().get_user_agp_filter(
        uid
    )  # This will raise 403 if invalid

    # For AGP users, use their assigned AGP name; for admins, use query parameter
    target_agp = agp_filter or agp_name

    data = await get_dashboard_data().get_agp_stats(target_agp, agp_filter)
    if response is not None:
        response.headers["Cache-Control"] = "public, max-age=120"
    return JSONResponse(content=data)


@app.get("/dashboard/monthly-avg")
async def dashboard_monthly_avg(
    year: str = Query(None),
    current_user_with_profile=Depends(get_user_with_profile),
    response: Response = None,
):
    # SECURITY: Get AGP filter for the user - strict enforcement
    uid = current_user_with_profile.get("uid")
    agp_filter = get_user_manager().get_user_agp_filter(
        uid
    )  # This will raise 403 if invalid

    data = await get_dashboard_data().get_monthly_avg(year, agp_filter)
    if response is not None:
        response.headers["Cache-Control"] = "public, max-age=120"
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
    response: Response = None,
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
    if response is not None:
        response.headers["Cache-Control"] = "public, max-age=120"
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


@app.get("/dashboard/board-date-summary")
async def dashboard_board_date_summary(
    start_date: str = Query(None, description="Start date (YYYY-MM-DD)"),
    end_date: str = Query(None, description="End date (YYYY-MM-DD)"),
    year: Optional[int] = Query(None, description="Year filter, e.g. 2026"),
    quarter: Optional[int] = Query(None, description="Quarter filter (1-4)"),
    limit: int = Query(180, ge=1, le=1000),
    current_user_with_profile=Depends(get_user_with_profile),
    response: Response = None,
):
    """Get board-date summary with case counts and distinct pleader counts."""
    uid = current_user_with_profile.get("uid")
    agp_filter = get_user_manager().get_user_agp_filter(uid)

    data = await get_dashboard_data().get_board_date_summary(
        start_date=start_date,
        end_date=end_date,
        year=year,
        quarter=quarter,
        limit=limit,
        agp_filter=agp_filter,
    )
    if response is not None:
        response.headers["Cache-Control"] = "public, max-age=120"
    return JSONResponse(content=data)


@app.get("/dashboard/board-date-agp-distribution")
async def dashboard_board_date_agp_distribution(
    board_dates: List[str] = Query(..., description="One or more board_date values"),
    current_user_with_profile=Depends(get_user_with_profile),
):
    """Get AGP-wise case distribution for selected board dates."""
    uid = current_user_with_profile.get("uid")
    agp_filter = get_user_manager().get_user_agp_filter(uid)

    data = await get_dashboard_data().get_agp_distribution_for_board_dates(
        board_dates=board_dates,
        agp_filter=agp_filter,
    )
    return JSONResponse(content=data)


@app.get("/dashboard/board-date-cases")
async def dashboard_board_date_cases(
    board_dates: List[str] = Query(..., description="One or more board_date values"),
    limit: int = Query(2000, ge=1, le=5000),
    current_user_with_profile=Depends(get_user_with_profile),
):
    """Get case rows for selected board dates."""
    uid = current_user_with_profile.get("uid")
    agp_filter = get_user_manager().get_user_agp_filter(uid)

    data = await get_dashboard_data().get_cases_for_board_dates(
        board_dates=board_dates,
        limit=limit,
        agp_filter=agp_filter,
    )
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
            status[
                "message"
            ] = "ML Enhanced Parser is active and improving PDF processing quality"
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
        logger.error(f"Error fetching ML status: {e}")
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
        logger.error(f"Error storing learning data: {e}")
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


def _normalize_iso_date(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    if "T" in raw:
        raw = raw.split("T", 1)[0]
    return raw


class OrderLinkAnalysisRequest(BaseModel):
    url: str
    persist_result: bool = False


def _serialize_order_analysis_result(
    filename: str,
    analysis_result,
    analysis_id: Optional[str] = None,
    source_url: Optional[str] = None,
    download_metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    response_data: Dict[str, Any] = {
        "filename": filename,
        "order_category": analysis_result.order_category,
        "category_confidence": round(analysis_result.category_confidence, 3),
        "order_date": analysis_result.order_date,
        "cases": [
            {
                "case_type": case.case_type,
                "case_number": case.case_number,
                "case_year": case.case_year,
                "petitioner": case.petitioner,
                "respondent": case.respondent,
                "government_pleader": case.government_pleader,
            }
            for case in analysis_result.cases
        ],
        "summary": {
            "total_cases": len(analysis_result.cases),
        },
    }

    if analysis_id is not None:
        response_data["analysis_id"] = analysis_id
    if source_url is not None:
        response_data["source_url"] = source_url
    if download_metadata is not None:
        response_data["download_metadata"] = download_metadata

    return response_data


def _derive_pdf_filename(source_url: str) -> str:
    parsed = urlparse(source_url)
    basename = posixpath.basename(parsed.path or "") or "order.pdf"
    if not basename.lower().endswith(".pdf"):
        basename = f"{basename}.pdf"
    return basename


def _download_pdf_from_url(source_url: str) -> Dict[str, Any]:
    response = requests.get(source_url, timeout=60)
    response.raise_for_status()

    file_content = response.content or b""
    if not file_content:
        raise ValueError("Downloaded file is empty")

    content_type = (response.headers.get("content-type") or "").lower()
    is_pdf = (
        source_url.lower().endswith(".pdf")
        or "application/pdf" in content_type
        or file_content.startswith(b"%PDF")
    )
    if not is_pdf:
        raise ValueError(
            f"URL did not return a PDF document. Content-Type was '{content_type or 'unknown'}'"
        )

    return {
        "filename": _derive_pdf_filename(source_url),
        "file_content": file_content,
        "metadata": {
            "source_url": source_url,
            "resolved_url": response.url,
            "content_type": content_type,
            "content_length": len(file_content),
            "status_code": response.status_code,
        },
    }


def _get_cached_case_details_payload(case_ref: str) -> Optional[Dict]:
    normalized_case_ref = str(case_ref or "").strip().upper()
    if not normalized_case_ref:
        return None

    case_details = (
        get_auto_order_manager().case_store.get_case_details(normalized_case_ref) or {}
    )
    if not case_details:
        return None

    petitioner = str(case_details.get("petitioner") or "").strip()
    respondent = str(case_details.get("respondent") or "").strip()
    orders = case_details.get("orders") or []

    if not petitioner and not respondent and not orders:
        return None

    return {
        "status": "found",
        "source": "case_store_cached",
        "case_ref": normalized_case_ref,
        "case_number": normalized_case_ref,
        "petitioner": petitioner,
        "respondent": respondent,
        "latest_board_date": case_details.get("latest_board_date"),
        "latest_order_link": case_details.get("latest_order_link"),
        "orders_count": len(orders),
    }


def _get_cached_case_orders_payload(
    case_ref: str, date: Optional[str]
) -> Optional[Dict]:
    normalized_case_ref = str(case_ref or "").strip().upper()
    if not normalized_case_ref:
        return None

    case_details = (
        get_auto_order_manager().case_store.get_case_details(normalized_case_ref) or {}
    )
    orders = case_details.get("orders") or []
    if not isinstance(orders, list) or not orders:
        return None

    requested_date = _normalize_iso_date(date)
    normalized_orders = []
    for item in orders:
        if not isinstance(item, dict):
            continue

        board_date = _normalize_iso_date(item.get("board_date"))
        order_date = _normalize_iso_date(item.get("order_date"))
        if requested_date and requested_date not in {board_date, order_date}:
            continue

        order_link = str(item.get("order_link") or "").strip()
        if not order_link:
            continue

        normalized_orders.append(
            {
                "listing_date": board_date or order_date,
                "download_url": order_link,
                "order_description": item.get("order_filename")
                or item.get("order_category")
                or "Cached order",
                "order_status": item.get("order_status"),
                "order_source": item.get("order_source")
                or item.get("cache_validation_source")
                or "case_store_cached",
            }
        )

    if not normalized_orders:
        return None

    petitioner = str(case_details.get("petitioner") or "").strip() or None
    respondent = str(case_details.get("respondent") or "").strip() or None
    title: Optional[str] = None
    if petitioner and respondent:
        title = f"{petitioner} against {respondent}"
    elif petitioner or respondent:
        title = petitioner or respondent

    case_orders = [
        {
            "date": o.get("listing_date"),
            "download_link": o.get("download_url"),
        }
        for o in normalized_orders
        if o.get("download_url")
    ]

    return {
        "status": "found",
        "source": "case_store_cached",
        "case_ref": normalized_case_ref,
        "date": requested_date,
        "case_summary": None,
        "petitioner": petitioner,
        "respondent": respondent,
        "title": title,
        "case_orders": case_orders,
        "case_details": {
            "case_number": normalized_case_ref,
            "petitioner_name": petitioner,
            "respondent_name": respondent,
        },
        "court_orders": normalized_orders,
    }


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
        cached_payload = _get_cached_case_details_payload(case_ref)
        if cached_payload:
            return JSONResponse(content=cached_payload)

        case_details = get_court_scraper().get_case_details(case_ref, bench)
        return JSONResponse(content=case_details)
    except Exception as e:
        logger.error(f"Error fetching case details for {case_ref}: {e}")
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
        cached_payload = _get_cached_case_orders_payload(case_ref, date)
        if cached_payload:
            response_payload = {
                "case_ref": case_ref,
                "date": date,
                "orders": cached_payload.get("court_orders", []),
            }
            response_payload.update(cached_payload)
            return JSONResponse(content=response_payload)

        case_orders = get_court_scraper().get_case_orders(case_ref, date, bench)
        if isinstance(case_orders, dict):
            response_payload = {
                "case_ref": case_ref,
                "date": date,
                "orders": case_orders.get("court_orders", []),
            }
            response_payload.update(case_orders)
            return JSONResponse(content=response_payload)

        return JSONResponse(
            content={"case_ref": case_ref, "date": date, "orders": case_orders}
        )
    except Exception as e:
        logger.error(f"Error fetching case orders for {case_ref}: {e}")
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
            case_details = _get_cached_case_details_payload(case_ref)
            if not case_details:
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
        logger.error(f"Error in batch case lookup: {e}")
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
        logger.error(f"Error fetching cases without orders: {e}")
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

                    content_type = response.headers.get("Content-Type", "")
                    if response.status_code == 200 and content_type.lower().startswith(
                        "application/pdf"
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
                            result[
                                "analysis_message"
                            ] = "Order linked and analyzed successfully"
                            logger.info(
                                f"Auto-analysis completed for manually linked order: {case_id}"
                            )
                        else:
                            result["analysis_completed"] = False
                            result["analysis_error"] = analysis_result.get("error")
                    else:
                        result["analysis_completed"] = False
                        result["analysis_error"] = "Could not download PDF from link"

            except Exception as analysis_error:
                logger.error(
                    f"Auto-analysis failed for manual link {case_id}: {analysis_error}"
                )
                result["analysis_completed"] = False
                result["analysis_error"] = str(analysis_error)

        return JSONResponse(content=result)
    except Exception as e:
        logger.error(f"Error creating order link: {e}")
        return JSONResponse(
            status_code=500, content={"error": f"Failed to create order link: {str(e)}"}
        )


@app.put("/orders/update-status", tags=["Order Management"])
async def update_order_status(
    case_id: str = Query(..., description="Case document ID"),
    status: str = Query(
        ...,
        description="Order status: linked, analysed, order_failed, order_analysis_failed, manually_uploaded, not_linked",
    ),
    notes: str = Query("", description="Optional notes"),
    current_user=Depends(get_current_user),
):
    """Update the status of an order"""
    try:
        result = get_order_manager().update_order_status(case_id, status, notes)
        return JSONResponse(content=result)
    except Exception as e:
        logger.error(f"Error updating order status: {e}")
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
        logger.error(f"Error fetching orders by status: {e}")
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
        logger.error(f"Error fetching case with order info: {e}")
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
        filename = file.filename or "uploaded-order.pdf"

        # Validate file type
        if not filename.lower().endswith(".pdf"):
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

        logger.info(f"Starting order analysis for file: {filename}")

        # Analyze the order document
        analysis_result = get_order_analyzer().analyze_order_document(
            filename, file_content
        )

        # DEBUG: Log the actual category being returned
        logger.info(f"🔍 CATEGORY DEBUG for {filename}:")
        logger.info(f"   order_category: '{analysis_result.order_category}'")
        logger.info(f"   category_confidence: {analysis_result.category_confidence}")

        # Save analysis result to database
        doc_id = get_order_analyzer().save_analysis_result(filename, analysis_result)

        response_data = _serialize_order_analysis_result(
            filename=filename,
            analysis_result=analysis_result,
            analysis_id=doc_id,
        )

        logger.info(f"Order analysis completed successfully for {filename}")
        return JSONResponse(content=response_data)

    except HTTPException as he:
        logger.error(f"HTTP error in order analysis: {he.detail}")
        return JSONResponse(status_code=he.status_code, content={"error": he.detail})
    except Exception as e:
        logger.error(f"Unexpected error in order analysis: {str(e)}")
        return JSONResponse(
            status_code=500, content={"error": f"Order analysis failed: {str(e)}"}
        )


@app.post("/admin/order-analysis/from-link", tags=["Order Analysis"])
async def analyze_order_document_from_link(
    request: OrderLinkAnalysisRequest,
    current_user: dict = Depends(require_admin_active),
):
    """Download a PDF from the provided URL and run the existing order analyzer on it."""
    _ = current_user
    try:
        download = _download_pdf_from_url(request.url)
        filename = download["filename"]
        file_content = download["file_content"]

        analysis_result = get_order_analyzer().analyze_order_document(
            filename, file_content
        )
        analysis_id = None
        if request.persist_result:
            analysis_id = get_order_analyzer().save_analysis_result(
                filename, analysis_result
            )

        response_data = _serialize_order_analysis_result(
            filename=filename,
            analysis_result=analysis_result,
            analysis_id=analysis_id,
            source_url=request.url,
            download_metadata=download["metadata"],
        )
        response_data["persisted"] = bool(request.persist_result)
        return JSONResponse(content=response_data)
    except requests.exceptions.RequestException as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Failed to download order PDF from URL: {str(exc)}",
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.error(f"Unexpected error analyzing order from link: {exc}")
        raise HTTPException(
            status_code=500,
            detail=f"Order analysis failed for link: {str(exc)}",
        )


@app.get("/analysis-history", tags=["Order Analysis"])
async def get_analysis_history(
    limit: int = Query(50, description="Maximum number of analyses to return"),
    current_user=Depends(get_current_user),
):
    """Get history of order document analyses from case-details."""
    try:
        db = firestore.client()
        case_docs = (
            db.collection("case-details")
            .order_by("updated_at", direction=firestore.Query.DESCENDING)
            .limit(limit * 3)
            .stream()
        )

        analyses = []
        for doc in case_docs:
            case_data = doc.to_dict() or {}
            latest_status = case_data.get("latest_order_status")
            if latest_status != "analysed":
                continue

            orders = case_data.get("orders") or []
            latest_order = orders[-1] if orders and isinstance(orders[-1], dict) else {}

            board_date = case_data.get("latest_board_date")
            board_row = None
            if board_date:
                board_row = (
                    db.collection("daily-boards")
                    .where("case_ref", "==", case_data.get("case_ref"))
                    .where("board_date", "==", board_date)
                    .limit(1)
                    .get()
                )
            board_data = board_row[0].to_dict() if board_row else {}

            analysis_data = {
                "id": doc.id,
                "case_id": doc.id,
                "case_ref": case_data.get("case_ref"),
                "case_type": case_data.get("case_type"),
                "case_no": case_data.get("case_no"),
                "case_year": case_data.get("case_year"),
                "board_date": case_data.get("latest_board_date"),
                "petitioner_lawyer": board_data.get("petitioner_lawyer"),
                "respondent_lawyer": board_data.get("respondent_lawyer"),
                "order_category": case_data.get("latest_order_category")
                or latest_order.get("order_category"),
                "category_confidence": latest_order.get("order_category_confidence"),
                "order_date": case_data.get("latest_order_date")
                or latest_order.get("order_date"),
                "date_validation": latest_order.get("order_date_validation"),
                "order_link": case_data.get("latest_order_link")
                or latest_order.get("order_link"),
                "analysis_timestamp": latest_order.get("order_analysis_timestamp"),
            }

            analyses.append(analysis_data)
            if len(analyses) >= limit:
                break

        return JSONResponse(
            content={
                "analyses": analyses,
                "count": len(analyses),
                "total_fetched": len(analyses),
            }
        )

    except Exception as e:
        logger.error(f"Error fetching analysis history: {e}")
        return JSONResponse(
            status_code=500,
            content={"error": f"Failed to fetch analysis history: {str(e)}"},
        )


@app.get("/analysis/{analysis_id}", tags=["Order Analysis"])
async def get_analysis_details(
    analysis_id: str, current_user=Depends(get_current_user)
):
    """Get detailed analysis results for a specific case from case-details."""
    try:
        db = firestore.client()

        doc_ref = db.collection("daily-boards").document(analysis_id)
        doc = doc_ref.get()

        if not doc.exists:
            return JSONResponse(status_code=404, content={"error": "Case not found"})

        board_data = doc.to_dict() or {}
        case_ref = f"{board_data.get('case_type', '')}/{board_data.get('case_no', '')}/{board_data.get('case_year', '')}"
        case_data = get_auto_order_manager().case_store.get_case_details(case_ref) or {}
        latest_status = case_data.get("latest_order_status", "not_linked")
        orders = case_data.get("orders") or []
        latest_order = orders[-1] if orders and isinstance(orders[-1], dict) else {}

        if latest_status != "analysed":
            return JSONResponse(
                status_code=404,
                content={"error": "Order analysis not completed for this case"},
            )

        analysis_data = {
            "id": doc.id,
            "case_id": doc.id,
            "case_ref": case_ref,
            "case_type": board_data.get("case_type"),
            "case_no": board_data.get("case_no"),
            "case_year": board_data.get("case_year"),
            "board_date": board_data.get("board_date"),
            "petitioner_lawyer": board_data.get("petitioner_lawyer"),
            "respondent_lawyer": board_data.get("respondent_lawyer"),
            "serial_number": board_data.get("serial_number"),
            "additional_cases": board_data.get("additional_cases"),
            "order_category": case_data.get("latest_order_category")
            or latest_order.get("order_category"),
            "category_confidence": latest_order.get("order_category_confidence"),
            "order_date": case_data.get("latest_order_date")
            or latest_order.get("order_date"),
            "date_validation": latest_order.get("order_date_validation"),
            "order_link": case_data.get("latest_order_link")
            or latest_order.get("order_link"),
            "analysis_timestamp": latest_order.get("order_analysis_timestamp"),
            "last_updated": latest_order.get("updated_at"),
        }

        return JSONResponse(content=analysis_data)

    except Exception as e:
        logger.error(f"Error fetching analysis details: {e}")
        return JSONResponse(
            status_code=500,
            content={"error": f"Failed to fetch analysis details: {str(e)}"},
        )


@app.get("/analysis-stats", tags=["Order Analysis"])
async def get_analysis_statistics(current_user=Depends(get_current_user)):
    """Get statistics about order document analyses from case-details."""
    try:
        db = firestore.client()

        analyses_ref = db.collection("case-details").where(
            "latest_order_status", "==", "analysed"
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
            data = doc.to_dict() or {}
            latest_order = {}
            orders = data.get("orders") or []
            if orders and isinstance(orders[-1], dict):
                latest_order = orders[-1]
            stats["total_analyses"] += 1

            # Category distribution
            category = data.get("latest_order_category") or latest_order.get(
                "order_category", "UNKNOWN"
            )
            if category in stats["category_distribution"]:
                stats["category_distribution"][category] += 1

            # Confidence scores
            confidence = latest_order.get("order_category_confidence", 0)
            if confidence > 0:
                confidences.append(confidence)

            # Recent analyses - use order_analysis_timestamp
            timestamp_str = latest_order.get("order_analysis_timestamp", "")
            if timestamp_str:
                try:
                    timestamp = datetime.fromisoformat(
                        timestamp_str.replace("Z", "+00:00")
                    ).timestamp()
                    if timestamp > recent_cutoff:
                        stats["recent_analyses"] += 1
                except (ValueError, TypeError):
                    pass

        # Calculate average confidence
        if confidences:
            stats["avg_confidence"] = round(sum(confidences) / len(confidences), 3)

        return JSONResponse(content=stats)

    except Exception as e:
        logger.error(f"Error fetching analysis statistics: {e}")
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
        logger.error(f"Error in auto-process-orders: {e}")
        return JSONResponse(
            status_code=500, content={"error": f"Failed to process orders: {str(e)}"}
        )


@app.post("/jobs/fetch-orders", tags=["Auto Order Management"])
async def queue_fetch_orders_jobs(
    request: Request, current_user=Depends(require_admin_active)
):
    """Queue fetch jobs for eligible cases based on filters."""
    try:
        body = await request.json()
        filters = body.get("filters", {})
        board_dates = body.get("board_dates") or []
        case_refs = body.get("case_refs") or []
        limit = int(body.get("limit", 100))

        if limit < 1 or limit > 1000:
            return JSONResponse(
                status_code=400,
                content={"error": "limit must be between 1 and 1000"},
            )

        manager = get_auto_order_manager()
        candidate_cases = manager._get_filtered_matters(filters, limit)
        selected_case_refs = {
            str(value or "").strip().upper()
            for value in case_refs
            if str(value or "").strip()
        }

        if selected_case_refs:
            candidate_cases = [
                case_data
                for case_data in candidate_cases
                if str(case_data.get("case_ref") or "").strip().upper()
                in selected_case_refs
            ]

        selected_board_dates = {
            str(value or "").strip()
            for value in board_dates
            if str(value or "").strip()
        }
        if selected_board_dates and not selected_case_refs:
            candidate_cases = [
                case_data
                for case_data in candidate_cases
                if (
                    (
                        manager._parse_board_date(case_data.get("board_date"))
                        or datetime.min.date()
                    ).isoformat()
                    in selected_board_dates
                )
            ]

        queued = 0
        skipped_not_due = 0
        queued_case_refs = []
        today = datetime.now().date()

        for case_data in candidate_cases:
            board_date = manager._parse_board_date(case_data.get("board_date"))
            case_ref = case_data.get("case_ref")
            case_id = case_data.get("id")

            if board_date and board_date > today:
                skipped_not_due += 1
                manager.case_store.transition_lifecycle(
                    case_ref,
                    "fetch_not_due",
                    reason=(
                        f"Order fetch is not due yet for board date {board_date.isoformat()}"
                    ),
                    metadata={"source": "jobs.fetch-orders", "case_id": case_id},
                    event_type="fetch_job_not_due",
                )
                continue

            manager.case_store.transition_lifecycle(
                case_ref,
                "fetch_queued",
                metadata={"source": "jobs.fetch-orders", "case_id": case_id},
                event_type="fetch_job_queued",
            )

            await order_processing_queue.put(
                {
                    "id": case_id,
                    "case_ref": case_ref,
                    "board_date": case_data.get("board_date"),
                }
            )
            queued += 1
            queued_case_refs.append(case_ref)

        await ensure_background_processing_active()

        return JSONResponse(
            content={
                "success": True,
                "queued": queued,
                "skipped_not_due": skipped_not_due,
                "queue_size": order_processing_queue.qsize(),
                "queued_case_refs": queued_case_refs,
                "selected_board_dates": sorted(selected_board_dates),
                "selected_case_refs": sorted(selected_case_refs),
            }
        )
    except Exception as e:
        logger.error(f"Error queueing fetch jobs: {e}")
        return JSONResponse(
            status_code=500,
            content={"error": f"Failed to queue fetch jobs: {str(e)}"},
        )


@app.post("/jobs/analyze-orders", tags=["Auto Order Management"])
async def queue_analysis_jobs(
    request: Request, current_user=Depends(require_admin_active)
):
    """Queue analysis jobs for cases that already have order links."""
    try:
        db = firestore.client()
        body = await request.json()

        limit = int(body.get("limit", 100))
        days_back = body.get("days_back")
        case_refs = body.get("case_refs") or []
        board_dates = body.get("board_dates") or []

        if limit < 1 or limit > 1000:
            return JSONResponse(
                status_code=400,
                content={"error": "limit must be between 1 and 1000"},
            )

        manager = get_auto_order_manager()
        queued = 0
        skipped = 0
        queued_case_refs = []
        selected_board_dates = {
            str(value or "").strip()
            for value in board_dates
            if str(value or "").strip()
        }

        candidate_rows = []
        if case_refs:
            for case_ref in case_refs:
                normalized_ref = str(case_ref or "").strip().upper()
                if not normalized_ref:
                    continue
                parts = normalized_ref.split("/")
                if len(parts) != 3:
                    continue
                query = (
                    db.collection("daily-boards")
                    .where("case_type", "==", parts[0])
                    .where("case_no", "==", parts[1])
                    .where("case_year", "==", parts[2])
                    .limit(1)
                )
                rows = list(query.stream())
                if rows:
                    candidate_rows.append(rows[0])
        else:
            query = db.collection("daily-boards")
            if days_back:
                start_date = datetime.now() - timedelta(days=int(days_back))
                start_datetime = datetime(
                    start_date.year, start_date.month, start_date.day, 0, 0, 0
                )
                query = query.where("board_date", ">=", start_datetime)
            candidate_rows = list(query.limit(limit * 4).stream())

        for row in candidate_rows:
            row_data = row.to_dict() or {}
            board_date_obj = manager._parse_board_date(row_data.get("board_date"))
            board_date_iso = board_date_obj.isoformat() if board_date_obj else None
            if selected_board_dates and board_date_iso not in selected_board_dates:
                continue

            case_ref = manager.case_store.build_case_ref(
                row_data.get("case_type"),
                row_data.get("case_no"),
                row_data.get("case_year"),
            )
            order_context = manager._get_case_order_context(case_ref)
            order_link = order_context.get("order_link")

            if not order_link:
                skipped += 1
                continue

            manager.case_store.transition_lifecycle(
                case_ref,
                "analysis_queued",
                metadata={"source": "jobs.analyze-orders", "case_id": row.id},
                event_type="analysis_job_queued",
            )
            await analysis_processing_queue.put(
                {
                    "id": row.id,
                    "case_ref": case_ref,
                    "board_date": row_data.get("board_date"),
                }
            )
            queued += 1
            queued_case_refs.append(case_ref)

            if queued >= limit:
                break

        await ensure_background_analysis_processing_active()

        return JSONResponse(
            content={
                "success": True,
                "queued": queued,
                "skipped": skipped,
                "analysis_queue_size": analysis_processing_queue.qsize(),
                "queued_case_refs": queued_case_refs,
                "selected_board_dates": sorted(selected_board_dates),
            }
        )
    except Exception as e:
        logger.error(f"Error queueing analysis jobs: {e}")
        return JSONResponse(
            status_code=500,
            content={"error": f"Failed to queue analysis jobs: {str(e)}"},
        )


@app.post("/jobs/retry-failed", tags=["Auto Order Management"])
async def retry_failed_cases(
    request: Request, current_user=Depends(require_admin_active)
):
    """Re-queue cases stuck in order_failed, order_analysis_failed, or linked status.

    For order_failed cases: adds to the fetch queue (tries to re-download the order).
    For order_analysis_failed cases: adds to the analysis queue (re-analyzes the
    already-downloaded order without a fresh fetch).
    For linked cases: if an ``order_link`` is stored, adds to the analysis queue
    (order was downloaded but analysis was never completed or got stuck); otherwise,
    falls back to the fetch queue to re-download the order before analysis.

    Accepts optional ``board_dates`` (list of YYYY-MM-DD strings) and ``limit``
    (default 200) in the request body.
    """
    try:
        body = await request.json()
        board_dates = body.get("board_dates") or []
        limit = int(body.get("limit", 200))

        if limit < 1 or limit > 1000:
            return JSONResponse(
                status_code=400,
                content={"error": "limit must be between 1 and 1000"},
            )

        manager = get_auto_order_manager()
        selected_board_dates = {
            str(v or "").strip() for v in board_dates if str(v or "").strip()
        }

        # Gather candidates with retryable statuses
        filters: Dict = {}
        candidate_cases = manager._get_filtered_matters(filters, limit)

        fetch_queued = 0
        analysis_queued = 0
        skipped = 0
        fetch_queued_refs: list = []
        analysis_queued_refs: list = []

        for case_data in candidate_cases:
            status = case_data.get("order_status", "")
            if status not in ("order_failed", "order_analysis_failed", "linked"):
                continue

            board_date_obj = manager._parse_board_date(case_data.get("board_date"))
            board_date_iso = board_date_obj.isoformat() if board_date_obj else None
            if selected_board_dates and board_date_iso not in selected_board_dates:
                skipped += 1
                continue

            case_ref = case_data.get("case_ref")
            case_id = case_data.get("id")

            if status == "order_failed":
                # Re-fetch the order from scratch
                manager.case_store.transition_lifecycle(
                    case_ref,
                    "fetch_queued",
                    metadata={"source": "jobs.retry-failed", "case_id": case_id},
                    event_type="retry_fetch_queued",
                )
                await order_processing_queue.put(
                    {
                        "id": case_id,
                        "case_ref": case_ref,
                        "board_date": case_data.get("board_date"),
                    }
                )
                fetch_queued += 1
                fetch_queued_refs.append(case_ref)
            else:
                # order_analysis_failed or linked: order link exists (or should), just re-run analysis
                order_link = case_data.get("order_link")
                if not order_link:
                    # No link stored – fall back to fetch queue
                    manager.case_store.transition_lifecycle(
                        case_ref,
                        "fetch_queued",
                        metadata={
                            "source": "jobs.retry-failed",
                            "case_id": case_id,
                            "reason": "no_order_link_for_analysis_retry",
                        },
                        event_type="retry_fetch_queued",
                    )
                    await order_processing_queue.put(
                        {
                            "id": case_id,
                            "case_ref": case_ref,
                            "board_date": case_data.get("board_date"),
                        }
                    )
                    fetch_queued += 1
                    fetch_queued_refs.append(case_ref)
                else:
                    manager.case_store.transition_lifecycle(
                        case_ref,
                        "analysis_queued",
                        metadata={
                            "source": "jobs.retry-failed",
                            "case_id": case_id,
                        },
                        event_type="retry_analysis_queued",
                    )
                    await analysis_processing_queue.put(
                        {
                            "id": case_id,
                            "case_ref": case_ref,
                            "board_date": case_data.get("board_date"),
                        }
                    )
                    analysis_queued += 1
                    analysis_queued_refs.append(case_ref)

        await ensure_background_processing_active()
        await ensure_background_analysis_processing_active()

        return JSONResponse(
            content={
                "success": True,
                "fetch_queued": fetch_queued,
                "analysis_queued": analysis_queued,
                "skipped": skipped,
                "fetch_queue_size": order_processing_queue.qsize(),
                "analysis_queue_size": analysis_processing_queue.qsize(),
                "fetch_queued_refs": fetch_queued_refs,
                "analysis_queued_refs": analysis_queued_refs,
                "selected_board_dates": sorted(selected_board_dates),
            }
        )

    except Exception as e:
        logger.error(f"Error in retry-failed: {e}")
        return JSONResponse(
            status_code=500,
            content={"error": f"Failed to retry failed cases: {str(e)}"},
        )


async def mark_case_for_manual_review(
    case_ref: str,
    request: Request,
    current_user=Depends(require_active_user),
):
    """Move a case to manual review workflow with audit metadata."""
    try:
        body = await request.json()
        normalized_case_ref = str(case_ref or "").strip().upper()
        if not normalized_case_ref:
            return JSONResponse(
                status_code=400, content={"error": "case_ref is required"}
            )

        case_store = get_auto_order_manager().case_store
        case_details = case_store.get_case_details(normalized_case_ref)
        if not case_details:
            return JSONResponse(status_code=404, content={"error": "Case not found"})

        reason = body.get("reason") or "Marked for manual review"
        notes = body.get("notes")
        actor_uid = current_user.get("uid")

        transition = case_store.transition_lifecycle(
            normalized_case_ref,
            "manual_review_required",
            reason=reason,
            metadata={
                "source": "manual-review",
                "actor_uid": actor_uid,
                "notes": notes,
            },
            event_type="manual_review_marked",
            force=True,
        )

        return JSONResponse(
            content={
                "success": True,
                "case_ref": normalized_case_ref,
                "transition": transition,
                "lifecycle": case_store.build_lifecycle_summary(normalized_case_ref),
            }
        )
    except Exception as e:
        logger.error(f"Error marking manual review for {case_ref}: {e}")
        return JSONResponse(
            status_code=500,
            content={"error": f"Failed to mark manual review: {str(e)}"},
        )


@app.post("/cases/{case_ref:path}/manual-override", tags=["Auto Order Management"])
async def manual_override_case_outcome(
    case_ref: str,
    request: Request,
    current_user=Depends(require_admin_active),
):
    """Apply a reviewed final outcome and move case lifecycle to analysed."""
    try:
        body = await request.json()
        normalized_case_ref = str(case_ref or "").strip().upper()
        if not normalized_case_ref:
            return JSONResponse(
                status_code=400, content={"error": "case_ref is required"}
            )

        case_store = get_auto_order_manager().case_store
        case_details = case_store.get_case_details(normalized_case_ref)
        if not case_details:
            return JSONResponse(status_code=404, content={"error": "Case not found"})

        order_category = body.get("order_category")
        order_date = body.get("order_date")
        notes = body.get("notes") or "Manual override applied"
        actor_uid = current_user.get("uid")

        latest_link = case_details.get("latest_order_link")
        case_store.append_case_order(
            normalized_case_ref,
            {
                "order_status": "analysed",
                "order_category": order_category,
                "order_date": order_date,
                "order_link": latest_link,
                "order_analysis_timestamp": datetime.now().isoformat(),
                "order_manual_override": True,
                "order_manual_override_notes": notes,
                "order_manual_override_by": actor_uid,
            },
        )
        transition = case_store.transition_lifecycle(
            normalized_case_ref,
            "analysed",
            reason="Manual override completed",
            metadata={
                "source": "manual-override",
                "actor_uid": actor_uid,
                "notes": notes,
                "order_category": order_category,
                "order_date": order_date,
            },
            event_type="manual_override",
            force=True,
        )

        return JSONResponse(
            content={
                "success": True,
                "case_ref": normalized_case_ref,
                "transition": transition,
                "lifecycle": case_store.build_lifecycle_summary(normalized_case_ref),
            }
        )
    except Exception as e:
        logger.error(f"Error applying manual override for {case_ref}: {e}")
        return JSONResponse(
            status_code=500,
            content={"error": f"Failed to apply manual override: {str(e)}"},
        )


@app.post("/cases/{case_ref:path}/reset", tags=["Auto Order Management"])
async def reset_case_orders(
    case_ref: str,
    current_user=Depends(require_admin),
):
    """Hard-reset a case: clear all order history and requeue every board entry.

    Wipes the orders array and latest_order_* fields from case-details, then
    resets every daily-boards entry for this case to fetch_queued so the
    background pipeline re-fetches every order PDF and uploads them to GCS.

    Use this when a case has stale BHC links that retries have not replaced,
    or whenever a clean slate is needed.
    """
    try:
        ensure_firebase()
        normalized = str(case_ref or "").strip().upper()
        if not normalized:
            return JSONResponse(
                status_code=400, content={"error": "case_ref is required"}
            )

        case_store = get_auto_order_manager().case_store
        case_store.reset_case_for_reprocessing(normalized)

        return JSONResponse(
            content={
                "success": True,
                "case_ref": normalized,
                "message": f"Case {normalized} reset and queued for re-fetch.",
            }
        )
    except Exception as exc:
        logger.error("reset_case_orders failed for %s: %s", case_ref, exc)
        return JSONResponse(
            status_code=500,
            content={"error": f"Reset failed: {str(exc)}"},
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

        # Fetch existing case data from database
        case_doc = db.collection("daily-boards").document(case_id).get()

        if not case_doc.exists:
            return JSONResponse(status_code=404, content={"error": "Case not found"})

        case_data = case_doc.to_dict()

        # Enqueue asynchronously — do not block the request for up to 5 minutes.
        # The caller can poll GET /auto-orders/job-status/{case_id} for progress.
        auto_mgr = get_auto_order_manager()
        # force=True so retries always reset lifecycle regardless of current state
        # (e.g. fetch_in_progress from a previous stuck/timed-out attempt).
        auto_mgr.case_store.transition_lifecycle(
            case_ref,
            "fetch_queued",
            force=True,
            metadata={"source": "process_case_endpoint", "case_id": case_id},
            event_type="fetch_job_queued",
        )
        await order_processing_queue.put(
            {
                "id": case_id,
                "case_ref": case_ref,
                "board_date": board_date or case_data.get("board_date"),
            }
        )
        await ensure_background_processing_active()

        return JSONResponse(
            content={
                "success": True,
                "job_id": case_id,
                "status": "queued",
                "case_ref": case_ref,
                "message": "Case queued for processing. Poll /auto-orders/job-status/{case_id} for progress.",
            }
        )

    except Exception as e:
        logger.error(f"Error processing single case: {e}")
        return JSONResponse(
            status_code=500, content={"error": f"Failed to process case: {str(e)}"}
        )


@app.get("/auto-orders/job-status/{doc_id}", tags=["Auto Order Management"])
async def get_job_status(doc_id: str, current_user=Depends(get_current_user)):
    """Poll the processing status of a single case queued via /auto-orders/process-case."""
    try:
        db = firestore.client()
        # doc_id is the daily-boards document ID; read it to get case_ref
        board_doc = db.collection("daily-boards").document(doc_id).get()
        if not board_doc.exists:
            return JSONResponse(status_code=404, content={"error": "Case not found"})
        board_data = board_doc.to_dict() or {}

        # Lifecycle status lives in case-details (keyed by case_ref with / → -)
        case_ref = board_data.get(
            "case_ref"
        ) or get_auto_order_manager().case_store.build_case_ref(
            board_data.get("case_type"),
            board_data.get("case_no"),
            board_data.get("case_year"),
        )
        case_details_id = case_ref.replace("/", "-")
        case_doc = db.collection("case-details").document(case_details_id).get()
        case_data = case_doc.to_dict() if case_doc.exists else {}

        lifecycle_status = case_data.get("lifecycle_status") or "board_ingested"
        updated_at = case_data.get("updated_at")

        # Surface the last lifecycle event so the UI can show the actual error
        events = case_data.get("lifecycle_events") or []
        last_event = events[-1] if events else {}

        # Check if the most recent order was stored with an expiring court URL
        # because the GCS upload failed (persisted in order payload).
        orders = case_data.get("orders") or []
        orders_with_link = [
            o for o in orders if isinstance(o, dict) and o.get("order_link")
        ]
        latest_order = orders_with_link[-1] if orders_with_link else {}
        gcs_upload_failed = bool(latest_order.get("gcs_upload_failed"))

        return JSONResponse(
            content={
                "doc_id": doc_id,
                "status": lifecycle_status,
                "error_reason": case_data.get("lifecycle_status_reason"),
                "last_event": {
                    "event_type": last_event.get("event_type"),
                    "reason": last_event.get("reason"),
                    "timestamp": last_event.get("timestamp"),
                }
                if last_event
                else None,
                "order_category": case_data.get("latest_order_category")
                or board_data.get("order_category"),
                "order_link": case_data.get("latest_order_link")
                or board_data.get("order_link"),
                "gcs_upload_failed": gcs_upload_failed,
                "updated_at": updated_at.isoformat()
                if hasattr(updated_at, "isoformat")
                else str(updated_at)
                if updated_at
                else None,
            }
        )
    except Exception as e:
        logger.error(f"Error getting job status for {doc_id}: {e}")
        return JSONResponse(
            status_code=500, content={"error": f"Failed to get job status: {str(e)}"}
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
        case_ref = f"{case_data.get('case_type')}/{case_data.get('case_no')}/{case_data.get('case_year')}"
        case_details = (
            get_auto_order_manager().case_store.get_case_details(case_ref) or {}
        )
        latest_status = case_details.get("latest_order_status", "not_linked")
        latest_order_link = case_details.get("latest_order_link")

        if not latest_order_link:
            return JSONResponse(
                status_code=400,
                content={
                    "error": "No order available to analyze. Please download the order first."
                },
            )

        # If already analyzed, return existing analysis
        if latest_status == "analysed":
            orders = case_details.get("orders") or []
            latest_order = orders[-1] if orders and isinstance(orders[-1], dict) else {}
            return JSONResponse(
                content={
                    "success": True,
                    "message": "Order already analyzed",
                    "data": {
                        "order_category": case_details.get("latest_order_category")
                        or latest_order.get("order_category"),
                        "order_date": case_details.get("latest_order_date")
                        or latest_order.get("order_date"),
                        "order_petitioner": case_details.get("petitioner"),
                        "order_respondent": case_details.get("respondent"),
                        "government_pleader": case_details.get("government_pleader"),
                    },
                }
            )

        # Download the PDF from the link and analyze
        # If stored link fails, fallback to fresh download from court website
        try:
            import requests

            order_link = latest_order_link
            logger.info(f"Downloading order from: {order_link}")

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
                    logger.warning(
                        f"⚠️ {reason}. Attempting fresh download from court website..."
                    )

                    # Prepare case_data for fresh download (same as Download Order button)
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
                logger.info(f"Analyzing order for case: {case_ref}")

                analysis_result = (
                    get_auto_order_manager()._analyze_order_with_date_validation(
                        case_id,
                        case_ref,
                        response.content,
                        case_data.get("board_date"),
                        order_link,
                    )
                )
                if analysis_result.get("success") and analysis_result.get("data"):
                    analysis_result["data"].pop("order_cases", None)
                return JSONResponse(content=analysis_result)

            except requests.RequestException as req_error:
                # Network error accessing stored link - try fresh download
                logger.warning(
                    f"Network error accessing stored link: {req_error}. Attempting fresh download..."
                )

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
            logger.error(f"Unexpected error in download/analyze: {e}", exc_info=True)
            return JSONResponse(
                status_code=500, content={"error": f"Failed to analyze order: {str(e)}"}
            )

    except Exception as e:
        logger.error(f"Error in analyze-case: {e}")
        return JSONResponse(
            status_code=500, content={"error": f"Failed to analyze case: {str(e)}"}
        )


@app.post("/auto-orders/bulk-process", tags=["Auto Order Management"])
async def bulk_process_orders(request: Request, current_user=Depends(get_current_user)):
    """Bulk process specific cases by IDs with configurable max sequences"""
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
        logger.error(f"Error in bulk-process-orders: {e}")
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

        # Record manual link in case-details.
        get_auto_order_manager()._create_order_link(
            case_id,
            {
                "order_link": order_link,
                "filename": file.filename,
                "source": "manual_upload",
            },
        )

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
                logger.warning(f"Failed to create search index: {index_error}")

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
                        "order_petitioner": analysis_result["data"].get(
                            "order_petitioner"
                        ),
                        "order_respondent": analysis_result["data"].get(
                            "order_respondent"
                        ),
                        "government_pleader": analysis_result["data"].get(
                            "government_pleader"
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
        logger.error(f"Error uploading manual order: {e}")
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

        query = (
            db.collection("daily-boards")
            .where("board_date", ">=", start_date.strftime("%Y-%m-%d"))
            .where("board_date", "<=", end_date.strftime("%Y-%m-%d"))
            .limit(limit * 3)
        )

        cases = query.get()

        case_list = []
        for case_doc in cases:
            case_data = case_doc.to_dict()
            case_ref = f"{case_data.get('case_type')}/{case_data.get('case_no')}/{case_data.get('case_year')}"
            status = (
                get_auto_order_manager()
                ._get_case_order_context(case_ref)
                .get("order_status", "not_linked")
            )
            if status not in {"not_linked", "order_failed", "order_analysis_failed"}:
                continue
            case_info = {
                "id": case_doc.id,
                "case_ref": case_ref,
                "board_date": case_data.get("board_date"),
            }
            case_list.append(case_info)
            if len(case_list) >= limit:
                break

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

        logger.info(
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
        logger.error(f"Error in scheduled retry: {e}")
        return JSONResponse(
            status_code=500, content={"error": f"Scheduled retry failed: {str(e)}"}
        )


@app.get("/admin/test-gcs", tags=["Admin Order Management"])
async def test_gcs_access(current_user=Depends(require_admin)):
    """Smoke-test GCS bucket read and write access from Cloud Run.

    Writes a tiny sentinel object, reads it back, then deletes it.
    Returns ``status: ok`` when the service account can reach the bucket,
    or ``status: error`` with the exception detail when it cannot.
    """
    mgr = get_auto_order_manager()
    if not mgr._gcs_bucket_name:
        return {"status": "skipped", "reason": "ORDER_PDF_BUCKET env var is not set"}
    try:
        from google.cloud import storage as gcs_storage

        client = gcs_storage.Client()
        bucket = client.bucket(mgr._gcs_bucket_name)
        blob = bucket.blob("__health-check__.txt")
        blob.upload_from_string(b"ok", content_type="text/plain")
        data = blob.download_as_bytes()
        blob.delete()
        return {
            "status": "ok",
            "bucket": mgr._gcs_bucket_name,
            "read_write": data == b"ok",
        }
    except Exception as exc:
        return {
            "status": "error",
            "bucket": mgr._gcs_bucket_name,
            "detail": str(exc),
        }


@app.get("/admin/order-status-overview", tags=["Admin Order Management"])
async def get_order_status_overview(current_user=Depends(require_admin)):
    """
    Get overview of order statuses for admin dashboard
    Shows counts for each order status
    """
    try:
        db = firestore.client()

        cases = db.collection("daily-boards").stream()

        status_counts = {
            "not_linked": 0,
            "linked": 0,
            "analysed": 0,
            "order_failed": 0,
            "order_analysis_failed": 0,
        }

        for case_doc in cases:
            case_data = case_doc.to_dict()
            case_ref = f"{case_data.get('case_type', '')}/{case_data.get('case_no', '')}/{case_data.get('case_year', '')}"
            status = (
                get_auto_order_manager()
                ._get_case_order_context(case_ref)
                .get("order_status", "not_linked")
            )

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
        logger.error(f"Error getting order status overview: {e}")
        return JSONResponse(
            status_code=500,
            content={"error": f"Failed to get order status overview: {str(e)}"},
        )


@app.get("/admin/review-queue", tags=["Admin Order Management"])
async def get_admin_review_queue(current_user=Depends(require_admin)):
    """Return cases in the manual_review_required lifecycle state."""
    try:
        db = firestore.client()
        docs = (
            db.collection("case-details")
            .where("lifecycle_status", "==", "manual_review_required")
            .stream()
        )
        cases = []
        for doc in docs:
            data = doc.to_dict() or {}
            data.setdefault("id", doc.id)
            cases.append(data)
        return JSONResponse(content=cases)
    except Exception as e:
        logger.error(f"Error fetching review queue: {e}")
        return JSONResponse(
            status_code=500,
            content={"error": f"Failed to fetch review queue: {str(e)}"},
        )


@app.post("/admin/orders/{doc_id}/override", tags=["Admin Order Management"])
async def admin_override_order_category(
    doc_id: str, request: Request, current_user=Depends(require_admin)
):
    """Override the order category for a case in the manual review queue."""
    try:
        body = await request.json()
        order_category = body.get("order_category")
        if not order_category:
            return JSONResponse(
                status_code=400, content={"error": "order_category is required"}
            )

        db = firestore.client()
        doc_ref = db.collection("case-details").document(doc_id)
        doc_snap = doc_ref.get()
        if not doc_snap.exists:
            return JSONResponse(status_code=404, content={"error": "Case not found"})

        doc_ref.update(
            {
                "order_category": order_category,
                "lifecycle_status": "analysed",
                "order_manual_override": True,
                "order_manual_override_by": current_user.get("uid"),
                "order_analysis_timestamp": datetime.now().isoformat(),
            }
        )
        return JSONResponse(
            content={
                "success": True,
                "doc_id": doc_id,
                "order_category": order_category,
            }
        )
    except Exception as e:
        logger.error(f"Error overriding order category for {doc_id}: {e}")
        return JSONResponse(
            status_code=500,
            content={"error": f"Failed to override order category: {str(e)}"},
        )


@app.post("/admin/bulk-order-processing", tags=["Admin Order Management"])
async def admin_bulk_order_processing(
    request: Request, current_user=Depends(require_admin)
):
    """
    Admin endpoint to trigger bulk order processing for cases with specific order status.
    Adds cases to async processing queue and returns immediately.

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
            "order_statuses", ["not_linked", "linked", "order_failed"]
        )
        limit = body.get("limit", 100)
        days_back = body.get("days_back")
        query = db.collection("daily-boards")

        # Filter by date if specified (board_date is stored as datetime object)
        if days_back:
            start_date = datetime.now() - timedelta(days=days_back)
            # Convert to datetime object to match database storage format
            start_datetime = datetime(
                start_date.year, start_date.month, start_date.day, 0, 0, 0
            )
            query = query.where("board_date", ">=", start_datetime)

        # Get all cases and filter by status from case-details.
        all_cases = query.limit(limit * 3).stream()

        case_list = []
        for case_doc in all_cases:
            case_data = case_doc.to_dict()
            case_ref = f"{case_data.get('case_type')}/{case_data.get('case_no')}/{case_data.get('case_year')}"
            case_status = (
                get_auto_order_manager()
                ._get_case_order_context(case_ref)
                .get("order_status", "not_linked")
            )

            # Normalize: treat "unknown" or missing status as "not_linked"
            if case_status == "unknown" or case_status is None or case_status == "":
                case_status = "not_linked"

            if case_status in order_statuses:
                case_info = {
                    "id": case_doc.id,
                    "case_ref": case_ref,
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
        logger.info(
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
        logger.error(f"Error in admin bulk order processing: {e}")
        return JSONResponse(
            status_code=500,
            content={"error": f"Admin bulk processing failed: {str(e)}"},
        )


# Queue Management Endpoints
def _get_distributed_queue_metrics(scan_limit: int = 10000) -> Dict:
    """Approximate queue backlog from persisted lifecycle status across all instances."""
    try:
        db = firestore.client()
        docs = list(db.collection("case-details").limit(scan_limit).stream())

        fetch_pending_statuses = {
            "fetch_queued",
            "fetch_in_progress",
            "fetch_failed_retryable",
        }
        analysis_pending_statuses = {
            "analysis_queued",
            "analysis_in_progress",
            "analysis_failed_retryable",
        }

        fetch_pending = 0
        analysis_pending = 0

        for doc in docs:
            data = doc.to_dict() or {}
            lifecycle_status = str(data.get("lifecycle_status") or "").strip()
            if lifecycle_status in fetch_pending_statuses:
                fetch_pending += 1
            if lifecycle_status in analysis_pending_statuses:
                analysis_pending += 1

        return {
            "fetch_pending_cases": fetch_pending,
            "analysis_pending_cases": analysis_pending,
            "scan_limit": scan_limit,
            "sampled_case_count": len(docs),
        }
    except Exception as e:
        logger.error(f"Error building distributed queue metrics: {e}")
        return {
            "fetch_pending_cases": 0,
            "analysis_pending_cases": 0,
            "scan_limit": scan_limit,
            "sampled_case_count": 0,
            "error": str(e),
        }


@app.get("/queue/status", tags=["Queue Management"])
async def get_queue_status(current_user=Depends(get_current_user)):
    """Get status of async fetch and analysis processing queues."""
    try:
        import time as _time

        if (
            _time.time() - _queue_status_cache["ts"] < 30
            and _queue_status_cache["data"]
        ):
            return JSONResponse(content=_queue_status_cache["data"])

        queue_size = order_processing_queue.qsize()
        analysis_queue_size = analysis_processing_queue.qsize()
        distributed_metrics = _get_distributed_queue_metrics()

        # Count manual review cases inline so the frontend can derive the
        # badge count from this single endpoint instead of polling /admin/review-queue.
        try:
            db = firestore.client()
            review_count = (
                db.collection("case-details")
                .where("lifecycle_status", "==", "manual_review_required")
                .count()
                .get()[0][0]
                .value
            )
        except Exception:
            review_count = 0

        result = {
            "fetch_queue_size": queue_size,
            "analysis_queue_size": analysis_queue_size,
            "fetch_pending_cases": distributed_metrics.get("fetch_pending_cases", 0),
            "analysis_pending_cases": distributed_metrics.get(
                "analysis_pending_cases", 0
            ),
            "review_queue_count": review_count,
            "distributed_metrics": distributed_metrics,
            "fetch_processing_active": processing_active,
            "analysis_processing_active": analysis_processing_active,
            "status": (
                "active"
                if processing_active or analysis_processing_active
                else "inactive"
            ),
            "message": (
                f"Fetch queue: {queue_size}, Analysis queue: {analysis_queue_size}"
                if queue_size > 0 or analysis_queue_size > 0
                else (
                    "Local queues are empty; check distributed pending counts for multi-instance deployments"
                    if distributed_metrics.get("fetch_pending_cases", 0) > 0
                    or distributed_metrics.get("analysis_pending_cases", 0) > 0
                    else "Both queues are empty"
                )
            ),
        }
        _queue_status_cache["ts"] = _time.time()
        _queue_status_cache["data"] = result
        return JSONResponse(content=result)

    except Exception as e:
        logger.error(f"Error getting queue status: {e}")
        return JSONResponse(
            status_code=500, content={"error": f"Failed to get queue status: {str(e)}"}
        )


@app.post("/queue/restart", tags=["Queue Management"])
async def restart_queue_processing(current_user=Depends(require_admin)):
    """Restart background fetch and analysis processing (admin only)."""
    try:
        global processing_active, analysis_processing_active
        processing_active = False
        analysis_processing_active = False
        await asyncio.sleep(1)  # Allow current processing to finish
        await ensure_background_processing_active()
        await ensure_background_analysis_processing_active()

        return JSONResponse(
            content={
                "success": True,
                "message": "Background fetch and analysis processing restarted",
                "fetch_processing_active": processing_active,
                "analysis_processing_active": analysis_processing_active,
            }
        )

    except Exception as e:
        logger.error(f"Error restarting queue processing: {e}")
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
        logger.error(f"Error getting user matters: {e}")
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
        logger.error(f"Error getting matters summary: {e}")
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
        logger.error(f"Error getting user role config: {e}")
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
        logger.error(f"Error configuring user role: {e}")
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
        logger.error(f"Error generating name variations: {e}")
        return JSONResponse(
            status_code=500,
            content={"error": f"Failed to generate name variations: {str(e)}"},
        )


# Order Management Center Endpoints
@app.get("/orders/overview-stats", tags=["Order Management"])
async def get_order_overview_stats(current_user=Depends(get_current_user)):
    """Get comprehensive overview statistics for Order Management Center"""
    try:
        import time as _time

        if (
            _time.time() - _overview_stats_cache["ts"] < 120
            and _overview_stats_cache["data"]
        ):
            return JSONResponse(content=_overview_stats_cache["data"])

        ensure_firebase()
        db = firestore.client()
        total_cases_docs = list(db.collection("daily-boards").limit(10000).stream())
        total_cases = len(total_cases_docs)

        case_docs = list(db.collection("case-details").limit(10000).stream())
        cases_with_orders = 0
        recent_successful = 0
        recent_failed = 0

        for doc in case_docs:
            case_data = doc.to_dict() or {}
            status = case_data.get("latest_order_status", "not_linked")
            if status and status != "not_linked":
                cases_with_orders += 1
            if status == "analysed":
                recent_successful += 1
            if status in {"order_failed", "order_analysis_failed"}:
                recent_failed += 1

        cases_without_orders = total_cases - cases_with_orders
        analysis_completion_rate = round(
            (cases_with_orders / total_cases * 100) if total_cases > 0 else 0, 1
        )

        result = {
            "total_cases": total_cases,
            "cases_with_orders": cases_with_orders,
            "cases_without_orders": cases_without_orders,
            "analysis_completion_rate": analysis_completion_rate,
            "recent_successful_analyses": recent_successful,
            "recent_failed_analyses": recent_failed,
            "last_updated": datetime.now().isoformat(),
        }
        _overview_stats_cache["ts"] = _time.time()
        _overview_stats_cache["data"] = result
        return JSONResponse(content=result)

    except Exception as e:
        logger.error(f"Error getting order overview stats: {e}")
        return JSONResponse(
            status_code=500,
            content={"error": f"Failed to get overview stats: {str(e)}"},
        )


@app.get("/orders/queue-status", tags=["Order Management"])
async def get_orders_queue_status(current_user=Depends(get_current_user)):
    """Get current processing queue status"""
    try:
        # Get approximate queue size (this is in-memory, so basic check)
        pending_items = order_processing_queue.qsize() if order_processing_queue else 0
        analysis_pending_items = (
            analysis_processing_queue.qsize() if analysis_processing_queue else 0
        )
        distributed_metrics = _get_distributed_queue_metrics()

        return JSONResponse(
            content={
                "active": processing_active or analysis_processing_active,
                "fetch_active": processing_active,
                "analysis_active": analysis_processing_active,
                "pending": pending_items,
                "analysis_pending": analysis_pending_items,
                "fetch_pending_cases": distributed_metrics.get(
                    "fetch_pending_cases", 0
                ),
                "analysis_pending_cases": distributed_metrics.get(
                    "analysis_pending_cases", 0
                ),
                "distributed_metrics": distributed_metrics,
                "last_checked": datetime.now().isoformat(),
            }
        )

    except Exception as e:
        logger.error(f"Error getting queue status: {e}")
        return JSONResponse(content={"active": False, "pending": 0, "error": str(e)})


_LIFECYCLE_ACTION_LABELS = {
    "analysed": ("Analysis Complete", "success"),
    "fetch_succeeded": ("Order Downloaded", "success"),
    "fetch_failed_terminal": ("Download Failed", "error"),
    "fetch_failed_retryable": ("Download Failed (Retrying)", "warning"),
    "analysis_failed_terminal": ("Analysis Failed", "error"),
    "analysis_failed_retryable": ("Analysis Failed (Retrying)", "warning"),
    "manual_review_required": ("Manual Review Required", "warning"),
    "fetch_in_progress": ("Fetching Order", "info"),
    "analysis_in_progress": ("Analysing Order", "info"),
    "fetch_queued": ("Queued for Download", "info"),
    "analysis_queued": ("Queued for Analysis", "info"),
}


@app.get("/orders/recent-activity", tags=["Order Management"])
async def get_recent_activity(
    limit: int = Query(20, description="Number of recent activities to return"),
    current_user=Depends(get_current_user),
):
    """Get recent order processing activity from case-details lifecycle events."""
    try:
        db = firestore.client()
        docs = (
            db.collection("case-details")
            .order_by("updated_at", direction=firestore.Query.DESCENDING)
            .limit(limit)
            .stream()
        )
        recent_activity = []
        for doc in docs:
            data = doc.to_dict() or {}
            lifecycle_status = str(data.get("lifecycle_status") or "")
            action, status = _LIFECYCLE_ACTION_LABELS.get(
                lifecycle_status, ("Status Update", "info")
            )
            case_type = data.get("case_type") or ""
            case_no = str(data.get("case_no") or "")
            case_year = str(data.get("case_year") or "")
            if case_type and case_no and case_year:
                case_ref = f"{case_type}/{case_no}/{case_year}"
            else:
                case_ref = doc.id.replace("-", "/", 2)
            updated_at = data.get("updated_at")
            timestamp = (
                updated_at.isoformat()
                if hasattr(updated_at, "isoformat")
                else datetime.now().isoformat()
            )
            recent_activity.append(
                {
                    "timestamp": timestamp,
                    "action": action,
                    "case_ref": case_ref,
                    "status": status,
                    "lifecycle_status": lifecycle_status,
                }
            )
        return JSONResponse(content=recent_activity)
    except Exception as e:
        logger.error(f"Error getting recent activity: {e}")
        return JSONResponse(
            status_code=500,
            content={"error": f"Failed to get recent activity: {str(e)}"},
        )


@app.get("/orders/pdf/{doc_id}", tags=["Order Management"])
async def get_order_pdf(doc_id: str):
    """Serve a court order PDF with automatic GCS upgrade.

    - GCS URLs: fetched via service-account credentials and streamed back
      (no public bucket access required; Cloud Run ADC authenticates).
    - Live court URLs: stream PDF to client and upgrade the stored link to GCS
      in the background so the next access is served from GCS.
    - Expired court URLs: queue re-fetch via AutoOrderManager, return 503.

    No authentication required — court PDFs are public documents, consistent
    with the current behaviour where court URLs are opened directly.
    """
    try:
        ensure_firebase()
        db = firestore.client()
        doc = db.collection("daily-boards").document(doc_id).get()
        if not doc.exists:
            raise HTTPException(status_code=404, detail="Case not found")

        case_data = doc.to_dict() or {}

        # order_link lives in case-details — daily-boards is immutable board data.
        _ct = case_data.get("case_type", "")
        _cn = str(case_data.get("case_no") or "")
        _cy = str(case_data.get("case_year") or "")
        order_link = ""
        if _ct and _cn and _cy:
            _details_id = f"{_ct}-{_cn}-{_cy}"
            _details_snap = db.collection("case-details").document(_details_id).get()
            if _details_snap.exists:
                _details = _details_snap.to_dict() or {}
                order_link = (_details.get("latest_order_link") or "").strip()
                if not order_link:
                    for _o in reversed(_details.get("orders") or []):
                        if isinstance(_o, dict) and _o.get("order_link"):
                            order_link = _o["order_link"].strip()
                            break

        if not order_link:
            raise HTTPException(
                status_code=404, detail="No order link stored for this case"
            )

        # GCS URL: download via service-account credentials and stream back.
        # Public bucket access is not required — Cloud Run ADC authenticates
        # transparently, so the bucket can stay private.
        if order_link.startswith("https://storage.googleapis.com"):
            try:
                from google.cloud import storage as gcs_storage

                # Parse  https://storage.googleapis.com/{bucket}/{blob_path}
                without_prefix = order_link[len("https://storage.googleapis.com/") :]
                bucket_name, _, blob_name = without_prefix.partition("/")
                client = gcs_storage.Client()
                pdf_bytes = (
                    client.bucket(bucket_name).blob(blob_name).download_as_bytes()
                )
                return Response(
                    content=pdf_bytes,
                    media_type="application/pdf",
                    headers={
                        "Content-Disposition": f'inline; filename="order-{doc_id}.pdf"'
                    },
                )
            except Exception as gcs_err:
                logger.warning(
                    "get_order_pdf: GCS download failed for doc_id=%s: %s",
                    doc_id,
                    gcs_err,
                )
                # Blob missing or inaccessible — queue a re-fetch so the PDF is
                # retrieved from the court API and re-uploaded to GCS, exactly as
                # we do for expired court URLs.
                _case_type = case_data.get("case_type", "")
                _case_no = str(case_data.get("case_no") or "")
                _case_year = str(case_data.get("case_year") or "")
                if _case_type and _case_no:
                    _refetch_data = {**case_data, "id": doc_id}
                    if not _refetch_data.get("case_ref") and _case_type and _case_year:
                        _refetch_data[
                            "case_ref"
                        ] = f"{_case_type}/{_case_no}/{_case_year}"
                    loop = asyncio.get_event_loop()
                    loop.run_in_executor(
                        executor,
                        get_auto_order_manager()._process_single_case,
                        _refetch_data,
                    )
                return JSONResponse(
                    status_code=503,
                    content={
                        "error": "order_link_expired",
                        "message": (
                            "Order PDF is unavailable. The system is re-fetching it — "
                            "please try again in a few minutes."
                        ),
                        "doc_id": doc_id,
                    },
                )

        # Court URL: attempt download
        try:
            resp = requests.get(order_link, timeout=15)
            resp.raise_for_status()
            pdf_bytes = resp.content
            if not pdf_bytes or b"%PDF" not in pdf_bytes[:10]:
                raise ValueError("Response is not a valid PDF")
        except Exception:
            # Expired or unreachable — queue re-fetch and tell the client to retry
            case_type = case_data.get("case_type", "")
            case_no = str(case_data.get("case_no") or "")
            case_year = str(case_data.get("case_year") or "")
            if case_type and case_no:
                _refetch_data = {**case_data, "id": doc_id}
                if not _refetch_data.get("case_ref") and case_type and case_year:
                    _refetch_data["case_ref"] = f"{case_type}/{case_no}/{case_year}"
                loop = asyncio.get_event_loop()
                loop.run_in_executor(
                    executor,
                    get_auto_order_manager()._process_single_case,
                    _refetch_data,
                )
            return JSONResponse(
                status_code=503,
                content={
                    "error": "order_link_expired",
                    "message": (
                        "Order link has expired. The system is re-fetching it — "
                        "please try again in a few minutes."
                    ),
                    "doc_id": doc_id,
                },
            )

        # Court URL still live: serve the PDF and upgrade to GCS in the background
        case_type = case_data.get("case_type", "")
        case_no = str(case_data.get("case_no") or "")
        case_year = str(case_data.get("case_year") or "")
        case_ref = f"{case_type}/{case_no}/{case_year}"
        # Use the actual order date from case-details (preferred) to match the
        # blob name used during the original upload. Board date can differ from
        # the order date (e.g. a hearing listed on 2025-04-09 whose order was
        # issued on 2025-04-08).
        _raw_order_date = (
            _details.get("latest_order_date")
            or case_data.get("board_date")
            or datetime.now().strftime("%Y-%m-%d")
        )
        # Firestore Timestamps stringify as "YYYY-MM-DD HH:MM:SS"; strip the time
        # component so GCS blob names don't contain spaces.
        order_date = str(_raw_order_date).split(" ")[0].split("T")[0]

        def _upgrade_to_gcs(
            _pdf: bytes, _case_ref: str, _order_date: str, _doc_id: str
        ) -> None:
            mgr = get_auto_order_manager()
            gcs_url = mgr._upload_order_to_gcs(_pdf, _case_ref, _order_date)
            if not gcs_url:
                return
            try:
                mgr.case_store.append_case_order(
                    _case_ref, {"order_link": gcs_url, "order_date": _order_date}
                )
                logger.info(
                    "get_order_pdf: upgraded order_link to GCS for doc_id=%s", _doc_id
                )
            except Exception as _e:
                logger.warning(
                    "get_order_pdf: Firestore update after GCS upload failed: %s", _e
                )

        asyncio.get_event_loop().run_in_executor(
            executor, _upgrade_to_gcs, pdf_bytes, case_ref, order_date, doc_id
        )

        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": f'inline; filename="order-{doc_id}.pdf"'},
        )

    except HTTPException:
        raise
    except Exception as exc:
        logger.error("get_order_pdf failed for doc_id=%s: %s", doc_id, exc)
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/admin/gcs-bucket-info", tags=["Admin"])
async def gcs_bucket_info(current_user=Depends(require_admin)):
    """Return GCS bucket metadata so admins can verify no lifecycle rules are deleting blobs.

    If the bucket has a lifecycle rule that deletes objects after N days, order PDFs
    would silently disappear, causing the proxy to return 503 even for GCS URLs.
    """
    try:
        from google.cloud import storage as gcs_storage

        mgr = get_auto_order_manager()
        bucket_name = mgr._gcs_bucket_name
        if not bucket_name:
            return JSONResponse(
                status_code=400,
                content={"error": "ORDER_PDF_BUCKET env var not set on this instance"},
            )
        client = gcs_storage.Client()
        bucket = client.get_bucket(bucket_name)
        rules = []
        if bucket.lifecycle_rules:
            for rule in bucket.lifecycle_rules:
                rules.append(rule)
        return JSONResponse(
            content={
                "bucket": bucket_name,
                "location": bucket.location,
                "storage_class": bucket.storage_class,
                "lifecycle_rules": rules,
                "lifecycle_rule_count": len(rules),
                "versioning_enabled": bucket.versioning_enabled,
                "diagnosis": (
                    "No lifecycle rules — blobs are retained indefinitely."
                    if not rules
                    else f"WARNING: {len(rules)} lifecycle rule(s) found — "
                    "they may be deleting order PDFs. Check rules above."
                ),
            }
        )
    except Exception as exc:
        logger.error("gcs_bucket_info failed: %s", exc)
        return JSONResponse(
            status_code=500,
            content={"error": str(exc)},
        )


@app.post("/orders/migrate-to-gcs", tags=["Order Management"])
async def migrate_orders_to_gcs(
    limit: int = Query(100, description="Max docs to process per call (max 500)"),
    current_user=Depends(require_admin),
):
    """Admin: backfill existing court order URLs to permanent GCS URLs.

    Scans ``daily-boards`` documents that hold expiring court URLs, downloads
    each PDF, uploads it to the configured GCS bucket, and updates Firestore.
    Run repeatedly with the default ``limit`` until ``skipped`` == ``total_scanned``.
    """
    mgr = get_auto_order_manager()
    if not mgr._gcs_bucket_name:
        raise HTTPException(
            status_code=400,
            detail=(
                "ORDER_PDF_BUCKET is not configured. "
                "Set the environment variable and redeploy before running the backfill."
            ),
        )

    limit = min(limit, 500)
    db = firestore.client()
    migrated = skipped = failed = 0

    # Firestore has no "not starts-with" filter; over-fetch and filter in Python
    docs = list(
        db.collection("daily-boards")
        .where("order_link", "!=", "")
        .limit(limit * 5)
        .stream()
    )

    for doc in docs:
        if migrated + failed >= limit:
            break

        data = doc.to_dict() or {}
        order_link = (data.get("order_link") or "").strip()

        if not order_link or order_link.startswith("https://storage.googleapis.com"):
            skipped += 1
            continue

        case_type = data.get("case_type", "")
        case_no = str(data.get("case_no") or "")
        case_year = str(data.get("case_year") or "")
        case_ref = f"{case_type}/{case_no}/{case_year}"
        order_date = str(data.get("latest_order_date") or data.get("board_date") or "")

        try:
            resp = requests.get(order_link, timeout=15)
            resp.raise_for_status()
            pdf_bytes = resp.content
            if not pdf_bytes or b"%PDF" not in pdf_bytes[:10]:
                raise ValueError("Not a valid PDF")

            gcs_url = mgr._upload_order_to_gcs(pdf_bytes, case_ref, order_date)
            if not gcs_url:
                raise ValueError("GCS upload returned None")

            doc.reference.update({"order_link": gcs_url})
            mgr.case_store.append_case_order(
                case_ref, {"order_link": gcs_url, "order_date": order_date}
            )
            migrated += 1
        except Exception as exc:
            logger.warning("migrate-to-gcs failed for %s: %s", doc.id, exc)
            failed += 1

    return {
        "migrated": migrated,
        "skipped": skipped,
        "failed": failed,
        "total_scanned": len(docs),
    }


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
        from datetime import datetime

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
            logger.info(f"Admin {user_id} generating bill for user: {user_name}")

            # Step 1: Collect all unique AGP names with PRIORITY ORDER
            # Priority: 1) government_pleader (from order analysis)
            #          2) respondent_lawyer (from board data)
            #          3) additional_respondent_lawyers (from board data)
            # Restrict to the requested date range so we don't scan the entire
            # collection — avoids timeouts on large deployments.
            boards_ref = db.collection("daily-boards")
            all_cases = (
                boards_ref.where("board_date", ">=", start_dt)
                .where("board_date", "<=", end_dt)
                .stream()
            )

            unique_agp_names = set()
            cases_by_agp: Dict[str, List[Any]] = {}

            for case_doc in all_cases:
                case_data = case_doc.to_dict()
                case_id = case_doc.id

                # PRIORITY 1: government_pleader (from order analysis)
                # This is the MOST ACCURATE source as it's extracted from the actual court order
                government_pleader = case_data.get("government_pleader")
                has_order_agp = False

                if government_pleader:
                    # Handle both string and list formats
                    if isinstance(government_pleader, str):
                        # Single string - treat as one name
                        agp_name = government_pleader.strip()
                        if agp_name:
                            unique_agp_names.add(agp_name)
                            if agp_name not in cases_by_agp:
                                cases_by_agp[agp_name] = []
                            cases_by_agp[agp_name].append((case_id, case_data))
                            has_order_agp = True
                    elif isinstance(government_pleader, list):
                        # List of names
                        for agp_name in government_pleader:
                            agp_name = str(agp_name).strip() if agp_name else ""
                            if agp_name:
                                unique_agp_names.add(agp_name)
                                if agp_name not in cases_by_agp:
                                    cases_by_agp[agp_name] = []
                                cases_by_agp[agp_name].append((case_id, case_data))
                                has_order_agp = True

                # PRIORITY 2 & 3: Only use board data if NO government_pleader exists
                # This ensures government_pleader from order analysis takes precedence
                if not has_order_agp:
                    # Source 2: respondent_lawyer (from board data)
                    respondent_lawyer = case_data.get("respondent_lawyer", "").strip()
                    if respondent_lawyer:
                        unique_agp_names.add(respondent_lawyer)
                        if respondent_lawyer not in cases_by_agp:
                            cases_by_agp[respondent_lawyer] = []
                        cases_by_agp[respondent_lawyer].append((case_id, case_data))

                    # Source 3: additional_respondent_lawyers (from board data)
                    additional_lawyers = case_data.get(
                        "additional_respondent_lawyers", []
                    )
                    if additional_lawyers and isinstance(additional_lawyers, list):
                        for lawyer_name in additional_lawyers:
                            lawyer_name = lawyer_name.strip().rstrip(",")
                            if lawyer_name:
                                unique_agp_names.add(lawyer_name)
                                if lawyer_name not in cases_by_agp:
                                    cases_by_agp[lawyer_name] = []
                                cases_by_agp[lawyer_name].append((case_id, case_data))

            logger.info(
                f"📚 Collected {len(unique_agp_names)} unique AGP names (PRIORITY: government_pleader > respondent_lawyer > additional_respondent_lawyers)"
            )

            # Log sample of AGP names for debugging
            agp_names_list = sorted(list(unique_agp_names))
            logger.info(f"📝 Sample AGP names (first 10): {agp_names_list[:10]}")
            logger.info(f"📝 Sample AGP names (last 10): {agp_names_list[-10:]}")

            # Step 2: Use ENHANCED fuzzy matching with initials support
            # Changed: Instead of finding only the BEST match, find ALL AGP names that match with >= 50% confidence
            user_manager = get_user_manager()
            threshold = 0.50

            # Find ALL matching AGP names with scores >= 50% in one efficient pass
            all_matching_agps = user_manager.match_user_name_to_all_agps(
                user_name, list(unique_agp_names), threshold=threshold
            )

            if all_matching_agps:
                # Step 3: Collect cases from ALL matching AGP names
                matched_cases = []
                matched_variants = []
                for agp_variant, confidence in all_matching_agps:
                    if agp_variant in cases_by_agp:
                        variant_cases = cases_by_agp[agp_variant]
                        matched_cases.extend(variant_cases)
                        matched_variants.append(agp_variant)
                        logger.info(
                            f"   📁 '{agp_variant}' ({confidence:.0%}): {len(variant_cases)} cases"
                        )

                # Use the best match for display purposes
                matched_agp = all_matching_agps[0][0] if all_matching_agps else None
                confidence = all_matching_agps[0][1] if all_matching_agps else 0.0

                logger.info(
                    f"📊 Collected {len(matched_variants)} AGP variants matching '{user_name}'"
                )
                logger.info(f"📁 Total cases across all variants: {len(matched_cases)}")

                # Track filtering for debugging
                date_filtered = 0
                duplicate_filtered = 0

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
                                fee_info = calculate_case_fee(
                                    case_data, board_date=board_date_str
                                )

                                # Extract parties information
                                parties = extract_parties_info(case_data)

                                bill_entry = {
                                    "id": case_id,
                                    "date": board_date_str,
                                    "case_detail": f"{case_data.get('case_type')}/{case_data.get('case_no')}/{case_data.get('case_year')}",
                                    "case_type": case_data.get("case_type", ""),
                                    "case_no": case_data.get("case_no", ""),
                                    "case_year": case_data.get("case_year", ""),
                                    "parties_name": parties,
                                    "results": fee_info["result"],
                                    "fees_rs": fee_info["fee"],
                                    "order_link": fee_info.get("order_link"),
                                    "order_category": fee_info.get("order_category"),
                                    "agp_name": matched_agp,  # Show the actual AGP name from data
                                    "user_name": user_name,  # Show the selected user name
                                    "name_match_confidence": round(
                                        confidence, 3
                                    ),  # Include confidence score
                                    "editable": True,
                                }
                                bill_entries.append(bill_entry)
                        except ValueError:
                            logger.warning(
                                f"Invalid date format for case {case_id}: {board_date_str}"
                            )
                            continue

                logger.info(
                    f"📊 Filtering summary: {len(matched_cases)} total cases → {len(bill_entries)} included"
                )
                logger.info(f"   - Date range: {start_date} to {end_date}")
                logger.info(
                    f"   - Cases outside date range: {len(matched_cases) - len(bill_entries)}"
                )
                logger.info(
                    f"✅ Found {len(bill_entries)} bill entries for user '{user_name}'"
                )
            else:
                # No AGP name in the date range matched the requested user name.
                # bill_entries stays empty — return a valid empty bill rather than
                # a 400, so the UI shows "0 entries" instead of an error banner.
                logger.warning(
                    "No AGP name in %s–%s matched '%s' above 50%% threshold",
                    start_date,
                    end_date,
                    user_name,
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
                                fee_info = calculate_case_fee(
                                    case_data, board_date=board_date_str
                                )

                                # Extract parties information
                                parties = extract_parties_info(case_data)

                                bill_entry = {
                                    "id": case_id,
                                    "date": board_date_str,
                                    "case_detail": f"{case_data.get('case_type')}/{case_data.get('case_no')}/{case_data.get('case_year')}",
                                    "case_type": case_data.get("case_type", ""),
                                    "case_no": case_data.get("case_no", ""),
                                    "case_year": case_data.get("case_year", ""),
                                    "parties_name": parties,
                                    "results": fee_info["result"],
                                    "fees_rs": fee_info["fee"],
                                    "order_link": fee_info.get("order_link"),
                                    "order_category": fee_info.get("order_category"),
                                    "confidence_score": mapping_data.get(
                                        "confidence_score", 0.0
                                    ),
                                    "match_source": mapping_data.get("match_source"),
                                    "agp_name": case_data.get("agp_name", "N/A"),
                                    "editable": True,
                                }
                                bill_entries.append(bill_entry)

                        except ValueError:
                            logger.warning(
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
        if user_name and "matched_agp" in locals() and matched_agp is not None:
            response_data["debug_info"] = {
                "requested_name": user_name,
                "matched_agp_name": matched_agp,
                "match_confidence": round(confidence, 3),
                "total_cases_for_agp": len(cases_by_agp.get(matched_agp, [])),
                "cases_in_date_range": len(bill_entries),
            }

        return JSONResponse(content=response_data)

    except Exception as e:
        logger.error(f"Error generating bill data: {e}")
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
            transaction.set(
                counter_ref,
                {
                    "user_id": user_id,
                    "year": year,
                    "sequence": next_sequence,
                    "last_updated": firestore.SERVER_TIMESTAMP,
                },
            )

            return next_sequence

        # Execute transaction
        transaction = db.transaction()
        next_sequence = increment_counter(transaction)

        # Format: BILL/YEAR/SEQUENCE (e.g., BILL/2025/001)
        bill_number = f"BILL/{year}/{next_sequence:03d}"

        logger.info(f"✨ Generated bill number: {bill_number} for user {user_id}")
        return bill_number, next_sequence

    except Exception as e:
        logger.error(f"Error generating bill number: {e}")
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
        logger.error(f"Error generating month description: {e}")
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
            except ValueError:
                pass

        # Generate unique bill number (transaction-safe to prevent duplicates)
        bill_number, bill_sequence = generate_bill_number_safe(
            db, user_id, current_year
        )

        # Generate month description
        month_description = (
            generate_month_description(start_date, end_date)
            if start_date and end_date
            else ""
        )

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

        logger.info(
            f"✅ Bill saved: {bill_number} for user {user_id}, {month_description}"
        )

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
        logger.error(f"Error saving bill entries: {e}")
        import traceback

        traceback.print_exc()
        return JSONResponse(
            status_code=500, content={"error": f"Failed to save bill entries: {str(e)}"}
        )


@app.get("/bills/my-bills", tags=["Bill Generation"])
async def get_my_bills(
    limit: int = Query(20, description="Maximum number of bills to return"),
    user_id_filter: Optional[str] = Query(
        None, description="Filter by user ID (admin only)"
    ),
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
            query = bills_ref.order_by(
                "created_at", direction=firestore.Query.DESCENDING
            ).limit(limit)
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
        logger.error(f"Error getting user bills: {e}")
        return JSONResponse(
            status_code=500, content={"error": f"Failed to get user bills: {str(e)}"}
        )


def calculate_case_fee(case_data: Dict, board_date: Optional[str] = None) -> Dict:
    """Calculate fee and result based on order analysis.

    Returns a dict with keys: result, fee, order_link, order_category.
    order_link and order_category are populated when the order has been
    analysed; both are None when the case has no linked order.

    When *board_date* (YYYY-MM-DD) is provided, the order whose board_date
    or order_date matches is used for fee calculation and the returned
    order_link.  This prevents a later hearing's order from being shown
    against an earlier bill entry for the same case.
    """
    try:
        case_ref = f"{case_data.get('case_type', '')}/{case_data.get('case_no', '')}/{case_data.get('case_year', '')}"
        case_details = (
            get_auto_order_manager().case_store.get_case_details(case_ref) or {}
        )

        orders = case_details.get("orders") or []

        # When board_date is given, only use an order that specifically belongs
        # to that hearing date.  Do NOT fall back to a different date's order —
        # the bill entry for May 6 must not show April 30's order.
        # Without board_date (legacy callers) fall back to the last analysed order.
        target_order: Dict = {}
        if board_date and orders:
            for o in reversed(orders):
                if not isinstance(o, dict):
                    continue
                if (
                    o.get("board_date") == board_date
                    or o.get("order_date") == board_date
                ):
                    target_order = o
                    break
            # No date-specific match → show no link for this hearing
        else:
            # No board_date context (legacy callers) — use last analysed order
            for o in reversed(orders):
                if isinstance(o, dict) and o.get("order_status") == "analysed":
                    target_order = o
                    break

        # If we still have nothing, the case is not yet analysed
        if not target_order or target_order.get("order_status") != "analysed":
            return {
                "result": "*ADJOURNED*",
                "fee": 1250,
                "order_link": None,
                "order_category": None,
            }

        order_link = target_order.get("order_link") or None
        order_category = (target_order.get("order_category") or "").upper()
        order_text = str(target_order.get("order_text") or "").lower()
        order_disposal_reason = str(
            target_order.get("order_disposal_reason") or ""
        ).lower()

        # Fee calculation logic based on order category and content
        # Check for disposal first (highest fee)
        if (
            "DISPOSED" in order_category
            or "disposed" in order_text
            or "disposed" in order_disposal_reason
        ):
            return {
                "result": "WP DISPOSED OF",
                "fee": 2500,
                "order_link": order_link,
                "order_category": order_category,
            }

        # Check for heard & adjourned (middle fee)
        elif "HEARD" in order_category and "ADJOURNED" in order_category:
            return {
                "result": "HEARD & ADJN.",
                "fee": 1875,
                "order_link": order_link,
                "order_category": order_category,
            }

        # Check for simple adjournment (lowest fee)
        elif "ADJOURNED" in order_category or "adjourned" in order_text:
            return {
                "result": "ADJOURNED",
                "fee": 1250,
                "order_link": order_link,
                "order_category": order_category,
            }

        # Default
        else:
            if "HEARD" in order_category:
                return {
                    "result": "HEARD & ADJN.",
                    "fee": 1875,
                    "order_link": order_link,
                    "order_category": order_category,
                }
            else:
                return {
                    "result": "*ADJOURNED*",
                    "fee": 1250,
                    "order_link": None,
                    "order_category": None,
                }

    except Exception as e:
        logger.error(f"Error calculating case fee for case: {e}")
        return {
            "result": "*ADJOURNED*",
            "fee": 1250,
            "order_link": None,
            "order_category": None,
        }


def extract_parties_info(case_data: Dict) -> str:
    """Extract parties information from case data (format: Petitioner vs Respondent)"""
    try:
        case_ref = f"{case_data.get('case_type', '')}/{case_data.get('case_no', '')}/{case_data.get('case_year', '')}"
        case_details = (
            get_auto_order_manager().case_store.get_case_details(case_ref) or {}
        )
        petitioner = str(case_details.get("petitioner") or "").strip()
        respondent = str(case_details.get("respondent") or "").strip()
        if petitioner and respondent:
            return f"{petitioner} Versus {respondent}"

        # Fallback to case reference
        return f"Matter in {case_ref}"

    except Exception as e:
        logger.error(f"Error extracting parties info: {e}")
        return "Parties information not available"


@app.get("/bills/export/excel", tags=["Bill Generation"])
async def export_bill_excel(
    bill_id: str = Query(None, description="Bill ID to export"),
    start_date: str = Query(None, description="Start date for generating fresh export"),
    end_date: str = Query(None, description="End date for generating fresh export"),
    user_name: Optional[str] = Query(
        None, description="User name for bill header (admin only)"
    ),
    current_user=Depends(get_current_user),
):
    """Export bill data as Excel format matching AGP bill specification"""
    try:
        import io
        from datetime import datetime

        from openpyxl import Workbook
        from openpyxl.styles import Alignment, Border, Font, Side

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
            bill_number = bill_data.get("bill_number", bill_number)
            filename = f"bill_{bill_id}.xlsx"

        elif start_date and end_date:
            # Generate fresh export
            response = await generate_bill_data(
                start_date, end_date, user_name, current_user
            )
            if response.status_code != 200:
                return response

            response_data = json.loads(response.body.decode())
            entries = response_data.get("bill_entries", [])
            metadata = {"date_range": {"start": start_date, "end": end_date}}

            # Get AGP name from entries or debug info
            if entries and entries[0].get("agp_name"):
                agp_name = entries[0].get("agp_name")
            elif "debug_info" in response_data and response_data["debug_info"].get(
                "matched_agp_name"
            ):
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
            left=Side(style="thin"),
            right=Side(style="thin"),
            top=Side(style="thin"),
            bottom=Side(style="thin"),
        )
        center_align = Alignment(horizontal="center", vertical="center", wrap_text=True)
        left_align = Alignment(horizontal="left", vertical="center", wrap_text=True)

        # Parse dates for header
        date_range = metadata.get("date_range", {})
        start_dt = datetime.strptime(date_range.get("start", start_date), "%Y-%m-%d")
        end_dt = datetime.strptime(date_range.get("end", end_date), "%Y-%m-%d")
        period_str = (
            f"{start_dt.strftime('%B %Y').upper()} - {end_dt.strftime('%B %Y').upper()}"
        )

        # Row counter
        current_row = 1

        # Header Section
        # Title
        ws.merge_cells(f"A{current_row}:H{current_row}")
        ws[
            f"A{current_row}"
        ] = f"STATEMENT OF PROFESSIONAL FEES BILL OF {agp_name.upper()}"
        ws[f"A{current_row}"].font = title_font
        ws[f"A{current_row}"].alignment = center_align
        current_row += 1

        # Subtitle
        ws.merge_cells(f"A{current_row}:H{current_row}")
        ws[
            f"A{current_row}"
        ] = "A.S.(WRIT CELL),HIGH COURT, MUMBAI FOR CONDUCTING WRIT MATTERS ETC."
        ws[f"A{current_row}"].alignment = center_align
        current_row += 1

        # Government Resolution
        ws.merge_cells(f"A{current_row}:H{current_row}")
        ws[
            f"A{current_row}"
        ] = "SANCTIONED VIDE:- GOVERNMENT OF MAHARASHTRA\nLAW AND JUDICIARY DEPARTMENT,\nGOVERNMENT RESOLUTION NO. MEETING-GPH-2023/C.R.29/D-14,\nDATED-30TH OCTOBER, 2023"
        ws[f"A{current_row}"].alignment = center_align
        current_row += 1

        # Period and Bill Number
        ws.merge_cells(f"A{current_row}:D{current_row}")
        ws[f"A{current_row}"] = f"MONTHS :- {period_str}"
        ws.merge_cells(f"E{current_row}:H{current_row}")
        ws[f"E{current_row}"] = f"BILL NO:- {bill_number}"
        ws[f"E{current_row}"].alignment = Alignment(
            horizontal="right", vertical="center"
        )
        current_row += 1

        # Declaration
        ws.merge_cells(f"A{current_row}:H{current_row}")
        declaration_text = (
            f"DECLARATION : I hereby certify that the below mentioned matters were allotted to me by the Government Pleader, "
            f"I personally appeared in the below mentioned matters. The below mentioned entries/information given in above columns "
            f"are true and correct to the best of my knowledge and belief. I further certify that nothing is suppressed by me. "
            f"Also, the fees which is claimed in bill no. {bill_number} has not been claimed by me earlier."
        )
        ws[f"A{current_row}"] = declaration_text
        ws[f"A{current_row}"].alignment = left_align
        ws.row_dimensions[current_row].height = 60
        current_row += 1

        # Column Headers
        headers = [
            "SR. NO.",
            "DATE",
            "CASE TYPE",
            "CASE NO",
            "CASE YEAR",
            "RESULTS",
            "PARTIES NAME",
            "FEES (RS.)",
        ]
        for col_num, header in enumerate(headers, 1):
            cell = ws.cell(row=current_row, column=col_num, value=header)
            cell.font = header_font
            cell.alignment = center_align
            cell.border = border_thin
        current_row += 1

        # Data rows
        total_fees = 0
        for idx, entry in enumerate(entries, 1):
            # Get case details from separate fields (or parse case_detail if not available)
            case_type = entry.get("case_type", "")
            case_no = entry.get("case_no", "")
            case_year = entry.get("case_year", "")

            # Fallback: parse case_detail if separate fields not present
            if not case_type and not case_no and not case_year:
                case_detail = entry.get("case_detail", "")
                if case_detail:
                    case_parts = case_detail.split("/")
                    case_type = case_parts[0].strip() if len(case_parts) > 0 else ""
                    case_no = case_parts[1].strip() if len(case_parts) > 1 else ""
                    case_year = case_parts[2].strip() if len(case_parts) > 2 else ""

            # Ensure all values are strings (not None) to avoid Excel corruption
            case_type = str(case_type) if case_type else ""
            case_no = str(case_no) if case_no else ""
            case_year = str(case_year) if case_year else ""

            # Format date
            date_str = entry.get("date", "")
            try:
                date_obj = datetime.strptime(date_str, "%Y-%m-%d")
                formatted_date = date_obj.strftime("%d-%m-%Y")
            except ValueError:
                formatted_date = str(date_str) if date_str else ""

            # Get other fields and ensure they're not None
            results = (
                str(entry.get("results", ""))
                if entry.get("results") is not None
                else ""
            )
            parties_name = (
                str(entry.get("parties_name", ""))
                if entry.get("parties_name") is not None
                else ""
            )
            fees_rs = entry.get("fees_rs", 0)

            # Ensure fees is a number
            try:
                fees_rs = float(fees_rs) if fees_rs is not None else 0.0
            except (ValueError, TypeError):
                fees_rs = 0.0

            row_data = [
                idx,  # SR. NO.
                formatted_date,  # DATE
                case_type,  # CASE TYPE
                case_no,  # CASE NO
                case_year,  # CASE YEAR
                results,  # RESULTS
                parties_name,  # PARTIES NAME
                fees_rs,  # FEES (RS.)
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
        ws.merge_cells(f"A{current_row}:G{current_row}")
        ws[f"A{current_row}"] = "TOTAL:"
        ws[f"A{current_row}"].font = header_font
        ws[f"A{current_row}"].alignment = Alignment(
            horizontal="right", vertical="center"
        )
        ws[f"A{current_row}"].border = border_thin

        cell = ws.cell(row=current_row, column=8, value=total_fees)
        cell.font = header_font
        cell.alignment = center_align
        cell.border = border_thin

        # Adjust column widths
        ws.column_dimensions["A"].width = 10  # SR. NO.
        ws.column_dimensions["B"].width = 15  # DATE
        ws.column_dimensions["C"].width = 12  # CASE TYPE
        ws.column_dimensions["D"].width = 12  # CASE NO
        ws.column_dimensions["E"].width = 12  # CASE YEAR
        ws.column_dimensions["F"].width = 18  # RESULTS
        ws.column_dimensions["G"].width = 50  # PARTIES NAME
        ws.column_dimensions["H"].width = 15  # FEES (RS.)

        # Save to BytesIO and extract raw bytes for response
        output = io.BytesIO()
        wb.save(output)

        # Return as downloadable file with proper headers
        return Response(
            content=output.getvalue(),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
            },
        )

    except Exception as e:
        logger.error(f"Error exporting bill to Excel: {e}")
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
        logger.error(f"Error getting bill details: {e}")
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
        logger.error(f"Error deleting bill: {e}")
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
        search_params: Dict[str, Any] = {}
        search_params: Dict[str, Any] = {}

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
        logger.error(f"Error in search-orders: {e}")
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
        logger.error(f"Error getting search index stats: {e}")
        return JSONResponse(
            status_code=500, content={"error": f"Failed to get search stats: {str(e)}"}
        )


@app.post("/auto-orders/rebuild-search-index", tags=["Auto Order Management"])
async def rebuild_search_index(
    limit: int = Query(100, description="Number of cases to rebuild"),
    current_user=Depends(get_current_user),
):
    """Rebuild search index for analyzed orders to pick up flattened data structure"""
    try:
        db = firestore.client()

        query = db.collection("daily-boards").limit(limit * 3)

        docs = query.stream()

        rebuilt_count = 0
        errors = []

        for doc in docs:
            try:
                case_id = doc.id
                case_data = doc.to_dict()
                case_ref = f"{case_data.get('case_type', '')}/{case_data.get('case_no', '')}/{case_data.get('case_year', '')}"
                case_details = (
                    get_auto_order_manager().case_store.get_case_details(case_ref) or {}
                )
                if case_details.get("latest_order_status") != "analysed":
                    continue
                orders = case_details.get("orders") or []
                latest_order = (
                    orders[-1] if orders and isinstance(orders[-1], dict) else {}
                )

                # Rebuild search index entry
                get_auto_order_manager()._create_search_index_entry(
                    case_id,
                    case_data,
                    {
                        "order_petitioner": case_details.get("petitioner"),
                        "order_respondent": case_details.get("respondent"),
                        "government_pleader": case_details.get(
                            "government_pleader", []
                        ),
                        "order_category": case_details.get("latest_order_category")
                        or latest_order.get("order_category"),
                        "order_category_confidence": latest_order.get(
                            "order_category_confidence"
                        ),
                        "order_date": case_details.get("latest_order_date")
                        or latest_order.get("order_date"),
                        "order_date_validation": latest_order.get(
                            "order_date_validation", {}
                        ),
                        "order_link": case_details.get("latest_order_link")
                        or latest_order.get("order_link"),
                        "order_analysis_timestamp": latest_order.get(
                            "order_analysis_timestamp"
                        ),
                    },
                )
                rebuilt_count += 1
                if rebuilt_count >= limit:
                    break

            except Exception as e:
                logger.error(f"Error rebuilding search index for {doc.id}: {e}")
                errors.append({"case_id": doc.id, "error": str(e)})

        return JSONResponse(
            content={
                "success": True,
                "rebuilt_count": rebuilt_count,
                "errors": errors,
                "message": f"Rebuilt search index for {rebuilt_count} cases",
            }
        )

    except Exception as e:
        logger.error(f"Error rebuilding search index: {e}")
        return JSONResponse(
            status_code=500,
            content={"error": f"Failed to rebuild search index: {str(e)}"},
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
    """Get structured tabular data from order-search-index."""
    try:
        db = firestore.client()
        query_ref = db.collection("order-search-index")

        # Apply filters - only filter on indexed fields
        if order_category:
            query_ref = query_ref.where("order_category", "==", order_category)
        if date_validation_valid is not None:
            query_ref = query_ref.where(
                "date_validation_valid", "==", date_validation_valid
            )

        # Execute query with limit
        docs = query_ref.limit(limit).stream()

        results = []
        for doc in docs:
            data = doc.to_dict() or {}

            # Apply text-based filters (post-query)
            if petitioner_search:
                petitioner_text = str(data.get("petitioner") or "").lower()
                if petitioner_search.lower() not in petitioner_text:
                    continue

            if respondent_search:
                respondent_text = str(data.get("respondent") or "").lower()
                if respondent_search.lower() not in respondent_text:
                    continue

            # Apply additional filters (post-query)
            if case_type and data.get("case_type") != case_type:
                continue
            if case_year and str(data.get("case_year")) != str(case_year):
                continue

            result = {
                "case_id": data.get("case_id"),
                "case_ref": data.get("case_ref"),
                "case_type": data.get("case_type"),
                "case_number": data.get("case_number"),
                "case_year": data.get("case_year"),
                "board_date": data.get("board_date"),
                "order_date": data.get("order_date"),
                "order_category": data.get("order_category"),
                "category_confidence": data.get("order_category_confidence"),
                "petitioner": data.get("petitioner", ""),
                "respondent": data.get("respondent", ""),
                "agp_names": data.get("agp_names", []),
                "key_phrases": data.get("key_phrases", []),
                "date_validation": {"valid": data.get("date_validation_valid", False)},
                "order_link": data.get("order_link"),
                "analysis_timestamp": data.get("order_analysis_timestamp"),
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
        logger.error(f"Error getting tabular data: {e}")
        return JSONResponse(
            status_code=500, content={"error": f"Failed to get tabular data: {str(e)}"}
        )


@app.get("/scraper/status", tags=["Case Orders"])
async def scraper_status(current_user: dict = Depends(require_admin_active)):
    """Return current Bombay High Court scraper configuration and provider status."""
    _ = current_user  # Explicitly keep dependency for admin-only access.
    scraper = get_court_scraper()
    return JSONResponse(content=scraper.get_scraper_config())


@app.post("/scraper/configure", tags=["Case Orders"])
async def scraper_configure(
    provider: Optional[str] = None,
    current_user: dict = Depends(require_admin_active),
):
    """Update scraper provider settings at runtime without redeploying the backend."""
    _ = current_user  # Explicitly keep dependency for admin-only access.
    scraper = get_court_scraper()
    try:
        updated = scraper.configure_scraper(
            provider=provider,
        )
        return JSONResponse(
            content={
                "message": "Scraper configuration updated",
                **updated,
            }
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/scraper/test-case", tags=["Case Orders"])
async def scraper_test_case(
    request: Request,
    current_user: dict = Depends(require_admin_active),
):
    """Run a live scrape for a case reference and return full diagnostics.

    POST body: {"case_ref": "WP/3434/2026", "date": "2026-05-30"}
    Returns the raw provider result including court_orders, case_details,
    the provider sequence that ran, and each attempt's duration and status.
    Useful for diagnosing download failures without triggering a full pipeline run.
    """
    _ = current_user
    import time as _time

    body = await request.json()
    case_ref = str(body.get("case_ref") or "").strip().upper()
    date = body.get("date")

    if not case_ref:
        return JSONResponse(status_code=400, content={"error": "case_ref is required"})

    scraper = get_court_scraper()
    started = _time.time()

    loop = asyncio.get_event_loop()
    try:
        diagnostics = await asyncio.wait_for(
            loop.run_in_executor(
                executor,
                lambda: scraper._fetch_with_provider(
                    case_ref=case_ref,
                    date=date,
                    bench="mumbai",
                    include_diagnostics=True,
                ),
            ),
            timeout=120.0,
        )
    except asyncio.TimeoutError:
        return JSONResponse(
            status_code=504,
            content={
                "error": "Scraper timed out after 120 seconds",
                "case_ref": case_ref,
            },
        )
    except Exception as exc:
        return JSONResponse(
            status_code=500,
            content={"error": str(exc), "case_ref": case_ref},
        )

    elapsed_ms = int((_time.time() - started) * 1000)
    result = diagnostics.get("result") or {}
    court_orders = result.get("court_orders") or []
    return JSONResponse(
        content={
            "case_ref": case_ref,
            "date_filter": date,
            "elapsed_ms": elapsed_ms,
            "provider": diagnostics.get("provider"),
            "provider_sequence": diagnostics.get("provider_sequence"),
            "provider_attempts": diagnostics.get("provider_attempts"),
            "found": bool(result),
            "orders_found": len(court_orders),
            "court_orders": court_orders,
            "case_details": result.get("case_details"),
            "source": result.get("source"),
        }
    )


# Cloud Run entry point - uvicorn will run the app directly
# For Cloud Functions deployment, use a separate functions_entry.py file

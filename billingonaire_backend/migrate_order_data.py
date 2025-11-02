#!/usr/bin/env python3
"""
Migration script to consolidate order data from case-orders collection into daily-boards collection.
This script moves order status information from the separate case-orders collection into the daily-boards collection.
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import firebase_admin
from firebase_admin import credentials, firestore
import logging
from datetime import datetime

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def initialize_firebase():
    """Initialize Firebase Admin SDK"""
    try:
        # Check if already initialized
        firebase_admin.get_app()
    except ValueError:
        # Initialize with service account if available
        cred_path = os.getenv('FIREBASE_SERVICE_ACCOUNT_KEY')
        if cred_path and os.path.exists(cred_path):
            cred = credentials.Certificate(cred_path)
            firebase_admin.initialize_app(cred)
        else:
            # Use default credentials (for deployed environments)
            firebase_admin.initialize_app()

def migrate_order_data():
    """Migrate order data from case-orders to daily-boards collection"""
    try:
        initialize_firebase()
        db = firestore.client()

        logger.info("Starting migration of order data from case-orders to daily-boards...")

        # Get all documents from case-orders collection
        case_orders_ref = db.collection("case-orders")
        docs = case_orders_ref.stream()

        migrated_count = 0
        skipped_count = 0
        error_count = 0

        for doc in docs:
            try:
                order_data = doc.to_dict()
                case_id = doc.id

                logger.info(f"Processing case {case_id}...")

                # Check if daily-boards document exists
                board_doc = db.collection("daily-boards").document(case_id).get()
                if not board_doc.exists:
                    logger.warning(f"Daily-boards document not found for case {case_id}, skipping...")
                    skipped_count += 1
                    continue

                # Map case-orders fields to daily-boards fields
                migration_data = {
                    "order_status": order_data.get("status", "linked"),
                    "order_notes": order_data.get("notes", ""),
                    "order_fetch_date": order_data.get("fetch_date"),
                    "order_court_bench": order_data.get("court_bench", "mumbai"),
                    "order_text": order_data.get("order_text"),
                    "order_created_at": order_data.get("created_at"),
                    "order_updated_at": order_data.get("updated_at"),
                }

                # Update the daily-boards document
                db.collection("daily-boards").document(case_id).update(migration_data)

                logger.info(f"Successfully migrated order data for case {case_id}")
                migrated_count += 1

            except Exception as e:
                logger.error(f"Error migrating case {case_id}: {e}")
                error_count += 1

        logger.info(f"Migration completed:")
        logger.info(f"  - Migrated: {migrated_count} cases")
        logger.info(f"  - Skipped: {skipped_count} cases")
        logger.info(f"  - Errors: {error_count} cases")

        return {
            "success": True,
            "migrated": migrated_count,
            "skipped": skipped_count,
            "errors": error_count
        }

    except Exception as e:
        logger.error(f"Migration failed: {e}")
        return {"success": False, "error": str(e)}

def cleanup_case_orders_collection():
    """Remove the case-orders collection after successful migration"""
    try:
        initialize_firebase()
        db = firestore.client()

        logger.info("Starting cleanup of case-orders collection...")

        # Get all documents from case-orders collection
        case_orders_ref = db.collection("case-orders")
        docs = case_orders_ref.stream()

        deleted_count = 0
        for doc in docs:
            try:
                doc.reference.delete()
                deleted_count += 1
            except Exception as e:
                logger.error(f"Error deleting document {doc.id}: {e}")

        logger.info(f"Cleanup completed: deleted {deleted_count} documents from case-orders collection")
        return {"success": True, "deleted": deleted_count}

    except Exception as e:
        logger.error(f"Cleanup failed: {e}")
        return {"success": False, "error": str(e)}

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Migrate order data from case-orders to daily-boards collection")
    parser.add_argument("--cleanup", action="store_true", help="Also cleanup the case-orders collection after migration")

    args = parser.parse_args()

    # Run migration
    result = migrate_order_data()

    if result["success"] and args.cleanup and result["migrated"] > 0:
        logger.info("Migration successful, proceeding with cleanup...")
        cleanup_result = cleanup_case_orders_collection()
        if cleanup_result["success"]:
            logger.info("Migration and cleanup completed successfully!")
        else:
            logger.error(f"Cleanup failed: {cleanup_result['error']}")
    elif result["success"]:
        logger.info("Migration completed successfully!")
        if not args.cleanup:
            logger.info("Run with --cleanup flag to also remove the case-orders collection")
    else:
        logger.error(f"Migration failed: {result['error']}")
        sys.exit(1)
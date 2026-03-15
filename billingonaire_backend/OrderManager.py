import logging
from datetime import datetime
from typing import Dict, List

from firebase_admin import firestore


class OrderManager:
    """
    Manages court orders and their linking with case data
    Tracks order states: not_present, linked, failed, manually_uploaded
    Order status information is now stored directly in daily-boards collection
    """

    def __init__(self):
        self.db = firestore.client()
        # Order status is now stored in daily-boards collection
        self.boards_collection = "daily-boards"

    def get_cases_without_orders(self, limit: int = 100, offset: int = 0) -> Dict:
        """
        Fetch cases from board data that don't have linked orders
        Only includes cases with status 'not_present' or 'failed' for reprocessing

        Args:
            limit: Number of cases to return
            offset: Pagination offset

        Returns:
            Dictionary with cases and pagination info
        """
        try:
            # Get board cases efficiently
            board_query = (
                self.db.collection(self.boards_collection)
                .limit(limit * 2)  # Get more to account for filtering
                .offset(offset)
                .stream()
            )

            cases_without_orders = []
            total_processed = 0

            for doc in board_query:
                total_processed += 1
                case_data = doc.to_dict()
                case_id = doc.id

                # Check if order is already downloaded and linked in case document
                order_downloaded = case_data.get("order_downloaded", False)

                # Get order status from daily-boards document (consolidated structure)
                order_status = case_data.get("order_status", "not_present")

                # Only include cases that need order linking (no download flag AND no linked status)
                if not order_downloaded and order_status in ["not_present", "failed"]:
                    # Format case reference for court lookup
                    case_ref = f"{case_data.get('case_type', '')}/{case_data.get('case_no', '')}/{case_data.get('case_year', '')}"

                    # Convert Firebase datetime to string for JSON serialization
                    board_date = case_data.get("board_date")
                    if hasattr(board_date, "strftime"):
                        board_date = board_date.strftime("%Y-%m-%d")
                    elif hasattr(board_date, "isoformat"):
                        board_date = board_date.isoformat()[:10]  # Get just date part

                    case_info = {
                        "id": case_id,
                        "case_ref": case_ref,
                        "board_date": board_date,
                        "case_type": case_data.get("case_type"),
                        "case_no": case_data.get("case_no"),
                        "case_year": case_data.get("case_year"),
                        "petitioner_lawyer": case_data.get("petitioner_lawyer"),
                        "respondent_lawyer": case_data.get("respondent_lawyer"),
                        "order_petitioner": case_data.get("order_petitioner", ""),
                        "order_respondent": case_data.get("order_respondent", ""),
                        "file_name": case_data.get("file_name"),
                        "order_status": order_status,
                        "order_notes": case_data.get("order_notes", ""),
                    }
                    cases_without_orders.append(case_info)

                # Stop when we have enough cases
                if len(cases_without_orders) >= limit:
                    break

            return {
                "cases": cases_without_orders,
                "total_returned": len(cases_without_orders),
                "total_processed": total_processed,
                "has_more": len(cases_without_orders) == limit,
                "offset": offset,
            }

        except Exception as e:
            logging.error(f"Error fetching cases without orders: {e}")
            return {"error": str(e), "cases": []}

    def _check_order_exists(self, case_id: str) -> bool:
        """Check if an order exists for this case in daily-boards collection"""
        try:
            board_doc = (
                self.db.collection(self.boards_collection).document(case_id).get()
            )
            if board_doc.exists:
                board_data = board_doc.to_dict()
                order_status = board_data.get("order_status", "not_present")
                return order_status != "not_present"
            return False
        except Exception as e:
            logging.debug(f"Error checking order for case {case_id}: {e}")
            return False

    def create_order_link(self, case_id: str, order_data: Dict) -> Dict:
        """
        Create or update an order link for a case
        Order information is now stored directly in daily-boards collection

        Args:
            case_id: The board case document ID
            order_data: Order information including status, link, etc.

        Returns:
            Result of the operation
        """
        try:
            # Prepare order data for daily-boards collection
            order_update = {
                "order_status": order_data.get(
                    "status", "linked"
                ),  # linked, failed, manually_uploaded
                "order_link": order_data.get("order_link"),
                "order_text": order_data.get("order_text"),
                "order_fetch_date": datetime.now().isoformat(),
                "order_court_bench": order_data.get("court_bench", "mumbai"),
                "order_notes": order_data.get("notes", ""),
                "order_created_at": datetime.now().isoformat(),
                "order_updated_at": datetime.now().isoformat(),
            }

            # Update the daily-boards document directly
            self.db.collection(self.boards_collection).document(case_id).update(
                order_update
            )

            return {
                "success": True,
                "case_id": case_id,
                "status": order_update["order_status"],
            }

        except Exception as e:
            logging.error(f"Error creating order link for case {case_id}: {e}")
            return {"error": str(e), "case_id": case_id}

    def update_order_status(self, case_id: str, status: str, notes: str = "") -> Dict:
        """
        Update the status of an order
        Order status is now stored in daily-boards collection

        Args:
            case_id: The board case document ID
            status: New status (linked, failed, manually_uploaded, not_present)
            notes: Optional notes

        Returns:
            Result of the operation
        """
        try:
            update_data = {
                "order_status": status,
                "order_notes": notes,
                "order_updated_at": datetime.now().isoformat(),
            }

            self.db.collection(self.boards_collection).document(case_id).update(
                update_data
            )

            return {"success": True, "case_id": case_id, "new_status": status}

        except Exception as e:
            logging.error(f"Error updating order status for case {case_id}: {e}")
            return {"error": str(e), "case_id": case_id}

    def get_order_details(self, case_id: str) -> Dict:
        """Get order details for a specific case from daily-boards collection"""
        try:
            # Get order details from daily-boards document
            board_doc = (
                self.db.collection(self.boards_collection).document(case_id).get()
            )

            if board_doc.exists:
                board_data = board_doc.to_dict()

                # Extract order-related fields and map to expected format
                order_details = {
                    "case_id": case_id,
                    "status": board_data.get("order_status", "not_present"),
                    "order_link": board_data.get("order_link"),
                    "order_text": board_data.get("order_text"),
                    "fetch_date": board_data.get("order_fetch_date"),
                    "court_bench": board_data.get("order_court_bench", "mumbai"),
                    "notes": board_data.get("order_notes", ""),
                    "created_at": board_data.get("order_created_at"),
                    "updated_at": board_data.get("order_updated_at"),
                }
                return order_details
            else:
                return {"status": "not_present", "case_id": case_id}

        except Exception as e:
            logging.error(f"Error fetching order details for case {case_id}: {e}")
            return {"error": str(e), "case_id": case_id}

    def get_orders_by_status(self, status: str, limit: int = 100) -> List[Dict]:
        """Get all orders with a specific status from daily-boards collection"""
        try:
            query = (
                self.db.collection(self.boards_collection)
                .where("order_status", "==", status)
                .limit(limit)
                .stream()
            )

            orders = []
            for doc in query:
                board_data = doc.to_dict()

                # Extract order-related fields and format like the old case-orders structure
                order_data = {
                    "id": doc.id,
                    "case_id": doc.id,
                    "status": board_data.get("order_status", "not_present"),
                    "order_link": board_data.get("order_link"),
                    "order_text": board_data.get("order_text"),
                    "fetch_date": board_data.get("order_fetch_date"),
                    "court_bench": board_data.get("order_court_bench", "mumbai"),
                    "notes": board_data.get("order_notes", ""),
                    "created_at": board_data.get("order_created_at"),
                    "updated_at": board_data.get("order_updated_at"),
                }
                orders.append(order_data)

            return orders

        except Exception as e:
            logging.error(f"Error fetching orders by status {status}: {e}")
            return []

    def get_case_with_order_info(self, case_id: str) -> Dict:
        """Get complete case information including order status"""
        try:
            # Get board case data
            case_doc = (
                self.db.collection(self.boards_collection).document(case_id).get()
            )
            if not case_doc.exists:
                return {"error": "Case not found", "case_id": case_id}

            case_data = case_doc.to_dict()
            case_data["id"] = case_id

            # Convert Firebase datetime to string for JSON serialization
            board_date = case_data.get("board_date")
            if hasattr(board_date, "strftime"):
                case_data["board_date"] = board_date.strftime("%Y-%m-%d")
            elif hasattr(board_date, "isoformat"):
                case_data["board_date"] = board_date.isoformat()[
                    :10
                ]  # Get just date part

            # Get order information
            order_info = self.get_order_details(case_id)
            case_data["order_info"] = order_info

            # Format case reference
            case_data["case_ref"] = (
                f"{case_data.get('case_type', '')}/{case_data.get('case_no', '')}/{case_data.get('case_year', '')}"
            )

            return case_data

        except Exception as e:
            logging.error(f"Error fetching case with order info for {case_id}: {e}")
            return {"error": str(e), "case_id": case_id}

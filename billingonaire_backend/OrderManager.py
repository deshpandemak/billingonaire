import logging
from datetime import datetime
from typing import Dict, List

from firebase_admin import firestore

try:
    from case_data_store import CaseDataStore
except ImportError:
    from .case_data_store import CaseDataStore


class OrderManager:
    """
    Manages court orders and their linking with case data
    Tracks order states: not_linked, linked, analysed, order_failed,
    order_analysis_failed, manually_uploaded
    Order status information is now stored directly in daily-boards collection
    """

    def __init__(self):
        self.db = firestore.client()
        self.boards_collection = "daily-boards"
        self.case_store = CaseDataStore(self.db)

    def _case_ref_from_board(self, case_data: Dict) -> str:
        return self.case_store.build_case_ref(
            case_data.get("case_type"),
            case_data.get("case_no"),
            case_data.get("case_year"),
        )

    def _latest_order_from_case(self, case_ref: str) -> Dict:
        case_detail = self.case_store.get_case_details(case_ref) or {}
        orders = case_detail.get("orders") or []
        latest_order = orders[-1] if orders and isinstance(orders[-1], dict) else {}
        return {
            "case_detail": case_detail,
            "latest_order": latest_order,
            "status": case_detail.get("latest_order_status")
            or latest_order.get("order_status")
            or "not_linked",
            "order_link": case_detail.get("latest_order_link")
            or latest_order.get("order_link"),
        }

    def get_cases_without_orders(self, limit: int = 100, offset: int = 0) -> Dict:
        """
        Fetch cases from board data that don't have linked orders
        Only includes cases with active retry statuses for reprocessing

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
                case_ref = self._case_ref_from_board(case_data)
                latest = self._latest_order_from_case(case_ref)

                # Only include cases that need order linking/retry.
                order_status = latest["status"]
                if order_status in [
                    "not_linked",
                    "order_failed",
                    "order_analysis_failed",
                ]:
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
                        "order_petitioner": latest["case_detail"].get("petitioner", ""),
                        "order_respondent": latest["case_detail"].get("respondent", ""),
                        "file_name": case_data.get("file_name"),
                        "order_status": order_status,
                        "order_notes": (latest["latest_order"] or {}).get(
                            "order_notes", ""
                        ),
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
            board_doc = (
                self.db.collection(self.boards_collection).document(case_id).get()
            )
            if not board_doc.exists:
                return {"error": "Case not found", "case_id": case_id}

            board_data = board_doc.to_dict() or {}
            case_ref = self._case_ref_from_board(board_data)
            status = order_data.get("status", "linked")
            self.case_store.append_case_order(
                case_ref,
                {
                    "order_status": status,
                    "order_link": order_data.get("order_link"),
                    "order_text": order_data.get("order_text"),
                    "order_fetch_date": datetime.now().isoformat(),
                    "order_court_bench": order_data.get("court_bench", "mumbai"),
                    "order_notes": order_data.get("notes", ""),
                },
            )

            return {
                "success": True,
                "case_id": case_id,
                "status": status,
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
            status: New status (linked, analysed, order_failed, order_analysis_failed, manually_uploaded, not_linked)
            notes: Optional notes

        Returns:
            Result of the operation
        """
        try:
            board_doc = (
                self.db.collection(self.boards_collection).document(case_id).get()
            )
            if not board_doc.exists:
                return {"error": "Case not found", "case_id": case_id}

            board_data = board_doc.to_dict() or {}
            case_ref = self._case_ref_from_board(board_data)
            self.case_store.append_case_order(
                case_ref,
                {
                    "order_status": status,
                    "order_notes": notes,
                    "order_updated_at": datetime.now().isoformat(),
                },
            )

            return {"success": True, "case_id": case_id, "new_status": status}

        except Exception as e:
            logging.error(f"Error updating order status for case {case_id}: {e}")
            return {"error": str(e), "case_id": case_id}

    def get_order_details(self, case_id: str) -> Dict:
        """Get order details for a specific case from case-details collection"""
        try:
            board_doc = (
                self.db.collection(self.boards_collection).document(case_id).get()
            )

            if not board_doc.exists:
                return {"status": "not_linked", "case_id": case_id}

            board_data = board_doc.to_dict() or {}
            case_ref = self._case_ref_from_board(board_data)
            latest = self._latest_order_from_case(case_ref)
            latest_order = latest["latest_order"] or {}
            return {
                "case_id": case_id,
                "status": latest["status"],
                "order_link": latest["order_link"],
                "order_text": latest_order.get("order_text"),
                "fetch_date": latest_order.get("order_fetch_date"),
                "court_bench": latest_order.get("order_court_bench", "mumbai"),
                "notes": latest_order.get("order_notes", ""),
                "created_at": latest_order.get("created_at"),
                "updated_at": latest_order.get("updated_at"),
            }

        except Exception as e:
            logging.error(f"Error fetching order details for case {case_id}: {e}")
            return {"error": str(e), "case_id": case_id}

    def get_orders_by_status(self, status: str, limit: int = 100) -> List[Dict]:
        """Get all orders with a specific status from case-details collection"""
        try:
            query = (
                self.db.collection("case-details")
                .where("latest_order_status", "==", status)
                .limit(limit)
                .stream()
            )

            orders = []
            for doc in query:
                case_data = doc.to_dict() or {}
                latest_order = {}
                case_orders = case_data.get("orders") or []
                if case_orders and isinstance(case_orders[-1], dict):
                    latest_order = case_orders[-1]

                order_data = {
                    "id": doc.id,
                    "case_id": doc.id,
                    "case_ref": case_data.get("case_ref"),
                    "status": case_data.get("latest_order_status", "not_linked"),
                    "order_link": case_data.get("latest_order_link")
                    or latest_order.get("order_link"),
                    "order_text": latest_order.get("order_text"),
                    "fetch_date": latest_order.get("order_fetch_date"),
                    "court_bench": latest_order.get("order_court_bench", "mumbai"),
                    "notes": latest_order.get("order_notes", ""),
                    "created_at": latest_order.get("created_at"),
                    "updated_at": latest_order.get("updated_at"),
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
            case_ref = self._case_ref_from_board(case_data)
            case_data["case_ref"] = case_ref

            # Convert Firebase datetime to string for JSON serialization
            board_date = case_data.get("board_date")
            if hasattr(board_date, "strftime"):
                case_data["board_date"] = board_date.strftime("%Y-%m-%d")
            elif hasattr(board_date, "isoformat"):
                case_data["board_date"] = board_date.isoformat()[
                    :10
                ]  # Get just date part

            latest = self._latest_order_from_case(case_ref)
            latest_order = latest["latest_order"] or {}
            case_data["order_info"] = {
                "case_id": case_id,
                "status": latest["status"],
                "order_link": latest["order_link"],
                "order_text": latest_order.get("order_text"),
                "fetch_date": latest_order.get("order_fetch_date"),
                "court_bench": latest_order.get("order_court_bench", "mumbai"),
                "notes": latest_order.get("order_notes", ""),
                "created_at": latest_order.get("created_at"),
                "updated_at": latest_order.get("updated_at"),
            }

            return case_data

        except Exception as e:
            logging.error(f"Error fetching case with order info for {case_id}: {e}")
            return {"error": str(e), "case_id": case_id}

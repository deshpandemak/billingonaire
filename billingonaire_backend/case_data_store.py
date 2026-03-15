import logging
from datetime import datetime
from typing import Dict, List, Optional

from firebase_admin import firestore


class CaseDataStore:
    """Maintains a normalized case master and board assignment documents."""

    def __init__(self, db: firestore.Client):
        self.db = db
        self.case_collection = "case-details"
        self.assignment_collection = "board-assignments"

    @staticmethod
    def build_case_ref(case_type: str, case_no, case_year) -> str:
        return f"{str(case_type or '').strip().upper()}/{str(case_no or '').strip()}/{str(case_year or '').strip()}"

    @staticmethod
    def _case_doc_id(case_ref: str) -> str:
        return (case_ref or "").replace("/", "-")

    @staticmethod
    def _to_iso_date(value) -> Optional[str]:
        if value is None:
            return None
        if hasattr(value, "strftime"):
            return value.strftime("%Y-%m-%d")
        raw = str(value).strip()
        if not raw:
            return None
        if "T" in raw:
            return raw.split("T")[0]
        return raw

    @staticmethod
    def _unique_names(values: List[str]) -> List[str]:
        seen = set()
        merged = []
        for name in values:
            cleaned = str(name or "").strip()
            if not cleaned:
                continue
            key = cleaned.lower()
            if key in seen:
                continue
            seen.add(key)
            merged.append(cleaned)
        return merged

    def _collect_assigned_pleaders(self, row: Dict) -> List[str]:
        names = []
        primary = row.get("respondent_lawyer")
        if primary:
            names.append(primary)
        additional = row.get("additional_respondent_lawyers") or []
        if isinstance(additional, list):
            names.extend(additional)
        return self._unique_names(names)

    def upsert_from_board_entry(self, board_doc_id: str, row: Dict) -> str:
        """Persist board assignment and seed/update normalized case details."""
        case_ref = row.get("case_ref") or self.build_case_ref(
            row.get("case_type"), row.get("case_no"), row.get("case_year")
        )
        board_date = self._to_iso_date(row.get("board_date"))
        assigned_pleaders = self._collect_assigned_pleaders(row)
        now = datetime.now().isoformat()

        assignment_doc = {
            "board_doc_id": board_doc_id,
            "case_ref": case_ref,
            "board_date": board_date,
            "file_name": row.get("file_name"),
            "serial_number": row.get("serial_number"),
            "assigned_government_pleaders": assigned_pleaders,
            "petitioner_lawyer": row.get("petitioner_lawyer"),
            "respondent_lawyer": row.get("respondent_lawyer"),
            "updated_at": now,
        }
        self.db.collection(self.assignment_collection).document(board_doc_id).set(
            assignment_doc, merge=True
        )

        case_doc_ref = self.db.collection(self.case_collection).document(
            self._case_doc_id(case_ref)
        )
        snapshot = case_doc_ref.get()
        existing = snapshot.to_dict() if snapshot.exists else {}

        merged_pleaders = self._unique_names(
            (existing.get("assigned_government_pleaders") or []) + assigned_pleaders
        )
        board_ids = list(existing.get("board_assignment_ids") or [])
        if board_doc_id not in board_ids:
            board_ids.append(board_doc_id)

        case_doc = {
            "case_ref": case_ref,
            "case_type": str(row.get("case_type") or "").strip().upper(),
            "case_no": row.get("case_no"),
            "case_year": row.get("case_year"),
            "petitioner": existing.get("petitioner")
            or row.get("order_petitioner")
            or "",
            "respondent": existing.get("respondent")
            or row.get("order_respondent")
            or "",
            "government_pleader": existing.get("government_pleader")
            or row.get("government_pleader")
            or [],
            "assigned_government_pleaders": merged_pleaders,
            "latest_board_date": board_date,
            "board_assignment_ids": board_ids,
            "orders": existing.get("orders") or [],
            "updated_at": now,
        }

        if not snapshot.exists:
            case_doc["created_at"] = now
        else:
            case_doc["created_at"] = existing.get("created_at") or now

        case_doc_ref.set(case_doc, merge=True)
        return case_ref

    def append_case_order(self, case_ref: str, order_payload: Dict) -> None:
        """Append or update an order event under case-details.orders."""
        if not case_ref:
            return

        case_doc_ref = self.db.collection(self.case_collection).document(
            self._case_doc_id(case_ref)
        )
        snapshot = case_doc_ref.get()
        existing = snapshot.to_dict() if snapshot.exists else {}

        orders = list(existing.get("orders") or [])
        order_link = (order_payload.get("order_link") or "").strip()
        order_date = self._to_iso_date(order_payload.get("order_date"))
        board_date = self._to_iso_date(order_payload.get("board_date"))

        def _match(entry: Dict) -> bool:
            if order_link and entry.get("order_link") == order_link:
                return True
            if order_date and entry.get("order_date") == order_date:
                return True
            return False

        replaced = False
        for idx, item in enumerate(orders):
            if not isinstance(item, dict):
                continue
            if _match(item):
                merged = dict(item)
                merged.update(order_payload)
                merged["order_date"] = order_date or item.get("order_date")
                merged["board_date"] = board_date or item.get("board_date")
                merged["updated_at"] = datetime.now().isoformat()
                orders[idx] = merged
                replaced = True
                break

        if not replaced:
            new_event = dict(order_payload)
            new_event["order_date"] = order_date
            new_event["board_date"] = board_date
            new_event["created_at"] = datetime.now().isoformat()
            new_event["updated_at"] = new_event["created_at"]
            orders.append(new_event)

        if len(orders) > 100:
            orders = orders[-100:]

        latest = orders[-1] if orders else {}
        petitioner_value = (
            order_payload.get("order_petitioner")
            or order_payload.get("petitioner")
            or existing.get("petitioner")
            or ""
        )
        respondent_value = (
            order_payload.get("order_respondent")
            or order_payload.get("respondent")
            or existing.get("respondent")
            or ""
        )
        update_data = {
            "case_ref": case_ref,
            "orders": orders,
            "latest_order_link": latest.get("order_link"),
            "latest_order_date": latest.get("order_date"),
            "latest_order_status": latest.get("order_status"),
            "latest_order_category": latest.get("order_category"),
            "petitioner": petitioner_value,
            "respondent": respondent_value,
            "government_pleader": order_payload.get("government_pleader")
            or existing.get("government_pleader")
            or [],
            "updated_at": datetime.now().isoformat(),
        }
        if not snapshot.exists:
            update_data["created_at"] = update_data["updated_at"]

        case_doc_ref.set(update_data, merge=True)

    def get_case_details_map(self, case_refs: List[str]) -> Dict[str, Dict]:
        refs = [ref for ref in case_refs if ref]
        if not refs:
            return {}

        result: Dict[str, Dict] = {}
        for i in range(0, len(refs), 10):
            chunk = refs[i : i + 10]
            docs = (
                self.db.collection(self.case_collection)
                .where("case_ref", "in", chunk)
                .stream()
            )
            for doc in docs:
                data = doc.to_dict() or {}
                case_ref = data.get("case_ref")
                if case_ref:
                    result[case_ref] = data
        return result

    def get_case_details(self, case_ref: str) -> Optional[Dict]:
        if not case_ref:
            return None
        doc = (
            self.db.collection(self.case_collection)
            .document(self._case_doc_id(case_ref))
            .get()
        )
        if not doc.exists:
            return None
        return doc.to_dict()

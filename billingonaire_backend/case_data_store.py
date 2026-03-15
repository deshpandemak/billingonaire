import logging
from datetime import datetime
from typing import Dict, List, Optional

from firebase_admin import firestore


class CaseDataStore:
    """Maintains a normalized case master and board assignment documents."""

    DEFAULT_LIFECYCLE_STATUS = "board_ingested"
    MAX_LIFECYCLE_EVENTS = 200
    LEGACY_STATUS_MAP = {
        "not_linked": "fetch_queued",
        "linked": "fetch_succeeded",
        "order_failed": "fetch_failed_retryable",
        "order_analysis_failed": "analysis_failed_retryable",
        "analysed": "analysed",
        "manually_uploaded": "fetch_succeeded",
    }
    ALLOWED_LIFECYCLE_TRANSITIONS = {
        "board_ingested": {
            "board_ingested",
            "fetch_not_due",
            "fetch_queued",
            "fetch_in_progress",
        },
        "fetch_not_due": {"fetch_not_due", "fetch_queued", "fetch_in_progress"},
        "fetch_queued": {
            "fetch_queued",
            "fetch_in_progress",
            "fetch_failed_retryable",
            "fetch_failed_terminal",
            "fetch_succeeded",
        },
        "fetch_in_progress": {
            "fetch_in_progress",
            "fetch_succeeded",
            "fetch_failed_retryable",
            "fetch_failed_terminal",
        },
        "fetch_succeeded": {
            "fetch_succeeded",
            "analysis_queued",
            "analysis_in_progress",
            "analysed",
            "analysis_failed_retryable",
            "analysis_failed_terminal",
            "manual_review_required",
        },
        "fetch_failed_retryable": {
            "fetch_failed_retryable",
            "fetch_queued",
            "fetch_in_progress",
            "fetch_failed_terminal",
            "manual_review_required",
        },
        "fetch_failed_terminal": {
            "fetch_failed_terminal",
            "manual_review_required",
            "fetch_queued",
        },
        "analysis_queued": {
            "analysis_queued",
            "analysis_in_progress",
            "analysis_failed_retryable",
            "analysis_failed_terminal",
            "manual_review_required",
            "analysed",
        },
        "analysis_in_progress": {
            "analysis_in_progress",
            "analysed",
            "analysis_failed_retryable",
            "analysis_failed_terminal",
            "manual_review_required",
        },
        "analysed": {
            "analysed",
            "analysis_queued",
            "analysis_in_progress",
            "manual_review_required",
        },
        "analysis_failed_retryable": {
            "analysis_failed_retryable",
            "analysis_queued",
            "analysis_in_progress",
            "analysis_failed_terminal",
            "manual_review_required",
        },
        "analysis_failed_terminal": {
            "analysis_failed_terminal",
            "manual_review_required",
            "analysis_queued",
        },
        "manual_review_required": {
            "manual_review_required",
            "analysis_queued",
            "analysis_in_progress",
            "analysed",
            "fetch_queued",
        },
    }

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

    @classmethod
    def map_legacy_order_status(cls, order_status: Optional[str]) -> Optional[str]:
        if not order_status:
            return None
        return cls.LEGACY_STATUS_MAP.get(str(order_status).strip().lower())

    def _current_lifecycle_status(self, case_detail: Dict) -> str:
        explicit = case_detail.get("lifecycle_status")
        if explicit:
            return explicit
        mapped = self.map_legacy_order_status(case_detail.get("latest_order_status"))
        return mapped or self.DEFAULT_LIFECYCLE_STATUS

    def _append_lifecycle_event(
        self,
        existing_events: List[Dict],
        status: str,
        event_type: str,
        reason: Optional[str],
        metadata: Optional[Dict],
    ) -> List[Dict]:
        event = {
            "status": status,
            "event_type": event_type,
            "timestamp": datetime.now().isoformat(),
        }
        if reason:
            event["reason"] = reason
        if metadata:
            event["metadata"] = metadata

        events = list(existing_events or [])
        events.append(event)
        if len(events) > self.MAX_LIFECYCLE_EVENTS:
            events = events[-self.MAX_LIFECYCLE_EVENTS :]
        return events

    def transition_lifecycle(
        self,
        case_ref: str,
        to_status: str,
        reason: Optional[str] = None,
        metadata: Optional[Dict] = None,
        force: bool = False,
        event_type: str = "status_transition",
    ) -> Dict:
        if not case_ref or not to_status:
            return {"applied": False, "reason": "missing_case_or_status"}

        case_doc_ref = self.db.collection(self.case_collection).document(
            self._case_doc_id(case_ref)
        )
        snapshot = case_doc_ref.get()
        existing = snapshot.to_dict() if snapshot.exists else {}

        from_status = self._current_lifecycle_status(existing)
        allowed_targets = self.ALLOWED_LIFECYCLE_TRANSITIONS.get(from_status, set())
        can_transition = (
            force or to_status == from_status or to_status in allowed_targets
        )
        if not can_transition:
            logging.warning(
                "Rejected lifecycle transition for %s: %s -> %s",
                case_ref,
                from_status,
                to_status,
            )
            return {
                "applied": False,
                "reason": "invalid_transition",
                "from_status": from_status,
                "to_status": to_status,
            }

        lifecycle_events = self._append_lifecycle_event(
            existing.get("lifecycle_events") or [],
            to_status,
            event_type,
            reason,
            metadata,
        )
        now = datetime.now().isoformat()
        update_data = {
            "case_ref": case_ref,
            "lifecycle_status": to_status,
            "lifecycle_status_updated_at": now,
            "lifecycle_events": lifecycle_events,
            "updated_at": now,
        }
        if reason:
            update_data["lifecycle_status_reason"] = reason
        if not snapshot.exists:
            update_data["created_at"] = now

        case_doc_ref.set(update_data, merge=True)
        return {
            "applied": True,
            "from_status": from_status,
            "to_status": to_status,
        }

    def get_case_timeline(self, case_ref: str, limit: int = 50) -> List[Dict]:
        case_detail = self.get_case_details(case_ref) or {}
        events = list(case_detail.get("lifecycle_events") or [])
        if limit and limit > 0:
            events = events[-limit:]
        return events

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
            "lifecycle_status": self._current_lifecycle_status(existing),
            "updated_at": now,
        }

        case_doc["lifecycle_events"] = existing.get("lifecycle_events") or []
        if not case_doc["lifecycle_events"]:
            case_doc["lifecycle_events"] = self._append_lifecycle_event(
                [],
                case_doc["lifecycle_status"],
                "board_assignment_upserted",
                None,
                {"board_doc_id": board_doc_id, "board_date": board_date},
            )
        else:
            case_doc["lifecycle_events"] = self._append_lifecycle_event(
                case_doc["lifecycle_events"],
                case_doc["lifecycle_status"],
                "board_assignment_upserted",
                None,
                {"board_doc_id": board_doc_id, "board_date": board_date},
            )
        case_doc["lifecycle_status_updated_at"] = (
            existing.get("lifecycle_status_updated_at") or now
        )

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

    def build_lifecycle_summary(self, case_ref: str) -> Dict:
        details = self.get_case_details(case_ref) or {}
        orders = details.get("orders") or []
        latest_order = orders[-1] if orders and isinstance(orders[-1], dict) else {}
        return {
            "case_ref": case_ref,
            "lifecycle_status": self._current_lifecycle_status(details),
            "lifecycle_status_updated_at": details.get("lifecycle_status_updated_at"),
            "latest_order_status": details.get("latest_order_status")
            or latest_order.get("order_status")
            or "not_linked",
            "latest_order_link": details.get("latest_order_link")
            or latest_order.get("order_link"),
            "latest_order_date": details.get("latest_order_date")
            or latest_order.get("order_date"),
            "latest_order_category": details.get("latest_order_category")
            or latest_order.get("order_category"),
            "latest_board_date": details.get("latest_board_date"),
            "event_count": len(details.get("lifecycle_events") or []),
        }

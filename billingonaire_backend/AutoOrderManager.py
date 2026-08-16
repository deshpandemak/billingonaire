import logging
import os
from datetime import date, datetime
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Set
from urllib.parse import urlparse

import requests
from firebase_admin import firestore

try:
    from google.cloud import storage as gcs_storage  # type: ignore[import-untyped]
except ImportError:  # pragma: no cover
    gcs_storage = None  # type: ignore[assignment]

from CourtScraper import BombayHighCourtScraper

try:
    from case_data_store import CaseDataStore
except ImportError:
    from .case_data_store import CaseDataStore

from court_http import court_get
from order_analyzer import OrderDocumentAnalyzer

logger = logging.getLogger(__name__)


def _redact_url(url: Optional[str]) -> str:
    """Return only the scheme+host+path of a URL, stripping query params that may contain auth tokens."""
    if not url:
        return "<none>"
    try:
        parsed = urlparse(str(url))
        return f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
    except Exception:
        return "<redacted>"


class AutoOrderManager:
    """
    Automated Court Order Download and Analysis Manager
    Handles automatic fetching, linking, and analysis of court orders
    """

    # Classifications below this confidence go to manual_review_required rather
    # than analysed, so a person confirms them before they can reach a bill.
    # Per docs/CURRENT_WORKFLOW.md section 7.3.  For scale: the classifier
    # returns 0.50 when no patterns matched at all and it fell back to
    # ADJOURNED, and 0.95 when a hard gate fired.
    REVIEW_CONFIDENCE_THRESHOLD = float(
        os.getenv("ORDER_REVIEW_CONFIDENCE_THRESHOLD", "0.55")
    )

    def __init__(self):
        self.db = firestore.client()
        self.order_analyzer = OrderDocumentAnalyzer()
        self.court_scraper = BombayHighCourtScraper()
        self.case_store = CaseDataStore(self.db)

        # Collections - consolidated order status into daily-boards
        self.boards_collection = "daily-boards"

        # GCS bucket for permanent PDF storage (empty string → GCS upload disabled)
        self._gcs_bucket_name: str = os.getenv("ORDER_PDF_BUCKET", "")
        if self._gcs_bucket_name:
            logger.info(
                "AutoOrderManager: GCS PDF storage configured — bucket=%s",
                self._gcs_bucket_name,
            )
        else:
            logger.warning(
                "AutoOrderManager: ORDER_PDF_BUCKET env var not set — "
                "court order PDFs will NOT be uploaded to GCS. "
                "Set ORDER_PDF_BUCKET=<bucket-name> to enable permanent storage."
            )

        # AGP name patterns for extraction
        self.agp_patterns = [
            r"Pooja\s*(?:M\.)?\s*(?:J\.)?\s*(?:Joshi|Deshpande)+",
            r"P(?:ooja)?\.\s*(?:M\.)?\s*(?:J\.)?\s*(?:Joshi|Des(?:h)?pande)+",
            r"Ms\.\s*Pooja\s*(?:Joshi\s*)?Deshpande",
            r"Smt\.\s*Pooja\s*(?:Joshi\s*)?Deshpande",
        ]

    def get_orders_for_cases(
        self,
        case_filters: Optional[Dict[str, Any]] = None,
        limit: int = 50,
    ) -> Dict[str, Any]:
        """
        Main method to automatically get orders for filtered cases

        Args:
            case_filters: Optional filters for case selection
            limit: Maximum number of cases to process

        Returns:
            Dictionary with processing results
        """
        try:
            # Get filtered cases that need orders
            filtered_cases = self._get_filtered_matters(case_filters, limit)

            if not filtered_cases:
                logger.info(
                    "get_orders_for_cases: no cases found matching filters=%s",
                    case_filters,
                )
                return {
                    "success": True,
                    "message": "No cases found matching criteria",
                    "processed": 0,
                }

            logger.info(
                "get_orders_for_cases: processing %d cases (filters=%s)",
                len(filtered_cases),
                case_filters,
            )
            results: Dict[str, Any] = {
                "total_cases": len(filtered_cases),
                "successful_downloads": 0,
                "failed_downloads": 0,
                "successful_analyses": 0,
                "failed_analyses": 0,
                "errors": [],
                "processed_cases": [],
            }

            for case_data in filtered_cases:
                try:
                    case_result = self._process_single_case(case_data)
                    results["processed_cases"].append(case_result)

                    if case_result.get("download_success"):
                        results["successful_downloads"] += 1
                    else:
                        results["failed_downloads"] += 1

                    if case_result.get("analysis_success"):
                        results["successful_analyses"] += 1
                    else:
                        results["failed_analyses"] += 1

                except Exception as e:
                    error_msg = f"Error processing case {case_data.get('case_ref', 'unknown')}: {str(e)}"
                    logger.error(error_msg)
                    results["errors"].append(error_msg)
                    results["failed_downloads"] += 1

            logger.info(
                "get_orders_for_cases completed: total=%d success_dl=%d failed_dl=%d "
                "success_analysis=%d failed_analysis=%d",
                results["total_cases"],
                results["successful_downloads"],
                results["failed_downloads"],
                results["successful_analyses"],
                results["failed_analyses"],
            )
            return {"success": True, "results": results}

        except Exception as e:
            logger.error("Error in get_orders_for_cases: %s", e)
            return {"success": False, "error": str(e)}

    def bulk_process_orders(self, case_ids: List[str]) -> Dict[str, Any]:
        """
        Bulk process specific cases by their IDs.

        Args:
            case_ids: List of case document IDs to process

        Returns:
            Dictionary with processing results
        """
        try:
            if not case_ids:
                return {"success": False, "error": "No case IDs provided"}

            logger.info(
                "bulk_process_orders starting: case_count=%d",
                len(case_ids),
            )
            results: Dict[str, Any] = {
                "total_cases": len(case_ids),
                "successful": 0,
                "failed": 0,
                "processed_cases": [],
                "errors": [],
            }

            for case_id in case_ids:
                try:
                    # Get case data from Firestore
                    doc_ref = self.db.collection(self.boards_collection).document(
                        case_id
                    )
                    doc = doc_ref.get()

                    if not doc.exists:
                        logger.warning(
                            "bulk_process_orders: case_id=%s not found", case_id
                        )
                        results["errors"].append(f"Case {case_id} not found")
                        results["failed"] += 1
                        continue

                    case_data = doc.to_dict()
                    case_data["id"] = case_id

                    # Format case reference
                    case_ref = f"{case_data.get('case_type', '')}/{case_data.get('case_no', '')}/{case_data.get('case_year', '')}"
                    case_data["case_ref"] = case_ref

                    # Process the case
                    case_result = self._process_single_case(case_data)
                    results["processed_cases"].append(case_result)

                    if case_result.get("download_success"):
                        results["successful"] += 1
                    else:
                        results["failed"] += 1

                except Exception as e:
                    error_msg = f"Error processing case {case_id}: {str(e)}"
                    logger.error(error_msg)
                    results["errors"].append(error_msg)
                    results["failed"] += 1

            logger.info(
                "bulk_process_orders completed: total=%d successful=%d failed=%d",
                results["total_cases"],
                results["successful"],
                results["failed"],
            )
            results["success"] = True
            return results

        except Exception as e:
            logger.error("Error in bulk_process_orders: %s", e)
            return {"success": False, "error": str(e)}

    @staticmethod
    def _to_board_date_query_value(value: Any) -> Optional[datetime]:
        """Coerce a YYYY-MM-DD string (or date/datetime) to the datetime form
        used for ``board_date`` in Firestore.

        ``Board.saveData`` writes ``board_date`` as a midnight ``datetime``, so
        comparing it against a raw ``"YYYY-MM-DD"`` string in a Firestore query
        matches nothing (Firestore orders timestamps before strings).  Every
        board_date query value must go through this helper.
        """
        if value is None:
            return None
        if isinstance(value, datetime):
            return value
        if isinstance(value, date):
            return datetime(value.year, value.month, value.day)
        raw = str(value).strip()
        if not raw:
            return None
        parsed = AutoOrderManager._parse_board_date(raw)
        if not parsed:
            return None
        return datetime(parsed.year, parsed.month, parsed.day)

    #: order_status values selected by each ``scope`` in _get_filtered_matters.
    #: ``None`` means "no order_status filtering at all" (every case matched
    #: by the board-level filters, including already-analysed ones).
    SCOPE_ORDER_STATUSES = {
        "missing_only": {"not_linked"},
        "actionable": {"not_linked", "linked", "order_failed", "order_analysis_failed"},
        "all": None,
    }

    def _get_filtered_matters(
        self,
        filters: Optional[Dict[str, Any]] = None,
        limit: int = 50,
        board_dates: Optional[List[str]] = None,
        scope: str = "actionable",
        order_statuses: Optional[Set[str]] = None,
    ) -> List[Dict[str, Any]]:
        """Get cases that need order processing based on filters.

        ``board_dates`` (a list of YYYY-MM-DD strings) is pushed down into the
        Firestore query as one equality query per date.  This matters: callers
        used to fetch ``limit`` arbitrary documents and *then* drop everything
        outside the selected dates, which returned zero rows whenever the
        selected dates were not in that arbitrary first page.

        ``scope`` narrows by order_status: "missing_only" (no order downloaded
        yet), "actionable" (the historical default -- not_linked, linked,
        or previously failed; excludes analysed cases), or "all" (every case
        matched by the board-level filters, for a deliberate full re-fetch
        regardless of current status).

        ``order_statuses``, when given, is an explicit allowlist of
        order_status values and takes priority over ``scope`` -- lets a
        caller offer a free multi-select (e.g. admin bulk processing's
        status checkboxes) without inventing a new named scope for every
        combination. ``None`` means "no override, defer to scope".
        """
        logger.info(
            "_get_filtered_matters called with filters=%s limit=%d board_dates=%s scope=%s",
            filters,
            limit,
            board_dates,
            scope,
        )
        if order_statuses is not None:
            allowed_statuses = set(order_statuses)
        else:
            allowed_statuses = self.SCOPE_ORDER_STATUSES.get(
                scope, self.SCOPE_ORDER_STATUSES["actionable"]
            )
        # Deliberately no try/except around the query below: a Firestore
        # error (e.g. a missing composite index) used to be swallowed here
        # and turned into an empty list, which every caller then reported as
        # a confident "no cases found" / "already up to date" -- an honest-
        # looking lie. Every caller already has its own outer exception
        # handler that turns a propagated exception into a real error
        # response, so letting it propagate is strictly better: the user
        # sees what actually went wrong instead of a false all-clear.
        base = self.db.collection(self.boards_collection)

        def _apply_filters(query):
            if not filters:
                return query
            if filters.get("case_type"):
                query = query.where("case_type", "==", filters["case_type"])
            if filters.get("case_year"):
                query = query.where("case_year", "==", filters["case_year"])
            # board_date is stored as a datetime — coerce string inputs so
            # the range comparison actually matches documents.
            date_from = self._to_board_date_query_value(filters.get("date_from"))
            if date_from:
                query = query.where("board_date", ">=", date_from)
            date_to = self._to_board_date_query_value(filters.get("date_to"))
            if date_to:
                query = query.where("board_date", "<=", date_to)
            return query

        # Build the query set.  One equality query per selected board date so
        # the date filter is applied by Firestore rather than after the limit.
        queries = []
        normalized_dates = [
            self._to_board_date_query_value(value)
            for value in (board_dates or [])
            if str(value or "").strip()
        ]
        normalized_dates = [d for d in normalized_dates if d is not None]

        if normalized_dates:
            for board_dt in normalized_dates:
                queries.append(
                    _apply_filters(base.where("board_date", "==", board_dt)).limit(
                        limit * 2
                    )
                )
        else:
            queries.append(_apply_filters(base).limit(limit * 2))

        cases: List[Dict[str, Any]] = []
        seen_ids = set()

        for query in queries:
            if len(cases) >= limit:
                break
            for doc in query.stream():
                if doc.id in seen_ids:
                    continue
                seen_ids.add(doc.id)

                case_data = doc.to_dict()
                case_data["id"] = doc.id
                case_ref = f"{case_data.get('case_type', '')}/{case_data.get('case_no', '')}/{case_data.get('case_year', '')}"
                case_data["case_ref"] = case_ref

                order_context = self._get_case_order_context(case_ref)
                order_status = order_context["order_status"]
                case_data["order_status"] = order_status
                case_data["order_link"] = order_context.get("order_link")

                if allowed_statuses is None or order_status in allowed_statuses:
                    cases.append(case_data)

                    if len(cases) >= limit:
                        break

        logger.info("_get_filtered_matters returned %d actionable cases", len(cases))
        return cases

    def _get_case_order_context(
        self, case_ref: str, order_date: Optional[str] = None
    ) -> Dict[str, Any]:
        """*order_date*, when given, targets that specific hearing date's
        order entry instead of the last one appended. Needed once a case
        can have several hearing dates pending review at once (see
        add_pending_review_date) -- "Get AI read" for an older flagged date
        must not silently analyse a newer, unrelated order instead."""
        case_detail = self.case_store.get_case_details(case_ref) or {}
        orders = case_detail.get("orders") or []
        normalized_date = (
            self.case_store._to_iso_date(order_date) if order_date else None
        )
        matched_order: Dict[str, Any] = {}
        if normalized_date:
            for o in reversed(orders):
                if not isinstance(o, dict):
                    continue
                if normalized_date in (
                    self.case_store._to_iso_date(o.get("order_date")),
                    self.case_store._to_iso_date(o.get("board_date")),
                ):
                    matched_order = o
                    break
        if matched_order:
            latest_order = matched_order
        else:
            # No date given, or none matched it — fall back to the last
            # entry that actually has an order_link. Blank status-only
            # entries (order_failed, not_linked markers) have no order_link
            # and must not shadow a previously stored valid link.
            orders_with_link = [
                o for o in orders if isinstance(o, dict) and o.get("order_link")
            ]
            latest_order = (
                orders_with_link[-1]
                if orders_with_link
                else (orders[-1] if orders and isinstance(orders[-1], dict) else {})
            )
        return {
            "case_detail": case_detail,
            "latest_order": latest_order,
            "order_status": (
                latest_order.get("order_status")
                or case_detail.get("latest_order_status")
                or "not_linked"
                if matched_order
                else case_detail.get("latest_order_status")
                or latest_order.get("order_status")
                or "not_linked"
            ),
            "order_link": (
                latest_order.get("order_link") or case_detail.get("latest_order_link")
                if matched_order
                else case_detail.get("latest_order_link")
                or latest_order.get("order_link")
            ),
            # Only present for orders analysed after order text persistence
            # shipped (see _upload_order_text_to_gcs) -- callers must handle
            # None by falling back to re-downloading/re-parsing order_link.
            "order_text_url": latest_order.get("order_text_url"),
        }

    @staticmethod
    def build_case_ref_from_data(case_data: Dict[str, Any]) -> str:
        """Reconstruct a case_ref string from case_type/case_no/case_year fields."""
        ct = str(case_data.get("case_type") or "").strip().upper()
        cn = str(case_data.get("case_no") or "").strip()
        cy = str(case_data.get("case_year") or "").strip()
        return f"{ct}/{cn}/{cy}" if ct and cn and cy else ""

    @staticmethod
    def _parse_board_date(value: Optional[str]) -> Optional[date]:
        if value is None:
            return None
        if hasattr(value, "date"):
            try:
                return value.date()
            except Exception:
                return None
        raw = str(value).strip()
        if not raw:
            return None
        if "T" in raw:
            raw = raw.split("T", 1)[0]
        elif " " in raw:
            raw = raw.split(" ", 1)[0]
        try:
            return datetime.strptime(raw, "%Y-%m-%d").date()
        except ValueError:
            return None

    def _upload_order_to_gcs(
        self, pdf_content: bytes, case_ref: str, order_date: str
    ) -> Optional[str]:
        """Upload a PDF to Google Cloud Storage and return a permanent public HTTPS URL.

        Returns None when GCS is not configured or the upload fails.
        The blob is stored at:
            court-orders/<case_ref_dashes>/<order_date>.pdf
        e.g. court-orders/WP-294-2025/2025-03-01.pdf

        The returned URL is in the form
        ``https://storage.googleapis.com/<bucket>/<blob_name>`` so that it can
        be used as an ``<a href>`` target and with ``requests.get`` — unlike a
        ``gs://`` URI which neither browsers nor the ``requests`` library can
        fetch.  The bucket must have the uploaded objects readable (public or
        via an IAM binding appropriate for the deployment).
        """
        if not self._gcs_bucket_name or gcs_storage is None:
            return None
        try:
            client = gcs_storage.Client()
            bucket = client.bucket(self._gcs_bucket_name)
            blob_name = f"court-orders/{case_ref.replace('/', '-')}/{order_date}.pdf"
            blob = bucket.blob(blob_name)
            blob.upload_from_string(pdf_content, content_type="application/pdf")
            # Return a public HTTPS URL; callers (UI, requests.get) cannot use gs://
            https_url = (
                f"https://storage.googleapis.com/{self._gcs_bucket_name}/{blob_name}"
            )
            logger.info(
                "_upload_order_to_gcs: uploaded %s for case_ref=%s date=%s",
                blob_name,
                case_ref,
                order_date,
            )
            return https_url
        except Exception as exc:
            logger.error(
                "_upload_order_to_gcs failed for case_ref=%s date=%s: %s — "
                "check Cloud Run service account permissions on bucket %s. "
                "Run GET /admin/test-gcs to diagnose.",
                case_ref,
                order_date,
                exc,
                self._gcs_bucket_name,
                exc_info=True,
            )
            return None

    def _upload_order_text_to_gcs(
        self, order_text: str, case_ref: str, order_date: str
    ) -> Optional[str]:
        """Upload the extracted order text alongside its PDF and return a
        permanent public HTTPS URL, or None when GCS is not configured, the
        upload fails, or there is no text to store.

        order_analyzer.analyze_order_document() produces this text on every
        analysis (OrderAnalysisResult.order_text) but nothing has ever
        persisted it -- it is discarded the moment the request returns.
        That means there are no features to train or evaluate a classifier
        change against without re-downloading and re-parsing every PDF, and
        main.calculate_case_fee's order_text-matching branches were
        permanently dead code (order_text was always the empty string).

        Stored at the same stable key _upload_order_to_gcs uses, so the two
        blobs sit side by side:
            court-orders/<case_ref_dashes>/<order_date>.pdf
            court-orders/<case_ref_dashes>/<order_date>.txt
        Text, not a Firestore field: Firestore documents cap out at 1MB and
        case-details.orders[] already holds up to 100 entries per case, so
        inlining full order text there would eventually break large cases.
        """
        if not order_text or not self._gcs_bucket_name or gcs_storage is None:
            return None
        try:
            client = gcs_storage.Client()
            bucket = client.bucket(self._gcs_bucket_name)
            blob_name = f"court-orders/{case_ref.replace('/', '-')}/{order_date}.txt"
            blob = bucket.blob(blob_name)
            blob.upload_from_string(order_text, content_type="text/plain")
            https_url = (
                f"https://storage.googleapis.com/{self._gcs_bucket_name}/{blob_name}"
            )
            logger.info(
                "_upload_order_text_to_gcs: uploaded %s for case_ref=%s date=%s",
                blob_name,
                case_ref,
                order_date,
            )
            return https_url
        except Exception as exc:
            # Never let a text-persistence failure break analysis -- the
            # category/confidence result is already computed and must still
            # be saved even if this best-effort text upload fails.
            logger.error(
                "_upload_order_text_to_gcs failed for case_ref=%s date=%s: %s",
                case_ref,
                order_date,
                exc,
                exc_info=True,
            )
            return None

    def _normalise_order_date(self, value: Optional[str]) -> Optional[str]:
        """Normalise various date string formats to a canonical ``YYYY-MM-DD`` string.

        Handles the formats commonly seen from CourtScraper/Firestore:
        ``YYYY-MM-DD``, ``DD/MM/YYYY``, ``DD-MM-YYYY``, ``YYYY/MM/DD``.
        Returns ``None`` if the value cannot be parsed as a date.
        """
        if value is None:
            return None
        raw = str(value).strip()
        if not raw:
            return None
        # Strip time component if present (e.g. "2025-04-09T12:34:56" or "2025-04-09 12:34:56")
        if "T" in raw:
            raw = raw.split("T", 1)[0]
        elif " " in raw:
            raw = raw.split(" ", 1)[0]
        for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d"):
            try:
                return datetime.strptime(raw, fmt).date().isoformat()
            except ValueError:
                continue
        return None

    def _is_order_already_analysed(self, case_ref: str, order_date: str) -> bool:
        """Return True when case-details already contains an analysed order for *order_date*.

        Both the incoming *order_date* and stored order dates are normalised to
        ``YYYY-MM-DD`` before comparison so that ``DD/MM/YYYY`` values from the
        court API match ISO-formatted dates stored in Firestore.
        """
        case_detail = self.case_store.get_case_details(case_ref) or {}
        orders = case_detail.get("orders") or []
        normalised_target = self._normalise_order_date(order_date)
        if normalised_target is None:
            logger.warning(
                "_is_order_already_analysed: cannot normalise incoming date %r "
                "for case_ref=%s; falling back to raw string comparison",
                order_date,
                case_ref,
            )
        for order in orders:
            if not isinstance(order, dict):
                continue
            if order.get("order_status") != "analysed":
                continue
            stored_date = order.get("order_date")
            normalised_stored = self._normalise_order_date(stored_date)
            if normalised_stored is None and stored_date is not None:
                logger.warning(
                    "_is_order_already_analysed: cannot normalise stored date %r "
                    "for case_ref=%s; falling back to raw string comparison",
                    stored_date,
                    case_ref,
                )
            if normalised_target is not None and normalised_stored is not None:
                if normalised_stored == normalised_target:
                    # When GCS is configured, force a re-fetch for orders that
                    # still have an expiring BHC URL so the PDF is uploaded to
                    # GCS for permanent storage.  When GCS is NOT configured
                    # (bucket name empty or library unavailable), accept the BHC
                    # URL as-is — otherwise every retry would loop indefinitely
                    # without ever upgrading the link.
                    order_link = order.get("order_link") or ""
                    gcs_configured = bool(
                        self._gcs_bucket_name and gcs_storage is not None
                    )
                    if (
                        gcs_configured
                        and order_link
                        and not order_link.startswith("https://storage.googleapis.com")
                    ):
                        return False
                    return True
            elif stored_date == order_date:
                # Fallback: raw string comparison when neither side could be parsed
                order_link = order.get("order_link") or ""
                gcs_configured = bool(self._gcs_bucket_name and gcs_storage is not None)
                if (
                    gcs_configured
                    and order_link
                    and not order_link.startswith("https://storage.googleapis.com")
                ):
                    return False
                return True
        return False

    def _get_analysed_order_for_date(
        self, case_ref: str, order_date_str: str
    ) -> Optional[Dict[str, Any]]:
        """Return the first analysed order in case-details that matches *order_date_str*.

        Both the target and stored dates are normalised to YYYY-MM-DD before
        comparison.  Returns ``None`` when no match is found.
        """
        case_detail = self.case_store.get_case_details(case_ref) or {}
        orders = case_detail.get("orders") or []
        normalized_target = self._normalise_order_date(order_date_str)
        for order in orders:
            if not isinstance(order, dict):
                continue
            if order.get("order_status") != "analysed":
                continue
            if self._normalise_order_date(order.get("order_date")) == normalized_target:
                return order
        return None

    def _update_board_entries_for_case_date(
        self,
        case_ref: str,
        order_date_str: str,
        order_link: Optional[str],
        order_category: Optional[str],
    ) -> int:
        """Update every daily-boards entry whose case_ref and board_date match.

        Queries the collection by *case_ref* equality and *board_date* equality
        (board_date is stored as a Python datetime / Firestore Timestamp), so the
        composite index on ``(board_date, case_ref)`` is used.

        Returns the number of documents updated.
        """
        if not order_link and not order_category:
            return 0
        try:
            bd_datetime = datetime.strptime(order_date_str, "%Y-%m-%d")
        except (ValueError, TypeError):
            logger.warning(
                "_update_board_entries_for_case_date: cannot parse date %r for "
                "case_ref=%s — skipping board-entry update",
                order_date_str,
                case_ref,
            )
            return 0
        try:
            update_payload: Dict[str, Any] = {}
            if order_link:
                update_payload["order_link"] = order_link
            if order_category:
                update_payload["order_category"] = order_category
            docs = (
                self.db.collection("daily-boards")
                .where("case_ref", "==", case_ref)
                .where("board_date", "==", bd_datetime)
                .stream()
            )
            updated = 0
            for doc in docs:
                try:
                    doc.reference.update(update_payload)
                    updated += 1
                except Exception as _ue:
                    logger.warning(
                        "_update_board_entries_for_case_date: failed to update "
                        "doc=%s for case_ref=%s date=%s: %s",
                        doc.id,
                        case_ref,
                        order_date_str,
                        _ue,
                    )
            if updated:
                logger.info(
                    "_update_board_entries_for_case_date: updated %d board "
                    "entries for case_ref=%s date=%s",
                    updated,
                    case_ref,
                    order_date_str,
                )
            return updated
        except Exception as exc:
            logger.warning(
                "_update_board_entries_for_case_date failed for case_ref=%s "
                "date=%s: %s",
                case_ref,
                order_date_str,
                exc,
            )
            return 0

    def _maybe_llm_assist(
        self, analysis_result, case_ref: Optional[str] = None
    ) -> Dict[str, Any]:
        """Roadmap #2: route only the ambiguous cases to an LLM, not every
        order. The regex classifier's hard gates (NO_TIME_PATTERNS,
        STRONG_DISPOSAL_PATTERNS) are already reliable and stay untouched --
        this only fires when the regex scorer landed below the same
        threshold that routes a case to manual review in the first place,
        i.e. cases a human would otherwise have to look at anyway.

        Auto-resolves (raises confidence enough to clear the review gate)
        ONLY when the LLM independently agrees with the regex category --
        two independent signals agreeing is a materially stronger bar than
        either alone. On disagreement, the regex result is left completely
        unchanged (still goes to manual review, same as before this
        existed) but the LLM's read is attached to the analysis metadata so
        the review queue can show it without a second, duplicate API call.

        No-op without GEMINI_API_KEY -- e.g. local dev, or the feature is
        turned off by removing the key -- and any call failure (timeout,
        quota, bad response) falls back to the unmodified regex result
        rather than ever breaking analysis.
        """
        category = analysis_result.order_category
        confidence = float(analysis_result.category_confidence or 0.0)
        result: Dict[str, Any] = {
            "category": category,
            "confidence": confidence,
            "llm_suggestion": None,
        }

        api_key = os.environ.get("GEMINI_API_KEY")
        order_text = (analysis_result.order_text or "").strip()
        if (
            not api_key
            or not order_text
            or confidence >= self.REVIEW_CONFIDENCE_THRESHOLD
        ):
            return result

        try:
            from review_copilot import call_gemini

            suggestion = call_gemini(order_text, api_key)
        except (
            Exception
        ) as exc:  # noqa: BLE001 - never let an LLM hiccup break analysis
            logger.warning(
                "LLM-assist call failed for a low-confidence case, falling back "
                "to the regex result unchanged: %s",
                exc,
            )
            return result

        agreed = suggestion.get("category") == category
        result["llm_suggestion"] = {
            "category": suggestion.get("category"),
            "confidence": suggestion.get("confidence"),
            "rationale": suggestion.get("rationale"),
            "agreed_with_regex": agreed,
        }
        if agreed:
            new_confidence = max(confidence, float(suggestion.get("confidence") or 0.0))
            logger.info(
                "LLM-assist: regex and LLM agree on %s for case_ref=%s "
                "(regex=%.2f, llm=%.2f) -- confidence raised to %.2f",
                category,
                case_ref or "unknown",
                confidence,
                suggestion.get("confidence") or 0.0,
                new_confidence,
            )
            result["confidence"] = new_confidence
        else:
            # Disagreement is the interesting case for tuning the regex
            # classifier or the LLM prompt -- the case still goes to manual
            # review either way (confidence is deliberately left untouched
            # here), but until this line existed there was no log signal
            # for it at all: only the "agree" branch above logged anything,
            # so a disagreement was indistinguishable from the LLM call
            # never having been attempted. The (regex, LLM, human) triple
            # this and tools/export_correction_dataset.py are meant to
            # build depends on being able to find these.
            logger.info(
                "LLM-assist: regex and LLM DISAGREE for case_ref=%s -- "
                "regex=%s (%.2f), llm=%s (%.2f): %s",
                case_ref or "unknown",
                category,
                confidence,
                suggestion.get("category"),
                suggestion.get("confidence") or 0.0,
                (suggestion.get("rationale") or "")[:200],
            )
        return result

    def _download_gcs_text(self, url: str) -> str:
        """Download a stored order-text blob (court-orders/.../<date>.txt)
        by its full https://storage.googleapis.com/... URL. Raises on any
        failure -- callers decide how to handle it."""
        if not gcs_storage:
            raise RuntimeError("google-cloud-storage is not installed")
        prefix = "https://storage.googleapis.com/"
        if not url.startswith(prefix):
            raise ValueError(f"not a GCS URL: {url}")
        bucket_name, _, blob_name = url[len(prefix) :].partition("/")
        client = gcs_storage.Client()
        return (
            client.bucket(bucket_name)
            .blob(blob_name)
            .download_as_bytes()
            .decode("utf-8")
        )

    def reclassify_pending_order(
        self, case_ref: str, order_date: str
    ) -> Dict[str, Any]:
        """Re-run classification against an order's ALREADY-STORED text,
        without re-fetching or re-parsing the PDF.

        Built for shrinking the manual-review backlog: a case flagged for
        review under an older classifier scores forever at that old
        confidence -- nothing ever re-evaluates it after the classifier
        improves (e.g. the AGP-presence confidence floor, or the LLM prompt
        no longer requiring "substantive arguments" for HEARD_AND_ADJOURNED),
        so every fix only helps orders analysed AFTER it ships and the
        existing backlog never shrinks on its own. This lets an admin job
        clear it out safely, reusing the exact same classification and
        LLM-assist code path a fresh analysis would use.

        Only ever raises confidence and only writes to Firestore when the
        new score actually clears REVIEW_CONFIDENCE_THRESHOLD -- a case
        that's still ambiguous is left completely untouched, still exactly
        where a human would expect to find it.

        Returns a dict describing what happened; see the ``reason`` values
        below. Never raises -- every failure mode is caught and reported.
        """
        normalized_date = self._normalise_order_date(order_date) or order_date
        base_result = {"case_ref": case_ref, "order_date": normalized_date}

        order = self._get_analysed_order_for_date(case_ref, normalized_date)
        if not order:
            return {**base_result, "resolved": False, "reason": "order_not_found"}

        order_text_url = order.get("order_text_url")
        if not order_text_url:
            # Predates order-text persistence (Stage 2) -- reclassifying would
            # require re-downloading and re-OCR'ing the PDF, which this
            # deliberately does not do (that's a full re-analysis, not a
            # cheap backfill). Left for manual review as before.
            return {**base_result, "resolved": False, "reason": "no_stored_text"}

        old_category = order.get("order_category")
        old_confidence = float(order.get("order_category_confidence") or 0.0)

        try:
            order_text = self._download_gcs_text(order_text_url)
        except Exception as exc:
            logger.warning(
                "reclassify_pending_order: could not fetch stored text for "
                "case_ref=%s date=%s: %s",
                case_ref,
                normalized_date,
                exc,
            )
            return {**base_result, "resolved": False, "reason": "text_fetch_failed"}

        if not order_text.strip():
            return {**base_result, "resolved": False, "reason": "empty_stored_text"}

        document_structure = self.order_analyzer._parse_document_structure(order_text)
        new_category, new_confidence = self.order_analyzer._classify_order_enhanced(
            order_text, document_structure
        )

        analysis_stub = SimpleNamespace(
            order_category=new_category,
            category_confidence=new_confidence,
            order_text=order_text,
        )
        llm_assist = self._maybe_llm_assist(analysis_stub, case_ref=case_ref)
        new_category = llm_assist["category"]
        new_confidence = llm_assist["confidence"]

        if new_confidence < self.REVIEW_CONFIDENCE_THRESHOLD:
            return {
                **base_result,
                "resolved": False,
                "reason": "still_below_threshold",
                "old_category": old_category,
                "old_confidence": old_confidence,
                "new_category": new_category,
                "new_confidence": new_confidence,
            }

        # This case's other pending dates (if any) must be read BEFORE the
        # write below, which will atomically remove *this* date -- the
        # difference between the two tells us whether the case is fully
        # resolved or must stay manual_review_required for another date.
        pending_before = self.case_store.get_pending_review_dates(case_ref)
        still_pending_after = [d for d in pending_before if d != normalized_date]

        analysis_metadata = dict(order.get("order_analysis_metadata") or {})
        analysis_metadata["llm_suggestion"] = llm_assist["llm_suggestion"]
        analysis_metadata["reclassified_from"] = {
            "category": old_category,
            "confidence": old_confidence,
        }
        self.case_store.append_case_order(
            case_ref,
            {
                "order_link": order.get("order_link"),
                "order_status": "analysed",
                "order_category": new_category,
                "order_date": order.get("order_date"),
                "board_date": order.get("board_date"),
                "order_category_confidence": new_confidence,
                "petitioner": order.get("petitioner"),
                "respondent": order.get("respondent"),
                "government_pleader": order.get("government_pleader"),
                "order_analysis_metadata": analysis_metadata,
                "order_text_url": order_text_url,
            },
            resolve_pending_date=normalized_date,
        )
        self._update_board_entries_for_case_date(
            case_ref, normalized_date, order.get("order_link"), new_category
        )

        final_status = "manual_review_required" if still_pending_after else "analysed"
        self.case_store.transition_lifecycle(
            case_ref,
            final_status,
            reason=(
                f"Reclassified {old_category} ({old_confidence:.2f}) -> "
                f"{new_category} ({new_confidence:.2f}) from stored text "
                "using updated classifier logic"
            ),
            metadata={
                "source": "reclassify_pending_order",
                "old_category": old_category,
                "old_confidence": old_confidence,
                "new_category": new_category,
                "new_confidence": new_confidence,
            },
            event_type="manual_review_reclassified",
            force=True,
        )
        logger.info(
            "reclassify_pending_order: resolved case_ref=%s date=%s "
            "%s (%.2f) -> %s (%.2f)",
            case_ref,
            normalized_date,
            old_category,
            old_confidence,
            new_category,
            new_confidence,
        )
        return {
            **base_result,
            "resolved": True,
            "reason": "cleared_review_threshold",
            "old_category": old_category,
            "old_confidence": old_confidence,
            "new_category": new_category,
            "new_confidence": new_confidence,
        }

    def reclassify_all_pending_reviews(self, limit: int = 500) -> Dict[str, Any]:
        """Run reclassify_pending_order over every currently
        manual_review_required case's pending dates, bounded by *limit*
        cases per call so one request can't run indefinitely against a
        large backlog -- call again (or on a schedule) to keep draining it.
        """
        db = self.case_store.db
        docs = (
            db.collection(self.case_store.case_collection)
            .where("lifecycle_status", "==", "manual_review_required")
            .limit(max(1, min(limit, 2000)))
            .stream()
        )
        summary = {
            "cases_scanned": 0,
            "dates_scanned": 0,
            "resolved": 0,
            "still_pending": 0,
            "errors": 0,
            "results": [],
        }
        for doc in docs:
            data = doc.to_dict() or {}
            case_ref = data.get("case_ref")
            if not case_ref:
                continue
            summary["cases_scanned"] += 1
            pending_dates = [
                d for d in (data.get("pending_review_order_dates") or []) if d
            ]
            for pending_date in pending_dates:
                summary["dates_scanned"] += 1
                try:
                    result = self.reclassify_pending_order(case_ref, pending_date)
                except Exception as exc:  # noqa: BLE001 - one bad case must not
                    # abort the whole backfill run.
                    logger.error(
                        "reclassify_all_pending_reviews: unexpected error for "
                        "case_ref=%s date=%s: %s",
                        case_ref,
                        pending_date,
                        exc,
                        exc_info=True,
                    )
                    summary["errors"] += 1
                    continue
                if result.get("resolved"):
                    summary["resolved"] += 1
                    summary["results"].append(result)
                else:
                    summary["still_pending"] += 1
        logger.info(
            "reclassify_all_pending_reviews: scanned %d cases / %d dates, "
            "resolved %d, still pending %d, errors %d",
            summary["cases_scanned"],
            summary["dates_scanned"],
            summary["resolved"],
            summary["still_pending"],
            summary["errors"],
        )
        return summary

    def _analyze_order_with_api_metadata(
        self,
        case_id: str,
        case_ref: str,
        pdf_content: bytes,
        api_order_date: str,
        api_petitioner: str,
        api_respondent: str,
        order_link: Optional[str] = None,
        board_date: Optional[str] = None,
        gcs_upload_failed: bool = False,
    ) -> Dict[str, Any]:
        """Analyse a PDF using the court API-provided date and party names.

        Unlike ``_analyze_order_with_date_validation``, this method trusts the
        *api_order_date*, *api_petitioner*, and *api_respondent* values from the
        direct API response rather than extracting them from the PDF text.  The PDF
        is still analysed so that ``order_category`` and related metadata are
        populated.
        """
        try:
            temp_filename = f"{case_ref.replace('/', '-')}.pdf"
            analysis_result = self.order_analyzer.analyze_order_document(
                temp_filename, pdf_content
            )
            analysis_metadata = getattr(analysis_result, "analysis_metadata", {}) or {}
            order_text_url = self._upload_order_text_to_gcs(
                getattr(analysis_result, "order_text", "") or "",
                case_ref,
                api_order_date,
            )

            llm_assist = self._maybe_llm_assist(analysis_result, case_ref=case_ref)
            if llm_assist["llm_suggestion"] is not None:
                analysis_metadata = {
                    **analysis_metadata,
                    "llm_suggestion": llm_assist["llm_suggestion"],
                }

            # Extract government pleaders from the analysis result.
            # Try to find the CaseInfo that matches case_ref; fall back to
            # the first case (or combine all when there is only one case).
            gp_list: List[str] = []
            if analysis_result.cases:
                target_case = None
                for c in analysis_result.cases:
                    if c.case_type and c.case_number and c.case_year:
                        candidate = f"{c.case_type}/{c.case_number}/{c.case_year}"
                        if candidate == case_ref:
                            target_case = c
                            break
                if target_case is None:
                    target_case = analysis_result.cases[0]
                gp_list = list(target_case.government_pleader or [])

            order_analysis: Dict[str, Any] = {
                "order_category": llm_assist["category"],
                "order_category_confidence": llm_assist["confidence"],
                "order_date": api_order_date,
                "order_petitioner": api_petitioner,
                "order_respondent": api_respondent,
                "government_pleader": gp_list,
                "order_link": order_link,
                "order_status": "analysed",
                "order_analysis_timestamp": datetime.now().isoformat(),
                "order_last_updated": datetime.now().isoformat(),
                "order_analysis_metadata": analysis_metadata,
                "date_source": "api",
                "gcs_upload_failed": gcs_upload_failed,
                "order_text_url": order_text_url,
            }

            self.case_store.transition_lifecycle(
                case_ref,
                "analysis_in_progress",
                metadata={"source": "auto_order_manager", "case_id": case_id},
                event_type="analysis_started",
            )
            self.case_store.append_case_order(
                case_ref,
                {
                    "order_link": order_analysis["order_link"],
                    "order_status": order_analysis["order_status"],
                    "order_category": order_analysis["order_category"],
                    "order_date": order_analysis["order_date"],
                    "board_date": board_date,
                    "order_category_confidence": order_analysis[
                        "order_category_confidence"
                    ],
                    "petitioner": order_analysis["order_petitioner"],
                    "respondent": order_analysis["order_respondent"],
                    "government_pleader": order_analysis["government_pleader"],
                    "order_analysis_timestamp": order_analysis[
                        "order_analysis_timestamp"
                    ],
                    "order_analysis_metadata": order_analysis[
                        "order_analysis_metadata"
                    ],
                    "date_source": "api",
                    "gcs_upload_failed": gcs_upload_failed,
                    "order_text_url": order_analysis["order_text_url"],
                },
            )
            # Route a low-confidence classification to a human instead of
            # letting it flow silently into a bill.  Until now nothing ever set
            # manual_review_required, so the review queue was structurally empty
            # while guesses (the scorer returns 0.50 for "no patterns matched")
            # were billed as if they were certain.  Threshold per
            # docs/CURRENT_WORKFLOW.md section 7.3.
            confidence = float(order_analysis.get("order_category_confidence") or 0.0)
            needs_review = confidence < self.REVIEW_CONFIDENCE_THRESHOLD
            if needs_review:
                # ArrayUnion, not a read-modify-write -- a case with many
                # hearing dates gets each one analysed independently (often
                # within seconds of each other during backlog processing),
                # so this must survive a concurrent add for a different date
                # of the same case.
                self.case_store.add_pending_review_date(case_ref, api_order_date)
            # The case must stay flagged as long as ANY hearing date is still
            # unresolved, not just this one. Confirmed live: a case with 15+
            # hearing dates had an earlier low-confidence date's
            # manual_review_required silently cleared the moment the NEXT
            # date analysed successfully -- that order was never actually
            # reviewed by a human, it just fell out of the queue. Reading
            # the pending set fresh (rather than trusting only this order's
            # own outcome) closes that gap.
            still_pending = self.case_store.get_pending_review_dates(case_ref)
            target_status = "manual_review_required" if still_pending else "analysed"
            self.case_store.transition_lifecycle(
                case_ref,
                target_status,
                reason=(
                    f"Classified {order_analysis['order_category']} with low "
                    f"confidence ({confidence:.2f}) — needs review"
                    if needs_review
                    else (
                        f"Other hearing dates still awaiting review: {still_pending}"
                        if still_pending
                        else None
                    )
                ),
                metadata={
                    "source": "auto_order_manager",
                    "case_id": case_id,
                    "order_category": order_analysis["order_category"],
                    "order_category_confidence": confidence,
                },
                event_type=(
                    "analysis_low_confidence"
                    if needs_review
                    else (
                        "analysis_succeeded_case_still_flagged"
                        if still_pending
                        else "analysis_succeeded"
                    )
                ),
            )
            if needs_review:
                logger.info(
                    "_analyze_order_with_api_metadata: case_ref=%s category=%s "
                    "confidence=%.2f below %.2f — queued for manual review",
                    case_ref,
                    order_analysis["order_category"],
                    confidence,
                    self.REVIEW_CONFIDENCE_THRESHOLD,
                )
            # NOTE: board-entry updates (propagating order_link / order_category back
            # to daily-boards) are now done centrally by _update_board_entries_for_case_date
            # so that ALL board entries for the order date are updated, not only the one
            # document whose case_id was passed here.
            logger.info(
                "_analyze_order_with_api_metadata: analysed case_ref=%s date=%s category=%s",
                case_ref,
                api_order_date,
                order_analysis["order_category"],
            )
            return {"success": True, "data": order_analysis}
        except Exception as exc:
            logger.error(
                "_analyze_order_with_api_metadata failed for case_ref=%s date=%s: %s",
                case_ref,
                api_order_date,
                exc,
            )
            return {"success": False, "error": str(exc)}

    def _analyze_existing_order(
        self,
        case_data: Dict[str, Any],
        result_template: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Analyse an order whose PDF has already been fetched and linked.

        This is the analysis-queue counterpart to
        ``_process_all_orders_from_api``: the fetch stage already ran and stored
        an ``order_link``, so here we download that single PDF and run the
        analyser over it instead of re-querying the court for the order list.

        Called by ``main._run_case_analysis_job`` for every job on the analysis
        queue (i.e. everything queued by ``POST /jobs/analyze-orders``).

        The order date and party names are taken from the stored order entry
        written by the fetch stage; they came from the court API and are more
        reliable than re-deriving them from the PDF text.  Analysis, lifecycle
        transitions and the case-details write are all delegated to
        ``_analyze_order_with_api_metadata`` so there is exactly one code path
        that records an analysed order.
        """
        result = dict(result_template)
        case_ref = case_data.get("case_ref") or ""
        case_id = case_data.get("id") or ""
        order_link = case_data.get("order_link")
        board_date = case_data.get("board_date")

        if not order_link:
            result["error"] = "No order link available for analysis"
            return result

        # Recover the metadata the fetch stage stored alongside the link.
        latest_order = self._get_case_order_context(case_ref).get("latest_order") or {}
        order_date_str = self._normalise_order_date(
            latest_order.get("order_date")
        ) or self._normalise_order_date(board_date)
        if not order_date_str:
            result["error"] = "Could not determine an order date for analysis"
            return result

        # Nothing to do if this date was already analysed — keeps re-queues and
        # the fetch worker's auto-retry idempotent.
        if self._is_order_already_analysed(case_ref, order_date_str):
            logger.info(
                "_analyze_existing_order: case_ref=%s date=%s already analysed, skipping",
                case_ref,
                order_date_str,
            )
            existing = self._get_analysed_order_for_date(case_ref, order_date_str) or {}
            result["analysis_success"] = True
            result["analysis_data"] = existing
            return result

        try:
            headers = {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) " "AppleWebKit/537.36"
                )
            }
            # court_get, not requests.get -- the court requires legacy TLS
            # renegotiation that a default session refuses. See court_http.
            response = court_get(order_link, headers=headers, timeout=30)
            content_type = response.headers.get("Content-Type", "")
            pdf_content = response.content or b""
            is_pdf = (
                "application/pdf" in content_type.lower()
                or pdf_content.startswith(b"%PDF")
            )
            if response.status_code != 200 or not is_pdf:
                result["error"] = (
                    f"Order link did not return a PDF "
                    f"(HTTP {response.status_code}, {content_type or 'unknown type'})"
                )
                return result
        except requests.exceptions.RequestException as exc:
            result["error"] = f"Could not download stored order PDF: {exc}"
            return result

        analysis = self._analyze_order_with_api_metadata(
            case_id=case_id,
            case_ref=case_ref,
            pdf_content=pdf_content,
            api_order_date=order_date_str,
            api_petitioner=latest_order.get("petitioner") or "",
            api_respondent=latest_order.get("respondent") or "",
            order_link=order_link,
            # The stored order entry must be tagged with the hearing this
            # order belongs to -- which, by the rule the rest of the system
            # uses (see _update_board_entries_for_case_date, and the fetch
            # path at _process_all_orders_from_api), is the order's own date.
            #
            # This used to pass `board_date`, which the analysis poll loop
            # sources from a case-details doc. case-details has no board_date
            # field, only latest_board_date, so it was ALWAYS the case's most
            # recent appearance regardless of which order was being analysed.
            # For any case listed more than once that tagged the order to the
            # wrong hearing, and Search Orders -- which matches
            # orders[].board_date against each board row's own date -- then
            # showed that order against the wrong board date, and nothing
            # against the right one.
            board_date=order_date_str,
        )

        if not analysis.get("success"):
            result["error"] = analysis.get("error") or "Order analysis failed"
            return result

        order_analysis = analysis.get("data") or {}
        # Propagate order_link / order_category back to every daily-boards row
        # for this case+date, exactly as the fetch path does.
        self._update_board_entries_for_case_date(
            case_ref,
            order_date_str,
            order_link,
            order_analysis.get("order_category"),
        )

        result["analysis_success"] = True
        result["analysis_data"] = order_analysis
        logger.info(
            "_analyze_existing_order: analysed case_ref=%s date=%s category=%s",
            case_ref,
            order_date_str,
            order_analysis.get("order_category"),
        )
        return result

    def _process_all_orders_from_api(
        self,
        case_ref: str,
        case_id: str,
        board_date: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Fetch **all** orders for a case from the court direct API and process each.

        Key behaviours
        --------------
        * Uses the date provided in the API array for every order — PDF text is not
          used for date extraction.  The API date is normalised to ``YYYY-MM-DD``
          immediately so that skip checks, GCS blob names, and Firestore storage
          all use a single canonical format regardless of the format emitted by
          the court scraper (which commonly uses ``DD/MM/YYYY``).
        * Uses petitioner/respondent names from the API response.
        * Each PDF is uploaded to GCS with a stable name
          ``court-orders/<case-ref-dashes>/<order-date>.pdf`` so that the stored URL
          never expires.  If GCS is not configured the original download link is kept.
        * Orders whose date is already ``analysed`` in ``case-details`` are skipped
          without re-downloading.
        * Orders are stored in ``case-details`` regardless of whether a matching
          board entry exists (board matching happens at query time).
        """
        result: Dict[str, Any] = {
            "success": False,
            "orders_processed": 0,
            "orders_skipped": 0,
            "order_link": None,
            "error": None,
        }
        try:
            # Use include_diagnostics so we can log each provider attempt
            diagnostics = self.court_scraper._fetch_with_provider(
                case_ref=case_ref,
                date=board_date,
                bench="mumbai",
                include_diagnostics=True,
            )
            attempts = diagnostics.get("provider_attempts") or []
            logger.info(
                "_process_all_orders_from_api scraper diagnostics for %s: "
                "sequence=%s attempts=%s",
                case_ref,
                diagnostics.get("provider_sequence"),
                [
                    {
                        "step": a.get("step"),
                        "status": a.get("status"),
                        "duration_ms": a.get("duration_ms"),
                        "error": a.get("error"),
                        "orders_found": a.get("orders_found"),
                    }
                    for a in attempts
                ],
            )
            api_response = (
                self.court_scraper._enrich_case_orders_result(diagnostics["result"])
                if diagnostics.get("result")
                else {
                    "status": "not_found",
                    "message": "All scraper providers returned no result. "
                    + "; ".join(
                        f"{a.get('step')} {a.get('status')}"
                        + (f": {a.get('error')}" if a.get("error") else "")
                        for a in attempts
                    ),
                    "case_orders": [],
                }
            )

            if not isinstance(api_response, dict):
                result["error"] = "Direct API returned non-dict response"
                return result

            # Party names from the API are deterministic — same values every call.
            # Persist them unconditionally, even if there are no orders to process.
            api_petitioner: str = str(api_response.get("petitioner") or "").strip()
            api_respondent: str = str(api_response.get("respondent") or "").strip()
            if api_petitioner or api_respondent:
                self.case_store.update_case_party_names(
                    case_ref, api_petitioner, api_respondent
                )

            case_orders = api_response.get("case_orders") or []
            if not case_orders:
                result["error"] = api_response.get(
                    "message", "Direct API returned no orders"
                )
                return result

            last_order_link: Optional[str] = None
            normalized_bd: Optional[str] = (
                (self._normalise_order_date(board_date) or board_date)
                if board_date
                else None
            )

            # Fast-path: if board_date is already analysed in case-details, skip
            # the portal call entirely — just re-link the existing order to the
            # board entry and return.  This is the hot path for re-uploaded boards
            # and for secondary hearing dates after the first analysis already
            # fetched all historical orders.
            if normalized_bd:
                existing_for_bd = self._get_analysed_order_for_date(
                    case_ref, normalized_bd
                )
                if existing_for_bd:
                    logger.info(
                        "_process_all_orders_from_api: board_date=%s already "
                        "analysed for case_ref=%s — linking to board entry and "
                        "skipping portal call",
                        board_date,
                        case_ref,
                    )
                    self._update_board_entries_for_case_date(
                        case_ref,
                        normalized_bd,
                        existing_for_bd.get("order_link"),
                        existing_for_bd.get("order_category"),
                    )
                    result["orders_skipped"] += 1
                    result["success"] = True
                    result["order_link"] = existing_for_bd.get("order_link")
                    return result

            for order_entry in case_orders:
                if not isinstance(order_entry, dict):
                    continue

                raw_date: str = str(order_entry.get("date") or "").strip()
                # Normalise to YYYY-MM-DD immediately — the scraper commonly emits
                # DD/MM/YYYY which would break skip checks and GCS blob naming.
                order_date_str: str = self._normalise_order_date(raw_date) or raw_date
                download_link: str = str(order_entry.get("download_link") or "").strip()

                if not download_link:
                    continue

                # Skip orders already fully analysed for this date.
                # Opportunistically re-link them to board entries so that any
                # board entries inserted after the initial analysis are backfilled.
                if order_date_str and self._is_order_already_analysed(
                    case_ref, order_date_str
                ):
                    result["orders_skipped"] += 1
                    ex_order = self._get_analysed_order_for_date(
                        case_ref, order_date_str
                    )
                    if ex_order:
                        self._update_board_entries_for_case_date(
                            case_ref,
                            order_date_str,
                            ex_order.get("order_link"),
                            ex_order.get("order_category"),
                        )
                        last_order_link = ex_order.get("order_link") or last_order_link
                    logger.info(
                        "_process_all_orders_from_api: skipping already-analysed "
                        "order for case_ref=%s date=%s",
                        case_ref,
                        order_date_str,
                    )
                    continue

                # Download the PDF
                try:
                    headers = {
                        "User-Agent": (
                            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                            "AppleWebKit/537.36"
                        )
                    }
                    # court_get, not requests.get -- the court requires
                    # legacy TLS renegotiation that a default session
                    # refuses. This is the download that was failing for
                    # every order with UNSAFE_LEGACY_RENEGOTIATION_DISABLED
                    # even after the case-status lookup started working.
                    dl_response = court_get(download_link, headers=headers, timeout=30)
                    content_type = dl_response.headers.get("Content-Type", "")
                    pdf_bytes = dl_response.content or b""
                    is_pdf = (
                        "application/pdf" in content_type.lower()
                        or pdf_bytes.startswith(b"%PDF")
                    )
                    if dl_response.status_code != 200 or not is_pdf:
                        logger.warning(
                            "_process_all_orders_from_api: non-PDF for "
                            "case_ref=%s date=%s HTTP=%d content_type=%s",
                            case_ref,
                            order_date_str,
                            dl_response.status_code,
                            content_type,
                        )
                        continue
                except requests.exceptions.Timeout as dl_err:
                    logger.warning(
                        "_process_all_orders_from_api: timeout for case_ref=%s date=%s: %s",
                        case_ref,
                        order_date_str,
                        dl_err,
                    )
                    continue
                except requests.exceptions.ConnectionError as dl_err:
                    logger.warning(
                        "_process_all_orders_from_api: connection error for case_ref=%s date=%s: %s",
                        case_ref,
                        order_date_str,
                        dl_err,
                    )
                    continue
                except (ValueError, KeyError, TypeError) as dl_err:
                    logger.error(
                        "_process_all_orders_from_api: permanent download error for case_ref=%s date=%s: %s",
                        case_ref,
                        order_date_str,
                        dl_err,
                    )
                    continue

                # Upload PDF to GCS for permanent storage (returns HTTPS URL).
                # Fall back to the (expiring) API link if GCS is not configured.
                stored_url = self._upload_order_to_gcs(
                    pdf_bytes, case_ref, order_date_str
                )
                final_order_link: str = stored_url or download_link
                gcs_upload_failed = stored_url is None and bool(self._gcs_bucket_name)
                if gcs_upload_failed:
                    logger.error(
                        "_process_all_orders_from_api: GCS upload failed for "
                        "case_ref=%s date=%s — storing expiring court URL instead. "
                        "Run GET /admin/test-gcs to diagnose the bucket permission.",
                        case_ref,
                        order_date_str,
                    )

                # Analyse and persist
                try:
                    anal = self._analyze_order_with_api_metadata(
                        case_id=case_id,
                        case_ref=case_ref,
                        pdf_content=pdf_bytes,
                        api_order_date=order_date_str,
                        api_petitioner=api_petitioner,
                        api_respondent=api_respondent,
                        order_link=final_order_link,
                        board_date=order_date_str,
                        gcs_upload_failed=gcs_upload_failed,
                    )
                    if anal.get("success"):
                        result["orders_processed"] += 1
                        last_order_link = final_order_link
                        order_category = (anal.get("data") or {}).get("order_category")
                        # Link to all board entries whose board_date == order_date.
                        # If no board entry exists for this date, nothing to update.
                        self._update_board_entries_for_case_date(
                            case_ref, order_date_str, final_order_link, order_category
                        )
                    else:
                        logger.warning(
                            "_process_all_orders_from_api: analysis failed for "
                            "case_ref=%s date=%s: %s",
                            case_ref,
                            order_date_str,
                            anal.get("error"),
                        )
                except Exception as anal_err:
                    logger.warning(
                        "_process_all_orders_from_api: analysis exception for "
                        "case_ref=%s date=%s: %s",
                        case_ref,
                        order_date_str,
                        anal_err,
                    )

            if result["orders_processed"] > 0 or result["orders_skipped"] > 0:
                result["success"] = True
                # When only skips occurred (all orders already analysed), surface the
                # last known order link from case-details so callers are not left with
                # order_link=None on a pure no-op run.
                if last_order_link is None and result["orders_skipped"] > 0:
                    case_detail = self.case_store.get_case_details(case_ref) or {}
                    last_order_link = case_detail.get("latest_order_link")
                result["order_link"] = last_order_link
            else:
                result["error"] = "No orders could be downloaded or processed"

        except Exception as exc:
            logger.error(
                "_process_all_orders_from_api failed for case_ref=%s: %s",
                case_ref,
                exc,
            )
            result["error"] = str(exc)

        return result

    def _process_single_case(self, case_data: Dict[str, Any]) -> Dict[str, Any]:
        """Download and analyse all orders for a single case.

        Delegates to ``_process_all_orders_from_api`` which drives the
        CourtScraper HTTP-first pipeline (direct POST to court portal, then
        Playwright fallback retried up to PLAYWRIGHT_RETRY_COUNT times, default 3).
        If the scraper finds no orders for the board date the case is transitioned
        to ``fetch_failed_retryable``.
        """
        case_id = case_data["id"]
        case_ref = case_data.get("case_ref") or self.build_case_ref_from_data(case_data)
        if not case_ref:
            raise ValueError(
                f"_process_single_case: case_ref missing and cannot be reconstructed "
                f"for case_id={case_id}"
            )
        result: Dict[str, Any] = {
            "case_id": case_id,
            "case_ref": case_ref,
            "download_success": False,
            "analysis_success": False,
            "order_link": None,
            "analysis_data": None,
            "error": None,
        }

        board_date_value = self._parse_board_date(case_data.get("board_date"))
        if board_date_value and board_date_value > datetime.now().date():
            reason = f"Order fetch is not due yet for board date {board_date_value.isoformat()}"
            self.case_store.transition_lifecycle(
                case_ref,
                "fetch_not_due",
                reason=reason,
                metadata={
                    "source": "auto_order_manager",
                    "board_date": board_date_value.isoformat(),
                },
                event_type="fetch_not_due",
            )
            result["error"] = reason
            return result

        self.case_store.transition_lifecycle(
            case_ref,
            "fetch_in_progress",
            metadata={"source": "auto_order_manager"},
            event_type="fetch_started",
        )

        # Scraper path: direct API first, Playwright as fallback (configured in CourtScraper).
        # board_date_value was parsed by _parse_board_date which handles Firestore Timestamps
        # correctly — str() on a Timestamp produces "YYYY-MM-DD HH:MM:SS" which breaks
        # date comparisons downstream.
        board_date_str = board_date_value.isoformat() if board_date_value else ""
        api_result = self._process_all_orders_from_api(
            case_ref=case_ref,
            case_id=case_id,
            board_date=board_date_str or None,
        )
        if api_result.get("success"):
            result["download_success"] = True
            result["order_link"] = api_result.get("order_link")
            result["analysis_success"] = True
            if api_result.get("orders_processed", 0) == 0:
                # All orders already analysed — restore lifecycle so the case does
                # not stay permanently stuck at fetch_in_progress.
                #
                # Exception: a case awaiting human review must not be quietly
                # marked analysed by a re-fetch.  Its order entries already read
                # order_status="analysed", so without this guard a re-fetch would
                # clear the review flag and the low-confidence result would reach
                # a bill unconfirmed.
                current_status = (self.case_store.get_case_details(case_ref) or {}).get(
                    "lifecycle_status"
                )
                if current_status != "manual_review_required":
                    self.case_store.transition_lifecycle(
                        case_ref,
                        "analysed",
                        metadata={
                            "source": "auto_order_manager",
                            "reason": "already_analysed",
                        },
                        event_type="analysis_skipped",
                    )
            logger.info(
                "✅ _process_single_case: scraper succeeded for %s "
                "(processed=%d skipped=%d)",
                case_ref,
                api_result.get("orders_processed", 0),
                api_result.get("orders_skipped", 0),
            )
            return result

        # Scraper found no orders for this board date.
        error_msg = api_result.get("error", "Scraper returned no orders")
        logger.info(
            "❌ _process_single_case: scraper found no orders for %s — %s",
            case_ref,
            error_msg,
        )
        self.case_store.transition_lifecycle(
            case_ref,
            "fetch_failed_retryable",
            reason=error_msg,
            metadata={"source": "auto_order_manager"},
            event_type="fetch_failed",
        )
        result["error"] = error_msg
        return result

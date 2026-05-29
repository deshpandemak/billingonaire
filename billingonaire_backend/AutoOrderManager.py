import base64
import logging
import os
import random
import re
import time
from dataclasses import asdict
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple
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

    def __init__(self):
        self.db = firestore.client()
        self.order_analyzer = OrderDocumentAnalyzer()
        self.court_scraper = BombayHighCourtScraper()
        self.case_store = CaseDataStore(self.db)

        # Collections - consolidated order status into daily-boards
        self.boards_collection = "daily-boards"
        self.search_index_collection = "order-search-index"

        # GCS bucket for permanent PDF storage (empty string → GCS upload disabled)
        self._gcs_bucket_name: str = os.getenv("ORDER_PDF_BUCKET", "")

        # Case type mappings for court lookup
        self.casetype_dict = {
            "WP": "2001",
            "IA": "2069",
            "IA(ST)": "2069",
            "CP": "2010",
            "RPW": "2019",
            "PIL": "2002",
            "CRLP": "2020",
            "CRLWP": "2021",
        }

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
        max_sequences: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Main method to automatically get orders for filtered cases

        Args:
            case_filters: Optional filters for case selection
            limit: Maximum number of cases to process
            max_sequences: Maximum number of sequence numbers to try per case

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
                "get_orders_for_cases: processing %d cases (filters=%s max_sequences=%s)",
                len(filtered_cases),
                case_filters,
                max_sequences,
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
                    case_result = self._process_single_case(case_data, max_sequences)
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

    def bulk_process_orders(
        self, case_ids: List[str], max_sequences: int = 50
    ) -> Dict[str, Any]:
        """
        Bulk process specific cases by their IDs with configurable max sequences

        Args:
            case_ids: List of case document IDs to process
            max_sequences: Maximum number of sequence numbers to try per case

        Returns:
            Dictionary with processing results
        """
        try:
            if not case_ids:
                return {"success": False, "error": "No case IDs provided"}

            logger.info(
                "bulk_process_orders starting: case_count=%d max_sequences=%d",
                len(case_ids),
                max_sequences,
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
                    case_result = self._process_single_case(case_data, max_sequences)
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

    def _get_filtered_matters(
        self, filters: Optional[Dict[str, Any]] = None, limit: int = 50
    ) -> List[Dict[str, Any]]:
        """Get cases that need order processing based on filters"""
        logger.info(
            "_get_filtered_matters called with filters=%s limit=%d", filters, limit
        )
        try:
            query = self.db.collection(self.boards_collection)

            # Apply filters if provided
            if filters:
                if filters.get("case_type"):
                    query = query.where("case_type", "==", filters["case_type"])
                if filters.get("case_year"):
                    query = query.where("case_year", "==", filters["case_year"])
                if filters.get("date_from"):
                    query = query.where("board_date", ">=", filters["date_from"])
                if filters.get("date_to"):
                    query = query.where("board_date", "<=", filters["date_to"])

            # Get cases without order analysis
            query = query.limit(limit * 2)  # Get more to filter
            cases: List[Dict[str, Any]] = []

            for doc in query.stream():
                case_data = doc.to_dict()
                case_data["id"] = doc.id
                case_ref = f"{case_data.get('case_type', '')}/{case_data.get('case_no', '')}/{case_data.get('case_year', '')}"
                case_data["case_ref"] = case_ref

                order_context = self._get_case_order_context(case_ref)
                order_status = order_context["order_status"]
                case_data["order_status"] = order_status
                case_data["order_link"] = order_context.get("order_link")

                # Include cases that need linking or analysis/retry.
                if order_status in [
                    "not_linked",
                    "linked",
                    "order_failed",
                    "order_analysis_failed",
                ]:
                    cases.append(case_data)

                    if len(cases) >= limit:
                        break

            logger.info(
                "_get_filtered_matters returned %d actionable cases", len(cases)
            )
            return cases

        except Exception as e:
            logger.error("Error getting filtered matters: %s", e)
            return []

    def _get_case_order_context(self, case_ref: str) -> Dict[str, Any]:
        case_detail = self.case_store.get_case_details(case_ref) or {}
        orders = case_detail.get("orders") or []
        # Use the last entry that actually has an order_link — blank status-only
        # entries (order_failed, not_linked markers) have no order_link and must
        # not shadow a previously stored valid link.
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
            "order_status": case_detail.get("latest_order_status")
            or latest_order.get("order_status")
            or "not_linked",
            "order_link": case_detail.get("latest_order_link")
            or latest_order.get("order_link"),
        }

    def _record_case_order_status(
        self, case_ref: str, status: str, reason: Optional[str] = None
    ) -> None:
        logger.info(
            "_record_case_order_status: case_ref=%s status=%s reason=%s",
            case_ref,
            status,
            reason,
        )
        # Only update the lifecycle — do NOT call append_case_order with a
        # status-only payload. Status entries have no order_date or order_link
        # and would be appended as blank rows in the orders array, clobbering
        # latest_order_link and showing empty rows in the modal.
        mapped_lifecycle = self.case_store.map_legacy_order_status(status)
        if mapped_lifecycle:
            self.case_store.transition_lifecycle(
                case_ref,
                mapped_lifecycle,
                reason=reason,
                metadata={"source": "auto_order_manager", "order_status": status},
                event_type="order_status_synced",
            )

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
            logger.warning(
                "_upload_order_to_gcs failed for case_ref=%s date=%s: %s",
                case_ref,
                order_date,
                exc,
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

    def _board_entry_exists_for_date(self, case_ref: str, date_str: str) -> bool:
        """Return True when daily-boards contains an entry for *case_ref* on *date_str*.

        IMPORTANT: Board.py saves board_date as a Python ``datetime`` object
        (``datetime.strptime(..., "%Y-%m-%d")``), so Firestore stores it as a
        Timestamp — NOT a string.  A string-equality WHERE clause never matches.
        We must compare with a ``datetime`` object.

        Order date and board date (hearing date) are always the same day, so we
        use an exact equality match — no date window tolerance.
        """
        if not case_ref or not date_str:
            return False
        try:
            try:
                board_date_dt = datetime.strptime(date_str, "%Y-%m-%d")
            except ValueError:
                logger.warning(
                    "_board_entry_exists_for_date: unparseable date %r for case_ref=%s",
                    date_str,
                    case_ref,
                )
                return False
            docs = (
                self.db.collection(self.boards_collection)
                .where("case_ref", "==", case_ref)
                .where("board_date", "==", board_date_dt)
                .limit(1)
                .stream()
            )
            return any(True for _ in docs)
        except Exception as exc:
            logger.warning(
                "_board_entry_exists_for_date: query failed for case_ref=%s date=%s: %s",
                case_ref,
                date_str,
                exc,
            )
            return False

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
                "order_category": analysis_result.order_category,
                "order_category_confidence": analysis_result.category_confidence,
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
                },
            )
            self.case_store.transition_lifecycle(
                case_ref,
                "analysed",
                metadata={
                    "source": "auto_order_manager",
                    "case_id": case_id,
                    "order_category": order_analysis["order_category"],
                },
                event_type="analysis_succeeded",
            )
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
            api_response = self.court_scraper.get_case_orders(
                case_ref=case_ref,
                date=board_date,
                bench="mumbai",
            )

            if not isinstance(api_response, dict):
                result["error"] = "Direct API returned non-dict response"
                return result

            case_orders = api_response.get("case_orders") or []
            if not case_orders:
                result["error"] = api_response.get(
                    "message", "Direct API returned no orders"
                )
                return result

            # Party names from the API — preferred over PDF extraction
            api_petitioner: str = str(api_response.get("petitioner") or "").strip()
            api_respondent: str = str(api_response.get("respondent") or "").strip()

            # Eagerly persist party names directly on the case document without
            # creating a dummy order entry (which would corrupt latest_order_*).
            if api_petitioner or api_respondent:
                self.case_store.update_case_party_names(
                    case_ref, api_petitioner, api_respondent
                )

            last_order_link: Optional[str] = None

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

                # Only process the order that matches the board_date that triggered
                # this download.  The court API returns ALL historical orders for the
                # case; processing a different date's order would corrupt the hearing
                # record.  When board_date is not supplied (back-fill), all orders are
                # eligible.
                if board_date:
                    normalized_bd = self._normalise_order_date(board_date) or board_date
                    if order_date_str != normalized_bd:
                        logger.info(
                            "_process_all_orders_from_api: skipping order for "
                            "case_ref=%s order_date=%s — does not match board_date=%s",
                            case_ref,
                            order_date_str,
                            board_date,
                        )
                        continue

                # Skip orders already fully analysed for this date
                if order_date_str and self._is_order_already_analysed(
                    case_ref, order_date_str
                ):
                    result["orders_skipped"] += 1
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
                    dl_response = requests.get(
                        download_link, headers=headers, timeout=30
                    )
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
                        board_date=board_date,
                    )
                    if anal.get("success"):
                        result["orders_processed"] += 1
                        last_order_link = final_order_link
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

    def _process_single_case(
        self, case_data: Dict[str, Any], max_sequences: Optional[int] = None
    ) -> Dict[str, Any]:
        """Process a single case: download and analyse all orders.

        Strategy (in priority order)
        -----------------------------
        1. **Direct API** – call ``court_scraper.get_case_orders`` to obtain the
           full array of orders (each with an explicit date and download link).
           All orders that are not yet analysed are downloaded, uploaded to GCS for
           permanent storage, and analysed.  The date and party names come from
           the API, not from PDF text extraction.
        2. **Cached existing order** – if the case already has status ``linked`` and
           the direct API yielded nothing, re-analyse the stored order link.
        3. **Sequence-number fallback** – brute-force trial of sequence numbers 1..N,
           used only when both the direct API and the cached link are unavailable.

        Args:
            case_data: Dictionary containing case information
            max_sequences: Maximum number of sequence numbers to try in the
                fallback path (default: from env or 10)
        """
        case_id = case_data["id"]
        case_ref = case_data["case_ref"]
        order_context = self._get_case_order_context(case_ref)
        order_status = order_context["order_status"]
        case_data["order_status"] = order_status
        case_data["order_link"] = order_context.get("order_link")
        case_data["case_detail"] = order_context.get("case_detail")

        # Check if case has existing order link
        has_existing_order_link = bool(case_data.get("order_link"))

        result: Dict[str, Any] = {
            "case_id": case_id,
            "case_ref": case_ref,
            "download_success": False,
            "analysis_success": False,
            "order_link": None,
            "analysis_data": None,
            "error": None,
            "retry_attempts": [],
            "has_existing_order": has_existing_order_link,
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

        # ---------------------------------------------------------------
        # Path 1: Direct API — fetch all orders with explicit dates.
        # This is attempted regardless of whether the case already has a
        # stored order link because:
        #  (a) new orders may have been published since the last run, and
        #  (b) previously stored download URLs may have expired.
        # ---------------------------------------------------------------
        # board_date_value was already parsed above via _parse_board_date which
        # handles Firestore Timestamp objects correctly (str() would produce
        # "2026-05-15 00:00:00" which breaks the date comparison downstream).
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
                # All orders were already analysed (skipped). Restore lifecycle so
                # the case does not stay permanently stuck at fetch_in_progress.
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
                "✅ _process_single_case: direct-API path succeeded for %s "
                "(processed=%d skipped=%d)",
                case_ref,
                api_result.get("orders_processed", 0),
                api_result.get("orders_skipped", 0),
            )
            return result

        logger.info(
            "_process_single_case: direct-API path failed for %s (%s), "
            "trying fallback paths",
            case_ref,
            api_result.get("error"),
        )

        # ---------------------------------------------------------------
        # Path 2: Re-analyse a previously stored order link.
        # Applies whenever the case already has a stored order link and the
        # direct API yielded nothing — covers both legacy "linked" status and
        # already-"analysed" cases being retried (e.g. to upgrade a BHC URL
        # to a GCS-hosted copy).
        # ---------------------------------------------------------------
        if has_existing_order_link:
            logger.info(
                "📋 %s - has existing order link (status=%s), re-analysing stored order",
                case_ref,
                order_status,
            )
            try:
                return self._analyze_existing_order(case_data, result, max_sequences)
            except Exception as e:
                logger.error(f"Failed to analyze existing order for {case_ref}: {e}")
                result["error"] = f"Failed to analyze existing order: {str(e)}"
                return result

        # ---------------------------------------------------------------
        # Path 3: Brute-force sequence-number fallback.
        # ---------------------------------------------------------------
        # Configurable max retries - use parameter, env var, or default to 10
        if max_sequences is not None and max_sequences > 0:
            MAX_RETRIES = max_sequences
        else:
            MAX_RETRIES = int(os.getenv("ORDER_MAX_SEQUENCE_RETRIES", "10"))
        logger.info(
            f"Processing {case_ref} - will try up to {MAX_RETRIES} sequence numbers"
        )

        download_failures = 0
        date_mismatches = 0

        try:
            # Retry loop: Try sequence numbers 1 through MAX_RETRIES
            for sequence_num in range(1, MAX_RETRIES + 1):
                # Log progress every 5 sequences or on first/last attempt
                if (
                    sequence_num == 1
                    or sequence_num == MAX_RETRIES
                    or sequence_num % 5 == 0
                ):
                    logger.info(
                        f"{case_ref} - trying sequence {sequence_num}/{MAX_RETRIES}"
                    )

                attempt_log: Dict[str, Any] = {
                    "sequence": sequence_num,
                    "status": "attempting",
                    "message": None,
                }

                try:
                    # Step 1: Try to download order with specific sequence number
                    order_info = self._download_order_for_case(case_data, sequence_num)

                    if not order_info.get("success"):
                        # Download failed for this sequence
                        download_failures += 1
                        attempt_log["status"] = "download_failed"
                        attempt_log["message"] = order_info.get(
                            "error", "Unknown error"
                        )
                        result["retry_attempts"].append(attempt_log)
                        # Exponential backoff between sequence retries to avoid
                        # rate-limiting from the court API (cap at 30s + jitter).
                        # Skip in test environments to keep test suites fast.
                        if sequence_num < MAX_RETRIES and not os.getenv("TESTING"):
                            backoff = min(2 ** (sequence_num - 1), 30) + random.uniform(
                                0, 1
                            )
                            time.sleep(backoff)
                        continue

                    # Step 2: Analyze order to extract date
                    if not order_info.get("pdf_content"):
                        download_failures += 1
                        attempt_log["status"] = "no_pdf_content"
                        attempt_log["message"] = "No PDF content available"
                        result["retry_attempts"].append(attempt_log)
                        continue

                    temp_filename = f"{case_ref.replace('/', '-')}.pdf"
                    quick_analysis = self.order_analyzer.analyze_order_document(
                        temp_filename, order_info["pdf_content"]
                    )

                    # Step 3: Validate order date matches board date
                    date_validation = self._validate_order_date(
                        quick_analysis.order_date, case_data.get("board_date")
                    )

                    if not date_validation.get("valid"):
                        # Date mismatch - log and continue to next sequence
                        date_mismatches += 1
                        attempt_log["status"] = "date_mismatch"
                        attempt_log[
                            "message"
                        ] = f"Order date {date_validation.get('extracted_date')} does not match board date {date_validation.get('expected_date')}"
                        result["retry_attempts"].append(attempt_log)
                        logger.info(
                            f"Case {case_ref} seq {sequence_num}: {attempt_log['message']}"
                        )
                        continue

                    # SUCCESS! Date matches - mark success and stop retrying
                    attempt_log["status"] = "success"
                    attempt_log[
                        "message"
                    ] = f"Order found with matching date {date_validation.get('extracted_date')}"
                    result["retry_attempts"].append(attempt_log)
                    result["download_success"] = True
                    result["order_link"] = order_info.get("order_link")

                    logger.info(
                        f"✅ Case {case_ref} - SUCCESS at sequence {sequence_num}/{MAX_RETRIES}"
                    )

                    # Step 4: Create order link first (since download succeeded)
                    try:
                        self._create_order_link(case_id, order_info)
                    except Exception as link_error:
                        logger.error(
                            f"Failed to create order link for {case_ref}: {link_error}"
                        )
                        result[
                            "error"
                        ] = f"Order downloaded but link creation failed: {str(link_error)}"
                        result["download_success"] = True
                        result["order_link"] = order_info.get("order_link")
                        return result

                    # Step 5: Perform analysis (after order link is created)
                    try:
                        analysis_result = self._analyze_order_with_date_validation(
                            case_id,
                            case_ref,
                            order_info["pdf_content"],
                            str(case_data.get("board_date") or ""),
                            order_info.get("order_link"),
                        )

                        if not analysis_result.get("success"):
                            # Analysis failed but order download succeeded
                            # Keep the order link and mark status as order_analysis_failed
                            logger.warning(
                                f"Analysis failed for {case_ref} seq {sequence_num}: {analysis_result.get('error')}"
                            )
                            attempt_log["status"] = "analysis_failed"
                            attempt_log[
                                "message"
                            ] = f"Analysis failed: {analysis_result.get('error')}"
                            result["retry_attempts"].append(attempt_log)
                            result[
                                "error"
                            ] = f"Order downloaded but analysis failed: {analysis_result.get('error')}"

                            # Update status to order_analysis_failed
                            try:
                                self._record_case_order_status(
                                    case_ref,
                                    "order_analysis_failed",
                                    result["error"],
                                )
                            except Exception as status_error:
                                logger.error(
                                    f"Failed to update order_analysis_failed status: {status_error}"
                                )

                            # Return with download success but analysis failure
                            return result

                        # Analysis succeeded!
                        result["analysis_success"] = True
                        result["analysis_data"] = analysis_result.get("data")

                        # Step 6: Create search index
                        try:
                            self._create_search_index_entry(
                                case_id, case_data, analysis_result["data"]
                            )
                        except Exception as index_error:
                            logger.error(
                                f"Failed to create search index for {case_ref}: {index_error}"
                            )
                            # Not critical - we have the order and analysis

                        # Step 7: Link order to additional cases found in the order (multi-case linking)
                        try:
                            link_analysis_data = dict(result["analysis_data"] or {})
                            link_analysis_data["order_cases"] = analysis_result.get(
                                "cases", []
                            )
                            linked_cases = self._link_order_to_additional_cases(
                                case_id,
                                case_ref,
                                link_analysis_data,
                                order_info,
                                str(case_data.get("board_date") or ""),
                            )
                            if linked_cases:
                                result["additional_cases_linked"] = linked_cases
                                logger.info(
                                    f"Linked order to {len(linked_cases)} additional cases: {linked_cases}"
                                )
                        except Exception as multi_link_error:
                            logger.warning(
                                f"Failed to link order to additional cases for {case_ref}: {multi_link_error}"
                            )
                            # Not critical - primary case is already linked

                        # Success! Stop retrying
                        return result

                    except Exception as analysis_error:
                        # Analysis threw an exception but order download succeeded
                        # Keep the order link and mark status as order_analysis_failed
                        logger.warning(
                            f"Analysis exception for {case_ref} seq {sequence_num}: {analysis_error}"
                        )
                        attempt_log["status"] = "analysis_exception"
                        attempt_log["message"] = str(analysis_error)
                        result["retry_attempts"].append(attempt_log)
                        result[
                            "error"
                        ] = f"Order downloaded but analysis threw exception: {str(analysis_error)}"

                        # Update status to order_analysis_failed
                        try:
                            self._record_case_order_status(
                                case_ref,
                                "order_analysis_failed",
                                result["error"],
                            )
                        except Exception as status_error:
                            logger.error(
                                f"Failed to update order_analysis_failed status: {status_error}"
                            )

                        # Return with download success but analysis failure
                        return result

                except Exception as e:
                    # Log this attempt's error and continue
                    attempt_log["status"] = "error"
                    attempt_log["message"] = str(e)
                    result["retry_attempts"].append(attempt_log)
                    logger.warning(f"Case {case_ref} seq {sequence_num} error: {e}")
                    continue

            # If we get here, all attempts failed - provide detailed error
            error_parts = [f"No matching order found after {MAX_RETRIES} attempts."]
            if download_failures > 0:
                error_parts.append(f"{download_failures} downloads failed.")
            if date_mismatches > 0:
                error_parts.append(f"{date_mismatches} orders had date mismatches.")
            result["error"] = " ".join(error_parts)
            logger.warning(
                f"❌ Case {case_ref} - FAILED after {MAX_RETRIES} sequences: {result['error']}"
            )

            # Set order_failed status after all attempts exhausted
            try:
                self._record_case_order_status(
                    case_ref, "order_failed", result["error"]
                )
            except Exception as status_error:
                logger.error(
                    f"Failed to update order_failed status for {case_id}: {status_error}"
                )

        except Exception as e:
            result["error"] = str(e)
            logger.error(f"Error processing case {case_ref}: {e}")

        return result

    def _analyze_existing_order(
        self,
        case_data: Dict[str, Any],
        result: Dict[str, Any],
        max_sequences: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Analyze an order that's already been downloaded (linked status)

        Args:
            case_data: Dictionary containing case information
            result: Existing result dictionary
            max_sequences: Maximum number of sequence numbers to try if fallback needed
        """
        case_id = case_data["id"]
        case_ref = case_data["case_ref"]
        order_link = case_data.get("order_link")

        try:
            logger.info(
                "Attempting to re-download existing order from %s for case_ref=%s",
                _redact_url(order_link),
                case_ref,
            )

            # Re-download the PDF from the stored link
            response = requests.get(order_link, timeout=30)

            # Validate response status
            if response.status_code != 200:
                logger.warning(
                    f"Order link returned HTTP {response.status_code} for {case_ref}, falling back to fresh download"
                )
                return self._fallback_to_fresh_download(
                    case_data,
                    result,
                    f"Stored order link expired (HTTP {response.status_code})",
                    max_sequences,
                )

            # Validate content type
            content_type = response.headers.get("Content-Type", "")
            if "application/pdf" not in content_type:
                logger.warning(
                    f"Order link returned {content_type} instead of PDF for {case_ref}, falling back to fresh download"
                )
                return self._fallback_to_fresh_download(
                    case_data,
                    result,
                    f"Stored order link returned invalid content type: {content_type}",
                    max_sequences,
                )

            pdf_content = response.content

            # Validate PDF content size
            if not pdf_content or len(pdf_content) < 100:
                logger.warning(
                    f"Order link returned empty/small content for {case_ref}, falling back to fresh download"
                )
                return self._fallback_to_fresh_download(
                    case_data,
                    result,
                    "Stored order link returned empty or invalid PDF",
                    max_sequences,
                )

            logger.info(
                f"Successfully re-downloaded order for {case_ref}, size: {len(pdf_content)} bytes"
            )

            # If the existing link is not already a GCS URL, try to upload to GCS
            # so future access uses a permanent, non-expiring link.
            if order_link and not order_link.startswith(
                "https://storage.googleapis.com"
            ):
                board_date_str = str(case_data.get("board_date") or "")
                gcs_url = self._upload_order_to_gcs(
                    pdf_content, case_ref, board_date_str
                )
                if gcs_url:
                    logger.info(
                        "_analyze_existing_order: upgraded BHC link to GCS for case_ref=%s",
                        case_ref,
                    )
                    order_link = gcs_url

            # Mark download as successful
            result["download_success"] = True
            result["order_link"] = order_link

            # Analyze the order
            analysis_result = self._analyze_order_with_date_validation(
                case_id,
                case_ref,
                pdf_content,
                str(case_data.get("board_date") or ""),
                order_link,
            )

            # If the stored order's date doesn't match this board entry's date,
            # the existing link is wrong (e.g. linked via old tolerance window).
            # Fall back to a fresh download so the correct order can be found.
            if analysis_result.get("error") == "date_mismatch":
                logger.warning(
                    "_analyze_existing_order: existing order date mismatch for "
                    "case_ref=%s — falling back to fresh download",
                    case_ref,
                )
                return self._fallback_to_fresh_download(
                    case_data,
                    result,
                    "Existing order date does not match board date",
                    max_sequences,
                )

            if analysis_result.get("success"):
                result["analysis_success"] = True
                result["analysis_data"] = analysis_result.get("data")

                # Create search index
                try:
                    self._create_search_index_entry(
                        case_id, case_data, analysis_result["data"]
                    )
                except Exception as index_error:
                    logger.error(
                        f"Failed to create search index for {case_ref}: {index_error}"
                    )

                # Link order to additional cases found in the order (multi-case linking)
                try:
                    link_analysis_data = dict(result["analysis_data"] or {})
                    link_analysis_data["order_cases"] = analysis_result.get("cases", [])
                    linked_cases = self._link_order_to_additional_cases(
                        case_id,
                        case_ref,
                        link_analysis_data,
                        {"order_link": order_link, "pdf_content": pdf_content},
                        str(case_data.get("board_date") or ""),
                    )
                    if linked_cases:
                        result["additional_cases_linked"] = linked_cases
                        logger.info(
                            f"Linked order to {len(linked_cases)} additional cases: {linked_cases}"
                        )
                except Exception as multi_link_error:
                    logger.warning(
                        f"Failed to link order to additional cases for {case_ref}: {multi_link_error}"
                    )

                logger.info(f"✅ Successfully analyzed existing order for {case_ref}")
            else:
                result["error"] = f"Analysis failed: {analysis_result.get('error')}"
                logger.error(
                    f"Analysis failed for existing order {case_ref}: {result['error']}"
                )

                # Update status to order_analysis_failed
                try:
                    self._record_case_order_status(
                        case_ref,
                        "order_analysis_failed",
                        result["error"],
                    )
                except Exception as status_error:
                    logger.error(
                        f"Failed to update order_analysis_failed status: {status_error}"
                    )

            return result

        except Exception as e:
            error_msg = f"Failed to analyze existing order: {str(e)}"
            result["error"] = error_msg
            logger.error(f"Error analyzing existing order for {case_ref}: {e}")

            # Update status to order_analysis_failed
            try:
                self._record_case_order_status(
                    case_ref, "order_analysis_failed", error_msg
                )
            except Exception as status_error:
                logger.error(
                    f"Failed to update order_analysis_failed status: {status_error}"
                )

            return result

    def _fallback_to_fresh_download(
        self,
        case_data: Dict[str, Any],
        result: Dict[str, Any],
        reason: str,
        max_sequences: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Fallback to fresh download when stored order link is invalid

        Args:
            case_data: Dictionary containing case information
            result: Existing result dictionary
            reason: Reason for fallback
            max_sequences: Maximum number of sequence numbers to try (default: from env or 50)
        """
        case_id = case_data["id"]
        case_ref = case_data["case_ref"]

        logger.info(f"Initiating fresh download for {case_ref} due to: {reason}")

        try:
            # Reset status to not_linked to trigger fresh download
            self._record_case_order_status(case_ref, "not_linked", reason)

            # Remove linked status from case_data to prevent infinite loop
            case_data_fresh = case_data.copy()
            case_data_fresh["order_status"] = "not_linked"
            case_data_fresh.pop("order_link", None)

            # Now process with normal download flow (will try up to N sequence numbers)
            # Use parameter, env var, or default to 10
            if max_sequences is not None and max_sequences > 0:
                MAX_RETRIES = max_sequences
            else:
                MAX_RETRIES = int(os.getenv("ORDER_MAX_SEQUENCE_RETRIES", "10"))

            logger.info(
                f"Processing {case_ref} with fresh download (trying up to {MAX_RETRIES} sequence numbers)"
            )

            # Use existing _process_single_case logic but with modified case_data
            download_failures = 0
            date_mismatches = 0

            for sequence_num in range(1, MAX_RETRIES + 1):
                if (
                    sequence_num == 1
                    or sequence_num == MAX_RETRIES
                    or sequence_num % 5 == 0
                ):
                    logger.info(
                        f"Fresh download {case_ref}: trying sequence {sequence_num}/{MAX_RETRIES}"
                    )

                try:
                    download_result = self._download_order_for_case(
                        case_data_fresh, sequence_num
                    )

                    if download_result.get("success"):
                        order_link = download_result.get("order_link")
                        pdf_content = download_result.get("pdf_content")
                        if not isinstance(pdf_content, bytes):
                            result[
                                "error"
                            ] = "Downloaded order did not contain PDF bytes"
                            continue

                        result["download_success"] = True
                        result["order_link"] = order_link

                        # Analyze the downloaded order
                        analysis_result = self._analyze_order_with_date_validation(
                            case_id,
                            case_ref,
                            pdf_content,
                            str(case_data.get("board_date") or ""),
                            order_link,
                        )

                        if analysis_result.get("success"):
                            result["analysis_success"] = True
                            result["analysis_data"] = analysis_result.get("data")

                            # Create search index
                            try:
                                self._create_search_index_entry(
                                    case_id, case_data_fresh, analysis_result["data"]
                                )
                            except Exception as index_error:
                                logger.error(
                                    f"Failed to create search index: {index_error}"
                                )

                            # Link to additional cases
                            try:
                                link_analysis_data = dict(result["analysis_data"] or {})
                                link_analysis_data["order_cases"] = analysis_result.get(
                                    "cases", []
                                )
                                linked_cases = self._link_order_to_additional_cases(
                                    case_id,
                                    case_ref,
                                    link_analysis_data,
                                    download_result,
                                    str(case_data.get("board_date") or ""),
                                )
                                if linked_cases:
                                    result["additional_cases_linked"] = linked_cases
                            except Exception as multi_link_error:
                                logger.warning(
                                    f"Multi-case linking failed: {multi_link_error}"
                                )

                            logger.info(
                                f"✅ Fresh download and analysis succeeded for {case_ref}"
                            )
                            return result
                        else:
                            result["error"] = analysis_result.get("error")
                            logger.error(
                                f"Analysis failed after fresh download: {result['error']}"
                            )
                            return result

                    elif download_result.get("error"):
                        if "date mismatch" in download_result.get("error", "").lower():
                            date_mismatches += 1
                        else:
                            download_failures += 1
                        continue

                except Exception as e:
                    logger.warning(f"Fresh download seq {sequence_num} error: {e}")
                    download_failures += 1
                    continue

            # All attempts failed
            error_msg = f"Fresh download failed after {MAX_RETRIES} attempts. {download_failures} downloads failed, {date_mismatches} date mismatches."
            result["error"] = error_msg

            # Update status to order_failed
            self._record_case_order_status(case_ref, "order_failed", error_msg)

            return result

        except Exception as e:
            error_msg = f"Fallback fresh download failed: {str(e)}"
            result["error"] = error_msg
            logger.error(f"Error in fallback fresh download for {case_ref}: {e}")

            # Update to order_analysis_failed
            try:
                self._record_case_order_status(
                    case_ref, "order_analysis_failed", error_msg
                )
            except Exception as status_error:
                logger.error(f"Failed to update status: {status_error}")

            return result

    def _download_order_for_case(
        self, case_data: Dict[str, Any], sequence_number: int = 0
    ) -> Dict[str, Any]:
        """
        Download order for a specific case using the Bombay High Court API

        Args:
            case_data: Case data dictionary
            sequence_number: Specific sequence number to try (0-49)
        """
        case_ref = case_data.get("case_ref", "UNKNOWN")
        logger.info(
            "_download_order_for_case called for case_ref=%s seq=%d",
            case_ref,
            sequence_number,
        )
        try:
            case_ref = case_data["case_ref"]
            board_date = case_data.get("board_date")

            # Determine if this needs stamp number search BEFORE parsing
            search_stamp_no = "(ST)" in case_ref
            # Remove (ST) suffix for parsing
            case_ref_for_parsing = case_ref.replace("(ST)", "").strip()

            # Parse case reference
            case_parts = self._parse_case_reference(case_ref_for_parsing)
            logger.info(
                "_download_order_for_case: parsed case_ref=%s -> %s",
                case_ref,
                case_parts,
            )
            if not case_parts:
                logger.warning(
                    "_download_order_for_case: invalid case reference format for case_ref=%s",
                    case_ref,
                )
                return {"success": False, "error": "Invalid case reference format"}

            case_type, case_number, year = case_parts
            logger.info(
                "_download_order_for_case: case_type=%s case_number=%s year=%s stamp=%s",
                case_type,
                case_number,
                year,
                search_stamp_no,
            )

            # Format case number with leading zeros
            case_number_str = str(case_number).zfill(7)

            # Convert board_date to datetime object for comparison
            case_board_date = None
            if isinstance(board_date, datetime):
                case_board_date = board_date
                date_str = board_date.strftime("%d%m%Y")
            elif isinstance(board_date, str):
                try:
                    case_board_date = datetime.strptime(board_date, "%Y-%m-%d")
                    date_str = case_board_date.strftime("%d%m%Y")
                except ValueError:
                    case_board_date = datetime.now()
                    date_str = case_board_date.strftime("%d%m%Y")
            else:
                case_board_date = datetime.now()
                date_str = case_board_date.strftime("%d%m%Y")

            order_filename = f"{case_ref.replace('/', '-')}-{date_str}.pdf"

            # First attempt structured scraper workflow once per case.
            if sequence_number == 1:
                cached_result = self._download_order_from_cached_case_data(
                    case_data=case_data,
                    order_filename=order_filename,
                )
                if cached_result.get("success"):
                    return cached_result

                structured_result = self._download_order_via_scraper(
                    case_ref=case_ref,
                    board_date=str(board_date) if board_date is not None else None,
                    order_filename=order_filename,
                )
                if structured_result.get("success"):
                    return structured_result
                logger.info(
                    f"Structured order lookup unavailable for {case_ref}: {structured_result.get('error')}"
                )

            # Check if case type is supported
            if case_type not in self.casetype_dict:
                return {
                    "success": False,
                    "error": f"Case type {case_type} not supported for automated download",
                    "suggested_filename": order_filename,
                }

            # Try to download using specific sequence number
            download_result = self._download_pdf_bombay_hc_simple(
                case_type,
                case_number_str,
                str(year),
                search_stamp_no,
                order_filename,
                sequence_number,
            )

            if download_result.get("success"):
                return {
                    "success": True,
                    "order_link": download_result.get("download_url"),
                    "pdf_content": download_result.get("pdf_content"),
                    "filename": order_filename,
                    "source": "bombay_hc_api",
                    "sequence_number": sequence_number,
                }
            else:
                return {
                    "success": False,
                    "error": download_result.get("error", "Unknown download error"),
                    "suggested_filename": order_filename,
                }

        except Exception as e:
            return {"success": False, "error": str(e)}

    def _download_order_from_cached_case_data(
        self, case_data: Dict[str, Any], order_filename: str
    ) -> Dict[str, Any]:
        """Try reusing normalized case-details order link for the same board date."""
        case_ref = case_data.get("case_ref")
        board_date = self._parse_board_date(case_data.get("board_date"))
        if not case_ref or not board_date:
            return {"success": False, "error": "missing_case_ref_or_board_date"}

        case_detail = case_data.get("case_detail")
        if not isinstance(case_detail, dict):
            return {"success": False, "error": "missing_case_detail_context"}

        has_court_details = bool(
            str(case_detail.get("petitioner") or "").strip()
            and str(case_detail.get("respondent") or "").strip()
        )
        if not has_court_details:
            return {"success": False, "error": "missing_court_details"}

        orders = case_detail.get("orders") or []
        if not isinstance(orders, list):
            return {"success": False, "error": "invalid_orders_cache"}

        cached_link = None
        for order in reversed(orders):
            if not isinstance(order, dict):
                continue
            order_link = str(order.get("order_link") or "").strip()
            if not order_link:
                continue
            order_date = self._parse_board_date(order.get("board_date"))
            if order_date and order_date == board_date:
                cached_link = order_link
                break

        if not cached_link:
            return {"success": False, "error": "no_matching_cached_order_link"}

        logger.info(
            "Using cached order link for %s on board date %s; skipping structured scraper",
            case_ref,
            board_date.isoformat(),
        )

        try:
            response = requests.get(cached_link, timeout=30)
            content_type = response.headers.get("Content-Type", "")
            pdf_bytes = response.content or b""
            is_pdf = "application/pdf" in content_type.lower() or pdf_bytes.startswith(
                b"%PDF"
            )

            if response.status_code != 200 or not is_pdf:
                return {
                    "success": False,
                    "error": (
                        "Cached order link did not return a valid PDF "
                        f"(HTTP {response.status_code}, Content-Type {content_type})"
                    ),
                }

            self.case_store.append_case_order(
                case_ref,
                {
                    "order_link": cached_link,
                    "board_date": board_date.isoformat(),
                    "cache_validated_at": datetime.now().isoformat(),
                    "cache_validation_source": "case_store_cached",
                },
            )

            return {
                "success": True,
                "order_link": cached_link,
                "pdf_content": pdf_bytes,
                "filename": order_filename,
                "source": "case_store_cached",
            }
        except Exception as e:
            return {
                "success": False,
                "error": f"Cached order link download failed: {str(e)}",
            }

    def _download_order_via_scraper(
        self, case_ref: str, board_date: Optional[str], order_filename: str
    ) -> Dict:
        """Use structured scraper output to fetch exact order URL before brute-force sequence attempts."""
        logger.info(
            "_download_order_via_scraper called for case_ref=%s board_date=%s",
            case_ref,
            board_date,
        )
        try:
            response = self.court_scraper.get_case_orders(
                case_ref=case_ref,
                date=board_date,
                bench="mumbai",
            )

            if not isinstance(response, dict):
                logger.warning(
                    "_download_order_via_scraper: non-dict response for case_ref=%s",
                    case_ref,
                )
                return {
                    "success": False,
                    "error": "Structured scraper returned non-dict response",
                }

            if response.get("status") != "found":
                logger.warning(
                    "_download_order_via_scraper: status=%s for case_ref=%s",
                    response.get("status"),
                    case_ref,
                )
                return {
                    "success": False,
                    "error": response.get(
                        "message", "No orders found from structured scraper"
                    ),
                }

            court_orders = response.get("court_orders") or []
            if not court_orders:
                logger.warning(
                    "_download_order_via_scraper: no court_orders returned for case_ref=%s",
                    case_ref,
                )
                return {
                    "success": False,
                    "error": "Structured scraper returned no court orders",
                }

            order_entry = next(
                (
                    order
                    for order in court_orders
                    if isinstance(order, dict) and order.get("download_url")
                ),
                None,
            )
            if not order_entry:
                return {
                    "success": False,
                    "error": "Structured scraper response missing order download URL",
                }

            download_url = order_entry["download_url"]
            structured_source = str(response.get("source") or "direct_api")
            logger.info(
                "_download_order_via_scraper: downloading PDF from %s source=%s for case_ref=%s",
                _redact_url(download_url),
                structured_source,
                case_ref,
            )
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            }
            download_response = requests.get(download_url, headers=headers, timeout=30)

            content_type = download_response.headers.get("Content-Type", "")
            pdf_bytes = download_response.content or b""
            is_pdf = "application/pdf" in content_type.lower() or pdf_bytes.startswith(
                b"%PDF"
            )

            if download_response.status_code != 200 or not is_pdf:
                logger.warning(
                    "_download_order_via_scraper: non-PDF response HTTP %d content_type=%s for case_ref=%s",
                    download_response.status_code,
                    content_type,
                    case_ref,
                )
                return {
                    "success": False,
                    "error": (
                        "Structured scraper provided non-PDF/invalid URL "
                        f"(HTTP {download_response.status_code}, Content-Type {content_type})"
                    ),
                }

            logger.info(
                "_download_order_via_scraper: PDF downloaded successfully size=%d bytes for case_ref=%s",
                len(pdf_bytes),
                case_ref,
            )
            return {
                "success": True,
                "order_link": download_url,
                "pdf_content": pdf_bytes,
                "filename": order_filename,
                "source": f"{structured_source}_structured",
                "listing_date": order_entry.get("listing_date"),
                "order_description": order_entry.get("order_description"),
            }
        except Exception as e:
            logger.error(
                "_download_order_via_scraper failed for case_ref=%s: %s", case_ref, e
            )
            return {
                "success": False,
                "error": f"Structured scraper lookup failed: {str(e)}",
            }

    def _download_pdf_bombay_hc_simple(
        self,
        case_type: str,
        case_number: str,
        year: str,
        search_stamp_no: bool,
        order_filename: str,
        sequence_number: int = 0,
    ) -> Dict:
        """
        Download PDF from Bombay High Court for a specific sequence number

        Args:
            case_type: Type of case (e.g., 'CP', 'WP')
            case_number: Case number with leading zeros
            year: Year of the case
            search_stamp_no: Whether to search with stamp number
            order_filename: Filename for the order
            sequence_number: Specific sequence number to try (0-49)
        """
        # Log function entry at info level
        logger.info(
            "_download_pdf_bombay_hc_simple: case_type=%s case_number=%s year=%s seq=%d stamp=%s",
            case_type,
            case_number,
            year,
            sequence_number,
            search_stamp_no,
        )
        try:
            base_url = "https://bombayhighcourt.nic.in/"
            url = "generatenewauth.php?bhcpar="
            query = "path=./writereaddata/data/civil/{year}/&fname={stamp_no}{case_type}{case_number}{year}_{seq}.pdf&smflag=N&rjuddate=&uploaddt=&spassphrase={current_time}&ncitation=&smcitation=&digcertflg=&interface="

            # Generate current timestamp
            date_time = datetime.now()
            current_time = date_time.strftime("%d%m%y%H%M%S")

            # Use the specific sequence number provided
            # Sequence numbers now start from 1, so use as-is
            api_seq_no = sequence_number

            # Format the query
            query_fmt = query.format(
                case_type=self.casetype_dict[case_type],
                case_number=case_number,
                year=year,
                seq=str(api_seq_no),
                current_time=current_time,
                stamp_no="F" if search_stamp_no else "",
            )

            # Encode the query
            query_utf_8 = query_fmt.encode("utf-8")
            encoded_query = base64.b64encode(query_utf_8)
            query_str = encoded_query.decode("utf-8")
            full_url = base_url + url + query_str

            # Make the request with browser-like User-Agent
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
            }

            try:
                response = requests.get(full_url, headers=headers, timeout=30)

                # Log response details for debugging
                content_type = response.headers.get("Content-Type", "unknown")
                logger.info(
                    f"Sequence {sequence_number}: HTTP {response.status_code}, "
                    f"Content-Type: {content_type}, Size: {len(response.content)} bytes"
                )

                # Check if response is a PDF
                if content_type == "application/pdf":
                    logger.info(
                        f"✅ PDF found for: {order_filename} (seq: {sequence_number})"
                    )
                    return {
                        "success": True,
                        "pdf_content": response.content,
                        "download_url": full_url,
                        "filename": order_filename,
                        "sequence_number": sequence_number,
                    }
                else:
                    # Log non-PDF response for debugging
                    response_preview = (
                        response.text[:500]
                        if len(response.text) < 500
                        else response.text[:500] + "..."
                    )
                    logger.warning(
                        f"⚠️ Sequence {sequence_number} returned non-PDF: "
                        f"Status={response.status_code}, "
                        f"Content-Type={content_type}, "
                        f"Response preview: {response_preview}"
                    )
                    return {
                        "success": False,
                        "error": f"No PDF found at sequence {sequence_number} (got {content_type})",
                        "http_status": response.status_code,
                        "response_preview": response_preview[:200],
                    }

            except requests.Timeout as e:
                error_msg = (
                    f"Timeout after 30s for sequence {sequence_number}: {str(e)}"
                )
                logger.error(
                    "_download_pdf_bombay_hc_simple timeout: case_type=%s seq=%d error=%s",
                    case_type,
                    sequence_number,
                    e,
                )
                return {"success": False, "error": error_msg}
            except requests.ConnectionError as e:
                error_msg = f"Connection error for sequence {sequence_number}: {str(e)}"
                logger.error(
                    "_download_pdf_bombay_hc_simple connection error: case_type=%s seq=%d error=%s",
                    case_type,
                    sequence_number,
                    e,
                )
                return {"success": False, "error": error_msg}
            except requests.RequestException as e:
                error_msg = f"Request failed for sequence {sequence_number}: {str(e)}"
                logger.error(
                    "_download_pdf_bombay_hc_simple request failed: case_type=%s seq=%d error=%s",
                    case_type,
                    sequence_number,
                    e,
                )
                return {"success": False, "error": error_msg}

        except Exception as e:
            logger.error("Error downloading PDF from Bombay HC: %s", e)
            return {"success": False, "error": str(e)}

    def _analyze_order_with_date_validation(
        self,
        case_id: str,
        case_ref: str,
        pdf_content: bytes,
        expected_board_date: str,
        order_link: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Analyze a downloaded order and persist the event in case-details."""
        try:
            # Create temporary filename for analysis
            temp_filename = f"{case_ref.replace('/', '-')}.pdf"

            # Analyze using existing order analyzer
            analysis_result = self.order_analyzer.analyze_order_document(
                temp_filename, pdf_content
            )
            analysis_metadata = getattr(analysis_result, "analysis_metadata", {}) or {}
            analyzer_fallback_metrics: Dict[str, Any] = {}
            if hasattr(self.order_analyzer, "get_fallback_metrics"):
                try:
                    analyzer_fallback_metrics = (
                        self.order_analyzer.get_fallback_metrics() or {}
                    )
                except Exception:
                    analyzer_fallback_metrics = {}

            # Validate the extracted order date against expected board date
            date_validation = self._validate_order_date(
                analysis_result.order_date, expected_board_date
            )

            # Convert CaseInfo dataclasses to plain dicts for Firestore
            cases_as_dicts = []
            if analysis_result.cases:
                for case_obj in analysis_result.cases:
                    try:
                        case_dict = (
                            asdict(case_obj)
                            if hasattr(case_obj, "__dataclass_fields__")
                            else case_obj
                        )
                        cases_as_dicts.append(case_dict)
                    except Exception as e:
                        logger.warning(f"Could not convert case object to dict: {e}")
                        continue

            # Find the data for THIS specific case from the cases array
            # Match by case_type, case_number, case_year
            this_case_data = None
            additional_cases = []

            # Parse the case_ref to get case details (e.g., "WP/12345/2025" → type="WP", number=12345, year=2025)
            case_parts = self._parse_case_reference(case_ref)
            if case_parts:
                for case_dict in cases_as_dicts:
                    if (
                        case_dict.get("case_type") == case_parts[0]
                        and case_dict.get("case_number") == case_parts[1]
                        and case_dict.get("case_year") == case_parts[2]
                    ):
                        this_case_data = case_dict
                    else:
                        additional_cases.append(case_dict)

            # If no match found, use first case or empty dict
            if not this_case_data and cases_as_dicts:
                this_case_data = cases_as_dicts[0]
                additional_cases = cases_as_dicts[1:] if len(cases_as_dicts) > 1 else []
            elif not this_case_data:
                this_case_data = {
                    "petitioner": "",
                    "respondent": "",
                    "government_pleader": [],
                }

            # Build case-specific order analysis payload.
            order_analysis = {
                "order_category": analysis_result.order_category,
                "order_category_confidence": analysis_result.category_confidence,
                "order_date": analysis_result.order_date,
                "order_petitioner": this_case_data.get("petitioner", ""),
                "order_respondent": this_case_data.get("respondent", ""),
                "government_pleader": this_case_data.get("government_pleader", []),
                "order_date_validation": date_validation,
                "order_link": order_link,
                "order_analysis_timestamp": datetime.now().isoformat(),
                "order_last_updated": datetime.now().isoformat(),
                "order_analysis_metadata": analysis_metadata,
                "order_analyzer_fallback_metrics": analyzer_fallback_metrics,
                "order_status": "analysed",
                "order_status_updated_at": datetime.now().isoformat(),
            }

            # Do not persist an order whose date clearly does not match the board
            # date — storing it would create a duplicate entry (wrong order_date
            # format from PDF vs ISO from API) or silently link the wrong order to
            # the wrong hearing.  When the date is unknown (order_date=None) we
            # accept the entry because the PDF may lack a date field entirely.
            if not date_validation.get("valid") and order_analysis.get("order_date"):
                logger.warning(
                    "_analyze_order_with_date_validation: date mismatch for "
                    "case_ref=%s (extracted=%s expected=%s) — skipping persist",
                    case_ref,
                    order_analysis.get("order_date"),
                    expected_board_date,
                )
                return {
                    "success": False,
                    "error": "date_mismatch",
                    "data": {
                        "order_date": order_analysis.get("order_date"),
                        "expected_board_date": expected_board_date,
                    },
                }

            try:
                self.case_store.transition_lifecycle(
                    case_ref,
                    "analysis_in_progress",
                    metadata={"source": "auto_order_manager", "case_id": case_id},
                    event_type="analysis_started",
                )
                self.case_store.append_case_order(
                    case_ref,
                    {
                        "order_link": order_analysis.get("order_link"),
                        "order_status": order_analysis.get("order_status"),
                        "order_category": order_analysis.get("order_category"),
                        "order_date": order_analysis.get("order_date"),
                        "order_category_confidence": order_analysis.get(
                            "order_category_confidence"
                        ),
                        "petitioner": order_analysis.get("order_petitioner"),
                        "respondent": order_analysis.get("order_respondent"),
                        "government_pleader": order_analysis.get(
                            "government_pleader", []
                        ),
                        "order_analysis_timestamp": order_analysis.get(
                            "order_analysis_timestamp"
                        ),
                        "order_analysis_metadata": order_analysis.get(
                            "order_analysis_metadata", {}
                        ),
                        "order_date_validation": order_analysis.get(
                            "order_date_validation", {}
                        ),
                    },
                )
                self.case_store.transition_lifecycle(
                    case_ref,
                    "analysed",
                    metadata={
                        "source": "auto_order_manager",
                        "case_id": case_id,
                        "order_category": order_analysis.get("order_category"),
                    },
                    event_type="analysis_succeeded",
                )
            except Exception as case_sync_error:
                logger.warning(
                    f"Failed to sync normalized order history for {case_ref}: {case_sync_error}"
                )

            # Also persist for additional cases extracted from the same order.
            if additional_cases:
                logger.info(
                    f"Found {len(additional_cases)} additional cases in order for {case_ref}, syncing case-details"
                )
                for add_case in additional_cases:
                    try:
                        add_case_ref = f"{add_case.get('case_type')}/{add_case.get('case_number')}/{add_case.get('case_year')}"
                        self.case_store.append_case_order(
                            add_case_ref,
                            {
                                "order_link": order_link,
                                "order_status": "analysed",
                                "order_category": analysis_result.order_category,
                                "order_date": analysis_result.order_date,
                                "order_category_confidence": analysis_result.category_confidence,
                                "petitioner": add_case.get("petitioner", ""),
                                "respondent": add_case.get("respondent", ""),
                                "government_pleader": add_case.get(
                                    "government_pleader", []
                                ),
                                "order_analysis_timestamp": datetime.now().isoformat(),
                                "order_analysis_metadata": analysis_metadata,
                                "order_date_validation": date_validation,
                            },
                        )
                        logger.info(
                            f"  ✅ Synced order analysis for additional case: {add_case_ref}"
                        )
                    except Exception as e:
                        logger.warning(
                            f"  ❌ Failed to sync additional case {add_case.get('case_type')}/{add_case.get('case_number')}: {e}"
                        )

            # Prepare full analysis data for response
            full_analysis_data = {
                "case_id": case_id,
                "case_ref": case_ref,
                **order_analysis,
                "additional_cases_updated": len(additional_cases),
            }

            return {
                "success": True,
                "data": full_analysis_data,
                "cases": cases_as_dicts,
            }

        except Exception as e:
            logger.error(f"Error analyzing order for case {case_id}: {e}")
            try:
                self._record_case_order_status(
                    case_ref, "order_analysis_failed", str(e)
                )
            except Exception as update_error:
                logger.error(
                    f"Failed to update order status for {case_id}: {update_error}"
                )
            return {"success": False, "error": str(e)}

    def _validate_order_date(
        self,
        extracted_order_date: Optional[Any],
        expected_board_date: Optional[Any],
    ) -> Dict[str, Any]:
        """
        Validate extracted order date against expected board date
        Returns validation result with details
        """
        try:
            if not extracted_order_date or not expected_board_date:
                return {
                    "valid": False,
                    "reason": "Missing date information",
                    "extracted_date": extracted_order_date,
                    "expected_date": expected_board_date,
                }

            # Parse dates for comparison
            try:
                if isinstance(expected_board_date, str):
                    expected_date = datetime.strptime(
                        expected_board_date, "%Y-%m-%d"
                    ).date()
                elif isinstance(expected_board_date, datetime):
                    expected_date = expected_board_date.date()
                else:
                    expected_date = expected_board_date

                # Try to parse extracted order date
                if isinstance(extracted_order_date, str):
                    # Try different date formats
                    for fmt in [
                        "%Y-%m-%d",
                        "%d-%m-%Y",
                        "%d/%m/%Y",
                        "%Y-%m-%dT%H:%M:%S",
                    ]:
                        try:
                            extracted_date = datetime.strptime(
                                extracted_order_date, fmt
                            ).date()
                            break
                        except ValueError:
                            continue
                    else:
                        return {
                            "valid": False,
                            "reason": "Could not parse extracted date format",
                            "extracted_date": extracted_order_date,
                            "expected_date": expected_board_date,
                        }
                else:
                    extracted_date = extracted_order_date

                # Compare dates
                date_match = extracted_date == expected_date

                return {
                    "valid": date_match,
                    "reason": "Date matches" if date_match else "Date mismatch",
                    "extracted_date": extracted_date.isoformat(),
                    "expected_date": expected_date.isoformat(),
                    "date_difference_days": (
                        (extracted_date - expected_date).days
                        if date_match is False
                        else 0
                    ),
                }

            except Exception as e:
                return {
                    "valid": False,
                    "reason": f"Date parsing error: {str(e)}",
                    "extracted_date": extracted_order_date,
                    "expected_date": expected_board_date,
                }

        except Exception as e:
            logger.error(f"Error validating order date: {e}")
            return {
                "valid": False,
                "reason": f"Validation error: {str(e)}",
                "extracted_date": extracted_order_date,
                "expected_date": expected_board_date,
            }

    def _create_search_index_entry(
        self, case_id: str, case_data: Dict, analysis_data: Dict
    ) -> None:
        """Create optimized search index entry using board data + case analysis."""
        try:
            petitioner = analysis_data.get("order_petitioner", "")
            respondent = analysis_data.get("order_respondent", "")
            agp_names = analysis_data.get("government_pleader", [])
            key_phrases = analysis_data.get("order_key_phrases", [])

            # Convert to strings (now simple since they're already strings, not arrays)
            petitioner_text = str(petitioner).strip() if petitioner else ""
            respondent_text = str(respondent).strip() if respondent else ""

            agp_name_strings = [
                str(name) if not isinstance(name, str) else name for name in agp_names
            ]

            # Create search-optimized document
            search_doc = {
                "case_id": case_id,
                "case_ref": f"{case_data.get('case_type', '')}/{case_data.get('case_no', '')}/{case_data.get('case_year', '')}",
                "case_type": case_data.get("case_type"),
                "case_number": case_data.get("case_no"),
                "case_year": case_data.get("case_year"),
                "board_date": case_data.get("board_date"),
                # Board data
                "petitioner_lawyer": case_data.get("petitioner_lawyer"),
                "respondent_lawyer": case_data.get("respondent_lawyer"),
                "serial_number": case_data.get("serial_number"),
                # Parties information from order analysis (now flattened strings, not arrays)
                "petitioner": petitioner_text,  # Single string for UI display
                "respondent": respondent_text,  # Single string for UI display
                "petitioner_text": petitioner_text.lower(),  # For text search
                "respondent_text": respondent_text.lower(),  # For text search
                # Order information with consistent field names
                "order_category": analysis_data.get("order_category"),
                "order_date": analysis_data.get("order_date"),
                "order_category_confidence": analysis_data.get(
                    "order_category_confidence"
                ),
                "agp_names": agp_name_strings,
                "key_phrases": key_phrases if isinstance(key_phrases, list) else [],
                # Date validation status
                "date_validation_valid": analysis_data.get(
                    "order_date_validation", {}
                ).get("valid", False),
                # Links
                "order_link": analysis_data.get("order_link"),
                # Analysis metadata
                "order_analysis_timestamp": analysis_data.get(
                    "order_analysis_timestamp"
                ),
                # Timestamps
                "created_at": datetime.now().isoformat(),
                "last_updated": datetime.now().isoformat(),
            }

            # Save to search index
            self.db.collection(self.search_index_collection).document(case_id).set(
                search_doc
            )

        except Exception as e:
            logger.error(f"Error creating search index for case {case_id}: {e}")

    def _create_order_link(self, case_id: str, order_info: Dict) -> None:
        """Create order link in case-details for the board case."""
        try:
            board_doc = (
                self.db.collection(self.boards_collection).document(case_id).get()
            )
            if not board_doc.exists:
                logger.error(f"Board document not found for {case_id}")
                return

            board_data = board_doc.to_dict() or {}
            case_ref = self.case_store.build_case_ref(
                board_data.get("case_type"),
                board_data.get("case_no"),
                board_data.get("case_year"),
            )

            self.case_store.append_case_order(
                case_ref,
                {
                    "order_status": "linked",
                    "order_link": order_info.get("order_link"),
                    "order_filename": order_info.get("filename"),
                    "order_source": order_info.get("source", "auto"),
                    "order_fetch_date": datetime.now().isoformat(),
                },
            )
            self.case_store.transition_lifecycle(
                case_ref,
                "fetch_succeeded",
                metadata={
                    "source": "auto_order_manager",
                    "case_id": case_id,
                    "order_link": order_info.get("order_link"),
                },
                event_type="fetch_succeeded",
            )
            logger.info(f"Order link created in case-details for {case_ref}")

        except Exception as e:
            logger.error(f"Error creating order link for case {case_id}: {e}")

    def _link_order_to_additional_cases(
        self,
        primary_case_id: str,
        primary_case_ref: str,
        analysis_data: Dict[str, Any],
        order_info: Dict[str, Any],
        board_date: str,
    ) -> List[str]:
        """
        Link the same order to additional cases found in the order document
        Handles multi-case orders where multiple cases are clubbed together

        Returns: List of case references that were successfully linked
        """
        linked_cases: List[str] = []

        try:
            # Extract case numbers from analysis
            order_cases = analysis_data.get("order_cases", [])

            if not order_cases or len(order_cases) <= 1:
                # No additional cases to link
                return linked_cases

            logger.info(
                f"Found {len(order_cases)} cases in order for {primary_case_ref}, attempting multi-case linking"
            )

            # Process each case found in the order
            for case_info in order_cases:
                try:
                    # Extract case details from simplified structure
                    case_type = case_info.get("case_type")
                    case_number = case_info.get("case_number")
                    case_year = case_info.get("case_year")

                    # Skip if missing required fields
                    if not case_type or not case_number or not case_year:
                        logger.warning(f"Missing required case fields in {case_info}")
                        continue

                    # Build case reference in standard format
                    case_ref = f"{case_type}/{case_number}/{case_year}"

                    # Skip if this is the primary case we already processed
                    if case_ref == primary_case_ref:
                        continue

                    # Find the case_id for this case reference in daily-boards
                    matching_case_id = self._find_case_id_by_reference(
                        case_ref, board_date
                    )

                    if not matching_case_id:
                        logger.info(
                            f"No matching case found in database for {case_ref} on date {board_date}"
                        )
                        continue

                    # Check if this case already has an order linked
                    existing_order = self._get_case_order_context(case_ref).get(
                        "order_status", "not_linked"
                    )
                    if existing_order in {"linked", "analysed", "manually_uploaded"}:
                        logger.info(
                            f"Case {case_ref} already has an order linked, skipping"
                        )
                        continue

                    # Create order link for this additional case
                    self._create_order_link(matching_case_id, order_info)

                    # Create case-specific analysis data with this case's party names
                    case_specific_analysis = self._create_case_specific_analysis(
                        analysis_data, case_info, order_info.get("order_link")
                    )

                    self.case_store.append_case_order(
                        case_ref,
                        {
                            "order_link": case_specific_analysis.get("order_link"),
                            "order_status": "analysed",
                            "order_category": case_specific_analysis.get(
                                "order_category"
                            ),
                            "order_date": case_specific_analysis.get("order_date"),
                            "order_category_confidence": case_specific_analysis.get(
                                "order_category_confidence"
                            ),
                            "order_analysis_timestamp": case_specific_analysis.get(
                                "order_analysis_timestamp"
                            ),
                            "order_date_validation": case_specific_analysis.get(
                                "order_date_validation", {}
                            ),
                        },
                    )

                    # Create search index for this case
                    case_data_for_search = (
                        self.db.collection(self.boards_collection)
                        .document(matching_case_id)
                        .get()
                        .to_dict()
                    )
                    self._create_search_index_entry(
                        matching_case_id, case_data_for_search, case_specific_analysis
                    )

                    linked_cases.append(case_ref)
                    logger.info(
                        f"Successfully linked order to additional case: {case_ref}"
                    )

                except Exception as e:
                    logger.error(f"Error linking order to case {case_number}: {e}")
                    continue

        except Exception as e:
            logger.error(f"Error in multi-case linking for {primary_case_ref}: {e}")

        return linked_cases

    def _find_case_id_by_reference(
        self, case_ref: str, board_date: str
    ) -> Optional[str]:
        """
        Find case_id in daily-boards collection by case reference and board date
        """
        try:
            # Parse case reference
            parts = self._parse_case_reference(case_ref)
            if not parts:
                return None

            case_type, case_no, case_year = parts

            # Query daily-boards collection
            query = (
                self.db.collection(self.boards_collection)
                .where("case_type", "==", case_type)
                .where("case_no", "==", case_no)
                .where("case_year", "==", case_year)
                .where("board_date", "==", board_date)
                .limit(1)
            )

            results = query.get()

            if results:
                return results[0].id

            return None
        except Exception as e:
            logger.error(f"Error finding case_id for {case_ref}: {e}")
            return None

    def _create_case_specific_analysis(
        self,
        analysis_data: Dict[str, Any],
        case_info: Dict[str, Any],
        order_link: Optional[str],
    ) -> Dict[str, Any]:
        """
        Create case-specific analysis data with the specific details for this case
        Uses simplified structure with case_type, case_number, case_year, petitioner, respondent, government_pleader
        """
        # Create the analysis data structure with case-specific data from simplified structure
        case_analysis = {
            # Core order information
            "order_category": analysis_data.get("order_category"),
            "order_category_confidence": analysis_data.get("order_category_confidence"),
            "order_date": analysis_data.get("order_date"),
            "order_petitioner": case_info.get("petitioner", ""),
            "order_respondent": case_info.get("respondent", ""),
            "government_pleader": case_info.get("government_pleader", []),
            # Date validation
            "order_date_validation": analysis_data.get("order_date_validation", {}),
            # Order link
            "order_link": order_link,
            "order_status": "analysed",
            # Analysis metadata
            "order_analysis_timestamp": datetime.now().isoformat(),
            "order_last_updated": datetime.now().isoformat(),
        }

        return case_analysis

    def _parse_case_reference(self, case_ref: str) -> Optional[Tuple[str, int, int]]:
        """Parse case reference like 'WP/294/2025' or 'IA(ST)/123/2025' into components (type, number, year)"""
        try:
            pattern = r"([A-Z]+(?:\([A-Z]+\))?)/(\d+)/(\d+)"
            match = re.match(pattern, case_ref)
            if match:
                case_type = match.group(1)
                case_no = int(match.group(2))
                case_year = int(match.group(3))
                return (case_type, case_no, case_year)
            return None
        except (ValueError, AttributeError) as e:
            logger.warning(f"Error parsing case reference {case_ref}: {e}")
            return None

    def search_orders(self, search_params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Search orders with optimized query

        Args:
            search_params: Dictionary with search criteria

        Returns:
            Search results with petitioner, respondent, and order links
        """
        try:
            query = self.db.collection(self.search_index_collection)

            # Apply filters
            if search_params.get("case_type"):
                query = query.where("case_type", "==", search_params["case_type"])

            if search_params.get("case_year"):
                query = query.where("case_year", "==", search_params["case_year"])

            if search_params.get("order_category"):
                query = query.where(
                    "order_category", "==", search_params["order_category"]
                )

            # Text search (basic implementation)
            results = []
            for doc in query.limit(search_params.get("limit", 100)).stream():
                data = doc.to_dict()

                # Apply text filters
                if search_params.get("petitioner_search"):
                    search_text = search_params["petitioner_search"].lower()
                    if search_text not in data.get("petitioner_text", ""):
                        continue

                if search_params.get("respondent_search"):
                    search_text = search_params["respondent_search"].lower()
                    if search_text not in data.get("respondent_text", ""):
                        continue

                results.append(data)

            return {"success": True, "results": results, "total_found": len(results)}

        except Exception as e:
            logger.error(f"Error searching orders: {e}")
            return {"success": False, "error": str(e)}

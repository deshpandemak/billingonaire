import logging
import os
from datetime import date, datetime
from typing import Any, Dict, List, Optional
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
            # Propagate the GCS URL back to daily-boards so the PDF proxy reads
            # the permanent link directly without falling back to case-details.
            # Without this, the proxy keeps reading the expired court URL from
            # daily-boards and re-queueing re-fetches indefinitely.
            if order_link and order_link.startswith("https://storage.googleapis.com"):
                try:
                    self.db.collection("daily-boards").document(case_id).update(
                        {
                            "order_link": order_link,
                            "order_category": order_analysis["order_category"],
                        }
                    )
                except Exception as _db_err:
                    logger.warning(
                        "_analyze_order_with_api_metadata: daily-boards update "
                        "failed for case_id=%s: %s",
                        case_id,
                        _db_err,
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

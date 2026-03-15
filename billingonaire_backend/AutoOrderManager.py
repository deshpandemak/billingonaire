import base64
import logging
import os
import re
from dataclasses import asdict
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import requests
from firebase_admin import firestore

from CourtScraper import BombayHighCourtScraper

try:
    from case_data_store import CaseDataStore
except ImportError:
    from .case_data_store import CaseDataStore
from order_analyzer import OrderDocumentAnalyzer


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

        # Case type mappings for court lookup
        self.casetype_dict = {
            "WP": "2001",
            "IA": "2069",
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
        self, case_filters: Dict = None, limit: int = 50, max_sequences: int = None
    ) -> Dict:
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
                return {
                    "success": True,
                    "message": "No cases found matching criteria",
                    "processed": 0,
                }

            results = {
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
                    logging.error(error_msg)
                    results["errors"].append(error_msg)
                    results["failed_downloads"] += 1

            return {"success": True, "results": results}

        except Exception as e:
            logging.error(f"Error in get_orders_for_cases: {e}")
            return {"success": False, "error": str(e)}

    def bulk_process_orders(self, case_ids: List[str], max_sequences: int = 50) -> Dict:
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

            results = {
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
                    logging.error(error_msg)
                    results["errors"].append(error_msg)
                    results["failed"] += 1

            results["success"] = True
            return results

        except Exception as e:
            logging.error(f"Error in bulk_process_orders: {e}")
            return {"success": False, "error": str(e)}

    def _get_filtered_matters(
        self, filters: Dict = None, limit: int = 50
    ) -> List[Dict]:
        """Get cases that need order processing based on filters"""
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
            cases = []

            for doc in query.stream():
                case_data = doc.to_dict()
                case_data["id"] = doc.id

                # Check if case needs order processing - look for order analysis completion
                order_analysis_completed = case_data.get(
                    "order_analysis_completed", False
                )
                order_status = case_data.get("order_status", "not_linked")

                # Include cases that:
                # 1. Don't have order analysis completed, OR
                # 2. Have failed order status
                if not order_analysis_completed or order_status in [
                    "not_linked",
                    "order_failed",
                    "order_analysis_failed",
                ]:
                    # Format case reference
                    case_ref = f"{case_data.get('case_type', '')}/{case_data.get('case_no', '')}/{case_data.get('case_year', '')}"
                    case_data["case_ref"] = case_ref
                    cases.append(case_data)

                    if len(cases) >= limit:
                        break

            return cases

        except Exception as e:
            logging.error(f"Error getting filtered matters: {e}")
            return []

    def _process_single_case(self, case_data: Dict, max_sequences: int = None) -> Dict:
        """Process a single case with retry logic - try up to N sequence numbers

        Args:
            case_data: Dictionary containing case information
            max_sequences: Maximum number of sequence numbers to try (default: from env or 50)
        """
        case_id = case_data["id"]
        case_ref = case_data["case_ref"]
        order_status = case_data.get("order_status", "not_linked")

        # Check if case has existing order link
        has_existing_order_link = case_data.get("order_link") is not None

        result = {
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

        # If case has status "linked", skip download and analyze existing order
        if order_status == "linked" and has_existing_order_link:
            logging.info(
                f"📋 {case_ref} - Status is 'linked', analyzing existing order"
            )
            try:
                return self._analyze_existing_order(case_data, result, max_sequences)
            except Exception as e:
                logging.error(f"Failed to analyze existing order for {case_ref}: {e}")
                result["error"] = f"Failed to analyze existing order: {str(e)}"
                return result

        # Configurable max retries - use parameter, env var, or default to 50
        if max_sequences is not None and max_sequences > 0:
            MAX_RETRIES = max_sequences
        else:
            MAX_RETRIES = int(os.getenv("ORDER_MAX_SEQUENCE_RETRIES", "50"))
        logging.info(
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
                    logging.info(
                        f"{case_ref} - trying sequence {sequence_num}/{MAX_RETRIES}"
                    )

                attempt_log = {
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
                        attempt_log["message"] = (
                            f"Order date {date_validation.get('extracted_date')} does not match board date {date_validation.get('expected_date')}"
                        )
                        result["retry_attempts"].append(attempt_log)
                        logging.info(
                            f"Case {case_ref} seq {sequence_num}: {attempt_log['message']}"
                        )
                        continue

                    # SUCCESS! Date matches - mark success and stop retrying
                    attempt_log["status"] = "success"
                    attempt_log["message"] = (
                        f"Order found with matching date {date_validation.get('extracted_date')}"
                    )
                    result["retry_attempts"].append(attempt_log)
                    result["download_success"] = True
                    result["order_link"] = order_info.get("order_link")

                    logging.info(
                        f"✅ Case {case_ref} - SUCCESS at sequence {sequence_num}/{MAX_RETRIES}"
                    )

                    # Step 4: Create order link first (since download succeeded)
                    try:
                        self._create_order_link(case_id, order_info)
                    except Exception as link_error:
                        logging.error(
                            f"Failed to create order link for {case_ref}: {link_error}"
                        )
                        result["error"] = (
                            f"Order downloaded but link creation failed: {str(link_error)}"
                        )
                        result["download_success"] = True
                        result["order_link"] = order_info.get("order_link")
                        return result

                    # Step 5: Perform analysis (after order link is created)
                    try:
                        analysis_result = self._analyze_order_with_date_validation(
                            case_id,
                            case_ref,
                            order_info["pdf_content"],
                            case_data.get("board_date"),
                            order_info.get("order_link"),
                        )

                        if not analysis_result.get("success"):
                            # Analysis failed but order download succeeded
                            # Keep the order link and mark status as order_analysis_failed
                            logging.warning(
                                f"Analysis failed for {case_ref} seq {sequence_num}: {analysis_result.get('error')}"
                            )
                            attempt_log["status"] = "analysis_failed"
                            attempt_log["message"] = (
                                f"Analysis failed: {analysis_result.get('error')}"
                            )
                            result["retry_attempts"].append(attempt_log)
                            result["error"] = (
                                f"Order downloaded but analysis failed: {analysis_result.get('error')}"
                            )

                            # Update status to order_analysis_failed
                            try:
                                self.db.collection(self.boards_collection).document(
                                    case_id
                                ).update(
                                    {
                                        "order_status": "order_analysis_failed",
                                        "order_status_updated_at": datetime.now().isoformat(),
                                        "order_failure_reason": result["error"],
                                    }
                                )
                            except Exception as status_error:
                                logging.error(
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
                            logging.error(
                                f"Failed to create search index for {case_ref}: {index_error}"
                            )
                            # Not critical - we have the order and analysis

                        # Step 7: Link order to additional cases found in the order (multi-case linking)
                        try:
                            linked_cases = self._link_order_to_additional_cases(
                                case_id,
                                case_ref,
                                analysis_result["data"],
                                order_info,
                                case_data.get("board_date"),
                            )
                            if linked_cases:
                                result["additional_cases_linked"] = linked_cases
                                logging.info(
                                    f"Linked order to {len(linked_cases)} additional cases: {linked_cases}"
                                )
                        except Exception as multi_link_error:
                            logging.warning(
                                f"Failed to link order to additional cases for {case_ref}: {multi_link_error}"
                            )
                            # Not critical - primary case is already linked

                        # Success! Stop retrying
                        return result

                    except Exception as analysis_error:
                        # Analysis threw an exception but order download succeeded
                        # Keep the order link and mark status as order_analysis_failed
                        logging.warning(
                            f"Analysis exception for {case_ref} seq {sequence_num}: {analysis_error}"
                        )
                        attempt_log["status"] = "analysis_exception"
                        attempt_log["message"] = str(analysis_error)
                        result["retry_attempts"].append(attempt_log)
                        result["error"] = (
                            f"Order downloaded but analysis threw exception: {str(analysis_error)}"
                        )

                        # Update status to order_analysis_failed
                        try:
                            self.db.collection(self.boards_collection).document(
                                case_id
                            ).update(
                                {
                                    "order_status": "order_analysis_failed",
                                    "order_status_updated_at": datetime.now().isoformat(),
                                    "order_failure_reason": result["error"],
                                }
                            )
                        except Exception as status_error:
                            logging.error(
                                f"Failed to update order_analysis_failed status: {status_error}"
                            )

                        # Return with download success but analysis failure
                        return result

                except Exception as e:
                    # Log this attempt's error and continue
                    attempt_log["status"] = "error"
                    attempt_log["message"] = str(e)
                    result["retry_attempts"].append(attempt_log)
                    logging.warning(f"Case {case_ref} seq {sequence_num} error: {e}")
                    continue

            # If we get here, all attempts failed - provide detailed error
            error_parts = [f"No matching order found after {MAX_RETRIES} attempts."]
            if download_failures > 0:
                error_parts.append(f"{download_failures} downloads failed.")
            if date_mismatches > 0:
                error_parts.append(f"{date_mismatches} orders had date mismatches.")
            result["error"] = " ".join(error_parts)
            logging.warning(
                f"❌ Case {case_ref} - FAILED after {MAX_RETRIES} sequences: {result['error']}"
            )

            # Set order_failed status after all attempts exhausted
            try:
                self.db.collection(self.boards_collection).document(case_id).update(
                    {
                        "order_status": "order_failed",
                        "order_status_updated_at": datetime.now().isoformat(),
                        "order_failure_reason": result["error"],
                    }
                )
            except Exception as status_error:
                logging.error(
                    f"Failed to update order_failed status for {case_id}: {status_error}"
                )

        except Exception as e:
            result["error"] = str(e)
            logging.error(f"Error processing case {case_ref}: {e}")

        return result

    def _analyze_existing_order(
        self, case_data: Dict, result: Dict, max_sequences: int = None
    ) -> Dict:
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
            logging.info(f"Attempting to re-download existing order from {order_link}")

            # Re-download the PDF from the stored link
            response = requests.get(order_link, timeout=30)

            # Validate response status
            if response.status_code != 200:
                logging.warning(
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
                logging.warning(
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
                logging.warning(
                    f"Order link returned empty/small content for {case_ref}, falling back to fresh download"
                )
                return self._fallback_to_fresh_download(
                    case_data,
                    result,
                    "Stored order link returned empty or invalid PDF",
                    max_sequences,
                )

            logging.info(
                f"Successfully re-downloaded order for {case_ref}, size: {len(pdf_content)} bytes"
            )

            # Mark download as successful
            result["download_success"] = True
            result["order_link"] = order_link

            # Analyze the order
            analysis_result = self._analyze_order_with_date_validation(
                case_id, case_ref, pdf_content, case_data.get("board_date"), order_link
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
                    logging.error(
                        f"Failed to create search index for {case_ref}: {index_error}"
                    )

                # Link order to additional cases found in the order (multi-case linking)
                try:
                    linked_cases = self._link_order_to_additional_cases(
                        case_id,
                        case_ref,
                        analysis_result["data"],
                        {"order_link": order_link, "pdf_content": pdf_content},
                        case_data.get("board_date"),
                    )
                    if linked_cases:
                        result["additional_cases_linked"] = linked_cases
                        logging.info(
                            f"Linked order to {len(linked_cases)} additional cases: {linked_cases}"
                        )
                except Exception as multi_link_error:
                    logging.warning(
                        f"Failed to link order to additional cases for {case_ref}: {multi_link_error}"
                    )

                logging.info(f"✅ Successfully analyzed existing order for {case_ref}")
            else:
                result["error"] = f"Analysis failed: {analysis_result.get('error')}"
                logging.error(
                    f"Analysis failed for existing order {case_ref}: {result['error']}"
                )

                # Update status to order_analysis_failed
                try:
                    self.db.collection(self.boards_collection).document(case_id).update(
                        {
                            "order_status": "order_analysis_failed",
                            "order_status_updated_at": datetime.now().isoformat(),
                            "order_failure_reason": result["error"],
                        }
                    )
                except Exception as status_error:
                    logging.error(
                        f"Failed to update order_analysis_failed status: {status_error}"
                    )

            return result

        except Exception as e:
            error_msg = f"Failed to analyze existing order: {str(e)}"
            result["error"] = error_msg
            logging.error(f"Error analyzing existing order for {case_ref}: {e}")

            # Update status to order_analysis_failed
            try:
                self.db.collection(self.boards_collection).document(case_id).update(
                    {
                        "order_status": "order_analysis_failed",
                        "order_status_updated_at": datetime.now().isoformat(),
                        "order_failure_reason": error_msg,
                    }
                )
            except Exception as status_error:
                logging.error(
                    f"Failed to update order_analysis_failed status: {status_error}"
                )

            return result

    def _fallback_to_fresh_download(
        self, case_data: Dict, result: Dict, reason: str, max_sequences: int = None
    ) -> Dict:
        """Fallback to fresh download when stored order link is invalid

        Args:
            case_data: Dictionary containing case information
            result: Existing result dictionary
            reason: Reason for fallback
            max_sequences: Maximum number of sequence numbers to try (default: from env or 50)
        """
        case_id = case_data["id"]
        case_ref = case_data["case_ref"]

        logging.info(f"Initiating fresh download for {case_ref} due to: {reason}")

        try:
            # Reset status to not_linked to trigger fresh download
            self.db.collection(self.boards_collection).document(case_id).update(
                {
                    "order_status": "not_linked",
                    "order_status_updated_at": datetime.now().isoformat(),
                    "order_link_invalidation_reason": reason,
                }
            )

            # Remove linked status from case_data to prevent infinite loop
            case_data_fresh = case_data.copy()
            case_data_fresh["order_status"] = "not_linked"
            case_data_fresh.pop("order_link", None)

            # Now process with normal download flow (will try up to N sequence numbers)
            # Use parameter, env var, or default to 50
            if max_sequences is not None and max_sequences > 0:
                MAX_RETRIES = max_sequences
            else:
                MAX_RETRIES = int(os.getenv("ORDER_MAX_SEQUENCE_RETRIES", "50"))

            logging.info(
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
                    logging.info(
                        f"Fresh download {case_ref}: trying sequence {sequence_num}/{MAX_RETRIES}"
                    )

                try:
                    download_result = self._download_order_for_case(
                        case_data_fresh, sequence_num
                    )

                    if download_result.get("success"):
                        order_link = download_result.get("order_link")
                        pdf_content = download_result.get("pdf_content")

                        result["download_success"] = True
                        result["order_link"] = order_link

                        # Analyze the downloaded order
                        analysis_result = self._analyze_order_with_date_validation(
                            case_id,
                            case_ref,
                            pdf_content,
                            case_data.get("board_date"),
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
                                logging.error(
                                    f"Failed to create search index: {index_error}"
                                )

                            # Link to additional cases
                            try:
                                linked_cases = self._link_order_to_additional_cases(
                                    case_id,
                                    case_ref,
                                    analysis_result["data"],
                                    download_result,
                                    case_data.get("board_date"),
                                )
                                if linked_cases:
                                    result["additional_cases_linked"] = linked_cases
                            except Exception as multi_link_error:
                                logging.warning(
                                    f"Multi-case linking failed: {multi_link_error}"
                                )

                            logging.info(
                                f"✅ Fresh download and analysis succeeded for {case_ref}"
                            )
                            return result
                        else:
                            result["error"] = analysis_result.get("error")
                            logging.error(
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
                    logging.warning(f"Fresh download seq {sequence_num} error: {e}")
                    download_failures += 1
                    continue

            # All attempts failed
            error_msg = f"Fresh download failed after {MAX_RETRIES} attempts. {download_failures} downloads failed, {date_mismatches} date mismatches."
            result["error"] = error_msg

            # Update status to order_failed
            self.db.collection(self.boards_collection).document(case_id).update(
                {
                    "order_status": "order_failed",
                    "order_status_updated_at": datetime.now().isoformat(),
                    "order_failure_reason": error_msg,
                }
            )

            return result

        except Exception as e:
            error_msg = f"Fallback fresh download failed: {str(e)}"
            result["error"] = error_msg
            logging.error(f"Error in fallback fresh download for {case_ref}: {e}")

            # Update to order_analysis_failed
            try:
                self.db.collection(self.boards_collection).document(case_id).update(
                    {
                        "order_status": "order_analysis_failed",
                        "order_status_updated_at": datetime.now().isoformat(),
                        "order_failure_reason": error_msg,
                    }
                )
            except Exception as status_error:
                logging.error(f"Failed to update status: {status_error}")

            return result

    def _download_order_for_case(
        self, case_data: Dict, sequence_number: int = 0
    ) -> Dict:
        """
        Download order for a specific case using the Bombay High Court API

        Args:
            case_data: Case data dictionary
            sequence_number: Specific sequence number to try (0-49)
        """
        case_ref = case_data.get("case_ref", "UNKNOWN")
        logging.warning(
            f"🔵 _download_order_for_case ENTERED for {case_ref}, seq={sequence_number}"
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
            logging.warning(f"🔵 After parse: case_parts={case_parts}")
            if not case_parts:
                logging.warning("🔵 EARLY RETURN: Invalid case reference format")
                return {"success": False, "error": "Invalid case reference format"}

            case_type, case_number, year = case_parts
            logging.warning(
                f"🔵 Before zfill: case_number={case_number}, type={type(case_number)}"
            )

            # Format case number with leading zeros
            case_number = str(case_number).zfill(7)
            logging.warning(f"🔵 After zfill: case_number={case_number}")

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
                structured_result = self._download_order_via_scraper(
                    case_ref=case_ref,
                    board_date=board_date,
                    order_filename=order_filename,
                )
                if structured_result.get("success"):
                    return structured_result
                logging.info(
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
                case_number,
                year,
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

    def _download_order_via_scraper(
        self, case_ref: str, board_date: Optional[str], order_filename: str
    ) -> Dict:
        """Use structured scraper output to fetch exact order URL before brute-force sequence attempts."""
        try:
            response = self.court_scraper.get_case_orders(
                case_ref=case_ref,
                date=board_date,
                bench="mumbai",
            )

            if not isinstance(response, dict):
                return {
                    "success": False,
                    "error": "Structured scraper returned non-dict response",
                }

            if response.get("status") != "found":
                return {
                    "success": False,
                    "error": response.get(
                        "message", "No orders found from structured scraper"
                    ),
                }

            court_orders = response.get("court_orders") or []
            if not court_orders:
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
                return {
                    "success": False,
                    "error": (
                        "Structured scraper provided non-PDF/invalid URL "
                        f"(HTTP {download_response.status_code}, Content-Type {content_type})"
                    ),
                }

            return {
                "success": True,
                "order_link": download_url,
                "pdf_content": pdf_bytes,
                "filename": order_filename,
                "source": "firecrawl_structured",
                "listing_date": order_entry.get("listing_date"),
                "order_description": order_entry.get("order_description"),
            }
        except Exception as e:
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
        # DEBUG: Log function entry
        logging.warning(
            f"🔍 ENTERING _download_pdf_bombay_hc_simple: seq={sequence_number}, case_type={case_type}, case_number={case_number}"
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
                logging.info(
                    f"Sequence {sequence_number}: HTTP {response.status_code}, "
                    f"Content-Type: {content_type}, Size: {len(response.content)} bytes"
                )

                # Check if response is a PDF
                if content_type == "application/pdf":
                    logging.info(
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
                    logging.warning(
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
                logging.error(f"🔴 {error_msg}")
                return {"success": False, "error": error_msg}
            except requests.ConnectionError as e:
                error_msg = f"Connection error for sequence {sequence_number}: {str(e)}"
                logging.error(f"🔴 {error_msg}")
                return {"success": False, "error": error_msg}
            except requests.RequestException as e:
                error_msg = f"Request failed for sequence {sequence_number}: {str(e)}"
                logging.error(f"🔴 {error_msg}")
                return {"success": False, "error": error_msg}

        except Exception as e:
            logging.error(f"Error downloading PDF from Bombay HC: {e}")
            return {"success": False, "error": str(e)}

    def _analyze_order_with_date_validation(
        self,
        case_id: str,
        case_ref: str,
        pdf_content: bytes,
        expected_board_date: str,
        order_link: Optional[str] = None,
    ) -> Dict:
        """
        Analyze the downloaded order using order_analyzer and validate date
        Store analysis results directly in daily-boards collection
        """
        try:
            # Create temporary filename for analysis
            temp_filename = f"{case_ref.replace('/', '-')}.pdf"

            # Analyze using existing order analyzer
            analysis_result = self.order_analyzer.analyze_order_document(
                temp_filename, pdf_content
            )
            analysis_metadata = getattr(analysis_result, "analysis_metadata", {}) or {}
            analyzer_fallback_metrics = {}
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
                        logging.warning(f"Could not convert case object to dict: {e}")
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

            # Create FLATTENED order analysis data (no order_cases array)
            order_analysis = {
                # Order analysis results
                "order_category": analysis_result.order_category,
                "order_category_confidence": analysis_result.category_confidence,
                "order_date": analysis_result.order_date,
                # FLATTENED case data for THIS case only (not an array)
                "order_petitioner": this_case_data.get("petitioner", ""),
                "order_respondent": this_case_data.get("respondent", ""),
                "government_pleader": this_case_data.get("government_pleader", []),
                # Date validation
                "order_date_validation": date_validation,
                # Order link
                "order_link": order_link,
                # Analysis metadata
                "order_analysis_timestamp": datetime.now().isoformat(),
                "order_analysis_completed": True,
                "order_last_updated": datetime.now().isoformat(),
                "order_analysis_metadata": analysis_metadata,
                "order_analyzer_fallback_metrics": analyzer_fallback_metrics,
                # Order status tracking
                "order_status": "analysed",
                "order_status_updated_at": datetime.now().isoformat(),
            }

            # Update the daily-boards document directly with FLATTENED order analysis
            self.db.collection(self.boards_collection).document(case_id).update(
                order_analysis
            )

            try:
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
            except Exception as case_sync_error:
                logging.warning(
                    f"Failed to sync normalized order history for {case_ref}: {case_sync_error}"
                )

            # If there are additional cases in this order, update their daily-boards too
            if additional_cases:
                logging.info(
                    f"Found {len(additional_cases)} additional cases in order for {case_ref}, updating their boards"
                )
                for add_case in additional_cases:
                    try:
                        add_case_ref = f"{add_case.get('case_type')}/{add_case.get('case_number')}/{add_case.get('case_year')}"
                        add_case_id = f"{expected_board_date.replace('-', '')}-{add_case_ref.replace('/', '-')}"

                        # Check if this case exists in daily-boards
                        add_board_doc = (
                            self.db.collection(self.boards_collection)
                            .document(add_case_id)
                            .get()
                        )
                        if add_board_doc.exists:
                            # Update with FLATTENED data for this specific case
                            add_case_order_data = {
                                "order_category": analysis_result.order_category,
                                "order_category_confidence": analysis_result.category_confidence,
                                "order_date": analysis_result.order_date,
                                "order_petitioner": add_case.get("petitioner", ""),
                                "order_respondent": add_case.get("respondent", ""),
                                "government_pleader": add_case.get(
                                    "government_pleader", []
                                ),
                                "order_date_validation": date_validation,
                                "order_link": order_link,
                                "order_analysis_timestamp": datetime.now().isoformat(),
                                "order_analysis_completed": True,
                                "order_last_updated": datetime.now().isoformat(),
                                "order_analysis_metadata": analysis_metadata,
                                "order_analyzer_fallback_metrics": analyzer_fallback_metrics,
                                "order_status": "analysed",
                                "order_status_updated_at": datetime.now().isoformat(),
                            }
                            self.db.collection(self.boards_collection).document(
                                add_case_id
                            ).update(add_case_order_data)
                            try:
                                self.case_store.append_case_order(
                                    add_case_ref,
                                    {
                                        "order_link": add_case_order_data.get(
                                            "order_link"
                                        ),
                                        "order_status": add_case_order_data.get(
                                            "order_status"
                                        ),
                                        "order_category": add_case_order_data.get(
                                            "order_category"
                                        ),
                                        "order_date": add_case_order_data.get(
                                            "order_date"
                                        ),
                                        "order_category_confidence": add_case_order_data.get(
                                            "order_category_confidence"
                                        ),
                                        "petitioner": add_case_order_data.get(
                                            "order_petitioner"
                                        ),
                                        "respondent": add_case_order_data.get(
                                            "order_respondent"
                                        ),
                                        "government_pleader": add_case_order_data.get(
                                            "government_pleader", []
                                        ),
                                        "order_analysis_timestamp": add_case_order_data.get(
                                            "order_analysis_timestamp"
                                        ),
                                        "order_analysis_metadata": add_case_order_data.get(
                                            "order_analysis_metadata", {}
                                        ),
                                        "order_date_validation": add_case_order_data.get(
                                            "order_date_validation", {}
                                        ),
                                    },
                                )
                            except Exception as case_sync_error:
                                logging.warning(
                                    f"  ⚠️  Failed normalized sync for additional case {add_case_ref}: {case_sync_error}"
                                )
                            logging.info(
                                f"  ✅ Updated order analysis for additional case: {add_case_ref}"
                            )
                        else:
                            logging.info(
                                f"  ⏭️  Skipping {add_case_ref} - not found in daily-boards for date {expected_board_date}"
                            )
                    except Exception as e:
                        logging.warning(
                            f"  ❌ Failed to update additional case {add_case.get('case_type')}/{add_case.get('case_number')}: {e}"
                        )

            # Prepare full analysis data for response
            full_analysis_data = {
                "case_id": case_id,
                "case_ref": case_ref,
                **order_analysis,
                "order_cases": cases_as_dicts,
                "additional_cases_updated": len(additional_cases),
            }

            return {"success": True, "data": full_analysis_data}

        except Exception as e:
            logging.error(f"Error analyzing order for case {case_id}: {e}")
            # Set order_analysis_failed status
            try:
                self.db.collection(self.boards_collection).document(case_id).update(
                    {
                        "order_status": "order_analysis_failed",
                        "order_status_updated_at": datetime.now().isoformat(),
                        "order_analysis_error": str(e),
                    }
                )
            except Exception as update_error:
                logging.error(
                    f"Failed to update order status for {case_id}: {update_error}"
                )
            return {"success": False, "error": str(e)}

    def _validate_order_date(
        self, extracted_order_date: str, expected_board_date: str
    ) -> Dict:
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
            logging.error(f"Error validating order date: {e}")
            return {
                "valid": False,
                "reason": f"Validation error: {str(e)}",
                "extracted_date": extracted_order_date,
                "expected_date": expected_board_date,
            }

    def _create_search_index_entry(
        self, case_id: str, case_data: Dict, analysis_data: Dict
    ) -> None:
        """Create optimized search index entry for fast searching from consolidated daily-boards data"""
        try:
            # Get the complete board document with analysis data
            board_doc = (
                self.db.collection(self.boards_collection).document(case_id).get()
            )
            if not board_doc.exists:
                logging.error(f"Board document not found for case {case_id}")
                return

            board_data = board_doc.to_dict()

            # Extract data with consistent field names (now flattened, not arrays)
            petitioner = board_data.get("order_petitioner", "")
            respondent = board_data.get("order_respondent", "")
            agp_names = board_data.get("government_pleader", [])
            key_phrases = board_data.get("order_key_phrases", [])

            # Convert to strings (now simple since they're already strings, not arrays)
            petitioner_text = str(petitioner).strip() if petitioner else ""
            respondent_text = str(respondent).strip() if respondent else ""

            agp_name_strings = [
                str(name) if not isinstance(name, str) else name for name in agp_names
            ]

            # Create search-optimized document
            search_doc = {
                "case_id": case_id,
                "case_ref": f"{board_data.get('case_type', '')}/{board_data.get('case_no', '')}/{board_data.get('case_year', '')}",
                "case_type": board_data.get("case_type"),
                "case_number": board_data.get("case_no"),
                "case_year": board_data.get("case_year"),
                "board_date": board_data.get("board_date"),
                # Board data
                "petitioner_lawyer": board_data.get("petitioner_lawyer"),
                "respondent_lawyer": board_data.get("respondent_lawyer"),
                "serial_number": board_data.get("serial_number"),
                # Parties information from order analysis (now flattened strings, not arrays)
                "petitioner": petitioner_text,  # Single string for UI display
                "respondent": respondent_text,  # Single string for UI display
                "petitioner_text": petitioner_text.lower(),  # For text search
                "respondent_text": respondent_text.lower(),  # For text search
                # Order information with consistent field names
                "order_category": board_data.get("order_category"),
                "order_date": board_data.get("order_date"),
                "order_category_confidence": board_data.get(
                    "order_category_confidence"
                ),
                "agp_names": agp_name_strings,
                "key_phrases": key_phrases if isinstance(key_phrases, list) else [],
                # Date validation status
                "date_validation_valid": board_data.get(
                    "order_date_validation", {}
                ).get("valid", False),
                # Links
                "order_link": board_data.get("order_link"),
                # Analysis metadata
                "order_analysis_completed": board_data.get(
                    "order_analysis_completed", False
                ),
                "order_analysis_timestamp": board_data.get("order_analysis_timestamp"),
                # Timestamps
                "created_at": datetime.now().isoformat(),
                "last_updated": datetime.now().isoformat(),
            }

            # Save to search index
            self.db.collection(self.search_index_collection).document(case_id).set(
                search_doc
            )

        except Exception as e:
            logging.error(f"Error creating search index for case {case_id}: {e}")

    def _create_order_link(self, case_id: str, order_info: Dict) -> None:
        """Create order link in the database - consolidated in daily-boards collection"""
        try:
            # Update the daily-boards case document with order information
            case_update = {
                "order_downloaded": True,
                "order_link": order_info.get("order_link"),
                "order_filename": order_info.get("filename"),
                "order_source": order_info.get("source", "auto"),
                "order_downloaded_at": datetime.now().isoformat(),
                "order_status": "linked",
                "order_fetch_date": datetime.now().isoformat(),
                "order_created_at": datetime.now().isoformat(),
                "order_updated_at": datetime.now().isoformat(),
            }

            self.db.collection(self.boards_collection).document(case_id).update(
                case_update
            )
            logging.info(f"Order link created in daily-boards for {case_id}")

            try:
                board_doc = (
                    self.db.collection(self.boards_collection).document(case_id).get()
                )
                board_data = board_doc.to_dict() if board_doc.exists else {}
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
                        "order_fetch_date": case_update.get("order_fetch_date"),
                    },
                )
            except Exception as case_sync_error:
                logging.warning(
                    f"Case order history sync failed for {case_id}: {case_sync_error}"
                )

        except Exception as e:
            logging.error(f"Error creating order link for case {case_id}: {e}")

    def _link_order_to_additional_cases(
        self,
        primary_case_id: str,
        primary_case_ref: str,
        analysis_data: Dict,
        order_info: Dict,
        board_date: str,
    ) -> List[str]:
        """
        Link the same order to additional cases found in the order document
        Handles multi-case orders where multiple cases are clubbed together

        Returns: List of case references that were successfully linked
        """
        linked_cases = []

        try:
            # Extract case numbers from analysis
            order_cases = analysis_data.get("order_cases", [])

            if not order_cases or len(order_cases) <= 1:
                # No additional cases to link
                return linked_cases

            logging.info(
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
                        logging.warning(f"Missing required case fields in {case_info}")
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
                        logging.info(
                            f"No matching case found in database for {case_ref} on date {board_date}"
                        )
                        continue

                    # Check if this case already has an order linked
                    existing_case_doc = (
                        self.db.collection(self.boards_collection)
                        .document(matching_case_id)
                        .get()
                    )
                    existing_order = (
                        existing_case_doc.to_dict().get("order_status", "not_linked")
                        if existing_case_doc.exists
                        else "not_linked"
                    )
                    if existing_order in {"linked", "analysed", "manually_uploaded"}:
                        logging.info(
                            f"Case {case_ref} already has an order linked, skipping"
                        )
                        continue

                    # Create order link for this additional case
                    self._create_order_link(matching_case_id, order_info)

                    # Create case-specific analysis data with this case's party names
                    case_specific_analysis = self._create_case_specific_analysis(
                        analysis_data, case_info, order_info.get("order_link")
                    )

                    # Update daily-boards with analysis for this case
                    self.db.collection(self.boards_collection).document(
                        matching_case_id
                    ).update(case_specific_analysis)

                    try:
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
                    except Exception as case_sync_error:
                        logging.warning(
                            f"Failed normalized sync for linked case {case_ref}: {case_sync_error}"
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
                    logging.info(
                        f"Successfully linked order to additional case: {case_ref}"
                    )

                except Exception as e:
                    logging.error(f"Error linking order to case {case_number}: {e}")
                    continue

        except Exception as e:
            logging.error(f"Error in multi-case linking for {primary_case_ref}: {e}")

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
            logging.error(f"Error finding case_id for {case_ref}: {e}")
            return None

    def _create_case_specific_analysis(
        self, analysis_data: Dict, case_info: Dict, order_link: str
    ) -> Dict:
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
            "order_analysis_completed": True,
            "order_last_updated": datetime.now().isoformat(),
        }

        return case_analysis

    def _parse_case_reference(self, case_ref: str) -> Optional[Tuple[str, int, int]]:
        """Parse case reference like 'WP/294/2025' into components (type, number, year)"""
        try:
            pattern = r"([A-Z]+)/(\d+)/(\d+)"
            match = re.match(pattern, case_ref)
            if match:
                case_type = match.group(1)
                case_no = int(match.group(2))
                case_year = int(match.group(3))
                return (case_type, case_no, case_year)
            return None
        except (ValueError, AttributeError) as e:
            logging.warning(f"Error parsing case reference {case_ref}: {e}")
            return None

    def search_orders(self, search_params: Dict) -> Dict:
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
            logging.error(f"Error searching orders: {e}")
            return {"success": False, "error": str(e)}

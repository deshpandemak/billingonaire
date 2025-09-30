from firebase_admin import firestore
import logging
import re
import os
import requests
from typing import List, Dict, Optional, Tuple
from datetime import datetime, timedelta
import pandas as pd
from urllib.parse import urljoin, urlparse
import tempfile
import base64
from io import BytesIO
from PyPDF2 import PdfReader, PdfWriter
from order_analyzer import OrderDocumentAnalyzer
from CourtScraper import BombayHighCourtScraper
import asyncio
from dataclasses import asdict

class AutoOrderManager:
    """
    Automated Court Order Download and Analysis Manager
    Handles automatic fetching, linking, and analysis of court orders
    """
    
    def __init__(self):
        self.db = firestore.client()
        self.order_analyzer = OrderDocumentAnalyzer()
        self.court_scraper = BombayHighCourtScraper()
        
        # Collections
        self.boards_collection = "daily-boards"
        self.orders_collection = "case-orders" 
        self.search_index_collection = "order-search-index"
        
        # Case type mappings for court lookup
        self.casetype_dict = {
            'WP': '2001', 'IA': '2069', 'CP': '2010', 'RPW': '2019',
            'PIL': '2002', 'CRLP': '2020', 'CRLWP': '2021'
        }
        
        # AGP name patterns for extraction
        self.agp_patterns = [
            r'Pooja\s*(?:M\.)?\s*(?:J\.)?\s*(?:Joshi|Deshpande)+',
            r'P(?:ooja)?\.\s*(?:M\.)?\s*(?:J\.)?\s*(?:Joshi|Des(?:h)?pande)+',
            r'Ms\.\s*Pooja\s*(?:Joshi\s*)?Deshpande',
            r'Smt\.\s*Pooja\s*(?:Joshi\s*)?Deshpande'
        ]

    def get_orders_for_cases(self, case_filters: Dict = None, limit: int = 50) -> Dict:
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
                return {"success": True, "message": "No cases found matching criteria", "processed": 0}
            
            results = {
                "total_cases": len(filtered_cases),
                "successful_downloads": 0,
                "failed_downloads": 0,
                "successful_analyses": 0,
                "failed_analyses": 0,
                "errors": [],
                "processed_cases": []
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
                    logging.error(error_msg)
                    results["errors"].append(error_msg)
                    results["failed_downloads"] += 1
            
            return {"success": True, "results": results}
            
        except Exception as e:
            logging.error(f"Error in get_orders_for_cases: {e}")
            return {"success": False, "error": str(e)}

    def _get_filtered_matters(self, filters: Dict = None, limit: int = 50) -> List[Dict]:
        """Get cases that need order processing based on filters"""
        try:
            query = self.db.collection(self.boards_collection)
            
            # Apply filters if provided
            if filters:
                if filters.get('case_type'):
                    query = query.where("case_type", "==", filters['case_type'])
                if filters.get('case_year'):
                    query = query.where("case_year", "==", filters['case_year'])
                if filters.get('date_from'):
                    query = query.where("board_date", ">=", filters['date_from'])
                if filters.get('date_to'):
                    query = query.where("board_date", "<=", filters['date_to'])
            
            # Get cases without order analysis
            query = query.limit(limit * 2)  # Get more to filter
            cases = []
            
            for doc in query.stream():
                case_data = doc.to_dict()
                case_data['id'] = doc.id
                
                # Check if case needs order processing - look for order analysis completion
                order_analysis_completed = case_data.get('order_analysis_completed', False)
                order_status = self._get_order_status(doc.id)
                
                # Include cases that:
                # 1. Don't have order analysis completed, OR
                # 2. Have failed order status
                if not order_analysis_completed or order_status in ['not_present', 'failed']:
                    # Format case reference
                    case_ref = f"{case_data.get('case_type', '')}/{case_data.get('case_no', '')}/{case_data.get('case_year', '')}"
                    case_data['case_ref'] = case_ref
                    cases.append(case_data)
                    
                    if len(cases) >= limit:
                        break
            
            return cases
            
        except Exception as e:
            logging.error(f"Error getting filtered matters: {e}")
            return []

    def _process_single_case(self, case_data: Dict) -> Dict:
        """Process a single case for order download and analysis"""
        case_id = case_data['id']
        case_ref = case_data['case_ref']
        
        result = {
            "case_id": case_id,
            "case_ref": case_ref,
            "download_success": False,
            "analysis_success": False,
            "order_link": None,
            "analysis_data": None,
            "error": None
        }
        
        try:
            # Step 1: Try to download/fetch order
            order_info = self._download_order_for_case(case_data)
            
            if order_info.get('success'):
                result["download_success"] = True
                result["order_link"] = order_info.get('order_link')
                
                # Step 2: Analyze order and validate date BEFORE linking
                if order_info.get('pdf_content'):
                    # Quick analysis to extract order date for validation
                    temp_filename = f"{case_ref.replace('/', '-')}.pdf"
                    quick_analysis = self.order_analyzer.analyze_order_document(temp_filename, order_info['pdf_content'])
                    
                    # Validate that order date matches board date
                    date_validation = self._validate_order_date(quick_analysis.order_date, case_data.get('board_date'))
                    
                    if not date_validation.get('valid'):
                        # Date mismatch - don't link the order
                        result["error"] = f"Order date mismatch: {date_validation.get('reason')}"
                        result["date_validation"] = date_validation
                        logging.warning(f"Case {case_id}: Order date does not match board date. Expected: {date_validation.get('expected_date')}, Found: {date_validation.get('extracted_date')}")
                        return result
                    
                    # Step 3: Date matches - now create order link in database
                    self._create_order_link(case_id, order_info)
                    
                    # Step 4: Perform full analysis and store results
                    analysis_result = self._analyze_order_with_date_validation(
                        case_id, case_ref, order_info['pdf_content'], 
                        case_data.get('board_date'), order_info.get('order_link')
                    )
                    
                    if analysis_result.get('success'):
                        result["analysis_success"] = True
                        result["analysis_data"] = analysis_result.get('data')
                        
                        # Step 5: Create search index (analyzed-orders collection already updated)
                        self._create_search_index_entry(case_id, case_data, analysis_result['data'])
                    else:
                        result["error"] = f"Analysis failed: {analysis_result.get('error')}"
                else:
                    result["error"] = "No PDF content available for analysis"
                    
            else:
                result["error"] = f"Download failed: {order_info.get('error')}"
                
        except Exception as e:
            result["error"] = str(e)
            logging.error(f"Error processing case {case_ref}: {e}")
        
        return result

    def _download_order_for_case(self, case_data: Dict) -> Dict:
        """
        Download order for a specific case using the Bombay High Court API
        Based on the provided working download_pdf function
        """
        try:
            case_ref = case_data['case_ref']
            board_date = case_data.get('board_date')
            
            # Parse case reference
            case_parts = self._parse_case_reference(case_ref)
            if not case_parts:
                return {"success": False, "error": "Invalid case reference format"}
            
            case_type, case_number, year = case_parts
            
            # Format case number with leading zeros
            case_number = case_number.zfill(7)
            
            # Convert board_date to datetime object for comparison
            case_board_date = None
            if isinstance(board_date, datetime):
                case_board_date = board_date
                date_str = board_date.strftime('%d%m%Y')
            elif isinstance(board_date, str):
                try:
                    case_board_date = datetime.strptime(board_date, '%Y-%m-%d')
                    date_str = case_board_date.strftime('%d%m%Y')
                except:
                    case_board_date = datetime.now()
                    date_str = case_board_date.strftime('%d%m%Y')
            else:
                case_board_date = datetime.now()
                date_str = case_board_date.strftime('%d%m%Y')
            
            order_filename = f"{case_ref.replace('/', '-')}-{date_str}.pdf"
            
            # Check if case type is supported
            if case_type not in self.casetype_dict:
                return {
                    "success": False,
                    "error": f"Case type {case_type} not supported for automated download",
                    "suggested_filename": order_filename
                }
            
            # Determine if this needs stamp number search
            search_stamp_no = 'ST' in case_type
            if search_stamp_no:
                case_type = case_type.replace(' ', '').replace('(ST)', '').strip()
            
            # Try to download using Bombay High Court API (simplified - no date validation here)
            download_result = self._download_pdf_bombay_hc_simple(
                case_type, case_number, year, search_stamp_no, order_filename
            )
            
            if download_result.get('success'):
                return {
                    "success": True,
                    "order_link": download_result.get('download_url'),
                    "pdf_content": download_result.get('pdf_content'),
                    "filename": order_filename,
                    "source": "bombay_hc_api"
                }
            else:
                return {
                    "success": False,
                    "error": download_result.get('error', 'Unknown download error'),
                    "suggested_filename": order_filename
                }
            
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _download_pdf_bombay_hc_simple(self, case_type: str, case_number: str, year: str, 
                                      search_stamp_no: bool, order_filename: str) -> Dict:
        """
        Simplified PDF download from Bombay High Court - just get the PDF, no validation
        Let order_analyzer handle all PDF parsing and validation
        """
        try:
            base_url = 'https://bombayhighcourt.nic.in/'
            url = 'generatenewauth.php?bhcpar='
            query = 'path=./writereaddata/data/civil/{year}/&fname={stamp_no}{case_type}{case_number}{year}_{seq}.pdf&smflag=N&rjuddate=&uploaddt=&spassphrase={current_time}&ncitation=&smcitation=&digcertflg=&interface='
            
            # Generate current timestamp
            date_time = datetime.now()
            current_time = date_time.strftime('%d%m%y%H%M%S')
            
            seq_no = 1
            count = 0
            
            while count < 20:  # Try up to 20 sequence numbers
                count += 1
                
                # Format the query
                query_fmt = query.format(
                    case_type=self.casetype_dict[case_type],
                    case_number=case_number,
                    year=year,
                    seq=str(seq_no),
                    current_time=current_time,
                    stamp_no='F' if search_stamp_no else ''
                )
                
                seq_no += 1
                
                # Encode the query
                query_utf_8 = query_fmt.encode('utf-8')
                encoded_query = base64.b64encode(query_utf_8)
                query_str = encoded_query.decode('utf-8')
                full_url = base_url + url + query_str
                
                # Make the request
                try:
                    response = requests.get(full_url, timeout=30)
                    
                    # Check if response is a PDF - just return the first valid PDF found
                    if response.headers.get('Content-Type') == 'application/pdf':
                        logging.info(f'PDF found for: {order_filename} (seq: {seq_no-1})')
                        return {
                            "success": True,
                            "pdf_content": response.content,
                            "download_url": full_url,
                            "filename": order_filename,
                            "sequence_number": seq_no - 1
                        }
                    
                except requests.RequestException as e:
                    logging.debug(f"Request failed for seq {seq_no-1}: {e}")
                    continue
            
            return {
                "success": False,
                "error": f"No PDF found after trying {count} sequence numbers",
                "last_url_tried": full_url if 'full_url' in locals() else None
            }
            
        except Exception as e:
            logging.error(f"Error downloading PDF from Bombay HC: {e}")
            return {"success": False, "error": str(e)}

    def _analyze_order_with_date_validation(self, case_id: str, case_ref: str, 
                                          pdf_content: bytes, expected_board_date: str, order_link: Optional[str] = None) -> Dict:
        """
        Analyze the downloaded order using order_analyzer and validate date
        Store analysis results directly in daily-boards collection
        """
        try:
            # Create temporary filename for analysis
            temp_filename = f"{case_ref.replace('/', '-')}.pdf"
            
            # Analyze using existing order analyzer
            analysis_result = self.order_analyzer.analyze_order_document(temp_filename, pdf_content)
            
            # Validate the extracted order date against expected board date
            date_validation = self._validate_order_date(analysis_result.order_date, expected_board_date)
            
            # Convert CaseInfo dataclasses to plain dicts for Firestore
            cases_as_dicts = []
            if analysis_result.cases:
                for case_obj in analysis_result.cases:
                    try:
                        case_dict = asdict(case_obj) if hasattr(case_obj, '__dataclass_fields__') else case_obj
                        cases_as_dicts.append(case_dict)
                    except Exception as e:
                        logging.warning(f"Could not convert case object to dict: {e}")
                        continue
            
            # Create order analysis data to merge with board data - ALL FIELDS PREFIXED
            order_analysis = {
                # Order analysis results
                "order_category": analysis_result.order_category,
                "order_category_confidence": analysis_result.category_confidence,
                "order_date": analysis_result.order_date,
                "order_petitioners": analysis_result.petitioners,
                "order_respondents": analysis_result.respondents,
                "order_agp_names": analysis_result.agp_names,
                
                # Complete tabular data structure
                "order_tabular_data": analysis_result.tabular_data,
                
                # Additional analysis details
                "order_key_phrases": analysis_result.key_phrases,
                "order_next_hearing_date": analysis_result.next_hearing_date,
                "order_disposal_reason": analysis_result.disposal_reason,
                "order_text": analysis_result.order_text[:1000] if analysis_result.order_text else "",  # Store first 1000 chars
                "order_cases": cases_as_dicts,  # Use converted list of dicts
                
                # Date validation
                "order_date_validation": date_validation,
                
                # Order link - use passed link or fallback to querying case-orders
                "order_link": order_link or self._get_order_link(case_id),
                
                # Analysis metadata
                "order_analysis_timestamp": datetime.now().isoformat(),
                "order_analysis_completed": True,
                "order_last_updated": datetime.now().isoformat()
            }
            
            # Update the daily-boards document directly with order analysis
            self.db.collection(self.boards_collection).document(case_id).update(order_analysis)
            
            # Prepare full analysis data for response (includes case_id and case_ref for compatibility)
            full_analysis_data = {
                "case_id": case_id,
                "case_ref": case_ref,
                **order_analysis
            }
            
            return {"success": True, "data": full_analysis_data}
            
        except Exception as e:
            logging.error(f"Error analyzing order for case {case_id}: {e}")
            return {"success": False, "error": str(e)}

    def _validate_order_date(self, extracted_order_date: str, expected_board_date: str) -> Dict:
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
                    "expected_date": expected_board_date
                }
            
            # Parse dates for comparison
            try:
                if isinstance(expected_board_date, str):
                    expected_date = datetime.strptime(expected_board_date, '%Y-%m-%d').date()
                elif isinstance(expected_board_date, datetime):
                    expected_date = expected_board_date.date()
                else:
                    expected_date = expected_board_date
                
                # Try to parse extracted order date
                if isinstance(extracted_order_date, str):
                    # Try different date formats
                    for fmt in ['%Y-%m-%d', '%d-%m-%Y', '%d/%m/%Y', '%Y-%m-%dT%H:%M:%S']:
                        try:
                            extracted_date = datetime.strptime(extracted_order_date, fmt).date()
                            break
                        except ValueError:
                            continue
                    else:
                        return {
                            "valid": False,
                            "reason": "Could not parse extracted date format",
                            "extracted_date": extracted_order_date,
                            "expected_date": expected_board_date
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
                    "date_difference_days": (extracted_date - expected_date).days if date_match is False else 0
                }
                
            except Exception as e:
                return {
                    "valid": False,
                    "reason": f"Date parsing error: {str(e)}",
                    "extracted_date": extracted_order_date,
                    "expected_date": expected_board_date
                }
                
        except Exception as e:
            logging.error(f"Error validating order date: {e}")
            return {
                "valid": False,
                "reason": f"Validation error: {str(e)}",
                "extracted_date": extracted_order_date,
                "expected_date": expected_board_date
            }


    def _create_search_index_entry(self, case_id: str, case_data: Dict, analysis_data: Dict) -> None:
        """Create optimized search index entry for fast searching from consolidated daily-boards data"""
        try:
            # Get the complete board document with analysis data
            board_doc = self.db.collection(self.boards_collection).document(case_id).get()
            if not board_doc.exists:
                logging.error(f"Board document not found for case {case_id}")
                return
                
            board_data = board_doc.to_dict()
            
            # Extract data with consistent field names
            petitioners = board_data.get('order_petitioners', [])
            respondents = board_data.get('order_respondents', [])
            agp_names = board_data.get('order_agp_names', [])
            key_phrases = board_data.get('order_key_phrases', [])
            
            # Convert party names to strings (handle both string and dict formats)
            def extract_text_from_parties(parties):
                """Extract text from party lists, handling both strings and dicts"""
                result = []
                for party in parties:
                    if isinstance(party, str):
                        result.append(party)
                    elif isinstance(party, dict):
                        # Extract name field from dict if present
                        result.append(party.get('name', ''))
                return result
            
            petitioner_strings = extract_text_from_parties(petitioners)
            respondent_strings = extract_text_from_parties(respondents)
            agp_name_strings = [str(name) if not isinstance(name, str) else name for name in agp_names]
            
            # Create search-optimized document
            search_doc = {
                "case_id": case_id,
                "case_ref": f"{board_data.get('case_type', '')}/{board_data.get('case_no', '')}/{board_data.get('case_year', '')}",
                "case_type": board_data.get('case_type'),
                "case_number": board_data.get('case_no'),
                "case_year": board_data.get('case_year'),
                "board_date": board_data.get('board_date'),
                
                # Board data
                "petitioner_lawyer": board_data.get('petitioner_lawyer'),
                "respondent_lawyer": board_data.get('respondent_lawyer'),
                "serial_number": board_data.get('serial_number'),
                
                # Parties information from order analysis
                "petitioner_names": petitioner_strings,
                "respondent_names": respondent_strings,
                "petitioner_text": " ".join(petitioner_strings).lower(),  # For text search
                "respondent_text": " ".join(respondent_strings).lower(),   # For text search
                
                # Order information with consistent field names
                "order_category": board_data.get('order_category'),
                "order_date": board_data.get('order_date'),
                "order_category_confidence": board_data.get('order_category_confidence'),
                "agp_names": agp_name_strings,
                "key_phrases": key_phrases if isinstance(key_phrases, list) else [],
                
                # Date validation status
                "date_validation_valid": board_data.get('order_date_validation', {}).get('valid', False),
                
                # Links
                "order_link": board_data.get('order_link'),
                
                # Analysis metadata
                "order_analysis_completed": board_data.get('order_analysis_completed', False),
                "order_analysis_timestamp": board_data.get('order_analysis_timestamp'),
                
                # Timestamps
                "created_at": datetime.now().isoformat(),
                "last_updated": datetime.now().isoformat()
            }
            
            # Save to search index
            self.db.collection(self.search_index_collection).document(case_id).set(search_doc)
            
        except Exception as e:
            logging.error(f"Error creating search index for case {case_id}: {e}")

    def _create_order_link(self, case_id: str, order_info: Dict) -> None:
        """Create order link in the database and update case document"""
        try:
            # Create order document in case-orders collection
            order_doc = {
                "case_id": case_id,
                "status": "linked",
                "order_link": order_info.get('order_link'),
                "fetch_date": datetime.now().isoformat(),
                "source": order_info.get('source', 'auto'),
                "filename": order_info.get('filename'),
                "created_at": datetime.now().isoformat(),
                "updated_at": datetime.now().isoformat()
            }
            
            self.db.collection(self.orders_collection).document(case_id).set(order_doc)
            
            # CRITICAL: Also update the daily-boards case document so UI can see the link
            case_update = {
                "order_downloaded": True,
                "order_link": order_info.get('order_link'),
                "order_filename": order_info.get('filename'),
                "order_source": order_info.get('source', 'auto'),
                "order_downloaded_at": datetime.now().isoformat()
            }
            
            self.db.collection(self.boards_collection).document(case_id).update(case_update)
            logging.info(f"Order link created and case document updated for {case_id}")
            
        except Exception as e:
            logging.error(f"Error creating order link for case {case_id}: {e}")

    def _get_order_status(self, case_id: str) -> str:
        """Get current order status for a case"""
        try:
            order_doc = self.db.collection(self.orders_collection).document(case_id).get()
            if order_doc.exists:
                return order_doc.to_dict().get('status', 'not_present')
            return 'not_present'
        except:
            return 'not_present'

    def _get_order_link(self, case_id: str) -> Optional[str]:
        """Get order link for a case"""
        try:
            order_doc = self.db.collection(self.orders_collection).document(case_id).get()
            if order_doc.exists:
                return order_doc.to_dict().get('order_link')
            return None
        except:
            return None

    def _parse_case_reference(self, case_ref: str) -> Optional[Tuple[str, str, str]]:
        """Parse case reference like 'WP/294/2025' into components"""
        try:
            pattern = r'([A-Z]+)/(\d+)/(\d+)'
            match = re.match(pattern, case_ref)
            if match:
                return (match.group(1), match.group(2), match.group(3))
            return None
        except:
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
            if search_params.get('case_type'):
                query = query.where("case_type", "==", search_params['case_type'])
            
            if search_params.get('case_year'):
                query = query.where("case_year", "==", search_params['case_year'])
            
            if search_params.get('order_category'):
                query = query.where("order_category", "==", search_params['order_category'])
            
            # Text search (basic implementation)
            results = []
            for doc in query.limit(search_params.get('limit', 100)).stream():
                data = doc.to_dict()
                
                # Apply text filters
                if search_params.get('petitioner_search'):
                    search_text = search_params['petitioner_search'].lower()
                    if search_text not in data.get('petitioner_text', ''):
                        continue
                
                if search_params.get('respondent_search'):
                    search_text = search_params['respondent_search'].lower()
                    if search_text not in data.get('respondent_text', ''):
                        continue
                
                results.append(data)
            
            return {
                "success": True,
                "results": results,
                "total_found": len(results)
            }
            
        except Exception as e:
            logging.error(f"Error searching orders: {e}")
            return {"success": False, "error": str(e)}

    def bulk_process_orders(self, case_ids: List[str]) -> Dict:
        """Process multiple cases for order download and analysis"""
        try:
            results = {
                "total_requested": len(case_ids),
                "successful": 0,
                "failed": 0,
                "results": []
            }
            
            for case_id in case_ids:
                try:
                    # Get case data
                    case_doc = self.db.collection(self.boards_collection).document(case_id).get()
                    if not case_doc.exists:
                        results["results"].append({
                            "case_id": case_id,
                            "success": False,
                            "error": "Case not found"
                        })
                        results["failed"] += 1
                        continue
                    
                    case_data = case_doc.to_dict()
                    case_data['id'] = case_id
                    case_ref = f"{case_data.get('case_type', '')}/{case_data.get('case_no', '')}/{case_data.get('case_year', '')}"
                    case_data['case_ref'] = case_ref
                    
                    # Process the case
                    result = self._process_single_case(case_data)
                    results["results"].append(result)
                    
                    if result.get("download_success") or result.get("analysis_success"):
                        results["successful"] += 1
                    else:
                        results["failed"] += 1
                        
                except Exception as e:
                    results["results"].append({
                        "case_id": case_id,
                        "success": False,
                        "error": str(e)
                    })
                    results["failed"] += 1
            
            return {"success": True, "results": results}
            
        except Exception as e:
            return {"success": False, "error": str(e)}
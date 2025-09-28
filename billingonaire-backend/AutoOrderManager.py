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
        self.analyzed_orders_collection = "analyzed-orders"
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
            
            # Get cases without orders or failed orders
            query = query.limit(limit * 2)  # Get more to filter
            cases = []
            
            for doc in query.stream():
                case_data = doc.to_dict()
                case_data['id'] = doc.id
                
                # Check if case needs order processing
                order_status = self._get_order_status(doc.id)
                if order_status in ['not_present', 'failed']:
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
                
                # Step 2: Create order link in database
                self._create_order_link(case_id, order_info)
                
                # Step 3: Analyze the order if we have PDF content
                if order_info.get('pdf_content'):
                    analysis_result = self._analyze_order(case_id, case_ref, order_info['pdf_content'])
                    
                    if analysis_result.get('success'):
                        result["analysis_success"] = True
                        result["analysis_data"] = analysis_result.get('data')
                        
                        # Step 4: Create search index entry
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
            
            # Try to download using Bombay High Court API
            download_result = self._download_pdf_bombay_hc(
                case_type, case_number, year, case_board_date, search_stamp_no, order_filename
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

    def _download_pdf_bombay_hc(self, case_type: str, case_number: str, year: str, 
                               case_board_date: datetime, search_stamp_no: bool, 
                               order_filename: str) -> Dict:
        """
        Download PDF from Bombay High Court using their actual API
        Based on the provided working download_pdf function
        """
        try:
            base_url = 'https://bombayhighcourt.nic.in/'
            url = 'generatenewauth.php?bhcpar='
            query = 'path=./writereaddata/data/civil/{year}/&fname={stamp_no}{case_type}{case_number}{year}_{seq}.pdf&smflag=N&rjuddate=&uploaddt=&spassphrase={current_time}&ncitation=&smcitation=&digcertflg=&interface='
            
            # Generate current timestamp
            date_time = datetime.now()
            current_time = date_time.strftime('%d%m%y%H%M%S')
            
            # Date patterns for validation
            date_pattern_fmts = ['%d%B%Y', '%B%d%Y']
            date_replace_pattern = ['st', 'ST', 'nd', 'ND', 'rd', 'RD', 'th', 'TH', ',', '.']
            
            # Order patterns to look for
            format_dated = '.*DATED *: *(.*)'
            format_date = '.*DATE *: *(.*)'
            order_list = [format_dated, format_date]
            
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
                    
                    # Check if response is a PDF
                    if response.headers.get('Content-Type') == 'application/pdf':
                        # Validate the PDF content
                        validation_result = self._validate_order_pdf(
                            response.content, case_board_date, order_list, 
                            date_pattern_fmts, date_replace_pattern
                        )
                        
                        if validation_result.get('order_found'):
                            logging.info(f'Order found for: {order_filename}')
                            return {
                                "success": True,
                                "pdf_content": response.content,
                                "download_url": full_url,
                                "filename": order_filename,
                                "validation": validation_result
                            }
                    
                except requests.RequestException as e:
                    logging.debug(f"Request failed for seq {seq_no-1}: {e}")
                    continue
            
            return {
                "success": False,
                "error": f"No order found after trying {count} sequence numbers",
                "last_url_tried": full_url if 'full_url' in locals() else None
            }
            
        except Exception as e:
            logging.error(f"Error downloading PDF from Bombay HC: {e}")
            return {"success": False, "error": str(e)}

    def _validate_order_pdf(self, pdf_content: bytes, case_board_date: datetime, 
                           order_list: List[str], date_pattern_fmts: List[str], 
                           date_replace_pattern: List[str]) -> Dict:
        """
        Validate that the downloaded PDF is the correct order by checking the date
        Based on the validation logic from the provided download_pdf function
        """
        try:
            pdf_data = PdfReader(BytesIO(pdf_content))
            pages = len(pdf_data.pages)
            order_found = False
            
            for i in range(pages):
                page = pdf_data.pages[i]
                text = page.extract_text()
                lines = text.splitlines()
                
                for line in lines:
                    for pattern in order_list:
                        matches = re.match(pattern, line)
                        if matches:
                            date_formatted = matches.group(1)
                            
                            # Clean up the date string
                            head, sep, tail = text.partition('2024')
                            date_formatted = date_formatted.replace(tail, '')
                            
                            for sub in date_replace_pattern:
                                date_formatted = date_formatted.replace(sub, '')
                            date_formatted = date_formatted.replace(' ', '')
                            
                            # Handle August variations
                            if 'AUGUST' in date_formatted.upper():
                                date_formatted = date_formatted
                            elif 'AUGU' in date_formatted.upper():
                                date_formatted = date_formatted.upper().replace('AUGU', 'AUGUST')
                            
                            # Try to parse the date
                            try:
                                order_date = None
                                for format_str in date_pattern_fmts:
                                    try:
                                        order_date = datetime.strptime(date_formatted, format_str)
                                        break
                                    except ValueError:
                                        continue
                                
                                if order_date and order_date.date() == case_board_date.date():
                                    order_found = True
                                    return {
                                        "order_found": True,
                                        "order_date": order_date.isoformat(),
                                        "matched_pattern": pattern,
                                        "raw_date_text": date_formatted
                                    }
                                    
                            except ValueError as e:
                                logging.debug(f'Date format invalid: {date_formatted} - {e}')
                                continue
            
            return {
                "order_found": False,
                "error": "No matching date found in PDF",
                "expected_date": case_board_date.isoformat()
            }
            
        except Exception as e:
            logging.error(f"Error validating PDF: {e}")
            return {
                "order_found": False,
                "error": f"PDF validation failed: {str(e)}"
            }

    def _analyze_order(self, case_id: str, case_ref: str, pdf_content: bytes) -> Dict:
        """Analyze the downloaded order using order_analyzer"""
        try:
            # Create temporary filename for analysis
            temp_filename = f"{case_ref.replace('/', '-')}.pdf"
            
            # Analyze using existing order analyzer
            analysis_result = self.order_analyzer.analyze_order_document(temp_filename, pdf_content)
            
            # Extract key information for search index
            analysis_data = {
                "case_id": case_id,
                "case_ref": case_ref,
                "order_category": analysis_result.order_category,
                "category_confidence": analysis_result.category_confidence,
                "order_date": analysis_result.order_date,
                "petitioners": analysis_result.petitioners,
                "respondents": analysis_result.respondents,
                "agp_names": analysis_result.agp_names,
                "key_phrases": analysis_result.key_phrases,
                "next_hearing_date": analysis_result.next_hearing_date,
                "disposal_reason": analysis_result.disposal_reason,
                "tabular_data": analysis_result.tabular_data,
                "order_text": analysis_result.order_text[:1000],  # Store first 1000 chars
                "analysis_timestamp": datetime.now().isoformat(),
                "cases": analysis_result.cases
            }
            
            # Save to analyzed orders collection
            self.db.collection(self.analyzed_orders_collection).document(case_id).set(analysis_data)
            
            return {"success": True, "data": analysis_data}
            
        except Exception as e:
            logging.error(f"Error analyzing order for case {case_id}: {e}")
            return {"success": False, "error": str(e)}

    def _create_search_index_entry(self, case_id: str, case_data: Dict, analysis_data: Dict) -> None:
        """Create optimized search index entry for fast searching"""
        try:
            # Extract petitioner and respondent names
            petitioners = analysis_data.get('petitioners', [])
            respondents = analysis_data.get('respondents', [])
            
            # Create search-optimized document
            search_doc = {
                "case_id": case_id,
                "case_ref": case_data['case_ref'],
                "case_type": case_data.get('case_type'),
                "case_number": case_data.get('case_no'),
                "case_year": case_data.get('case_year'),
                "board_date": case_data.get('board_date'),
                
                # Parties information
                "petitioner_names": petitioners,
                "respondent_names": respondents,
                "petitioner_text": " ".join(petitioners).lower(),  # For text search
                "respondent_text": " ".join(respondents).lower(),   # For text search
                
                # Order information
                "order_category": analysis_data.get('order_category'),
                "order_date": analysis_data.get('order_date'),
                "agp_names": analysis_data.get('agp_names', []),
                "key_phrases": analysis_data.get('key_phrases', []),
                
                # Links
                "order_link": self._get_order_link(case_id),
                
                # Timestamps
                "created_at": datetime.now().isoformat(),
                "last_updated": datetime.now().isoformat()
            }
            
            # Save to search index
            self.db.collection(self.search_index_collection).document(case_id).set(search_doc)
            
        except Exception as e:
            logging.error(f"Error creating search index for case {case_id}: {e}")

    def _create_order_link(self, case_id: str, order_info: Dict) -> None:
        """Create order link in the database"""
        try:
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
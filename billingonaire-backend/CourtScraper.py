import requests
from bs4 import BeautifulSoup
import re
from typing import Dict, Optional, List
import logging

class BombayHighCourtScraper:
    """
    Scraper for Bombay High Court case details using the E-Courts system
    """
    
    def __init__(self):
        self.base_url = "https://hcservices.ecourts.gov.in/ecourtindiaHC"
        self.search_url = f"{self.base_url}/cases/case_no.php"
        self.session = requests.Session()
        # Set headers to mimic a real browser
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Accept-Encoding': 'gzip, deflate',
            'Connection': 'keep-alive',
            'Referer': 'https://hcservices.ecourts.gov.in/',
        })
        
    def parse_case_number(self, case_ref: str) -> Dict[str, str]:
        """
        Parse case reference like 'WP/294/2025' into components
        Returns: {'case_type': 'WP', 'case_number': '294', 'year': '2025'}
        """
        try:
            # Pattern: CASE_TYPE/CASE_NUMBER/YEAR
            match = re.match(r'^([A-Z]+)\/(\d+)\/(\d{4})$', case_ref.strip())
            if match:
                return {
                    'case_type': match.group(1),
                    'case_number': match.group(2),
                    'year': match.group(3)
                }
            else:
                raise ValueError(f"Invalid case reference format: {case_ref}")
        except Exception as e:
            logging.error(f"Error parsing case number {case_ref}: {e}")
            return {}
    
    def get_case_details(self, case_ref: str, bench: str = "mumbai") -> Dict:
        """
        Fetch case details from Bombay High Court
        
        Args:
            case_ref: Case reference like 'WP/294/2025'
            bench: Court bench - 'mumbai', 'aurangabad', 'nagpur', 'goa'
        
        Returns:
            Dictionary with case details or error message
        """
        try:
            # Parse case reference
            case_parts = self.parse_case_number(case_ref)
            if not case_parts:
                return {"error": "Invalid case reference format", "case_ref": case_ref}
            
            # Set court code based on bench
            bench_codes = {
                "mumbai": "2",      # Original Side, Mumbai
                "aurangabad": "3",  # Aurangabad Bench 
                "nagpur": "4",      # Nagpur Bench
                "goa": "5"          # Goa Bench
            }
            court_code = bench_codes.get(bench.lower(), "2")
            
            # Get the search form page first
            form_params = {
                'state_cd': '1',
                'dist_cd': '1', 
                'court_code': court_code,
                'stateNm': 'Bombay'
            }
            
            form_response = self.session.get(self.search_url, params=form_params)
            if form_response.status_code != 200:
                return {"error": "Failed to access court website", "status_code": form_response.status_code}
            
            # Parse the form to get any hidden fields or session tokens
            soup = BeautifulSoup(form_response.content, 'html.parser')
            
            # For now, since there's a CAPTCHA, we'll use a different approach
            # Let's try the alternative E-Courts API or direct case lookup
            return self._try_alternative_lookup(case_parts, court_code)
            
        except Exception as e:
            logging.error(f"Error fetching case details for {case_ref}: {e}")
            return {"error": str(e), "case_ref": case_ref}
    
    def _try_alternative_lookup(self, case_parts: Dict, court_code: str) -> Dict:
        """
        Try alternative methods to get case information
        Since the main form has CAPTCHA, we'll try other endpoints
        """
        try:
            case_type = case_parts.get('case_type')
            case_number = case_parts.get('case_number')
            year = case_parts.get('year')
            
            # Try the case listing or order lookup endpoints
            # These might not require CAPTCHA
            
            # First attempt: Try direct case URL patterns used by some courts
            alt_urls = [
                f"{self.base_url}/cases/case_detail.php?case_type={case_type}&case_no={case_number}&case_year={year}&court_code={court_code}",
                f"{self.base_url}/order_list.php?case_type={case_type}&case_no={case_number}&case_year={year}&court_code={court_code}",
            ]
            
            for url in alt_urls:
                try:
                    response = self.session.get(url)
                    if response.status_code == 200 and "case" in response.text.lower():
                        soup = BeautifulSoup(response.content, 'html.parser')
                        return self._parse_case_details(soup, case_parts)
                except:
                    continue
            
            # If direct access fails, return a structured response indicating CAPTCHA requirement
            return {
                "status": "captcha_required",
                "message": "Case lookup requires manual CAPTCHA verification",
                "case_ref": f"{case_type}/{case_number}/{year}",
                "search_url": f"{self.search_url}?state_cd=1&dist_cd=1&court_code={court_code}&stateNm=Bombay",
                "instructions": "Please visit the court website manually to complete CAPTCHA verification"
            }
            
        except Exception as e:
            return {"error": f"Alternative lookup failed: {str(e)}"}
    
    def _parse_case_details(self, soup: BeautifulSoup, case_parts: Dict) -> Dict:
        """Parse case details from the court website response"""
        try:
            details = {
                "case_ref": f"{case_parts.get('case_type')}/{case_parts.get('case_number')}/{case_parts.get('year')}",
                "status": "found"
            }
            
            # Look for common case detail patterns
            tables = soup.find_all('table')
            for table in tables:
                rows = table.find_all('tr')
                for row in rows:
                    cells = row.find_all(['td', 'th'])
                    if len(cells) >= 2:
                        header = cells[0].get_text(strip=True).lower()
                        value = cells[1].get_text(strip=True)
                        
                        if 'petitioner' in header or 'appellant' in header:
                            details['petitioner'] = value
                        elif 'respondent' in header:
                            details['respondent'] = value
                        elif 'status' in header:
                            details['case_status'] = value
                        elif 'next' in header and 'date' in header:
                            details['next_date'] = value
                        elif 'stage' in header:
                            details['stage'] = value
            
            return details
            
        except Exception as e:
            return {"error": f"Failed to parse case details: {str(e)}"}

    def get_case_orders(self, case_ref: str, date: str = None) -> List[Dict]:
        """
        Fetch case orders for a specific case and date
        
        Args:
            case_ref: Case reference like 'WP/294/2025' 
            date: Specific date in YYYY-MM-DD format
            
        Returns:
            List of orders with details
        """
        try:
            case_parts = self.parse_case_number(case_ref)
            if not case_parts:
                return [{"error": "Invalid case reference format"}]
            
            # For now, return a mock structure showing what we'd expect
            # Once we solve the CAPTCHA issue, this will fetch real data
            return [{
                "status": "captcha_required",
                "message": "Order lookup requires manual CAPTCHA verification", 
                "case_ref": case_ref,
                "date": date,
                "instructions": "Please visit the court website manually to get case orders"
            }]
            
        except Exception as e:
            return [{"error": f"Failed to fetch orders: {str(e)}"}]
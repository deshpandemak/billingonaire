import logging
import os
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from pydantic import BaseModel, Field

try:
    from firecrawl import FirecrawlApp
except ImportError:
    FirecrawlApp = None


load_dotenv()


class FirecrawlCaseDetails(BaseModel):
    petitioner_name: Optional[str] = Field(default=None)
    petitioner_name_citation: Optional[str] = Field(default=None)
    respondent_name: Optional[str] = Field(default=None)
    respondent_name_citation: Optional[str] = Field(default=None)
    case_number: Optional[str] = Field(default=None)
    case_number_citation: Optional[str] = Field(default=None)
    case_status_url: Optional[str] = Field(default=None)
    case_status_url_citation: Optional[str] = Field(default=None)


class FirecrawlCourtOrder(BaseModel):
    listing_date: Optional[str] = Field(default=None)
    listing_date_citation: Optional[str] = Field(default=None)
    download_url: Optional[str] = Field(default=None)
    download_url_citation: Optional[str] = Field(default=None)
    order_description: Optional[str] = Field(default=None)
    order_description_citation: Optional[str] = Field(default=None)


class FirecrawlOrderExtraction(BaseModel):
    case_details: FirecrawlCaseDetails
    court_orders: List[FirecrawlCourtOrder] = Field(default_factory=list)


class BombayHighCourtScraper:
    """
    Scraper for Bombay High Court case details using the E-Courts system
    """

    def __init__(self):
        self.base_url = "https://hcservices.ecourts.gov.in/ecourtindiaHC"
        self.search_url = f"{self.base_url}/cases/case_no.php"
        self.bombay_high_court_url = "https://www.bombayhighcourt.nic.in"
        self.session = requests.Session()
        self.firecrawl_api_key = os.getenv("FIRECRAWL_API_KEY")
        self.firecrawl_model = os.getenv("FIRECRAWL_MODEL", "spark-1-mini")
        # Add timeout for all requests
        self.timeout = 30  # 30 seconds timeout
        # Set headers to mimic a real browser
        self.session.headers.update(
            {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.5",
                "Accept-Encoding": "gzip, deflate",
                "Connection": "keep-alive",
                "Referer": "https://hcservices.ecourts.gov.in/",
            }
        )

    def _normalize_case_ref(self, case_ref: str) -> str:
        """Normalize WP/3373/2025 to Civil Writ Petition 3373 of 2025."""
        case_parts = self.parse_case_number(case_ref)
        if not case_parts:
            return case_ref

        case_type_map = {
            "WP": "Civil Writ Petition",
            "WPL": "Writ Petition (L)",
            "PIL": "Public Interest Litigation",
            "APL": "Criminal Application",
        }
        case_type = case_type_map.get(case_parts["case_type"], case_parts["case_type"])
        return f"{case_type} {case_parts['case_number']} of {case_parts['year']}"

    def _build_firecrawl_prompt(self, case_ref: str) -> str:
        human_case_ref = self._normalize_case_ref(case_ref)
        return f"""
Extract case details and court orders from bombayhighcourt.nic.in for:
{human_case_ref}.

Return data exactly in this structure:
{{
  "case_details": {{
    "petitioner_name": "...",
    "petitioner_name_citation": "...",
    "respondent_name": "...",
    "respondent_name_citation": "...",
    "case_number": "...",
    "case_number_citation": "...",
    "case_status_url": "...",
    "case_status_url_citation": "..."
  }},
  "court_orders": [
    {{
      "listing_date": "DD/MM/YYYY",
      "listing_date_citation": "...",
      "download_url": "...",
      "download_url_citation": "...",
      "order_description": "...",
      "order_description_citation": "..."
    }}
  ]
}}

Navigation instructions:
1. Case Status -> Case Number Wise.
2. Resolve captcha if possible.
3. Open Listing Dates and extract all order rows.

Rules:
- Preserve full download URL values exactly.
- Keep court_orders as a list.
- Use null for missing values.
- Use citation URL values for each extracted field.
""".strip()

    def _parse_iso_date(self, value: str) -> Optional[datetime]:
        try:
            return datetime.strptime(value, "%Y-%m-%d")
        except (TypeError, ValueError):
            return None

    def _parse_listing_date(self, value: str) -> Optional[datetime]:
        if not value:
            return None
        formats = ["%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d", "%d %b %Y", "%d %B %Y"]
        for fmt in formats:
            try:
                return datetime.strptime(value.strip(), fmt)
            except ValueError:
                continue
        return None

    def _to_dict(self, result: Any) -> Dict[str, Any]:
        if isinstance(result, dict):
            return result
        if hasattr(result, "model_dump"):
            return result.model_dump()
        return {}

    def _normalize_firecrawl_payload(
        self, payload: Dict[str, Any], case_ref: str, date: Optional[str] = None
    ) -> Dict[str, Any]:
        citation_default = self.bombay_high_court_url
        case_details = payload.get("case_details") or {}
        raw_orders = payload.get("court_orders") or []
        expected_date = self._parse_iso_date(date) if date else None

        normalized_case_details = {
            "petitioner_name": case_details.get("petitioner_name"),
            "petitioner_name_citation": case_details.get("petitioner_name_citation")
            or citation_default,
            "respondent_name": case_details.get("respondent_name"),
            "respondent_name_citation": case_details.get("respondent_name_citation")
            or citation_default,
            "case_number": case_details.get("case_number") or case_ref,
            "case_number_citation": case_details.get("case_number_citation")
            or citation_default,
            "case_status_url": case_details.get("case_status_url")
            or f"{self.bombay_high_court_url}/casequery_action.php",
            "case_status_url_citation": case_details.get("case_status_url_citation")
            or citation_default,
        }

        normalized_orders: List[Dict[str, Optional[str]]] = []
        for order in raw_orders:
            if not isinstance(order, dict):
                continue

            listing_date = order.get("listing_date")
            if expected_date:
                parsed_listing_date = self._parse_listing_date(str(listing_date or ""))
                if (
                    not parsed_listing_date
                    or parsed_listing_date.date() != expected_date.date()
                ):
                    continue

            normalized_orders.append(
                {
                    "listing_date": listing_date,
                    "listing_date_citation": order.get("listing_date_citation")
                    or citation_default,
                    "download_url": order.get("download_url"),
                    "download_url_citation": order.get("download_url_citation")
                    or citation_default,
                    "order_description": order.get("order_description")
                    or "Order/Judg-1",
                    "order_description_citation": order.get(
                        "order_description_citation"
                    )
                    or citation_default,
                }
            )

        return {
            "status": "found" if normalized_orders else "not_found",
            "source": "firecrawl",
            "case_details": normalized_case_details,
            "court_orders": normalized_orders,
        }

    def _fetch_with_firecrawl(
        self, case_ref: str, date: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        if not self.firecrawl_api_key or FirecrawlApp is None:
            return None

        try:
            app = FirecrawlApp(api_key=self.firecrawl_api_key)
            result = app.agent(
                schema=FirecrawlOrderExtraction,
                prompt=self._build_firecrawl_prompt(case_ref),
                urls=[self.bombay_high_court_url],
                model=self.firecrawl_model,
            )

            payload = self._to_dict(result)
            if not payload:
                return None

            return self._normalize_firecrawl_payload(
                payload, case_ref=case_ref, date=date
            )
        except Exception as e:
            logging.error(f"Firecrawl extraction failed for {case_ref}: {e}")
            return None

    def parse_case_number(self, case_ref: str) -> Dict[str, str]:
        """
        Parse case reference like 'WP/294/2025' into components
        Returns: {'case_type': 'WP', 'case_number': '294', 'year': '2025'}
        """
        try:
            # Normalize input - convert to uppercase and strip whitespace
            case_ref = case_ref.strip().upper()

            # Pattern: CASE_TYPE/CASE_NUMBER/YEAR
            match = re.match(r"^([A-Z]+)\/(\d+)\/(\d{4})$", case_ref)
            if match:
                return {
                    "case_type": match.group(1),
                    "case_number": match.group(2),
                    "year": match.group(3),
                }
            else:
                raise ValueError(
                    f"Invalid case reference format: {case_ref}. Expected format: TYPE/NUMBER/YEAR (e.g., WP/294/2025)"
                )
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
                "mumbai": "2",  # Original Side, Mumbai
                "mumbai_appellate": "1",  # Appellate Side, Mumbai
                "aurangabad": "3",  # Aurangabad Bench
                "nagpur": "4",  # Nagpur Bench
                "goa": "5",  # Goa Bench
            }
            court_code = bench_codes.get(bench.lower(), "2")

            # Get the search form page first
            form_params = {
                "state_cd": "1",
                "dist_cd": "1",
                "court_code": court_code,
                "stateNm": "Bombay",
            }

            form_response = self.session.get(
                self.search_url, params=form_params, timeout=self.timeout
            )
            if form_response.status_code != 200:
                return {
                    "error": "Failed to access court website",
                    "status_code": form_response.status_code,
                }

            # Parse the form to get any hidden fields or session tokens
            # soup = BeautifulSoup(form_response.content, "html.parser")

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
            case_type = case_parts.get("case_type")
            case_number = case_parts.get("case_number")
            year = case_parts.get("year")

            # Try the case listing or order lookup endpoints
            # These might not require CAPTCHA

            # First attempt: Try direct case URL patterns used by some courts
            alt_urls = [
                f"{self.base_url}/cases/case_detail.php?case_type={case_type}&case_no={case_number}&case_year={year}&court_code={court_code}",
                f"{self.base_url}/order_list.php?case_type={case_type}&case_no={case_number}&case_year={year}&court_code={court_code}",
            ]

            for url in alt_urls:
                try:
                    response = self.session.get(url, timeout=self.timeout)
                    if response.status_code == 200 and "case" in response.text.lower():
                        soup = BeautifulSoup(response.content, "html.parser")
                        return self._parse_case_details(soup, case_parts)
                except Exception as e:
                    logging.debug(f"Alternative URL failed: {url}, error: {e}")
                    continue

            # If direct access fails, return a structured response indicating CAPTCHA requirement
            return {
                "status": "captcha_required",
                "message": "Case lookup requires manual CAPTCHA verification",
                "case_ref": f"{case_type}/{case_number}/{year}",
                "search_url": f"{self.search_url}?state_cd=1&dist_cd=1&court_code={court_code}&stateNm=Bombay",
                "instructions": "Please visit the court website manually to complete CAPTCHA verification",
            }

        except Exception as e:
            return {"error": f"Alternative lookup failed: {str(e)}"}

    def _parse_case_details(self, soup: BeautifulSoup, case_parts: Dict) -> Dict:
        """Parse case details from the court website response"""
        try:
            details = {
                "case_ref": f"{case_parts.get('case_type')}/{case_parts.get('case_number')}/{case_parts.get('year')}",
                "status": "found",
            }

            # Look for common case detail patterns
            tables = soup.find_all("table")
            for table in tables:
                rows = table.find_all("tr")
                for row in rows:
                    cells = row.find_all(["td", "th"])
                    if len(cells) >= 2:
                        header = cells[0].get_text(strip=True).lower()
                        value = cells[1].get_text(strip=True)

                        if "petitioner" in header or "appellant" in header:
                            details["petitioner"] = value
                        elif "respondent" in header:
                            details["respondent"] = value
                        elif "status" in header:
                            details["case_status"] = value
                        elif "next" in header and "date" in header:
                            details["next_date"] = value
                        elif "stage" in header:
                            details["stage"] = value

            return details

        except Exception as e:
            return {"error": f"Failed to parse case details: {str(e)}"}

    def get_case_orders(
        self, case_ref: str, date: Optional[str] = None, bench: str = "mumbai"
    ) -> Dict[str, Any]:
        """
        Fetch case orders for a specific case and date

        Args:
            case_ref: Case reference like 'WP/294/2025'
            date: Specific date in YYYY-MM-DD format
            bench: Court bench - 'mumbai', 'aurangabad', 'nagpur', 'goa'

        Returns:
            Structured case details and list of court orders
        """
        try:
            case_parts = self.parse_case_number(case_ref)
            if not case_parts:
                return {
                    "status": "error",
                    "error": "Invalid case reference format",
                    "case_details": {
                        "case_number": case_ref,
                        "case_number_citation": self.bombay_high_court_url,
                    },
                    "court_orders": [],
                }

            firecrawl_result = self._fetch_with_firecrawl(case_ref=case_ref, date=date)
            if firecrawl_result:
                return firecrawl_result

            # Set court code based on bench (same as case details)
            bench_codes = {
                "mumbai": "2",  # Original Side, Mumbai
                "mumbai_appellate": "1",  # Appellate Side, Mumbai
                "aurangabad": "3",  # Aurangabad Bench
                "nagpur": "4",  # Nagpur Bench
                "goa": "5",  # Goa Bench
            }
            court_code = bench_codes.get(bench.lower(), "2")

            # Fallback response when Firecrawl is not configured or cannot bypass captcha.
            return {
                "status": "captcha_required",
                "source": "ecourts_fallback",
                "message": "Court order lookup requires manual CAPTCHA verification",
                "case_details": {
                    "petitioner_name": None,
                    "petitioner_name_citation": self.bombay_high_court_url,
                    "respondent_name": None,
                    "respondent_name_citation": self.bombay_high_court_url,
                    "case_number": case_ref,
                    "case_number_citation": self.bombay_high_court_url,
                    "case_status_url": f"{self.search_url}?state_cd=1&dist_cd=1&court_code={court_code}&stateNm=Bombay",
                    "case_status_url_citation": self.bombay_high_court_url,
                },
                "court_orders": [],
                "bench": bench,
                "court_code": court_code,
                "instructions": "Please visit the court website manually to complete CAPTCHA verification and get case orders",
            }

        except Exception as e:
            return {
                "status": "error",
                "error": f"Failed to fetch orders: {str(e)}",
                "case_details": {
                    "case_number": case_ref,
                    "case_number_citation": self.bombay_high_court_url,
                },
                "court_orders": [],
            }

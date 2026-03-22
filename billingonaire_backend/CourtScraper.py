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
    respondent_name: Optional[str] = Field(default=None)
    case_number: Optional[str] = Field(default=None)


class FirecrawlCourtOrder(BaseModel):
    listing_date: Optional[str] = Field(default=None)
    download_url: Optional[str] = Field(default=None)


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

    def _build_firecrawl_prompt(
        self, case_ref: str, case_parts: Optional[Dict[str, str]] = None
    ) -> str:
        human_case_ref = self._normalize_case_ref(case_ref)
        case_type = (case_parts or {}).get("case_type", "")
        case_number = (case_parts or {}).get("case_number", "")
        case_year = (case_parts or {}).get("year", "")
        start_url = f"{self.base_url}/cases/case_no.php"
        return f"""
CRITICAL RESTRICTION — READ BEFORE DOING ANYTHING:
- You MUST NOT download, open, follow, fetch, or request any PDF or file URL at any point.
- You MUST NOT click any link in the "Order/Judgement" column — only read the href attribute value.
- There is NO date filter — collect ALL rows in the listing-dates table.

Task: Find case {human_case_ref} and return every court-order link from its Listing Dates page.

STEP-BY-STEP NAVIGATION (follow exactly in order):

Step 1 — Open the case-number search page:
  Go to: {start_url}
  (Or from the home page click "Case Status" → "Case Number Wise".)

Step 2 — Fill in the search form with these exact values:
  - Case Type  : {case_type}
  - Case Number: {case_number}
  - Year       : {case_year}
  - Bench      : Mumbai (High Court)
  Submit the form.

Step 3 — Handle CAPTCHA if shown, then re-submit.

Step 4 — On the case details page:
  The page header may show both a Stamp No. (e.g. WP/7203/{case_year}) and a
  Reg. No. (e.g. WP/{case_number}/{case_year}) — either is the correct case.
  Click the button or tab labelled exactly "Listing Dates"
  (it may also be labelled "Listing Dates/Orders", "Hearing Dates", or "View Orders").

Step 5 — On the Listing Dates table page you will see a table with these columns:
    Date | Coram | Action | Order/Judgement

  For EVERY data row in that table:
    a) Read the "Date" cell  → this is listing_date (format DD/MM/YYYY).
    b) Look at the "Order/Judgement" cell — it contains a link with text like
       "Order/Judg-1". DO NOT click it. Instead, read the href attribute of that
       link and store it as download_url.
  Collect ALL rows. Do not skip any row.

Return ONLY this JSON — nothing else:
{{
  "case_details": {{
    "petitioner_name": "...",
    "respondent_name": "...",
    "case_number": "..."
  }},
  "court_orders": [
    {{
      "listing_date": "DD/MM/YYYY",
      "download_url": "https://..."
    }}
  ]
}}

Rules:
- Copy the full URL from the href attribute exactly — do NOT shorten or modify it.
- court_orders must list ALL rows from the table (e.g. 3 rows → 3 entries).
- Use null only if a field is genuinely absent.
- NEVER open, fetch, or preview any PDF or linked file.
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
        case_details = payload.get("case_details") or {}
        raw_orders = payload.get("court_orders") or []

        normalized_case_details = {
            "petitioner_name": case_details.get("petitioner_name"),
            "respondent_name": case_details.get("respondent_name"),
            "case_number": case_details.get("case_number") or case_ref,
        }

        normalized_orders: List[Dict[str, Optional[str]]] = []
        for order in raw_orders:
            if not isinstance(order, dict):
                continue

            listing_date = order.get("listing_date")
            download_url = str(order.get("download_url") or "").strip()
            if not download_url:
                continue

            normalized_orders.append(
                {
                    "listing_date": listing_date,
                    "download_url": download_url,
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
        if not self.firecrawl_api_key:
            return None

        try:
            firecrawl_cls = FirecrawlApp
            if firecrawl_cls is None:
                try:
                    from firecrawl import FirecrawlApp as RuntimeFirecrawlApp

                    firecrawl_cls = RuntimeFirecrawlApp
                except ImportError as import_error:
                    logging.error(
                        "Firecrawl SDK unavailable at runtime for %s: %s",
                        case_ref,
                        import_error,
                    )
                    return None

            app = firecrawl_cls(api_key=self.firecrawl_api_key)
            case_parts = self.parse_case_number(case_ref) or {}
            prompt = self._build_firecrawl_prompt(case_ref, case_parts=case_parts)

            # Agent starts at the eCourts case-number search page; allow both domains.
            crawl_urls = [
                f"{self.base_url}/cases/case_no.php",
                f"{self.base_url}/*",
                f"{self.bombay_high_court_url}/*",
            ]
            if hasattr(app, "agent"):
                result = app.agent(
                    schema=FirecrawlOrderExtraction,
                    prompt=prompt,
                    urls=crawl_urls,
                    model=self.firecrawl_model,
                )
            elif hasattr(app, "extract"):
                schema = FirecrawlOrderExtraction.model_json_schema()
                result = app.extract(
                    urls=crawl_urls,
                    prompt=prompt,
                    schema=schema,
                    agent={"model": self.firecrawl_model},
                )
            else:
                logging.error("Firecrawl SDK missing both agent() and extract()")
                return None

            payload = self._to_dict(result)
            if not payload:
                return None

            # extract() responses usually wrap structured output under payload['data'].
            if isinstance(payload.get("data"), dict):
                payload = payload["data"]

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
            firecrawl_result = self._fetch_with_firecrawl(case_ref=case_ref, date=None)
            if firecrawl_result:
                case_details = firecrawl_result.get("case_details") or {}
                return {
                    "status": firecrawl_result.get("status") or "found",
                    "source": "firecrawl",
                    "case_ref": case_ref,
                    "case_number": case_details.get("case_number") or case_ref,
                    "petitioner": case_details.get("petitioner_name"),
                    "respondent": case_details.get("respondent_name"),
                    "case_status_url": case_details.get("case_status_url"),
                    "court_orders": firecrawl_result.get("court_orders") or [],
                }

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

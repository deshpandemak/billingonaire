import json
import logging
import os
import re
import time
from datetime import datetime
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, urlparse

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from pydantic import BaseModel, Field

try:
    from firecrawl import FirecrawlApp
except ImportError:
    FirecrawlApp = None

try:
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
    from playwright.sync_api import sync_playwright
except ImportError:
    PlaywrightTimeoutError = Exception  # type: ignore[misc,assignment]
    sync_playwright = None  # type: ignore[assignment]


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
        self.bombay_high_court_url = "https://bombayhighcourt.gov.in"
        self.bhc_case_status_url = (
            "https://bombayhighcourt.gov.in/bhc/casestatus/casenumber"
        )
        self.session = requests.Session()
        self.firecrawl_api_key = os.getenv("FIRECRAWL_API_KEY")
        self.firecrawl_model = os.getenv("FIRECRAWL_MODEL", "spark-1-mini")
        self.scraper_provider = (
            os.getenv("COURT_SCRAPER_PROVIDER", "playwright_first").strip().lower()
        )
        self.allow_firecrawl_fallback = (
            os.getenv("COURT_ALLOW_FIRECRAWL_FALLBACK", "true").strip().lower()
            == "true"
        )
        self.playwright_headless = (
            os.getenv("COURT_PLAYWRIGHT_HEADLESS", "true").strip().lower() == "true"
        )
        self.playwright_timeout_seconds = int(
            os.getenv("COURT_PLAYWRIGHT_TIMEOUT_SECONDS", "25")
        )
        self.ollama_base_url = (
            os.getenv("COURT_OLLAMA_BASE_URL")
            or os.getenv("OLLAMA_BASE_URL")
            or os.getenv("LLM_BASE_URL")
            or "http://localhost:11434"
        ).rstrip("/")
        self.ollama_model = (
            os.getenv("COURT_OLLAMA_MODEL")
            or os.getenv("ORDER_LLM_MODEL")
            or os.getenv("LLM_MODEL")
            or "llama3.2"
        )
        self.ollama_timeout_seconds = int(
            os.getenv("COURT_OLLAMA_TIMEOUT_SECONDS", "20")
        )
        self.ollama_health_timeout_seconds = int(
            os.getenv("COURT_OLLAMA_HEALTH_TIMEOUT_SECONDS", "8")
        )
        self.ollama_health_cache_ttl_seconds = int(
            os.getenv("COURT_OLLAMA_HEALTH_CACHE_TTL_SECONDS", "5")
        )
        self._ollama_health_cache: Optional[Dict[str, Any]] = None
        self._ollama_health_cache_at: float = 0.0
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

    def _get_stamp_regn_type(self, case_type: str) -> str:
        """
        Return the Stamp/Regn dropdown value for the court search form.

        Case types that end with "(ST)" (e.g. WP(ST)) indicate a Stamp
        number lookup; all others use the default Registration number lookup.
        """
        return "Stamp" if case_type.upper().endswith("(ST)") else "Registration"

    def _get_base_case_type(self, case_type: str) -> str:
        """
        Strip the '(ST)' suffix from the case type so it can be entered into
        the Case Type dropdown on the court search form (e.g. WP(ST) → WP).
        """
        return re.sub(r"\(ST\)$", "", case_type, flags=re.IGNORECASE).strip()

    def _get_stamp_regn_bhc(self, case_type: str) -> str:
        """
        Return the Stamp/Regn dropdown value for the new BHC case status portal
        (https://bombayhighcourt.gov.in/bhc/casestatus/casenumber).

        The portal uses "Register" for regular registration numbers and "Stamp"
        for stamp numbers (case types ending with "(ST)").
        """
        return "Stamp" if case_type.upper().endswith("(ST)") else "Register"

    def _get_side_code(self, bench: str = "mumbai") -> str:
        """
        Return the Side code for the BHC case status search form.

        The portal displays a "Side" dropdown.  Most writ/appellate matters are
        filed on the Appellate Side ("AS").  Original-side matters use "OS".
        """
        bench_side_map: Dict[str, str] = {
            "mumbai": "AS",
            "mumbai_appellate": "AS",
            "mumbai_original": "OS",
            "aurangabad": "AS",
            "nagpur": "AS",
            "goa": "AS",
        }
        return bench_side_map.get((bench or "mumbai").lower(), "AS")

    def _build_short_title(
        self,
        petitioner: Optional[str],
        respondent: Optional[str],
    ) -> Optional[str]:
        """
        Build a short case title in the form '<petitioner> against <respondent>'.

        Returns the petitioner or respondent alone when only one is available,
        and None when both are absent.
        """
        if petitioner and respondent:
            return f"{petitioner} against {respondent}"
        return petitioner or respondent or None

    def _supported_providers(self) -> List[str]:
        return [
            "playwright_first",
            "playwright_only",
            "playwright_then_ollama",
            "ollama_then_playwright",
            "firecrawl_first",
            "firecrawl_only",
            "ollama_first",
            "ollama_only",
        ]

    def get_scraper_config(self) -> Dict[str, Any]:
        return {
            "provider": self.scraper_provider,
            "supported_providers": self._supported_providers(),
            "allow_firecrawl_fallback": self.allow_firecrawl_fallback,
            "playwright": {
                "available": bool(sync_playwright),
                "headless": self.playwright_headless,
                "timeout_seconds": self.playwright_timeout_seconds,
            },
            "firecrawl": {
                "configured": bool(self.firecrawl_api_key),
                "model": self.firecrawl_model,
                "deprecated": True,
            },
            "ollama": {
                "base_url": self.ollama_base_url,
                "model": self.ollama_model,
                "timeout_seconds": self.ollama_timeout_seconds,
                "health_timeout_seconds": self.ollama_health_timeout_seconds,
            },
        }

    def configure_scraper(
        self,
        provider: Optional[str] = None,
        allow_firecrawl_fallback: Optional[bool] = None,
        ollama_base_url: Optional[str] = None,
        ollama_model: Optional[str] = None,
        ollama_timeout_seconds: Optional[int] = None,
    ) -> Dict[str, Any]:
        if provider is not None:
            normalized = provider.strip().lower()
            if normalized not in self._supported_providers():
                raise ValueError(
                    f"Unsupported scraper provider '{provider}'. "
                    f"Supported values: {', '.join(self._supported_providers())}"
                )
            self.scraper_provider = normalized

        if allow_firecrawl_fallback is not None:
            self.allow_firecrawl_fallback = bool(allow_firecrawl_fallback)

        if ollama_base_url is not None:
            normalized_base_url = ollama_base_url.strip().rstrip("/")
            # Avoid wiping a valid runtime configuration with blank input.
            if normalized_base_url:
                self.ollama_base_url = normalized_base_url

        if ollama_model is not None:
            self.ollama_model = ollama_model

        if ollama_timeout_seconds is not None:
            self.ollama_timeout_seconds = int(ollama_timeout_seconds)

        return self.get_scraper_config()

    def pull_ollama_model(self, model_name: Optional[str] = None) -> Dict[str, Any]:
        """
        Trigger an asynchronous model pull on the configured Ollama instance.

        Returns immediately with pull initiation status (not completion status).
        Model download may take several minutes depending on size.

        Args:
            model_name: Model name (e.g., 'llama3.1:8b').
                       Defaults to configured COURT_OLLAMA_MODEL.

        Returns:
            Dict with keys:
            - 'status': 'pulling' or error message
            - 'model': The model name being pulled
            - 'ollama_base_url': The Ollama endpoint URL
            - 'message': Human-readable status message
        """
        model = (model_name or self.ollama_model).strip()
        if not model:
            raise ValueError(
                "Model name not provided and no default configured. "
                "Set COURT_OLLAMA_MODEL or OLLAMA_MODEL environment variable."
            )

        if not self.ollama_base_url:
            raise ValueError(
                "Ollama base URL not configured. "
                "Set COURT_OLLAMA_BASE_URL or OLLAMA_BASE_URL environment variable."
            )

        try:
            pull_url = f"{self.ollama_base_url}/api/pull"
            payload = {"model": model}

            logging.info(
                f"Triggering Ollama model pull: {model} at {self.ollama_base_url}"
            )

            # POST with streaming disabled to get immediate response
            response = requests.post(
                pull_url,
                json=payload,
                timeout=self.ollama_timeout_seconds,
                stream=False,
            )
            response.raise_for_status()

            logging.info(
                f"Ollama pull initiated for {model}: HTTP {response.status_code}"
            )

            return {
                "status": "pulling",
                "model": model,
                "ollama_base_url": self.ollama_base_url,
                "message": f"Initiated pull of {model}. This may take several minutes.",
            }
        except requests.exceptions.Timeout:
            logging.error(
                f"Timeout pulling {model} from Ollama at {self.ollama_base_url}"
            )
            raise ValueError(
                f"Timeout connecting to Ollama at {self.ollama_base_url}. "
                "Ensure the endpoint is reachable and not overloaded."
            )
        except requests.exceptions.ConnectionError as e:
            logging.error(f"Connection error to Ollama: {e}")
            raise ValueError(
                f"Cannot reach Ollama at {self.ollama_base_url}. "
                "Check the URL and network connectivity."
            )
        except requests.exceptions.HTTPError as e:
            logging.error(f"HTTP error from Ollama: {e}")
            raise ValueError(f"Ollama returned error: {e.response.text}")

    def get_ollama_health(self) -> Dict[str, Any]:
        """
        Check if Ollama service is healthy and responsive.

        Returns:
            Dict with keys:
            - 'healthy': bool indicating if service is up
            - 'status': 'ok' or error message
            - 'base_url': The Ollama endpoint being checked
            - 'response_time_ms': How long the health check took
        """
        import time

        now = time.time()
        if (
            self._ollama_health_cache is not None
            and (now - self._ollama_health_cache_at)
            < self.ollama_health_cache_ttl_seconds
        ):
            cached_result = dict(self._ollama_health_cache)
            cached_result["cached"] = True
            return cached_result

        def _cache_and_return(payload: Dict[str, Any]) -> Dict[str, Any]:
            self._ollama_health_cache = dict(payload)
            self._ollama_health_cache_at = time.time()
            return payload

        if not self.ollama_base_url:
            return _cache_and_return(
                {
                    "healthy": False,
                    "status": "Ollama base URL not configured",
                    "base_url": None,
                    "response_time_ms": 0,
                }
            )

        start_time = time.time()
        try:
            health_url = f"{self.ollama_base_url}/api/tags"
            response = requests.get(
                health_url,
                timeout=self.ollama_health_timeout_seconds,
            )
            response_time_ms = (time.time() - start_time) * 1000

            if response.status_code == 200:
                logging.info(f"Ollama health check passed: {health_url}")
                return _cache_and_return(
                    {
                        "healthy": True,
                        "status": "ok",
                        "base_url": self.ollama_base_url,
                        "response_time_ms": int(response_time_ms),
                    }
                )
            else:
                logging.warning(f"Ollama health check returned {response.status_code}")
                return _cache_and_return(
                    {
                        "healthy": False,
                        "status": f"HTTP {response.status_code}",
                        "base_url": self.ollama_base_url,
                        "response_time_ms": int(response_time_ms),
                    }
                )
        except requests.exceptions.Timeout:
            response_time_ms = (time.time() - start_time) * 1000
            logging.warning("Ollama health check timed out")
            return _cache_and_return(
                {
                    "healthy": False,
                    "status": "timeout",
                    "base_url": self.ollama_base_url,
                    "response_time_ms": int(response_time_ms),
                }
            )
        except requests.exceptions.ConnectionError:
            response_time_ms = (time.time() - start_time) * 1000
            logging.warning(f"Cannot connect to Ollama at {self.ollama_base_url}")
            return _cache_and_return(
                {
                    "healthy": False,
                    "status": "connection_error",
                    "base_url": self.ollama_base_url,
                    "response_time_ms": int(response_time_ms),
                }
            )
        except Exception as e:
            response_time_ms = (time.time() - start_time) * 1000
            logging.error(f"Unexpected error checking Ollama health: {e}")
            return _cache_and_return(
                {
                    "healthy": False,
                    "status": str(e),
                    "base_url": self.ollama_base_url,
                    "response_time_ms": int(response_time_ms),
                }
            )

    def get_ollama_models(self) -> Dict[str, Any]:
        """
        Get list of available models on Ollama instance.

        Returns:
            Dict with keys:
            - 'models': List of model dicts with name, size, digest, etc.
            - 'healthy': bool if Ollama is reachable
            - 'status': 'ok' or error message
            - 'configured_model': The model that Billingonaire is configured to use
        """
        if not self.ollama_base_url:
            return {
                "models": [],
                "healthy": False,
                "status": "Ollama base URL not configured",
                "configured_model": self.ollama_model,
            }

        try:
            tags_url = f"{self.ollama_base_url}/api/tags"
            response = requests.get(
                tags_url,
                timeout=self.ollama_health_timeout_seconds,
            )

            if response.status_code == 200:
                data = response.json()
                models = data.get("models", [])
                logging.info(f"Retrieved {len(models)} models from Ollama")
                return {
                    "models": models or [],
                    "healthy": True,
                    "status": "ok",
                    "configured_model": self.ollama_model,
                    "available_model_names": [
                        m.get("name", "") for m in (models or [])
                    ],
                }
            else:
                logging.warning(f"Failed to get models: HTTP {response.status_code}")
                return {
                    "models": [],
                    "healthy": False,
                    "status": f"HTTP {response.status_code}",
                    "configured_model": self.ollama_model,
                }
        except requests.exceptions.Timeout:
            logging.warning("Timeout getting models from Ollama")
            return {
                "models": [],
                "healthy": False,
                "status": "timeout",
                "configured_model": self.ollama_model,
            }
        except requests.exceptions.ConnectionError:
            logging.warning(f"Cannot connect to Ollama at {self.ollama_base_url}")
            return {
                "models": [],
                "healthy": False,
                "status": "connection_error",
                "configured_model": self.ollama_model,
            }
        except Exception as e:
            logging.error(f"Error getting models from Ollama: {e}")
            return {
                "models": [],
                "healthy": False,
                "status": str(e),
                "configured_model": self.ollama_model,
            }

    def _get_bench_code(self, bench: str) -> str:
        bench_codes = {
            "mumbai": "2",  # Original Side, Mumbai
            "mumbai_appellate": "1",  # Appellate Side, Mumbai
            "aurangabad": "3",  # Aurangabad Bench
            "nagpur": "4",  # Nagpur Bench
            "goa": "5",  # Goa Bench
        }
        return bench_codes.get((bench or "mumbai").lower(), "2")

    def _build_candidate_urls(
        self, case_parts: Dict[str, str], court_code: str
    ) -> List[str]:
        case_type = case_parts.get("case_type")
        case_number = case_parts.get("case_number")
        year = case_parts.get("year")
        # Start from the new BHC case-number search portal (primary entry point).
        # Fall back to the legacy eCourts search page and direct case/order URLs.
        return [
            self.bhc_case_status_url,
            f"{self.search_url}?state_cd=1&dist_cd=1&court_code={court_code}&stateNm=Bombay",
            f"{self.base_url}/cases/case_detail.php?case_type={case_type}&case_no={case_number}&case_year={year}&court_code={court_code}",
            f"{self.base_url}/order_list.php?case_type={case_type}&case_no={case_number}&case_year={year}&court_code={court_code}",
        ]

    def _extract_links_from_html(
        self, html: str, source_url: str
    ) -> List[Dict[str, Optional[str]]]:
        soup = BeautifulSoup(html or "", "html.parser")
        rows: List[Dict[str, Optional[str]]] = []

        for anchor in soup.find_all("a", href=True):
            href = anchor.get("href") or ""
            text = (anchor.get_text(" ", strip=True) or "").lower()
            href_lower = href.lower()

            is_order_like = (
                ".pdf" in href_lower
                or "order" in href_lower
                or "judg" in href_lower
                or "judgment" in href_lower
                or "ordjud" in href_lower
                or "order" in text
                or "judg" in text
            )
            if not is_order_like:
                continue

            abs_url = requests.compat.urljoin(source_url, href)
            rows.append(
                {
                    "listing_date": None,
                    "download_url": abs_url,
                }
            )

        dedup: Dict[str, Dict[str, Optional[str]]] = {}
        for row in rows:
            url = (row.get("download_url") or "").strip()
            if not url:
                continue
            dedup[url] = row
        return list(dedup.values())

    def _extract_case_meta_from_html(
        self, html: str, case_ref: str
    ) -> Dict[str, Optional[str]]:
        soup = BeautifulSoup(html or "", "html.parser")
        text = soup.get_text("\n", strip=True)

        petitioner = None
        respondent = None

        petitioner_match = re.search(
            r"(?:petitioner|appellant)\s*[:\-]?\s*([^\n]{3,120})",
            text,
            flags=re.IGNORECASE,
        )
        if petitioner_match:
            petitioner = petitioner_match.group(1).strip()

        respondent_match = re.search(
            r"(?:respondent|defendant)\s*[:\-]?\s*([^\n]{3,120})",
            text,
            flags=re.IGNORECASE,
        )
        if respondent_match:
            respondent = respondent_match.group(1).strip()

        return {
            "petitioner_name": petitioner,
            "respondent_name": respondent,
            "case_number": case_ref,
        }

    def _build_ollama_extraction_prompt(
        self, case_ref: str, html_chunks: List[str]
    ) -> str:
        case_parts = self.parse_case_number(case_ref) or {}
        raw_case_type = case_parts.get("case_type", "")
        base_case_type = self._get_base_case_type(raw_case_type)
        stamp_regn = self._get_stamp_regn_bhc(raw_case_type)
        case_number = case_parts.get("case_number", "")
        case_year = case_parts.get("year", "")
        combined = "\n\n---PAGE-CHUNK---\n\n".join(html_chunks[:3])
        return f"""
Extract court-order links for case {case_ref} from the HTML text below.

The HTML was fetched by navigating the Bombay High Court case status portal:
1. Navigate directly to: {self.bhc_case_status_url}
2. Fill in the search form:
   - Side        : AS   (Appellate Side)
   - Stamp/Regn. : {stamp_regn}  (use "Stamp" when case type ends with "(ST)", else "Register")
   - Type        : {base_case_type}
   - Number      : {case_number}
   - Year        : {case_year}
   - Click the Search button
3. On the case details page: read the petitioner and respondent names and the full case summary text
4. Click the "Orders/Judgements" tab/button to view the orders table
5. The orders table has columns: Date | Order link

Return ONLY valid JSON in this shape:
{{
  "case_details": {{
    "petitioner_name": null,
    "respondent_name": null,
    "case_number": "{case_ref}",
    "case_summary": null,
    "title": null
  }},
  "court_orders": [
    {{
      "listing_date": null,
      "download_url": "https://..."
    }}
  ]
}}

Rules:
- Extract petitioner and respondent names from the case details section if present.
- Extract the full case summary sentence (e.g. "Case No. WP/3373/2025 with CNR No. ..., was filed on DD/MM/YYYY...").
- Set "title" to "<petitioner> against <respondent>" when both are available.
- Include only probable order/judgement links from the orders table.
- The order column contains links — extract their href values as download_url.
- The date column provides the listing_date (format DD/MM/YYYY).
- Do not invent URLs.
- If no order links are present, return an empty court_orders array.

HTML text:
{combined[:14000]}
""".strip()

    def _parse_ollama_order_response(
        self, llm_text: str, case_ref: str
    ) -> Dict[str, Any]:
        cleaned_text = re.sub(r"```(?:json)?\s*", "", llm_text or "")
        cleaned_text = re.sub(r"```\s*$", "", cleaned_text, flags=re.MULTILINE)

        parsed = None
        parse_error = None
        try:
            parsed = json.loads(cleaned_text)
        except json.JSONDecodeError:
            block = re.search(r"\{[\s\S]*\}", cleaned_text)
            if block:
                try:
                    parsed = json.loads(block.group())
                except json.JSONDecodeError as exc:
                    parse_error = str(exc)
            else:
                parse_error = "No JSON object found in Ollama response"

        normalized = None
        if isinstance(parsed, dict):
            normalized = self._normalize_firecrawl_payload(parsed, case_ref=case_ref)

        return {
            "cleaned_text": cleaned_text,
            "parsed": parsed if isinstance(parsed, dict) else None,
            "normalized": normalized,
            "parse_error": parse_error,
        }

    def _call_ollama_for_orders(
        self, case_ref: str, html_chunks: List[str]
    ) -> Optional[Dict[str, Any]]:
        if not html_chunks:
            return None

        prompt = self._build_ollama_extraction_prompt(case_ref, html_chunks)
        payload = {
            "model": self.ollama_model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0},
        }
        try:
            response = requests.post(
                f"{self.ollama_base_url}/api/generate",
                json=payload,
                timeout=self.ollama_timeout_seconds,
            )
            if response.status_code != 200:
                logging.warning(
                    "Ollama returned HTTP %s for case %s",
                    response.status_code,
                    case_ref,
                )
                return None

            llm_text = (response.json() or {}).get("response", "").strip()
            if not llm_text:
                return None

            parsed_payload = self._parse_ollama_order_response(llm_text, case_ref)
            return parsed_payload.get("normalized")
        except Exception as exc:
            logging.warning(
                "Ollama order-link extraction failed for %s: %s", case_ref, exc
            )
            return None

    def debug_case_orders(
        self,
        case_ref: str,
        date: Optional[str] = None,
        bench: str = "mumbai",
        compare_all: bool = False,
    ) -> Dict[str, Any]:
        try:
            return self._debug_case_orders_impl(
                case_ref=case_ref, date=date, bench=bench, compare_all=compare_all
            )
        except Exception as exc:
            logging.error(
                "Unexpected error in debug_case_orders for %s: %s", case_ref, exc
            )
            return {
                "ok": False,
                "error": str(exc),
                "request": {
                    "case_ref": case_ref,
                    "date": date,
                    "bench": bench,
                },
            }

    def _debug_case_orders_impl(
        self,
        case_ref: str,
        date: Optional[str] = None,
        bench: str = "mumbai",
        compare_all: bool = False,
    ) -> Dict[str, Any]:
        case_parts = self.parse_case_number(case_ref)
        if not case_parts:
            return {
                "ok": False,
                "error": "Invalid case reference format",
                "request": {
                    "case_ref": case_ref,
                    "date": date,
                    "bench": bench,
                },
            }

        court_code = self._get_bench_code(bench)
        urls = self._build_candidate_urls(case_parts, court_code)

        html_chunks: List[str] = []
        direct_orders: List[Dict[str, Optional[str]]] = []
        traces: List[Dict[str, Any]] = []

        for url in urls:
            trace: Dict[str, Any] = {
                "url": url,
                "status_code": None,
                "response_url": None,
                "content_length": 0,
                "html_preview": "",
                "extracted_order_count": 0,
                "extracted_case_meta": {},
            }
            try:
                resp = self.session.get(url, timeout=self.timeout)
                html = resp.text or ""

                trace["status_code"] = resp.status_code
                trace["response_url"] = getattr(resp, "url", url)
                trace["content_length"] = len(html)
                trace["html_preview"] = html[:1200]

                if resp.status_code == 200 and html.strip():
                    extracted_orders = self._extract_links_from_html(html, url)
                    extracted_meta = self._extract_case_meta_from_html(html, case_ref)
                    trace["extracted_order_count"] = len(extracted_orders)
                    trace["extracted_case_meta"] = extracted_meta
                    direct_orders.extend(extracted_orders)
                    html_chunks.append(html[:8000])
            except Exception as exc:
                trace["error"] = str(exc)

            traces.append(trace)

        prompt = self._build_ollama_extraction_prompt(case_ref, html_chunks)
        ollama_request: Dict[str, Any] = {
            "base_url": self.ollama_base_url,
            "model": self.ollama_model,
            "timeout_seconds": self.ollama_timeout_seconds,
            "html_chunk_count": len(html_chunks),
            "prompt_preview": prompt[:8000],
        }
        ollama_response: Dict[str, Any] = {
            "status_code": None,
            "raw_response": None,
            "parsed": None,
            "normalized": None,
            "parse_error": None,
            "error": None,
        }

        if html_chunks:
            payload = {
                "model": self.ollama_model,
                "prompt": prompt,
                "stream": False,
                "options": {"temperature": 0},
            }
            try:
                response = requests.post(
                    f"{self.ollama_base_url}/api/generate",
                    json=payload,
                    timeout=self.ollama_timeout_seconds,
                )
                ollama_response["status_code"] = response.status_code
                if response.status_code != 200:
                    ollama_response[
                        "error"
                    ] = f"Ollama returned HTTP {response.status_code}"
                else:
                    llm_text = (response.json() or {}).get("response", "").strip()
                    ollama_response["raw_response"] = llm_text[:8000]
                    parsed_payload = self._parse_ollama_order_response(
                        llm_text, case_ref
                    )
                    ollama_response["parsed"] = parsed_payload.get("parsed")
                    ollama_response["normalized"] = parsed_payload.get("normalized")
                    ollama_response["parse_error"] = parsed_payload.get("parse_error")
            except Exception as exc:
                ollama_response["error"] = str(exc)

        provider_debug = self._fetch_with_provider(
            case_ref=case_ref,
            date=date,
            bench=bench,
            include_diagnostics=True,
        )

        provider_matrix: List[Dict[str, Any]] = []
        if compare_all:
            provider_matrix = self._probe_provider_matrix(
                case_ref=case_ref,
                date=date,
                bench=bench,
            )

        final_result = self.get_case_orders(case_ref=case_ref, date=date, bench=bench)
        return {
            "ok": True,
            "request": {
                "case_ref": case_ref,
                "date": date,
                "bench": bench,
                "court_code": court_code,
            },
            "scraper_config": self.get_scraper_config(),
            "candidate_urls": urls,
            "http_trace": traces,
            "ollama_request": ollama_request,
            "ollama_response": ollama_response,
            "provider_sequence": provider_debug.get("provider_sequence") or [],
            "provider_attempts": provider_debug.get("provider_attempts") or [],
            "provider_matrix": provider_matrix,
            "direct_order_count": len(direct_orders),
            "final_result": final_result,
        }

    def _provider_attempt_sequence(self, provider: str) -> List[str]:
        normalized = (provider or "playwright_first").lower()
        if normalized == "ollama_only":
            return ["ollama"]
        if normalized == "ollama_first":
            return ["ollama", "playwright", "firecrawl"]
        if normalized == "ollama_then_playwright":
            return ["ollama", "playwright"]
        if normalized == "firecrawl_only":
            return ["firecrawl"]
        if normalized == "firecrawl_first":
            return ["playwright", "firecrawl", "ollama"]
        if normalized == "playwright_only":
            return ["playwright"]
        if normalized == "playwright_then_ollama":
            return ["playwright", "ollama"]
        return ["playwright", "ollama", "firecrawl"]

    def _run_provider_attempts(
        self,
        case_ref: str,
        date: Optional[str],
        bench: str,
        provider: str,
    ) -> Dict[str, Any]:
        sequence = self._provider_attempt_sequence(provider)
        attempts: List[Dict[str, Any]] = []
        final_result: Optional[Dict[str, Any]] = None

        for index, attempt_provider in enumerate(sequence, start=1):
            start = time.time()
            if (
                attempt_provider == "firecrawl"
                and not self.allow_firecrawl_fallback
                and provider != "firecrawl_only"
            ):
                attempts.append(
                    {
                        "step": index,
                        "provider": attempt_provider,
                        "status": "skipped",
                        "reason": "firecrawl_fallback_disabled",
                        "duration_ms": 0,
                    }
                )
                continue

            try:
                if attempt_provider == "playwright":
                    result = self._fetch_with_playwright(
                        case_ref=case_ref,
                        date=date,
                        bench=bench,
                    )
                elif attempt_provider == "ollama":
                    result = self._fetch_with_ollama_scraper(
                        case_ref=case_ref,
                        date=date,
                        bench=bench,
                    )
                else:
                    result = self._fetch_with_firecrawl(case_ref=case_ref, date=date)

                duration_ms = int((time.time() - start) * 1000)
                if result:
                    attempts.append(
                        {
                            "step": index,
                            "provider": attempt_provider,
                            "status": "success",
                            "source": result.get("source"),
                            "final_status": result.get("status"),
                            "orders_found": len(result.get("court_orders") or []),
                            "duration_ms": duration_ms,
                        }
                    )
                    final_result = result
                    break

                attempts.append(
                    {
                        "step": index,
                        "provider": attempt_provider,
                        "status": "no_result",
                        "duration_ms": duration_ms,
                    }
                )
            except Exception as exc:
                attempts.append(
                    {
                        "step": index,
                        "provider": attempt_provider,
                        "status": "error",
                        "error": str(exc),
                        "duration_ms": int((time.time() - start) * 1000),
                    }
                )

        return {
            "provider": provider,
            "provider_sequence": sequence,
            "provider_attempts": attempts,
            "result": final_result,
        }

    def _probe_provider_matrix(
        self,
        case_ref: str,
        date: Optional[str],
        bench: str,
    ) -> List[Dict[str, Any]]:
        matrix_providers = [
            "playwright_first",
            "playwright_only",
            "playwright_then_ollama",
            "ollama_then_playwright",
            "ollama_only",
            "firecrawl_only",
        ]
        matrix: List[Dict[str, Any]] = []
        for matrix_provider in matrix_providers:
            run = self._run_provider_attempts(
                case_ref=case_ref,
                date=date,
                bench=bench,
                provider=matrix_provider,
            )
            result = run.get("result") or {}
            matrix.append(
                {
                    "provider": matrix_provider,
                    "worked": bool(run.get("result")),
                    "source": result.get("source"),
                    "final_status": result.get("status"),
                    "orders_found": len(result.get("court_orders") or []),
                    "provider_sequence": run.get("provider_sequence") or [],
                    "provider_attempts": run.get("provider_attempts") or [],
                }
            )
        return matrix

    def _fetch_with_ollama_scraper(
        self, case_ref: str, date: Optional[str] = None, bench: str = "mumbai"
    ) -> Optional[Dict[str, Any]]:
        case_parts = self.parse_case_number(case_ref)
        if not case_parts:
            return None

        court_code = self._get_bench_code(bench)
        urls = self._build_candidate_urls(case_parts, court_code)

        html_chunks: List[str] = []
        direct_orders: List[Dict[str, Optional[str]]] = []
        case_details: Dict[str, Optional[str]] = {
            "petitioner_name": None,
            "respondent_name": None,
            "case_number": case_ref,
        }

        for url in urls:
            try:
                resp = self.session.get(url, timeout=self.timeout)
                if resp.status_code != 200:
                    continue
                html = resp.text or ""
                if not html.strip():
                    continue

                html_chunks.append(html[:8000])
                direct_orders.extend(self._extract_links_from_html(html, url))
                extracted_meta = self._extract_case_meta_from_html(html, case_ref)
                if extracted_meta.get("petitioner_name") and not case_details.get(
                    "petitioner_name"
                ):
                    case_details["petitioner_name"] = extracted_meta["petitioner_name"]
                if extracted_meta.get("respondent_name") and not case_details.get(
                    "respondent_name"
                ):
                    case_details["respondent_name"] = extracted_meta["respondent_name"]
            except Exception:
                continue

        normalized: Dict[str, Any] = {
            "status": "found" if direct_orders else "not_found",
            "source": "ollama_scraper",
            "case_details": case_details,
            "court_orders": direct_orders,
        }

        llm_result = self._call_ollama_for_orders(case_ref, html_chunks)
        if llm_result:
            merged: Dict[str, Dict[str, Optional[str]]] = {
                (row.get("download_url") or ""): row
                for row in normalized.get("court_orders", [])
                if row.get("download_url")
            }
            for row in llm_result.get("court_orders", []):
                url = (row.get("download_url") or "").strip()
                if not url:
                    continue
                merged[url] = {
                    "listing_date": row.get("listing_date"),
                    "download_url": url,
                }
            normalized["court_orders"] = list(merged.values())
            normalized["status"] = (
                "found" if normalized["court_orders"] else normalized["status"]
            )

            llm_case = llm_result.get("case_details") or {}
            normalized["case_details"] = {
                "petitioner_name": llm_case.get("petitioner_name")
                or normalized["case_details"].get("petitioner_name"),
                "respondent_name": llm_case.get("respondent_name")
                or normalized["case_details"].get("respondent_name"),
                "case_number": llm_case.get("case_number")
                or normalized["case_details"].get("case_number")
                or case_ref,
            }

        if normalized["court_orders"]:
            return normalized
        return None

    def _fetch_with_provider(
        self,
        case_ref: str,
        date: Optional[str] = None,
        bench: str = "mumbai",
        include_diagnostics: bool = False,
    ) -> Any:
        provider = (self.scraper_provider or "playwright_first").lower()
        diagnostics = self._run_provider_attempts(
            case_ref=case_ref,
            date=date,
            bench=bench,
            provider=provider,
        )
        if include_diagnostics:
            return diagnostics
        return diagnostics.get("result")

    def _looks_like_captcha(self, html: str) -> bool:
        snippet = (html or "").lower()
        return "captcha" in snippet or "security code" in snippet

    def _extract_listing_date_from_anchor_context(
        self,
        anchor: Any,
    ) -> Optional[str]:
        date_match = re.search(
            r"\b(\d{2}[/-]\d{2}[/-]\d{4})\b",
            anchor.get_text(" ", strip=True) or "",
        )
        if date_match:
            return date_match.group(1)

        parent_row = anchor.find_parent("tr")
        if not parent_row:
            return None

        row_text = parent_row.get_text(" ", strip=True)
        row_date_match = re.search(r"\b(\d{2}[/-]\d{2}[/-]\d{4})\b", row_text)
        if row_date_match:
            return row_date_match.group(1)
        return None

    def _extract_case_status_url(self, url: str) -> Optional[str]:
        parsed = urlparse(url or "")
        if not parsed.scheme:
            return None
        if "case" not in (parsed.path or "").lower():
            return None
        return url

    def _extract_case_ref_from_url(self, url: str) -> Optional[str]:
        parsed = urlparse(url or "")
        query = parse_qs(parsed.query)
        case_type = (query.get("case_type") or [""])[0].strip().upper()
        case_no = (query.get("case_no") or [""])[0].strip()
        case_year = (query.get("case_year") or [""])[0].strip()
        if case_type and case_no and case_year:
            return f"{case_type}/{case_no}/{case_year}"
        return None

    def _extract_order_rows_from_html(
        self, html: str, source_url: str
    ) -> List[Dict[str, Optional[str]]]:
        soup = BeautifulSoup(html or "", "html.parser")
        rows: List[Dict[str, Optional[str]]] = []
        for anchor in soup.find_all("a", href=True):
            href = anchor.get("href") or ""
            text = (anchor.get_text(" ", strip=True) or "").lower()
            href_lower = href.lower()
            if not (
                ".pdf" in href_lower
                or "order" in href_lower
                or "judg" in href_lower
                or "order" in text
                or "judg" in text
            ):
                continue

            rows.append(
                {
                    "listing_date": self._extract_listing_date_from_anchor_context(
                        anchor
                    ),
                    "download_url": requests.compat.urljoin(source_url, href),
                }
            )

        dedup: Dict[str, Dict[str, Optional[str]]] = {}
        for row in rows:
            url = (row.get("download_url") or "").strip()
            if not url:
                continue
            dedup[url] = row
        return list(dedup.values())

    def _playwright_try_select(
        self, page: Any, selectors: List[str], value: str, timeout_ms: int = 2000
    ) -> bool:
        """
        Attempt to select *value* from a dropdown using each selector in turn.

        Returns True on the first successful selection, False if all selectors fail.
        """
        for sel in selectors:
            try:
                locator = page.locator(sel).first
                locator.select_option(value, timeout=timeout_ms)
                return True
            except Exception:
                continue
        return False

    def _playwright_try_fill(
        self, page: Any, selectors: List[str], value: str, timeout_ms: int = 2000
    ) -> bool:
        """
        Attempt to fill *value* into an input using each selector in turn.

        Returns True on the first successful fill, False if all selectors fail.
        """
        for sel in selectors:
            try:
                locator = page.locator(sel).first
                locator.fill(value, timeout=timeout_ms)
                return True
            except Exception:
                continue
        return False

    def _playwright_fill_bhc_form(
        self,
        page: Any,
        side_code: str,
        stamp_regn: str,
        case_type: str,
        case_number: str,
        case_year: str,
    ) -> None:
        """
        Fill the case-number search form on the BHC portal
        (https://bombayhighcourt.gov.in/bhc/casestatus/casenumber).

        Uses prioritised lists of selectors so the scraper degrades gracefully
        when the portal HTML changes.
        """
        # Side dropdown (e.g. "AS" = Appellate Side, "OS" = Original Side)
        self._playwright_try_select(
            page,
            [
                "select[id*='side' i]",
                "select[name*='side' i]",
                "select[formcontrolname*='side' i]",
                "mat-select[formcontrolname*='side' i]",
                "select >> nth=0",
            ],
            side_code,
        )

        # Stamp/Regn. dropdown ("Register" or "Stamp")
        self._playwright_try_select(
            page,
            [
                "select[id*='stamp' i]",
                "select[id*='regn' i]",
                "select[name*='stamp' i]",
                "select[name*='regn' i]",
                "select[formcontrolname*='stamp' i]",
                "select[formcontrolname*='regn' i]",
                "select >> nth=1",
            ],
            stamp_regn,
        )

        # Type (case type) dropdown
        self._playwright_try_select(
            page,
            [
                "select[id*='type' i]",
                "select[name*='type' i]",
                "select[id*='ctype' i]",
                "select[name*='ctype' i]",
                "select[formcontrolname*='type' i]",
                "select >> nth=2",
            ],
            case_type,
        )

        # Number (case number) input
        self._playwright_try_fill(
            page,
            [
                "input[id*='number' i]",
                "input[name*='number' i]",
                "input[id*='cno' i]",
                "input[name*='cno' i]",
                "input[placeholder*='number' i]",
                "input[formcontrolname*='number' i]",
                "input[formcontrolname*='cno' i]",
            ],
            case_number,
        )

        # Year input
        self._playwright_try_fill(
            page,
            [
                "input[id*='year' i]",
                "input[name*='year' i]",
                "input[placeholder*='year' i]",
                "input[formcontrolname*='year' i]",
            ],
            case_year,
        )

    def _playwright_click_search(self, page: Any, timeout_ms: int) -> None:
        """Click the Search button on the BHC case status form."""
        search_selectors = [
            "button[type='submit']",
            "input[type='submit']",
            "button:has-text('Search')",
            "button:has-text('search')",
            "a:has-text('Search')",
            "[class*='search' i]",
        ]
        for sel in search_selectors:
            try:
                page.click(sel, timeout=3000)
                page.wait_for_load_state("domcontentloaded", timeout=timeout_ms)
                return
            except Exception:
                continue

    def _playwright_click_orders_tab(self, page: Any, timeout_ms: int) -> None:
        """
        Click the Orders/Judgements tab on the BHC case details page.

        Tries several text patterns used by the portal for this button/tab.
        """
        orders_selectors = [
            "text=Orders/Judgements",
            "text=Orders / Judgements",
            "text=Judgements",
            "text=Orders",
            "text=Listing Dates/Order",
            "text=View Orders",
            "text=Listing Dates",
            "a:has-text('Order')",
            "button:has-text('Order')",
            "a:has-text('Judgement')",
            "button:has-text('Judgement')",
        ]
        for sel in orders_selectors:
            try:
                page.click(sel, timeout=3000)
                page.wait_for_load_state("domcontentloaded", timeout=timeout_ms)
                return
            except Exception:
                continue

    def _playwright_extract_case_summary(self, page: Any, html: str) -> Optional[str]:
        """
        Extract the full case summary sentence from the BHC case details page.

        The summary typically reads:
        "Case No. WP/3373/2025 with CNR No. HCBM010116572025, was filed on
         26/02/2025 at Bombay High Court by <petitioner> against <respondent>"
        """
        soup = BeautifulSoup(html or "", "html.parser")
        text = soup.get_text(" ", strip=True)

        # Pattern 1: "Case No. … was filed on … by … against …"
        summary_match = re.search(
            r"(Case\s+No\.?\s+[A-Z]+/\d+/\d{4}[^.]*?(?:was\s+filed[^.]*?\.))",
            text,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if summary_match:
            return summary_match.group(1).strip()

        # Pattern 2: Any sentence containing "CNR No."
        cnr_match = re.search(
            r"(Case[^.]*?CNR\s+No\.?\s+[A-Z0-9]+[^.]*\.)",
            text,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if cnr_match:
            return cnr_match.group(1).strip()

        # Pattern 3: Try JavaScript to get relevant text visible on the page
        try:
            summary_js = page.evaluate(
                """() => {
                    const selectors = [
                        '[class*="case-summary" i]',
                        '[class*="casedetail" i]',
                        '[class*="case-detail" i]',
                        '[id*="case-summary" i]',
                        '[id*="caseSummary" i]',
                    ];
                    for (const sel of selectors) {
                        const el = document.querySelector(sel);
                        if (el) return el.innerText.trim();
                    }
                    return null;
                }"""
            )
            if summary_js and len(summary_js) > 20:
                return summary_js.strip()
        except Exception:
            pass

        return None

    def _playwright_extract_parties(
        self, page: Any, html: str, case_ref: str
    ) -> Dict[str, Optional[str]]:
        """
        Extract petitioner and respondent from the BHC case details page.

        Extends the base regex extraction with Playwright JS evaluation for
        portal-specific DOM patterns.
        """
        meta = self._extract_case_meta_from_html(html, case_ref)
        petitioner = meta.get("petitioner_name")
        respondent = meta.get("respondent_name")

        if not (petitioner and respondent):
            # Try JS evaluation for Angular/React rendered content
            try:
                parties_js = page.evaluate(
                    """() => {
                        const getText = (sel) => {
                            const el = document.querySelector(sel);
                            return el ? el.innerText.trim() : null;
                        };
                        return {
                            petitioner: getText('[class*="petitioner" i]')
                                || getText('[id*="petitioner" i]')
                                || getText('[class*="appellant" i]'),
                            respondent: getText('[class*="respondent" i]')
                                || getText('[id*="respondent" i]')
                                || getText('[class*="defendant" i]'),
                        };
                    }"""
                )
                if parties_js:
                    petitioner = petitioner or parties_js.get("petitioner")
                    respondent = respondent or parties_js.get("respondent")
            except Exception:
                pass

        return {
            "petitioner_name": petitioner,
            "respondent_name": respondent,
        }

    def _playwright_extract_orders_from_table(
        self, page: Any, html: str, current_url: str
    ) -> List[Dict[str, Optional[str]]]:
        """
        Extract order rows from the Orders/Judgements table on the BHC portal.

        Tries:
        1. DOM inspection via JavaScript for Angular/React rendered tables.
        2. Falls back to HTML parsing via _extract_order_rows_from_html().
        """
        orders: Dict[str, Dict[str, Optional[str]]] = {}

        # Attempt 1: JS-based extraction of rendered table rows
        try:
            rows_js = page.evaluate(
                """() => {
                    const results = [];
                    // Look for table rows that contain order links
                    const rows = document.querySelectorAll('tr');
                    for (const row of rows) {
                        const anchors = row.querySelectorAll('a[href]');
                        if (!anchors.length) continue;
                        // Date cell (first or second td)
                        const cells = row.querySelectorAll('td');
                        let dateText = null;
                        for (const cell of cells) {
                            const t = cell.innerText.trim();
                            if (/\\d{2}[\\/-]\\d{2}[\\/-]\\d{4}/.test(t)) {
                                dateText = t.match(/\\d{2}[\\/-]\\d{2}[\\/-]\\d{4}/)[0];
                                break;
                            }
                        }
                        for (const a of anchors) {
                            const href = a.href || a.getAttribute('href');
                            const txt = (a.innerText || '').toLowerCase();
                            if (!href) continue;
                            const lhref = href.toLowerCase();
                            if (lhref.includes('.pdf') || lhref.includes('order')
                                    || lhref.includes('judg') || txt.includes('order')
                                    || txt.includes('judg')) {
                                results.push({date: dateText, href: href});
                            }
                        }
                    }
                    return results;
                }"""
            )
            for item in rows_js or []:
                href = (item.get("href") or "").strip()
                if not href:
                    continue
                orders[href] = {
                    "listing_date": item.get("date"),
                    "download_url": href,
                }
        except Exception:
            pass

        # Attempt 2: HTML-based extraction as fallback
        for row in self._extract_order_rows_from_html(html, current_url):
            row_url = (row.get("download_url") or "").strip()
            if row_url and row_url not in orders:
                orders[row_url] = row

        return list(orders.values())

    def _fetch_with_playwright(
        self,
        case_ref: str,
        date: Optional[str] = None,
        bench: str = "mumbai",
    ) -> Optional[Dict[str, Any]]:
        """
        Fetch case details and court orders from the Bombay High Court portal
        using Playwright browser automation.

        Navigation flow (new BHC portal):
        1. Navigate to https://bombayhighcourt.gov.in/bhc/casestatus/casenumber
        2. Fill form: Side, Stamp/Regn., Type, Number, Year → click Search
        3. Extract case summary, petitioner, respondent from the case details page
        4. Click "Orders/Judgements" tab
        5. Collect all order rows (date + download link)

        Returns the structured result dict on success, or None when no orders
        are found or an unrecoverable error occurs.
        """
        if sync_playwright is None:
            return None

        case_parts = self.parse_case_number(case_ref)
        if not case_parts:
            return None

        raw_case_type = case_parts.get("case_type", "")
        base_case_type = self._get_base_case_type(raw_case_type)
        stamp_regn = self._get_stamp_regn_bhc(raw_case_type)
        case_number = case_parts.get("case_number", "")
        case_year = case_parts.get("year", "")
        side_code = self._get_side_code(bench)

        case_details: Dict[str, Optional[str]] = {
            "petitioner_name": None,
            "respondent_name": None,
            "case_number": case_ref,
            "case_status_url": self.bhc_case_status_url,
            "case_summary": None,
            "title": None,
        }
        aggregated_orders: Dict[str, Dict[str, Optional[str]]] = {}

        try:
            timeout_ms = self.playwright_timeout_seconds * 1000
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=self.playwright_headless)
                try:
                    page = browser.new_page()

                    # Step 1: Navigate to the BHC case status portal
                    try:
                        page.goto(
                            self.bhc_case_status_url,
                            wait_until="domcontentloaded",
                            timeout=timeout_ms,
                        )
                    except PlaywrightTimeoutError:
                        return None
                    except Exception as exc:
                        logging.warning(
                            "Playwright: failed to load BHC portal for %s: %s",
                            case_ref,
                            exc,
                        )
                        return None

                    # Step 2: Fill the search form
                    self._playwright_fill_bhc_form(
                        page,
                        side_code=side_code,
                        stamp_regn=stamp_regn,
                        case_type=base_case_type,
                        case_number=case_number,
                        case_year=case_year,
                    )

                    # Step 3: Submit the form
                    self._playwright_click_search(page, timeout_ms)

                    # Step 4: Extract case details from the result page
                    html = page.content()
                    current_url = page.url

                    parties = self._playwright_extract_parties(page, html, case_ref)
                    case_details["petitioner_name"] = parties.get("petitioner_name")
                    case_details["respondent_name"] = parties.get("respondent_name")
                    case_details[
                        "case_summary"
                    ] = self._playwright_extract_case_summary(page, html)
                    case_details["case_status_url"] = (
                        self._extract_case_status_url(current_url)
                        or self.bhc_case_status_url
                    )

                    # Step 5: Navigate to the Orders/Judgements tab
                    self._playwright_click_orders_tab(page, timeout_ms)

                    # Step 6: Collect all order rows
                    html = page.content()
                    current_url = page.url
                    for row in self._playwright_extract_orders_from_table(
                        page, html, current_url
                    ):
                        row_url = (row.get("download_url") or "").strip()
                        if row_url:
                            aggregated_orders[row_url] = row
                finally:
                    browser.close()

            # Build the short title from extracted parties
            petitioner = case_details.get("petitioner_name")
            respondent = case_details.get("respondent_name")
            case_details["title"] = self._build_short_title(petitioner, respondent)

            court_orders = list(aggregated_orders.values())

            # Optional date filter (keep all rows if date is absent)
            if date:
                parsed_target = self._parse_iso_date(date)
                if parsed_target:
                    date_matched: List[Dict[str, Optional[str]]] = [
                        row
                        for row in court_orders
                        if (
                            _row_dt := self._parse_listing_date(
                                row.get("listing_date") or ""
                            )
                        )
                        is not None
                        and _row_dt.date() == parsed_target.date()
                    ]
                    if date_matched:
                        court_orders = date_matched

            if not court_orders:
                return None

            return {
                "status": "found",
                "source": "playwright_scraper",
                "case_details": {
                    "petitioner_name": case_details.get("petitioner_name"),
                    "respondent_name": case_details.get("respondent_name"),
                    "case_number": case_details.get("case_number") or case_ref,
                    "case_status_url": case_details.get("case_status_url"),
                    "case_summary": case_details.get("case_summary"),
                    "title": case_details.get("title"),
                },
                "court_orders": court_orders,
            }
        except Exception as exc:
            logging.warning("Playwright scraper failed for %s: %s", case_ref, exc)
            return None

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
        base_type = self._get_base_case_type(case_parts["case_type"])
        case_type = case_type_map.get(base_type, base_type)
        return f"{case_type} {case_parts['case_number']} of {case_parts['year']}"

    def _build_firecrawl_prompt(
        self, case_ref: str, case_parts: Optional[Dict[str, str]] = None
    ) -> str:
        human_case_ref = self._normalize_case_ref(case_ref)
        raw_case_type = (case_parts or {}).get("case_type", "")
        case_type = self._get_base_case_type(raw_case_type)
        stamp_regn = self._get_stamp_regn_bhc(raw_case_type)
        case_number = (case_parts or {}).get("case_number", "")
        case_year = (case_parts or {}).get("year", "")
        portal_url = self.bhc_case_status_url
        return f"""
CRITICAL RESTRICTION — READ BEFORE DOING ANYTHING:
- You MUST NOT download, open, follow, fetch, or request any PDF or file URL at any point.
- You MUST NOT click any order link — only read the href attribute value.
- There is NO date filter — collect ALL rows in the orders table.

Task: Find case {human_case_ref} and return every court-order link from its Orders/Judgements page.

STEP-BY-STEP NAVIGATION (follow exactly in order):

Step 1 — Navigate directly to the BHC case status portal:
  Open: {portal_url}
  (This is the Bombay High Court case status search page at bombayhighcourt.gov.in)

Step 2 — Fill in the search form with these exact values:
  - Side        : AS               (select "AS" — Appellate Side — from the Side dropdown)
  - Stamp/Regn. : {stamp_regn}     (select "{stamp_regn}" from the Stamp/Regn. dropdown;
                                    use "Stamp" when the case type ends with "(ST)",
                                    otherwise use "Register")
  - Type        : {case_type}      (select from the Type dropdown)
  - Number      : {case_number}    (enter in the Number text field)
  - Year        : {case_year}      (enter in the Year field)
  Click the Search button.

Step 3 — On the case details page:
  Read and record:
  - The full case summary sentence (e.g. "Case No. WP/3373/2025 with CNR No. ..., was filed on...")
  - The petitioner name (labelled "Petitioner" or "Appellant" or the party before "against")
  - The respondent name (labelled "Respondent" or "Defendant" or the party after "against")
  Click the button or tab labelled "Orders/Judgements"
  (it may also be labelled "Orders", "Judgements", "View Orders", or "Listing Dates/Order").

Step 4 — On the Orders/Judgements table page you will see a table with date and order links.

  For EVERY data row in that table:
    a) Read the date cell  → this is listing_date (format DD/MM/YYYY).
    b) Look at the order/judgement cell — it contains a link with text like
       "Order/Judg-1". DO NOT click it. Instead, read the href attribute of that
       link and store it as download_url.
  Collect ALL rows. Do not skip any row.

Return ONLY this JSON — nothing else:
{{
  "case_details": {{
    "petitioner_name": "...",
    "respondent_name": "...",
    "case_number": "...",
    "case_summary": "...",
    "title": "<petitioner> against <respondent>"
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
- Set "title" to "<petitioner_name> against <respondent_name>".
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

        petitioner = case_details.get("petitioner_name")
        respondent = case_details.get("respondent_name")
        normalized_case_details = {
            "petitioner_name": petitioner,
            "respondent_name": respondent,
            "case_number": case_details.get("case_number") or case_ref,
            "case_summary": case_details.get("case_summary"),
            "title": case_details.get("title")
            or self._build_short_title(petitioner, respondent),
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

            if hasattr(app, "agent"):
                # Agent-based SDK: start at the new BHC case status portal so the
                # agent can fill the form directly; also allow both site domains.
                agent_urls = [
                    self.bhc_case_status_url,
                    f"{self.bombay_high_court_url}/*",
                    f"{self.base_url}/cases/case_no.php",
                    f"{self.base_url}/*",
                ]
                result = app.agent(
                    schema=FirecrawlOrderExtraction,
                    prompt=prompt,
                    urls=agent_urls,
                    model=self.firecrawl_model,
                )
            elif hasattr(app, "extract"):
                # Extract-based SDK: point at the BHC portal and both domains.
                extract_urls = [
                    self.bhc_case_status_url,
                    f"{self.bombay_high_court_url}/*",
                    f"{self.base_url}/*",
                ]
                schema = FirecrawlOrderExtraction.model_json_schema()
                result = app.extract(
                    urls=extract_urls,
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
        Parse case reference like 'WP/294/2025' or 'WP(ST)/294/2025' into components.

        The optional '(ST)' suffix on the case type indicates a Stamp-number lookup
        (see _get_stamp_regn_type).

        Returns: {'case_type': 'WP', 'case_number': '294', 'year': '2025'}
                 {'case_type': 'WP(ST)', 'case_number': '294', 'year': '2025'}
        """
        try:
            # Normalize input - convert to uppercase and strip whitespace
            case_ref = case_ref.strip().upper()

            # Pattern: CASE_TYPE[optional (ST)]/CASE_NUMBER/YEAR
            match = re.match(r"^([A-Z]+(?:\(ST\))?)\/(\d+)\/(\d{4})$", case_ref)
            if match:
                return {
                    "case_type": match.group(1),
                    "case_number": match.group(2),
                    "year": match.group(3),
                }
            else:
                raise ValueError(
                    f"Invalid case reference format: {case_ref}. Expected format: TYPE/NUMBER/YEAR (e.g., WP/294/2025 or WP(ST)/294/2025)"
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
            provider_result = self._fetch_with_provider(
                case_ref=case_ref, date=None, bench=bench
            )
            if provider_result:
                case_details = provider_result.get("case_details") or {}
                return {
                    "status": provider_result.get("status") or "found",
                    "source": provider_result.get("source") or "unknown",
                    "case_ref": case_ref,
                    "case_number": case_details.get("case_number") or case_ref,
                    "petitioner": case_details.get("petitioner_name"),
                    "respondent": case_details.get("respondent_name"),
                    "case_status_url": case_details.get("case_status_url"),
                    "court_orders": provider_result.get("court_orders") or [],
                }

            # Parse case reference
            case_parts = self.parse_case_number(case_ref)
            if not case_parts:
                return {"error": "Invalid case reference format", "case_ref": case_ref}

            # Set court code based on bench
            court_code = self._get_bench_code(bench)

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

            # If direct access fails, return a structured response indicating no results
            return {
                "status": "not_found",
                "message": "Case lookup did not return results via alternative URLs",
                "case_ref": f"{case_type}/{case_number}/{year}",
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
        Fetch case orders for a specific case and date.

        Args:
            case_ref: Case reference like 'WP/294/2025'
            date: Specific date in YYYY-MM-DD format
            bench: Court bench - 'mumbai', 'aurangabad', 'nagpur', 'goa'

        Returns:
            Structured result containing:
            - case_summary: Full case summary sentence from the portal
            - petitioner: Petitioner / appellant name
            - respondent: Respondent / defendant name
            - title: Short title "<petitioner> against <respondent>"
            - case_orders: [{"date": "DD/MM/YYYY", "download_link": "https://..."}]
            - case_details: (also present for backward compatibility)
            - court_orders: (also present for backward compatibility)
        """
        try:
            case_parts = self.parse_case_number(case_ref)
            if not case_parts:
                return {
                    "status": "error",
                    "error": "Invalid case reference format",
                    "case_summary": None,
                    "petitioner": None,
                    "respondent": None,
                    "title": None,
                    "case_orders": [],
                    "case_details": {
                        "case_number": case_ref,
                        "case_number_citation": self.bombay_high_court_url,
                    },
                    "court_orders": [],
                }

            provider_result = self._fetch_with_provider(
                case_ref=case_ref, date=date, bench=bench
            )
            if provider_result:
                return self._enrich_case_orders_result(provider_result)

            # Set court code based on bench (same as case details)
            court_code = self._get_bench_code(bench)

            # Fallback response when no scraper provider could retrieve orders.
            return {
                "status": "not_found",
                "source": "ecourts_fallback",
                "message": "Court order lookup did not yield downloadable links via configured scraper provider",
                "case_summary": None,
                "petitioner": None,
                "respondent": None,
                "title": None,
                "case_orders": [],
                "case_details": {
                    "petitioner_name": None,
                    "petitioner_name_citation": self.bombay_high_court_url,
                    "respondent_name": None,
                    "respondent_name_citation": self.bombay_high_court_url,
                    "case_number": case_ref,
                    "case_number_citation": self.bombay_high_court_url,
                    "case_status_url": self.bhc_case_status_url,
                    "case_status_url_citation": self.bombay_high_court_url,
                },
                "court_orders": [],
                "bench": bench,
                "court_code": court_code,
            }

        except Exception as e:
            return {
                "status": "error",
                "error": f"Failed to fetch orders: {str(e)}",
                "case_summary": None,
                "petitioner": None,
                "respondent": None,
                "title": None,
                "case_orders": [],
                "case_details": {
                    "case_number": case_ref,
                    "case_number_citation": self.bombay_high_court_url,
                },
                "court_orders": [],
            }

    def _enrich_case_orders_result(
        self, provider_result: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Add the new top-level convenience fields to a provider result dict.

        New fields:
        - case_summary  — full case summary sentence
        - petitioner    — petitioner / appellant name
        - respondent    — respondent / defendant name
        - title         — "<petitioner> against <respondent>"
        - case_orders   — [{date, download_link}] (mirrors court_orders with renamed keys)

        The original case_details and court_orders keys are preserved for
        backward compatibility.
        """
        case_details = provider_result.get("case_details") or {}
        court_orders = provider_result.get("court_orders") or []

        petitioner = case_details.get("petitioner_name")
        respondent = case_details.get("respondent_name")
        case_summary = case_details.get("case_summary")
        title = case_details.get("title") or self._build_short_title(
            petitioner, respondent
        )

        case_orders = [
            {
                "date": row.get("listing_date"),
                "download_link": row.get("download_url"),
            }
            for row in court_orders
            if row.get("download_url")
        ]

        enriched = dict(provider_result)
        enriched["case_summary"] = case_summary
        enriched["petitioner"] = petitioner
        enriched["respondent"] = respondent
        enriched["title"] = title
        enriched["case_orders"] = case_orders
        return enriched

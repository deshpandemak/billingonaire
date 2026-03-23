import json
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
        self.scraper_provider = (
            os.getenv("COURT_SCRAPER_PROVIDER", "firecrawl_first").strip().lower()
        )
        self.allow_firecrawl_fallback = (
            os.getenv("COURT_ALLOW_FIRECRAWL_FALLBACK", "true").strip().lower()
            == "true"
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

    def _supported_providers(self) -> List[str]:
        return [
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
            "firecrawl": {
                "configured": bool(self.firecrawl_api_key),
                "model": self.firecrawl_model,
            },
            "ollama": {
                "base_url": self.ollama_base_url,
                "model": self.ollama_model,
                "timeout_seconds": self.ollama_timeout_seconds,
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
            self.ollama_base_url = ollama_base_url.rstrip("/")

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

        if not self.ollama_base_url:
            return {
                "healthy": False,
                "status": "Ollama base URL not configured",
                "base_url": None,
                "response_time_ms": 0,
            }

        start_time = time.time()
        try:
            health_url = f"{self.ollama_base_url}/api/tags"
            response = requests.get(
                health_url,
                timeout=self.ollama_timeout_seconds,
            )
            response_time_ms = (time.time() - start_time) * 1000

            if response.status_code == 200:
                logging.info(f"Ollama health check passed: {health_url}")
                return {
                    "healthy": True,
                    "status": "ok",
                    "base_url": self.ollama_base_url,
                    "response_time_ms": int(response_time_ms),
                }
            else:
                logging.warning(f"Ollama health check returned {response.status_code}")
                return {
                    "healthy": False,
                    "status": f"HTTP {response.status_code}",
                    "base_url": self.ollama_base_url,
                    "response_time_ms": int(response_time_ms),
                }
        except requests.exceptions.Timeout:
            response_time_ms = (time.time() - start_time) * 1000
            logging.warning("Ollama health check timed out")
            return {
                "healthy": False,
                "status": "timeout",
                "base_url": self.ollama_base_url,
                "response_time_ms": int(response_time_ms),
            }
        except requests.exceptions.ConnectionError:
            response_time_ms = (time.time() - start_time) * 1000
            logging.warning(f"Cannot connect to Ollama at {self.ollama_base_url}")
            return {
                "healthy": False,
                "status": "connection_error",
                "base_url": self.ollama_base_url,
                "response_time_ms": int(response_time_ms),
            }
        except Exception as e:
            response_time_ms = (time.time() - start_time) * 1000
            logging.error(f"Unexpected error checking Ollama health: {e}")
            return {
                "healthy": False,
                "status": str(e),
                "base_url": self.ollama_base_url,
                "response_time_ms": int(response_time_ms),
            }

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
                timeout=self.ollama_timeout_seconds,
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
        # Start from the Bombay High Court home page (entry point for menu navigation).
        # Then try the case-number search page and direct case/order URLs as fallbacks.
        return [
            f"{self.bombay_high_court_url}/",
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
        stamp_regn = self._get_stamp_regn_type(raw_case_type)
        case_number = case_parts.get("case_number", "")
        case_year = case_parts.get("year", "")
        combined = "\n\n---PAGE-CHUNK---\n\n".join(html_chunks[:3])
        return f"""
Extract court-order links for case {case_ref} from the HTML text below.

The HTML was fetched by navigating the Bombay High Court website in this sequence:
1. Home page (bombayhighcourt.nic.in) → click "Case Status" → click "Case Number Wise"
2. Fill in the search form:
   - Case Type   : {base_case_type}
   - Stamp/Regn  : {stamp_regn}  (use "Stamp" when case type ends with "(ST)", else "Registration")
   - Case Number : {case_number}
   - Year        : {case_year}
   - Solve CAPTCHA and submit
3. On the case details page: read the petitioner and respondent names
4. Click the "Listing Dates/Order" button to view the orders table
5. The orders table has columns: Date | Coram | Action | Order/Judgement

Return ONLY valid JSON in this shape:
{{
  "case_details": {{
    "petitioner_name": null,
    "respondent_name": null,
    "case_number": "{case_ref}"
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
- Include only probable order/judgement links from the Listing Dates table.
- The "Order/Judgement" column contains links — extract their href values as download_url.
- The "Date" column provides the listing_date (format DD/MM/YYYY).
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
                response.raise_for_status()
                llm_text = (response.json() or {}).get("response", "").strip()
                ollama_response["raw_response"] = llm_text[:8000]
                parsed_payload = self._parse_ollama_order_response(llm_text, case_ref)
                ollama_response["parsed"] = parsed_payload.get("parsed")
                ollama_response["normalized"] = parsed_payload.get("normalized")
                ollama_response["parse_error"] = parsed_payload.get("parse_error")
            except Exception as exc:
                ollama_response["error"] = str(exc)

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
            "direct_order_count": len(direct_orders),
            "final_result": final_result,
        }

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
        self, case_ref: str, date: Optional[str] = None, bench: str = "mumbai"
    ) -> Optional[Dict[str, Any]]:
        provider = (self.scraper_provider or "firecrawl_first").lower()

        def _try_firecrawl() -> Optional[Dict[str, Any]]:
            if not self.allow_firecrawl_fallback and provider != "firecrawl_only":
                return None
            return self._fetch_with_firecrawl(case_ref=case_ref, date=date)

        def _try_ollama() -> Optional[Dict[str, Any]]:
            return self._fetch_with_ollama_scraper(
                case_ref=case_ref, date=date, bench=bench
            )

        if provider == "ollama_only":
            return _try_ollama()
        if provider == "ollama_first":
            return _try_ollama() or _try_firecrawl()
        if provider == "firecrawl_only":
            return _try_firecrawl()
        # Default: firecrawl_first for backward compatibility.
        return _try_firecrawl() or _try_ollama()

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
        stamp_regn = self._get_stamp_regn_type(raw_case_type)
        case_number = (case_parts or {}).get("case_number", "")
        case_year = (case_parts or {}).get("year", "")
        start_url = f"{self.base_url}/cases/case_no.php"
        home_url = self.bombay_high_court_url
        return f"""
CRITICAL RESTRICTION — READ BEFORE DOING ANYTHING:
- You MUST NOT download, open, follow, fetch, or request any PDF or file URL at any point.
- You MUST NOT click any link in the "Order/Judgement" column — only read the href attribute value.
- There is NO date filter — collect ALL rows in the listing-dates table.

Task: Find case {human_case_ref} and return every court-order link from its Listing Dates page.

STEP-BY-STEP NAVIGATION (follow exactly in order):

Step 1 — Navigate to the case search page via the home page menu:
  Open: {home_url}
  On the home page, locate the "Case Status" menu item in the navigation bar and click it.
  In the dropdown that appears, click "Case Number Wise".
  (Alternatively, navigate directly to: {start_url})

Step 2 — Fill in the search form with these exact values:
  - Case Type  : {case_type}       (select from the Case Type dropdown)
  - Stamp/Regn : {stamp_regn}      (select "{stamp_regn}" from the Stamp/Regn dropdown;
                                    use "Stamp" when the case type ends with "(ST)",
                                    otherwise use "Registration")
  - Case Number: {case_number}     (enter in the Case Number text field)
  - Year       : {case_year}       (enter in the Year field)
  - Bench      : Mumbai (High Court)
  Submit the form.

Step 3 — Handle CAPTCHA if shown, then re-submit.

Step 4 — On the case details page:
  Read and record:
  - The petitioner name (labelled "Petitioner" or "Appellant")
  - The respondent name (labelled "Respondent" or "Defendant")
  The page header may show both a Stamp No. (e.g. WP/7203/{case_year}) and a
  Reg. No. (e.g. WP/{case_number}/{case_year}) — either is the correct case.
  Click the button or tab labelled "Listing Dates/Order"
  (it may also be labelled "Listing Dates", "Listing Dates/Orders", "Hearing Dates", or "View Orders").

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

            # Start at the eCourts case-number search page; allow both site domains
            # via wildcard so the agent can navigate freely across them.
            crawl_urls = [
                f"{self.base_url}/cases/case_no.php",
                f"{self.bombay_high_court_url}/*",
                f"{self.base_url}/*",
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

            provider_result = self._fetch_with_provider(
                case_ref=case_ref, date=date, bench=bench
            )
            if provider_result:
                return provider_result

            # Set court code based on bench (same as case details)
            court_code = self._get_bench_code(bench)

            # Fallback response when Firecrawl is not configured or cannot bypass captcha.
            return {
                "status": "captcha_required",
                "source": "ecourts_fallback",
                "message": "Court order lookup did not yield downloadable links via configured scraper provider",
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

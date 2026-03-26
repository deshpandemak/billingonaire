import logging
import os
import re
import time
from typing import Any, Dict, List, Optional

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

try:
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
    from playwright.sync_api import sync_playwright
except ImportError:
    PlaywrightTimeoutError = Exception  # type: ignore[assignment,misc]
    sync_playwright = None  # type: ignore[assignment]


load_dotenv()


class BombayHighCourtScraper:
    """Bombay High Court scraper using direct API by default with Playwright fallback."""

    def __init__(self):
        self.case_status_url = (
            "https://bombayhighcourt.gov.in/bhc/casestatus/casenumber"
        )
        self.case_types_url = (
            "https://bombayhighcourt.gov.in/bhc/get-case-types-by-side"
        )
        self.scraper_provider = (
            os.getenv("COURT_SCRAPER_PROVIDER", "direct_api").strip().lower()
        )
        self.playwright_headless = (
            os.getenv("COURT_PLAYWRIGHT_HEADLESS", "true").strip().lower() == "true"
        )
        self.playwright_timeout_seconds = int(
            os.getenv("COURT_PLAYWRIGHT_TIMEOUT_SECONDS", "60")
        )
        self.request_timeout_seconds = int(
            os.getenv("COURT_REQUEST_TIMEOUT_SECONDS", "60")
        )
        self.session = requests.Session()
        self.session.headers.update(self._browser_headers())

    def _browser_headers(self) -> Dict[str, str]:
        return {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/91.0.4472.124 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
            "Accept-Encoding": "gzip, deflate",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
            "Cache-Control": "max-age=0",
        }

    def _supported_providers(self) -> List[str]:
        return ["direct_api", "playwright"]

    def get_scraper_config(self) -> Dict[str, Any]:
        return {
            "provider": self.scraper_provider,
            "supported_providers": self._supported_providers(),
            "playwright": {
                "available": bool(sync_playwright),
                "headless": self.playwright_headless,
                "timeout_seconds": self.playwright_timeout_seconds,
            },
            "requests": {
                "timeout_seconds": self.request_timeout_seconds,
            },
        }

    def configure_scraper(self, provider: Optional[str] = None) -> Dict[str, Any]:
        if provider is not None:
            normalized = provider.strip().lower()
            if normalized not in self._supported_providers():
                raise ValueError(
                    f"Unsupported scraper provider '{provider}'. Supported values: "
                    f"{', '.join(self._supported_providers())}"
                )
            self.scraper_provider = normalized
        return self.get_scraper_config()

    def _get_bench_code(self, bench: str) -> str:
        bench_codes = {
            "mumbai": "2",
            "mumbai_appellate": "1",
            "aurangabad": "3",
            "nagpur": "4",
            "goa": "5",
        }
        return bench_codes.get((bench or "mumbai").lower(), "2")

    def _get_stamp_regn_type(self, case_type: str) -> str:
        return "Stamp" if case_type.upper().endswith("(ST)") else "Registration"

    def _get_base_case_type(self, case_type: str) -> str:
        return re.sub(r"\(ST\)$", "", case_type, flags=re.IGNORECASE).strip()

    def parse_case_number(self, case_ref: str) -> Dict[str, str]:
        try:
            normalized = str(case_ref or "").strip().upper()
            match = re.match(r"^([A-Z]+(?:\(ST\))?)/(\d+)/(\d{4})$", normalized)
            if not match:
                raise ValueError("invalid case reference")
            return {
                "case_type": match.group(1),
                "case_number": match.group(2),
                "year": match.group(3),
            }
        except Exception as exc:
            logging.error("Error parsing case number %s: %s", case_ref, exc)
            return {}

    def _provider_attempt_sequence(self, provider: str) -> List[str]:
        normalized = (provider or "direct_api").lower()
        if normalized == "playwright":
            return ["playwright"]
        return ["direct_api", "playwright"]

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
            started = time.time()
            try:
                if attempt_provider == "playwright":
                    result = self._fetch_with_playwright_new(
                        case_ref, date=date, bench=bench
                    )
                else:
                    result = self._fetch_with_direct_api(
                        case_ref, date=date, bench=bench
                    )

                duration_ms = int((time.time() - started) * 1000)
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
                        "duration_ms": int((time.time() - started) * 1000),
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
        matrix: List[Dict[str, Any]] = []
        for matrix_provider in self._supported_providers():
            run = self._run_provider_attempts(case_ref, date, bench, matrix_provider)
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

    def _fetch_with_provider(
        self,
        case_ref: str,
        date: Optional[str] = None,
        bench: str = "mumbai",
        include_diagnostics: bool = False,
    ) -> Any:
        diagnostics = self._run_provider_attempts(
            case_ref=case_ref,
            date=date,
            bench=bench,
            provider=self.scraper_provider,
        )
        if include_diagnostics:
            return diagnostics
        return diagnostics.get("result")

    def _build_form_data(
        self,
        case_parts: Dict[str, str],
        hidden_html: str,
        case_type_options: List[Dict[str, Any]],
    ) -> Dict[str, str]:
        soup = BeautifulSoup(hidden_html, "html.parser")
        hidden_inputs = soup.find_all("input", {"type": "hidden"})
        form_data: Dict[str, str] = {}
        first_form_secret: Optional[str] = None

        for hidden_input in hidden_inputs:
            name = hidden_input.get("name")
            value = hidden_input.get("value", "")
            if name == "form_secret" and first_form_secret is None:
                first_form_secret = value
            elif name:
                form_data[name] = value

        if first_form_secret:
            form_data["form_secret"] = first_form_secret

        target_label = self._get_base_case_type(case_parts["case_type"])
        resolved_case_type = target_label
        for item in case_type_options:
            if not isinstance(item, dict):
                continue
            if str(item.get("type_name", "")).upper() == target_label.upper():
                resolved_case_type = str(item.get("case_type", target_label))
                if str(item.get("type_flag", "1")) == "1":
                    break

        form_data.update(
            {
                "side": "1",
                "stampreg": "R",
                "case_type": resolved_case_type,
                "case_no": case_parts["case_number"],
                "year": case_parts["year"],
            }
        )
        return form_data

    def _extract_case_details_from_html(
        self,
        html_content: str,
        case_ref: str,
    ) -> Optional[Dict[str, Optional[str]]]:
        try:
            soup = BeautifulSoup(html_content, "html.parser")
            case_info_selectors = [
                "#cn_CaseNoUpdates .card-header",
                ".case-details",
                ".case-info",
                "#caseDetails",
            ]

            case_text = ""
            for selector in case_info_selectors:
                for element in soup.select(selector):
                    text = element.get_text(" ", strip=True)
                    if case_ref in text and (
                        "filed on" in text.lower() or "against" in text.lower()
                    ):
                        case_text = text
                        break
                if case_text:
                    break

            if not case_text:
                for element in soup.find_all(["p", "div"]):
                    text = element.get_text(" ", strip=True)
                    if case_ref in text and len(text) > 50:
                        case_text = text
                        break

            if not case_text:
                return None

            petitioner = ""
            respondent = ""
            by_match = re.search(
                r"by\s+(.+?)\s+against\s+(.+?)$", case_text, re.IGNORECASE
            )
            if by_match:
                petitioner = by_match.group(1).strip()
                respondent = by_match.group(2).strip()
            else:
                filed_match = re.search(
                    r"filed.*?by\s+(.+?)(?:\s+against\s+(.+?))?(?:\s+through|\s*$)",
                    case_text,
                    re.IGNORECASE,
                )
                if filed_match:
                    petitioner = filed_match.group(1).strip()
                    if filed_match.group(2):
                        respondent = filed_match.group(2).strip()

            filing_date = ""
            date_match = re.search(r"filed\s+on\s+([\d/.-]+)", case_text, re.IGNORECASE)
            if date_match:
                filing_date = date_match.group(1).strip()

            return {
                "petitioner_name": petitioner or None,
                "respondent_name": respondent or None,
                "filing_date": filing_date or None,
                "case_number": case_ref,
                "court": "Bombay High Court",
                "case_status_url": self.case_status_url,
            }
        except Exception as exc:
            logging.error("Error extracting case details from HTML: %s", exc)
            return None

    def _extract_listing_date_from_text(self, text: str) -> Optional[str]:
        patterns = [
            r"(\d{1,2}[/-]\d{1,2}[/-]\d{4})",
            r"(\d{4}[/-]\d{1,2}[/-]\d{1,2})",
        ]
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                return match.group(1)
        return None

    def _extract_orders_from_html(
        self,
        html_content: str,
        base_url: str,
    ) -> List[Dict[str, Optional[str]]]:
        try:
            soup = BeautifulSoup(html_content, "html.parser")
            orders: List[Dict[str, Optional[str]]] = []

            orders_table = soup.select_one("#cn_CaseNoOrders table tbody")
            if orders_table:
                for row in orders_table.find_all("tr"):
                    cells = row.find_all("td")
                    if len(cells) < 5:
                        continue
                    link = cells[4].find("a")
                    if not link or not link.get("href"):
                        continue
                    orders.append(
                        {
                            "listing_date": cells[2].get_text(strip=True) or None,
                            "download_url": requests.compat.urljoin(
                                base_url, link["href"]
                            ),
                        }
                    )

            if not orders:
                for link in soup.select(
                    "a[href*='.pdf'], a[href*='order'], a[href*='judg']"
                ):
                    href = link.get("href")
                    if not href:
                        continue
                    orders.append(
                        {
                            "listing_date": self._extract_listing_date_from_text(
                                link.get_text(" ", strip=True)
                            ),
                            "download_url": requests.compat.urljoin(base_url, href),
                        }
                    )

            unique_orders: List[Dict[str, Optional[str]]] = []
            seen_urls = set()
            for order in orders:
                url = order.get("download_url")
                if url and url not in seen_urls:
                    seen_urls.add(url)
                    unique_orders.append(order)
            return unique_orders
        except Exception as exc:
            logging.error("Error extracting orders from HTML: %s", exc)
            return []

    def _fetch_with_direct_api(
        self,
        case_ref: str,
        date: Optional[str] = None,
        bench: str = "mumbai",
    ) -> Optional[Dict[str, Any]]:
        del date, bench
        case_parts = self.parse_case_number(case_ref)
        if not case_parts:
            return None

        headers = self._browser_headers()
        session = requests.Session()

        try:
            initial_response = session.get(
                self.case_status_url,
                headers=headers,
                timeout=self.request_timeout_seconds,
            )
            if initial_response.status_code != 200:
                return None

            ajax_response = session.get(
                self.case_types_url,
                params={"side": "1"},
                headers=headers,
                timeout=self.request_timeout_seconds,
            )
            case_type_options: List[Dict[str, Any]] = []
            if ajax_response.status_code == 200:
                payload = ajax_response.json()
                if isinstance(payload, list):
                    case_type_options = payload

            form_data = self._build_form_data(
                case_parts,
                initial_response.text,
                case_type_options,
            )
            headers["Content-Type"] = "application/x-www-form-urlencoded"
            headers["Referer"] = self.case_status_url

            response = session.post(
                self.case_status_url,
                data=form_data,
                headers=headers,
                timeout=self.request_timeout_seconds,
                allow_redirects=True,
            )
            if response.status_code not in {200, 302}:
                return None

            try:
                data = response.json()
            except ValueError:
                data = {"status": True, "page": response.text}

            if not data.get("status"):
                return None

            html_content = data.get("page", "")
            if not html_content:
                return None

            case_details = self._extract_case_details_from_html(html_content, case_ref)
            if not case_details:
                return None

            court_orders = self._extract_orders_from_html(html_content, response.url)
            return {
                "status": "found",
                "source": "direct_api",
                "case_details": case_details,
                "court_orders": court_orders,
            }
        except requests.exceptions.RequestException as exc:
            logging.error("HTTP request failed for %s: %s", case_ref, exc)
            return None
        except Exception as exc:
            logging.error("Direct API scraper failed for %s: %s", case_ref, exc)
            return None

    def _extract_case_details_new(
        self, page: Any, case_ref: str
    ) -> Optional[Dict[str, Optional[str]]]:
        selectors = [
            "#cn_CaseNoUpdates .card-header",
            ".case-details",
            ".case-info",
        ]
        for selector in selectors:
            element = page.query_selector(selector)
            if not element:
                continue
            text = element.inner_text().strip()
            if case_ref not in text:
                continue
            html = f"<div>{element.inner_html()}</div>"
            return self._extract_case_details_from_html(html, case_ref)
        return None

    def _extract_orders_new(
        self, page: Any, base_url: str
    ) -> List[Dict[str, Optional[str]]]:
        orders: List[Dict[str, Optional[str]]] = []
        rows = page.query_selector_all("#cn_CaseNoOrders table tbody tr")
        for row in rows:
            cells = row.query_selector_all("td")
            if len(cells) < 5:
                continue
            link = cells[4].query_selector("a")
            href = link.get_attribute("href") if link else None
            if not href:
                continue
            orders.append(
                {
                    "listing_date": cells[2].inner_text().strip() or None,
                    "download_url": requests.compat.urljoin(base_url, href),
                }
            )
        return orders

    def _fetch_with_playwright_new(
        self,
        case_ref: str,
        date: Optional[str] = None,
        bench: str = "mumbai",
    ) -> Optional[Dict[str, Any]]:
        del date, bench
        if sync_playwright is None:
            return None

        case_parts = self.parse_case_number(case_ref)
        if not case_parts:
            return None

        timeout_ms = self.playwright_timeout_seconds * 1000

        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=self.playwright_headless)
                page = browser.new_page()
                page.goto(
                    self.case_status_url,
                    wait_until="domcontentloaded",
                    timeout=timeout_ms,
                )

                page.select_option("select[name='side']", value="1")
                page.select_option("select[name='stampreg']", value="R")
                page.wait_for_timeout(2000)

                base_case_type = self._get_base_case_type(case_parts["case_type"])
                options = page.query_selector_all("select[name='case_type'] option")
                resolved_case_type = None
                for option in options:
                    text = option.inner_text().strip().upper()
                    if text == base_case_type.upper():
                        resolved_case_type = option.get_attribute("value")
                        break
                if not resolved_case_type:
                    resolved_case_type = base_case_type

                page.select_option("select[name='case_type']", value=resolved_case_type)
                page.fill("input[name='case_no']", case_parts["case_number"])
                page.fill("input[name='year']", case_parts["year"])
                page.click(
                    "button[type='submit'], input[type='submit']", timeout=timeout_ms
                )
                page.wait_for_timeout(3000)

                case_details = self._extract_case_details_new(page, case_ref)
                if not case_details:
                    browser.close()
                    return None

                court_orders = self._extract_orders_new(page, self.case_status_url)
                browser.close()
                return {
                    "status": "found",
                    "source": "playwright",
                    "case_details": case_details,
                    "court_orders": court_orders,
                }
        except PlaywrightTimeoutError as exc:
            logging.error("Playwright timed out for %s: %s", case_ref, exc)
            return None
        except Exception as exc:
            logging.error("Playwright scraper failed for %s: %s", case_ref, exc)
            return None

    def debug_case_orders(
        self,
        case_ref: str,
        date: Optional[str] = None,
        bench: str = "mumbai",
        compare_all: bool = False,
    ) -> Dict[str, Any]:
        try:
            case_parts = self.parse_case_number(case_ref)
            if not case_parts:
                return {
                    "ok": False,
                    "error": "Invalid case reference format",
                    "request": {"case_ref": case_ref, "date": date, "bench": bench},
                }

            provider_debug = self._fetch_with_provider(
                case_ref=case_ref,
                date=date,
                bench=bench,
                include_diagnostics=True,
            )
            provider_matrix = []
            if compare_all:
                provider_matrix = self._probe_provider_matrix(case_ref, date, bench)

            return {
                "ok": True,
                "request": {
                    "case_ref": case_ref,
                    "date": date,
                    "bench": bench,
                    "court_code": self._get_bench_code(bench),
                },
                "scraper_config": self.get_scraper_config(),
                "candidate_urls": [self.case_status_url, self.case_types_url],
                "http_trace": [],
                "provider_sequence": provider_debug.get("provider_sequence") or [],
                "provider_attempts": provider_debug.get("provider_attempts") or [],
                "provider_matrix": provider_matrix,
                "direct_order_count": len(
                    ((provider_debug.get("result") or {}).get("court_orders") or [])
                ),
                "final_result": self.get_case_orders(
                    case_ref=case_ref, date=date, bench=bench
                ),
            }
        except Exception as exc:
            logging.error(
                "Unexpected error in debug_case_orders for %s: %s", case_ref, exc
            )
            return {
                "ok": False,
                "error": str(exc),
                "request": {"case_ref": case_ref, "date": date, "bench": bench},
            }

    def get_case_details(self, case_ref: str, bench: str = "mumbai") -> Dict[str, Any]:
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
                    "case_status_url": case_details.get("case_status_url")
                    or self.case_status_url,
                    "court_orders": provider_result.get("court_orders") or [],
                }

            case_parts = self.parse_case_number(case_ref)
            if not case_parts:
                return {"error": "Invalid case reference format", "case_ref": case_ref}

            return {
                "status": "not_found",
                "message": "Case details not found via configured scraper provider",
                "case_ref": case_ref,
                "case_number": case_ref,
                "case_status_url": self.case_status_url,
            }
        except Exception as exc:
            logging.error("Error fetching case details for %s: %s", case_ref, exc)
            return {"error": str(exc), "case_ref": case_ref}

    def get_case_orders(
        self,
        case_ref: str,
        date: Optional[str] = None,
        bench: str = "mumbai",
    ) -> Dict[str, Any]:
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
                        "case_status_url": self.case_status_url,
                    },
                    "court_orders": [],
                }

            provider_result = self._fetch_with_provider(
                case_ref=case_ref, date=date, bench=bench
            )
            if provider_result:
                return self._enrich_case_orders_result(provider_result)

            return {
                "status": "not_found",
                "source": self.scraper_provider,
                "message": "Court order lookup did not yield downloadable links via configured scraper provider",
                "case_summary": None,
                "petitioner": None,
                "respondent": None,
                "title": None,
                "case_orders": [],
                "case_details": {
                    "petitioner_name": None,
                    "respondent_name": None,
                    "case_number": case_ref,
                    "case_status_url": self.case_status_url,
                },
                "court_orders": [],
                "bench": bench,
                "court_code": self._get_bench_code(bench),
            }
        except Exception as exc:
            return {
                "status": "error",
                "error": f"Failed to fetch orders: {exc}",
                "case_details": {
                    "case_number": case_ref,
                    "case_status_url": self.case_status_url,
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

    def _build_short_title(
        self, petitioner: Optional[str], respondent: Optional[str]
    ) -> Optional[str]:
        """Build a short title from petitioner and respondent names."""
        if petitioner and respondent:
            return f"{petitioner} against {respondent}"
        return petitioner or respondent

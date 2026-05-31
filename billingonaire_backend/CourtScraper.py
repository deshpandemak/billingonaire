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

logger = logging.getLogger(__name__)


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
            os.getenv("COURT_SCRAPER_PROVIDER", "http").strip().lower()
        )
        self.playwright_headless = (
            os.getenv("COURT_PLAYWRIGHT_HEADLESS", "true").strip().lower() == "true"
        )
        self.playwright_timeout_seconds = int(
            os.getenv("COURT_PLAYWRIGHT_TIMEOUT_SECONDS", "30")
        )
        self.playwright_retry_count = int(os.getenv("PLAYWRIGHT_RETRY_COUNT", "2"))
        self.request_timeout_seconds = int(
            os.getenv("COURT_REQUEST_TIMEOUT_SECONDS", "20")
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
        return ["http", "playwright"]

    def get_scraper_config(self) -> Dict[str, Any]:
        return {
            "provider": self.scraper_provider,
            "supported_providers": self._supported_providers(),
            "http": {
                "timeout_seconds": self.request_timeout_seconds,
            },
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

    def _get_base_case_type(self, case_type: str) -> str:
        return re.sub(r"\(ST\)$", "", case_type, flags=re.IGNORECASE).strip()

    def _get_stampreg_value(self, case_type: str) -> str:
        """Return the stampreg form value: 'S' for Stamp cases (ST suffix), 'R' otherwise."""
        return "S" if case_type.upper().endswith("(ST)") else "R"

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
            logger.error("Error parsing case number %s: %s", case_ref, exc)
            return {}

    def _provider_attempt_sequence(self, provider: str) -> List[str]:
        """Return the ordered list of providers to attempt for a given requested provider.

        Requesting ``"playwright"`` explicitly skips the HTTP path entirely.
        Any other value (including ``"http"``, the default) uses HTTP first
        then falls back to Playwright.
        """
        if (provider or "http").lower() == "playwright":
            return ["playwright"]
        return ["http", "playwright"]

    def _build_form_data(
        self,
        case_parts: Dict[str, str],
        initial_html: str,
        case_type_options: List[Dict[str, Any]],
    ) -> Dict[str, str]:
        """Build the POST body for the case-status form submission.

        Parses hidden CSRF/token fields from *initial_html*, resolves the
        numeric case_type value from *case_type_options*, and fills in the
        standard search fields.
        """
        form_data: Dict[str, str] = {}

        # Extract any hidden input fields (CSRF tokens, session keys)
        soup = BeautifulSoup(initial_html, "html.parser")
        for inp in soup.find_all("input", type="hidden"):
            name = inp.get("name")
            value = inp.get("value", "")
            if name:
                form_data[name] = value

        # Resolve the numeric case_type option value from the AJAX options list.
        # The portal AJAX endpoint returns {"type_name": "WP", "case_type": 1, ...}
        # (new format).  Older test fixtures use {"name": "WP", "value": "1"}.
        # Both formats are handled so unit tests and the live portal work identically.
        base_case_type = self._get_base_case_type(case_parts["case_type"])
        resolved_case_type = base_case_type  # fallback: use label string
        for opt in case_type_options:
            label = str(
                opt.get("type_name")  # new portal API key
                or opt.get("name")
                or opt.get("label")
                or opt.get("text")
                or ""
            )
            if label.strip().upper() == base_case_type.upper():
                resolved_case_type = str(
                    opt.get("case_type")  # new portal API key (numeric ID)
                    or opt.get("value")
                    or opt.get("id")
                    or base_case_type
                )
                break
        if resolved_case_type == base_case_type and case_type_options:
            logger.warning(
                "_build_form_data: case_type %r not found in options %s; using label fallback",
                base_case_type,
                [
                    o.get("type_name") or o.get("name") or o.get("label")
                    for o in case_type_options[:5]
                ],
            )

        form_data.update(
            {
                "side": "1",
                "stampreg": self._get_stampreg_value(case_parts["case_type"]),
                "case_type": resolved_case_type,
                "case_no": case_parts["case_number"],
                "year": case_parts["year"],
            }
        )
        return form_data

    def _extract_orders_from_html(
        self,
        html_content: str,
        base_url: str,
    ) -> List[Dict[str, Optional[str]]]:
        """Extract court orders from the HTML response of the case-status portal.

        Primary selector: ``#cn_CaseNoOrders table tbody tr`` — mirrors the
        Playwright ``_extract_orders_new`` method but uses BeautifulSoup.
        Falls back to any ``<a>`` tag whose href contains ``.pdf``, ``order``,
        or ``judg`` when the primary table is absent or empty.
        Deduplicates by download URL.
        """
        orders: List[Dict[str, Optional[str]]] = []
        seen_urls: set = set()
        try:
            soup = BeautifulSoup(html_content, "html.parser")

            # Primary: orders table
            table = soup.select_one("#cn_CaseNoOrders table tbody")
            if table:
                for row in table.find_all("tr"):
                    cells = row.find_all("td")
                    # Require at least 3 cells (date col + description + download link).
                    # The portal table can have 5 or 6 columns depending on court bench;
                    # always check the LAST cell for the download link so extra status
                    # columns don't cause the link to be silently skipped.
                    if len(cells) < 3:
                        continue
                    link = cells[-1].find("a")
                    href = link.get("href") if link else None
                    if not href:
                        continue
                    full_url = requests.compat.urljoin(base_url, href)
                    if full_url in seen_urls:
                        continue
                    seen_urls.add(full_url)
                    orders.append(
                        {
                            "listing_date": cells[2].get_text(strip=True) or None,
                            "download_url": full_url,
                        }
                    )

            # Fallback: any PDF/order/auth links when the table is absent or empty.
            # generatenewauth.php is the Bombay HC file-server auth endpoint used for
            # all order PDF downloads — it must be matched even when its href does not
            # contain "order" or ".pdf".
            if not orders:
                for link in soup.find_all(
                    "a",
                    href=re.compile(
                        r"\.(pdf)$|order|judg|generatenewauth", re.IGNORECASE
                    ),
                ):
                    href = link.get("href")
                    if not href:
                        continue
                    full_url = requests.compat.urljoin(base_url, href)
                    if full_url in seen_urls:
                        continue
                    seen_urls.add(full_url)
                    orders.append(
                        {
                            "listing_date": self._extract_listing_date_from_text(
                                link.get_text(strip=True)
                            ),
                            "download_url": full_url,
                        }
                    )
        except Exception as exc:
            logger.error("_extract_orders_from_html: parse error: %s", exc)
        return orders

    def _fetch_with_http(
        self,
        case_ref: str,
        date: Optional[str] = None,
        bench: str = "mumbai",
    ) -> Optional[Dict[str, Any]]:
        """Fetch case orders via direct HTTP POST — no browser required.

        Flow:
          1. GET the form page (establishes session cookies, reads hidden
             fields and case-type option values).
          2. GET the case-types AJAX endpoint to resolve the numeric case_type.
          3. POST the form with the resolved fields.
          4. Parse the response (JSON wrapper or plain HTML) with BeautifulSoup.

        Returns the same dict shape as ``_fetch_with_playwright_new`` on
        success, or ``None`` if any step fails (signals Playwright fallback).
        """
        del date, bench  # not used for the HTTP path — POST fetches all orders
        case_parts = self.parse_case_number(case_ref)
        if not case_parts:
            return None

        try:
            # Step 1: GET form page — establishes session cookies
            get_resp = self.session.get(
                self.case_status_url, timeout=self.request_timeout_seconds
            )
            if get_resp.status_code != 200:
                raise requests.exceptions.HTTPError(
                    f"HTTP {get_resp.status_code} on GET {self.case_status_url} for {case_ref}",
                    response=get_resp,
                )
            initial_html = get_resp.text

            # Step 2: GET case-type options via AJAX endpoint.
            # Mirror what the portal JS does: include stampreg so the server
            # returns the correct type list for Stamp (S) vs Registered (R) cases.
            # For IA(ST) the browser sends stampreg=S; without it the server may
            # return only Registered types where IA has a different numeric ID or
            # is absent entirely.
            stampreg_value = self._get_stampreg_value(case_parts["case_type"])
            case_type_options: List[Dict[str, Any]] = []
            try:
                types_resp = self.session.get(
                    self.case_types_url,
                    params={"side": "1", "stampreg": stampreg_value},
                    timeout=self.request_timeout_seconds,
                )
                if types_resp.status_code == 200:
                    case_type_options = types_resp.json()
                    if not isinstance(case_type_options, list):
                        case_type_options = []
            except Exception as types_exc:
                logger.warning(
                    "_fetch_with_http: case-types AJAX failed for %s: %s — "
                    "using label fallback for case_type",
                    case_ref,
                    types_exc,
                )

            # Step 3: POST form.
            # The portal uses AJAX form submission — the JS reads the CSRF token from
            # <meta name="csrf-token"> and sends it as X-CSRF-TOKEN header (not as a
            # hidden form field).  We also need X-Requested-With so the server treats
            # this as an XMLHttpRequest rather than a browser form POST.
            form_data = self._build_form_data(
                case_parts, initial_html, case_type_options
            )
            soup_get = BeautifulSoup(initial_html, "html.parser")
            csrf_meta = soup_get.find("meta", attrs={"name": "csrf-token"})
            post_headers: Dict[str, str] = {
                "Content-Type": "application/x-www-form-urlencoded",
                "Referer": self.case_status_url,
                "X-Requested-With": "XMLHttpRequest",
                "Accept": "application/json, text/javascript, */*; q=0.01",
            }
            if csrf_meta:
                post_headers["X-CSRF-TOKEN"] = csrf_meta.get("content", "")
            post_resp = self.session.post(
                self.case_status_url,
                data=form_data,
                timeout=self.request_timeout_seconds,
                headers=post_headers,
                allow_redirects=True,
            )

            # 419 = CSRF token expired — refresh the session and retry once.
            # This happens when the AJAX case-types GET takes long enough that
            # the server rotates the CSRF token before our POST arrives.
            if post_resp.status_code == 419:
                logger.info(
                    "_fetch_with_http: 419 CSRF expiry for %s — refreshing token and retrying",
                    case_ref,
                )
                get_resp2 = self.session.get(
                    self.case_status_url, timeout=self.request_timeout_seconds
                )
                soup_get2 = BeautifulSoup(get_resp2.text, "html.parser")
                csrf_meta2 = soup_get2.find("meta", attrs={"name": "csrf-token"})
                if csrf_meta2:
                    post_headers["X-CSRF-TOKEN"] = csrf_meta2.get("content", "")
                # Also rebuild hidden-field form data from the fresh page
                form_data2 = self._build_form_data(
                    case_parts, get_resp2.text, case_type_options
                )
                post_resp = self.session.post(
                    self.case_status_url,
                    data=form_data2,
                    timeout=self.request_timeout_seconds,
                    headers=post_headers,
                    allow_redirects=True,
                )

            if post_resp.status_code not in (200, 302):
                raise requests.exceptions.HTTPError(
                    f"HTTP {post_resp.status_code} on POST for {case_ref}",
                    response=post_resp,
                )

            # Step 4: Parse response (JSON wrapper {"status": true, "page": "<html>"} or raw HTML)
            html_content = ""
            try:
                data = post_resp.json()
                if not data.get("status"):
                    logger.info(
                        "_fetch_with_http: portal returned status=False for %s",
                        case_ref,
                    )
                    return None
                html_content = data.get("page", "")
            except ValueError:
                # Plain HTML response (no JSON wrapper)
                html_content = post_resp.text

            if not html_content:
                return None

            # Step 5: Extract case details and orders
            case_details = self._extract_case_details_from_html(html_content, case_ref)
            if not case_details:
                logger.info(
                    "_fetch_with_http: could not extract case details for %s — "
                    "Playwright fallback will be used",
                    case_ref,
                )
                return None

            court_orders = self._extract_orders_from_html(html_content, post_resp.url)
            logger.info(
                "_fetch_with_http: succeeded for %s orders_found=%d",
                case_ref,
                len(court_orders),
            )
            return {
                "status": "found",
                "source": "http",
                "case_details": case_details,
                "court_orders": court_orders,
            }

        except requests.exceptions.RequestException as exc:
            logger.warning("_fetch_with_http: network error for %s: %s", case_ref, exc)
            raise
        except Exception as exc:
            logger.warning(
                "_fetch_with_http: unexpected error for %s: %s", case_ref, exc
            )
            raise

    def _run_provider_attempts(
        self,
        case_ref: str,
        date: Optional[str],
        bench: str,
        provider: str,
    ) -> Dict[str, Any]:
        """Run the provider sequence for *case_ref*, returning on first success.

        The sequence is determined by ``_provider_attempt_sequence``:
        - ``"playwright"`` → Playwright only (retried up to playwright_retry_count)
        - anything else (default ``"http"``) → HTTP first, then Playwright fallback
        """
        sequence = self._provider_attempt_sequence(provider)
        attempts: List[Dict[str, Any]] = []
        final_result: Optional[Dict[str, Any]] = None

        logger.info(
            "Provider attempt sequence starting for case_ref=%s sequence=%s",
            case_ref,
            sequence,
        )

        for step_provider in sequence:
            if final_result:
                break

            if step_provider == "http":
                started = time.time()
                try:
                    result = self._fetch_with_http(case_ref, date=date, bench=bench)
                    duration_ms = int((time.time() - started) * 1000)
                    orders_found = (
                        len(result.get("court_orders") or []) if result else 0
                    )
                    # Only treat HTTP as a success when it found at least one order
                    # link.  Returning a result with 0 orders means the static HTML
                    # had no downloadable links (orders may be rendered via JS after
                    # page load), so we fall through to Playwright which executes the
                    # full page lifecycle.
                    if result and orders_found > 0:
                        logger.info(
                            "HTTP succeeded for case_ref=%s in %dms orders_found=%d",
                            case_ref,
                            duration_ms,
                            orders_found,
                        )
                        attempts.append(
                            {
                                "step": "http",
                                "attempt": 1,
                                "status": "success",
                                "source": "http",
                                "orders_found": orders_found,
                                "duration_ms": duration_ms,
                            }
                        )
                        final_result = result
                    else:
                        reason = (
                            "no_orders_in_html"
                            if result and orders_found == 0
                            else "no_result"
                        )
                        logger.info(
                            "HTTP %s for case_ref=%s in %dms — trying Playwright",
                            reason,
                            case_ref,
                            duration_ms,
                        )
                        attempts.append(
                            {
                                "step": "http",
                                "attempt": 1,
                                "status": reason,
                                "duration_ms": duration_ms,
                            }
                        )
                except Exception as exc:
                    duration_ms = int((time.time() - started) * 1000)
                    logger.warning(
                        "HTTP attempt raised for case_ref=%s in %dms: %s — "
                        "falling back to Playwright",
                        case_ref,
                        duration_ms,
                        exc,
                    )
                    attempts.append(
                        {
                            "step": "http",
                            "attempt": 1,
                            "status": "error",
                            "error": str(exc),
                            "duration_ms": duration_ms,
                        }
                    )

            elif step_provider == "playwright":
                for attempt_num in range(1, self.playwright_retry_count + 1):
                    if final_result:
                        break
                    started = time.time()
                    logger.info(
                        "Playwright attempt %d/%d for case_ref=%s",
                        attempt_num,
                        self.playwright_retry_count,
                        case_ref,
                    )
                    try:
                        result = self._fetch_with_playwright_new(
                            case_ref, date=date, bench=bench
                        )
                        duration_ms = int((time.time() - started) * 1000)
                        if result:
                            logger.info(
                                "Playwright succeeded attempt=%d for case_ref=%s "
                                "in %dms orders_found=%d",
                                attempt_num,
                                case_ref,
                                duration_ms,
                                len(result.get("court_orders") or []),
                            )
                            attempts.append(
                                {
                                    "step": "playwright",
                                    "attempt": attempt_num,
                                    "status": "success",
                                    "source": "playwright",
                                    "orders_found": len(
                                        result.get("court_orders") or []
                                    ),
                                    "duration_ms": duration_ms,
                                }
                            )
                            final_result = result
                        else:
                            logger.warning(
                                "Playwright attempt=%d returned no result for "
                                "case_ref=%s in %dms",
                                attempt_num,
                                case_ref,
                                duration_ms,
                            )
                            attempts.append(
                                {
                                    "step": "playwright",
                                    "attempt": attempt_num,
                                    "status": "no_result",
                                    "duration_ms": duration_ms,
                                }
                            )
                    except Exception as exc:
                        duration_ms = int((time.time() - started) * 1000)
                        logger.error(
                            "Playwright attempt=%d raised for case_ref=%s in %dms: %s",
                            attempt_num,
                            case_ref,
                            duration_ms,
                            exc,
                        )
                        attempts.append(
                            {
                                "step": "playwright",
                                "attempt": attempt_num,
                                "status": "error",
                                "error": str(exc),
                                "duration_ms": duration_ms,
                            }
                        )

        return {
            "provider": sequence[-1] if sequence else provider,
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
            logger.error("Error extracting case details from HTML: %s", exc)
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
            # Require at least 3 cells; always check the LAST cell for the download
            # link so that 6-column variants (extra status column) still resolve.
            if len(cells) < 3:
                continue
            link = cells[-1].query_selector("a")
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
            logger.warning(
                "Playwright not available for case_ref=%s; skipping Playwright fetch",
                case_ref,
            )
            return None

        case_parts = self.parse_case_number(case_ref)
        if not case_parts:
            return None

        logger.info(
            "Playwright fetch starting for case_ref=%s timeout_seconds=%d",
            case_ref,
            self.playwright_timeout_seconds,
        )
        timeout_ms = self.playwright_timeout_seconds * 1000

        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=self.playwright_headless)
                page = browser.new_page()
                logger.info(
                    "Playwright navigating to case status URL for case_ref=%s", case_ref
                )
                page.goto(
                    self.case_status_url,
                    wait_until="domcontentloaded",
                    timeout=timeout_ms,
                )

                stampreg_value = self._get_stampreg_value(case_parts["case_type"])
                base_case_type = self._get_base_case_type(case_parts["case_type"])

                page.select_option("select[name='side']", value="1")

                # Wait for the stampreg dropdown to be populated by its AJAX handler
                # before we select from it — selecting too early can leave the wrong
                # value or fail silently.
                try:
                    page.wait_for_selector(
                        "select[name='stampreg'] option:not([value=''])",
                        timeout=5000,
                    )
                except Exception:
                    page.wait_for_timeout(1000)

                page.select_option("select[name='stampreg']", value=stampreg_value)

                # Wait for the case_type dropdown to reload after the stampreg
                # selection.  The portal JS fires a second AJAX call when stampreg
                # changes, so case_type options may differ between Stamp (S) and
                # Registered (R).  Waiting here ensures we read the correct type list
                # for the case — e.g. IA(ST) must select from the Stamp type list.
                try:
                    page.wait_for_selector(
                        "select[name='case_type'] option:not([value=''])",
                        timeout=8000,
                    )
                except Exception:
                    # Fallback: give it a fixed wait if the selector never fires
                    page.wait_for_timeout(3000)

                # Prefer selecting by label (visible text) — avoids the label/numeric-ID
                # mismatch where option values are "1"/"6"/… but we only know "WP"/"PIL".
                try:
                    page.select_option("select[name='case_type']", label=base_case_type)
                except Exception:
                    # Label match failed — read the numeric value from the DOM directly
                    options = page.query_selector_all("select[name='case_type'] option")
                    resolved_case_type = None
                    for option in options:
                        if (
                            option.inner_text().strip().upper()
                            == base_case_type.upper()
                        ):
                            resolved_case_type = option.get_attribute("value")
                            break
                    if not resolved_case_type:
                        raise Exception(
                            f"Case type {base_case_type!r} not found in dropdown — "
                            f"options: {[o.inner_text().strip() for o in options[:10]]}"
                        )
                    page.select_option(
                        "select[name='case_type']", value=resolved_case_type
                    )
                page.fill("input[name='case_no']", case_parts["case_number"])
                page.fill("input[name='year']", case_parts["year"])
                page.click(
                    "button[type='submit'], input[type='submit']", timeout=timeout_ms
                )
                page.wait_for_timeout(3000)

                case_details = self._extract_case_details_new(page, case_ref)
                if not case_details:
                    logger.warning(
                        "Playwright could not extract case details for case_ref=%s",
                        case_ref,
                    )
                    browser.close()
                    return None

                court_orders = self._extract_orders_new(page, self.case_status_url)
                browser.close()
                logger.info(
                    "Playwright fetch succeeded for case_ref=%s orders_found=%d",
                    case_ref,
                    len(court_orders),
                )
                return {
                    "status": "found",
                    "source": "playwright",
                    "case_details": case_details,
                    "court_orders": court_orders,
                }
        except PlaywrightTimeoutError as exc:
            logger.error(
                "Playwright timed out for %s (timeout=%ds): %s",
                case_ref,
                self.playwright_timeout_seconds,
                exc,
            )
            raise
        except AttributeError as exc:
            # sync_playwright().__enter__() failed to set _playwright — this is a
            # flaky init failure that occurs when called from a thread pool while an
            # asyncio event loop is running.  Re-raise so the retry loop retries.
            logger.warning(
                "Playwright context init failed for %s (will retry): %s",
                case_ref,
                exc,
            )
            raise
        except Exception as exc:
            logger.error("Playwright scraper failed for %s: %s", case_ref, exc)
            raise

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
            logger.error(
                "Unexpected error in debug_case_orders for %s: %s", case_ref, exc
            )
            return {
                "ok": False,
                "error": str(exc),
                "request": {"case_ref": case_ref, "date": date, "bench": bench},
            }

    def get_case_details(self, case_ref: str, bench: str = "mumbai") -> Dict[str, Any]:
        logger.info("get_case_details called for case_ref=%s bench=%s", case_ref, bench)
        try:
            provider_result = self._fetch_with_provider(
                case_ref=case_ref, date=None, bench=bench
            )
            if provider_result:
                case_details = provider_result.get("case_details") or {}
                logger.info(
                    "get_case_details succeeded for case_ref=%s source=%s",
                    case_ref,
                    provider_result.get("source"),
                )
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

            logger.warning(
                "get_case_details: case not found for case_ref=%s provider=%s",
                case_ref,
                self.scraper_provider,
            )
            return {
                "status": "not_found",
                "message": "Case details not found via configured scraper provider",
                "case_ref": case_ref,
                "case_number": case_ref,
                "case_status_url": self.case_status_url,
            }
        except Exception as exc:
            logger.error("Error fetching case details for %s: %s", case_ref, exc)
            return {"error": str(exc), "case_ref": case_ref}

    def get_case_orders(
        self,
        case_ref: str,
        date: Optional[str] = None,
        bench: str = "mumbai",
    ) -> Dict[str, Any]:
        logger.info(
            "get_case_orders called for case_ref=%s date=%s bench=%s provider=%s",
            case_ref,
            date,
            bench,
            self.scraper_provider,
        )
        try:
            case_parts = self.parse_case_number(case_ref)
            if not case_parts:
                logger.warning(
                    "get_case_orders: invalid case reference format for case_ref=%s",
                    case_ref,
                )
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
                enriched = self._enrich_case_orders_result(provider_result)
                logger.info(
                    "get_case_orders succeeded for case_ref=%s source=%s orders=%d",
                    case_ref,
                    provider_result.get("source"),
                    len(enriched.get("case_orders") or []),
                )
                return enriched

            logger.warning(
                "get_case_orders: no orders found for case_ref=%s provider=%s",
                case_ref,
                self.scraper_provider,
            )
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
            logger.error("get_case_orders failed for case_ref=%s: %s", case_ref, exc)
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

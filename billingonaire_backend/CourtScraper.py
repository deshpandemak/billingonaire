import logging
import os
import random
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

    # Case types whose portal ``type_flag`` is "2" (Criminal).
    # Used only to disambiguate duplicate type_name entries in the AJAX response
    # (e.g. both Civil WP type_flag="1" and Criminal WP type_flag="2" share the
    # abbreviation "WP").  This set has NO effect on the ``side`` form field —
    # all searches use side=1 (Appellate Side) regardless of criminal/civil.
    _CRIMINAL_CASE_TYPES = frozenset(
        [
            "ABA",
            "ALP",
            "ALS",
            "AO",
            "APEAL",
            "APL",
            "APPA",
            "APPCO",
            "APPCP",
            "BA",
            "BAIL",
            "CRA",
            "CRB",
            "CRBA",
            "CRW",
            "CRR",
            "EXEA",
            "EXEP",
            "EXES",
            "CRL",
            "CRLP",
            "MCA",
        ]
    )

    def _get_side_for_case_type(self, case_type: str) -> str:
        """Return the portal 'side' value for a case search.

        On the BHC portal the ``side`` dropdown controls which bench division
        is searched:
            side=1 → Appellate Side  (Writ Petitions, Appeals, etc.)
            side=2 → Original Side   (Suits, Company Petitions, etc.)

        This application only handles Appellate Side matters, so this always
        returns "1".  The ``_CRIMINAL_CASE_TYPES`` set is kept separately for
        disambiguating duplicate ``type_name`` entries in the AJAX response
        (Civil WP = type_flag "1", Criminal WP = type_flag "2") — it does NOT
        affect the side value.
        """
        del case_type  # unused — all searches are Appellate Side
        return "1"

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
        # The portal AJAX endpoint returns {"type_name": "WP", "case_type": 1,
        # "type_flag": "1", ...} where type_flag "1"=Civil and "2"=Criminal.
        # The list contains BOTH "WP" (Civil Writ Petition, type_flag=1, case_type=1)
        # and "WP" (Cr. Writ Petition, type_flag=2, case_type=308).  We must pick
        # the correct entry — the first match is not necessarily the right one.
        # Strategy: prefer the entry whose type_flag matches the case type's
        # division (Criminal types in _CRIMINAL_CASE_TYPES → type_flag "2",
        # everything else including WP/PIL/IA → type_flag "1" = Civil).
        base_case_type = self._get_base_case_type(case_parts["case_type"])
        preferred_type_flag = (
            "2" if base_case_type.upper() in self._CRIMINAL_CASE_TYPES else "1"
        )
        resolved_case_type = base_case_type  # fallback: use label string
        first_match_value: Optional[str] = None  # best non-preferred match
        for opt in case_type_options:
            label = str(
                opt.get("type_name")  # new portal API key
                or opt.get("name")
                or opt.get("label")
                or opt.get("text")
                or ""
            )
            prefix = label.split(" - ")[0].split()[0] if label.strip() else ""
            if prefix.upper() != base_case_type.upper():
                continue
            opt_value = str(
                opt.get("case_type")  # new portal API key (numeric ID)
                or opt.get("value")
                or opt.get("id")
                or base_case_type
            )
            if str(opt.get("type_flag", "")) == preferred_type_flag:
                # Exact Civil/Criminal match — use immediately
                resolved_case_type = opt_value
                first_match_value = None  # clear fallback, we have the winner
                break
            if first_match_value is None:
                first_match_value = opt_value  # keep first match as fallback

        if resolved_case_type == base_case_type and first_match_value is not None:
            # No preferred type_flag match — use first match (old-format fixtures
            # that lack type_flag will always take this path)
            resolved_case_type = first_match_value

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
                "side": self._get_side_for_case_type(case_parts["case_type"]),
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
            # The portal filters case types by side (Appellate=1, Original=2).
            # This app only handles Appellate Side so side is always "1".
            # stampreg is a POST-only field — do NOT include it in the AJAX call;
            # passing stampreg here returns a different (wrong) numeric type ID.
            side_value = self._get_side_for_case_type(case_parts["case_type"])
            case_type_options: List[Dict[str, Any]] = []
            try:
                types_resp = self.session.get(
                    self.case_types_url,
                    params={"side": side_value},
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
            logger.warning(
                "_fetch_with_http POST form_data for %s: "
                "side=%r stampreg=%r case_type=%r case_no=%r year=%r csrf=%s",
                case_ref,
                form_data.get("side"),
                form_data.get("stampreg"),
                form_data.get("case_type"),
                form_data.get("case_no"),
                form_data.get("year"),
                (
                    "present"
                    if soup_get.find("meta", attrs={"name": "csrf-token"})
                    else "MISSING"
                ),
            )
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
                    logger.warning(
                        "_fetch_with_http: portal returned status=False for %s "
                        "(case_type_used=%r http_status=%d response_keys=%s msg=%r)",
                        case_ref,
                        form_data.get("case_type"),
                        post_resp.status_code,
                        list(data.keys()),
                        data.get("message") or data.get("error") or data.get("msg"),
                    )
                    return None
                html_content = data.get("page", "")
            except ValueError:
                # Plain HTML response (no JSON wrapper)
                html_content = post_resp.text

            if not html_content:
                logger.warning(
                    "_fetch_with_http: empty html_content for %s http_status=%d",
                    case_ref,
                    post_resp.status_code,
                )
                return None

            # Step 5: Diagnose what the HTML contains before extraction
            soup_diag = BeautifulSoup(html_content, "html.parser")
            orders_div = soup_diag.find(id="cn_CaseNoOrders")
            orders_table = soup_diag.select_one("#cn_CaseNoOrders table tbody")
            orders_rows = orders_table.find_all("tr") if orders_table else []
            all_links = soup_diag.find_all("a", href=True)
            pdf_links = [
                a["href"]
                for a in all_links
                if any(
                    kw in a["href"].lower() for kw in (".pdf", "order", "judg", "view")
                )
            ]
            logger.warning(
                "_fetch_with_http html_diag for %s: "
                "cn_CaseNoOrders_present=%s table_present=%s rows=%d "
                "total_links=%d pdf_like_links=%d sample=%s",
                case_ref,
                orders_div is not None,
                orders_table is not None,
                len(orders_rows),
                len(all_links),
                len(pdf_links),
                pdf_links[:3],
            )

            # Step 6: Extract case details and orders
            case_details = self._extract_case_details_from_html(html_content, case_ref)
            if not case_details:
                logger.warning(
                    "_fetch_with_http: could not extract case details for %s — "
                    "Playwright fallback will be used",
                    case_ref,
                )
                return None

            court_orders = self._extract_orders_from_html(html_content, post_resp.url)
            logger.warning(
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
                        logger.warning(
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
                        logger.warning(
                            "HTTP %s for case_ref=%s in %dms — order table not in "
                            "static HTML (JS-rendered), trying Playwright",
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
                    if attempt_num > 1:
                        delay = min(2 ** (attempt_num - 1), 30) + random.uniform(0, 1)
                        logger.info(
                            "Playwright retry back-off %.1fs before attempt %d for case_ref=%s",
                            delay,
                            attempt_num,
                            case_ref,
                        )
                        time.sleep(delay)
                    started = time.time()
                    logger.warning(
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

            _PARTY_KEYWORDS = re.compile(
                r"(?:filed\s+on|against|versus|vs\.?|v/s\.?|petitioners?|respondents?)",
                re.IGNORECASE,
            )

            case_text = ""

            # Primary: use the Bombay HC portal's case-output div directly.
            # This is authoritative for the searched case — no party-keyword
            # check needed here; if the div is present with non-trivial content
            # it IS the case section.  Party keywords only guard the loose
            # fallback loops below where false-positive matches are possible.
            cn_updates = soup.find(id="cn_CaseNoUpdates")
            if cn_updates:
                _cn_text = cn_updates.get_text(" ", strip=True)
                if len(_cn_text) > 20:
                    case_text = _cn_text

            # Selector-based fallback
            if not case_text:
                case_info_selectors = [
                    "#cn_CaseNoUpdates .card-header",
                    ".case-details",
                    ".case-info",
                    "#caseDetails",
                ]
                for selector in case_info_selectors:
                    for element in soup.select(selector):
                        text = element.get_text(" ", strip=True)
                        if case_ref in text and _PARTY_KEYWORDS.search(text):
                            case_text = text
                            break
                    if case_text:
                        break

            # Last-resort: iterate divs/paragraphs — but require both the case_ref
            # AND a party keyword so we don't match navigation or history sections
            # that might reference the case number alongside a different case's data.
            if not case_text:
                for element in soup.find_all(["p", "div"]):
                    text = element.get_text(" ", strip=True)
                    if (
                        case_ref in text
                        and len(text) > 50
                        and _PARTY_KEYWORDS.search(text)
                    ):
                        case_text = text
                        break

            if not case_text:
                return None

            petitioner = ""
            respondent = ""

            # Strip the leading case number from case_text so party-name patterns
            # don't accidentally capture it.
            stripped_text = case_text
            if case_ref in stripped_text:
                stripped_text = stripped_text[
                    stripped_text.index(case_ref) + len(case_ref) :
                ].strip()

            # Pattern 0: Bombay HC portal filing format (primary)
            # "#cn_CaseNoUpdates" text: "Case No. X was filed on DATE at Bombay High Court
            # by PETITIONER against RESPONDENT"
            # After case_ref strip: "...by PETITIONER against RESPONDENT"
            by_match = re.search(
                r"\bby\s+(.+?)\s+against\s+(.+?)(?:\s+filed|\s*$)",
                stripped_text,
                re.IGNORECASE,
            )
            if by_match:
                petitioner = by_match.group(1).strip()
                respondent = by_match.group(2).strip()

            # Pattern 1: "filed by X against Y" (fallback)
            if not petitioner:
                filed_match = re.search(
                    r"filed.*?by\s+(.+?)(?:\s+against\s+(.+?))?(?:\s+through|\s*$)",
                    stripped_text,
                    re.IGNORECASE,
                )
                if filed_match:
                    petitioner = filed_match.group(1).strip()
                    if filed_match.group(2):
                        respondent = filed_match.group(2).strip()

            # Pattern 2: "PETITIONER Versus/VS/V.S./V/S RESPONDENT"
            if not petitioner:
                vs_match = re.search(
                    r"^(.+?)\s+(?:versus|v\.?s\.?|v/s)\s+(.+?)(?:\s+filed|\s*$)",
                    stripped_text,
                    re.IGNORECASE,
                )
                if vs_match:
                    petitioner = vs_match.group(1).strip()
                    respondent = vs_match.group(2).strip()

            # Pattern 3: labelled "Petitioner(s): X  Respondent(s): Y"
            if not petitioner:
                pet_match = re.search(
                    r"Petitioner(?:\(s\))?\s*:\s*(.+?)(?=\s*Respondent\b|\s*$)",
                    stripped_text,
                    re.IGNORECASE,
                )
                res_match = re.search(
                    r"Respondent(?:\(s\))?\s*:\s*(.+?)(?=\s*Petitioner\b|\s*$)",
                    stripped_text,
                    re.IGNORECASE,
                )
                if pet_match:
                    petitioner = pet_match.group(1).strip()
                if res_match:
                    respondent = res_match.group(1).strip()

            # Strip any trailing filing-date suffix that leaked into the name
            _label_suffixes = (
                r"\s+[Ff]iled.*$",
                r"\s+\d{2}/\d{2}/\d{4}.*$",
            )
            for _suffix in _label_suffixes:
                if petitioner:
                    petitioner = re.sub(
                        _suffix, "", petitioner, flags=re.IGNORECASE
                    ).strip()
                if respondent:
                    respondent = re.sub(
                        _suffix, "", respondent, flags=re.IGNORECASE
                    ).strip()

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

                # side=1 → Appellate Side (the only side this app searches)
                page.select_option(
                    "select[name='side']",
                    value=self._get_side_for_case_type(case_parts["case_type"]),
                )

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

                # Portal renders options as "WP - Writ Petition" (abbreviation + full form).
                # select_option(label=) requires an exact text match, so we read the DOM
                # directly.  Two WP entries exist: Civil (value=1) and Criminal (value=308).
                # Pick the right one using the same Civil/Criminal logic as _build_form_data:
                # presence of "Cr." in the label text indicates the Criminal variant.
                is_criminal = base_case_type.upper() in self._CRIMINAL_CASE_TYPES
                all_opts = page.query_selector_all("select[name='case_type'] option")
                resolved_case_type = None
                fallback_value: Optional[str] = None
                for option in all_opts:
                    text = option.inner_text().strip()
                    prefix = text.split(" - ")[0].strip() if text else ""
                    if prefix.upper() != base_case_type.upper():
                        continue
                    val = option.get_attribute("value") or ""
                    text_upper = text.upper()
                    is_opt_criminal = "CR." in text_upper or " CR " in text_upper
                    if is_criminal == is_opt_criminal:
                        resolved_case_type = val
                        break
                    if fallback_value is None:
                        fallback_value = val

                if not resolved_case_type:
                    resolved_case_type = fallback_value
                if not resolved_case_type:
                    sample = [
                        o.inner_text().strip()
                        for o in page.query_selector_all(
                            "select[name='case_type'] option"
                        )[:10]
                    ]
                    raise Exception(
                        f"Case type {base_case_type!r} not found in dropdown — "
                        f"options: {sample}"
                    )
                page.select_option("select[name='case_type']", value=resolved_case_type)
                page.fill("input[name='case_no']", case_parts["case_number"])
                # year is a <select> on the portal, not an <input>
                page.select_option("select[name='year']", value=case_parts["year"])
                # The page has multiple Search buttons (one per form tab).
                # Scope click to #CaseNumber to avoid triggering the wrong form.
                page.click(
                    "#CaseNumber button[type='submit'], #CaseNumber input[type='submit']",
                    timeout=timeout_ms,
                )

                # Wait for AJAX result to be injected into the DOM
                try:
                    page.wait_for_selector(
                        "#cn_CaseNoUpdates, #cn_CaseNoOrders",
                        timeout=15000,
                    )
                except Exception:
                    page.wait_for_timeout(4000)

                case_details = self._extract_case_details_new(page, case_ref)
                if not case_details:
                    logger.warning(
                        "Playwright could not extract case details for case_ref=%s",
                        case_ref,
                    )
                    browser.close()
                    return None

                # Wait up to 10 s for the orders table — it loads via a second AJAX
                # call triggered after case details appear.  Cases with no orders will
                # time out here (safe — we just get an empty list).
                try:
                    page.wait_for_selector(
                        "#cn_CaseNoOrders table tbody tr", timeout=10000
                    )
                except Exception:
                    pass

                court_orders = self._extract_orders_new(page, self.case_status_url)
                logger.warning(
                    "Playwright orders_found=%d for case_ref=%s",
                    len(court_orders),
                    case_ref,
                )
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

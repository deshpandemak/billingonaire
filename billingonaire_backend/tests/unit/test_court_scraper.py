from unittest.mock import Mock, patch

import pytest
import requests as _requests

from billingonaire_backend.CourtScraper import BombayHighCourtScraper

# ---------------------------------------------------------------------------
# HTML fixtures used by multiple tests
# ---------------------------------------------------------------------------

_CASE_DETAILS_HTML = """
<div id="cn_CaseNoUpdates">
  <div class="card-header">
    WP/3373/2025 filed on 01/01/2025 by Petitioner A against Respondent B
  </div>
</div>
"""

_ORDERS_TABLE_HTML = """
<div id="cn_CaseNoOrders">
  <table>
    <tbody>
      <tr>
        <td>1</td><td>WP</td><td>09/04/2025</td><td>Some text</td>
        <td><a href="/orders/order1.pdf">Download</a></td>
      </tr>
      <tr>
        <td>2</td><td>WP</td><td>10/05/2025</td><td>Some text</td>
        <td><a href="/orders/order2.pdf">Download</a></td>
      </tr>
    </tbody>
  </table>
</div>
"""

_FULL_RESPONSE_HTML = _CASE_DETAILS_HTML + _ORDERS_TABLE_HTML

_CASE_TYPES_JSON = [
    {"name": "WP", "value": "1"},
    {"name": "PIL", "value": "5"},
    {"name": "IA", "value": "8"},
]


def _make_mock_session(
    get_html: str = "<html></html>",
    types_json=None,
    post_json=None,
    post_html: str = "",
):
    """Build a mock requests.Session whose get/post behave as configured.

    If *post_json* is given the POST response returns that JSON.
    Otherwise it returns *post_html* as plain text (no JSON wrapper).
    Returns (mock_session, submitted_form_data_capture_dict).
    """
    submitted: dict = {}

    get_resp = Mock()
    get_resp.status_code = 200
    get_resp.text = get_html

    types_resp = Mock()
    types_resp.status_code = 200 if types_json is not None else 404
    types_resp.json = Mock(return_value=types_json or [])

    post_resp = Mock()
    post_resp.status_code = 200
    post_resp.url = "https://bombayhighcourt.gov.in/bhc/casestatus/casenumber"
    if post_json is not None:
        post_resp.json = Mock(return_value=post_json)
        post_resp.text = ""
    else:
        post_resp.json = Mock(side_effect=ValueError("not json"))
        post_resp.text = post_html

    def fake_get(url, **kwargs):
        if "get-case-types" in url:
            return types_resp
        return get_resp

    def fake_post(url, data=None, **kwargs):
        if data:
            submitted.update(data)
        return post_resp

    mock_session = Mock()
    mock_session.get = Mock(side_effect=fake_get)
    mock_session.post = Mock(side_effect=fake_post)
    return mock_session, submitted


# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------


def test_scraper_initialization_defaults_to_http():
    scraper = BombayHighCourtScraper()
    assert scraper.scraper_provider == "http"
    assert scraper.get_scraper_config()["supported_providers"] == ["http", "playwright"]


# ---------------------------------------------------------------------------
# parse_case_number
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "case_ref, expected",
    [
        (
            "WP/10460/2023",
            {"case_type": "WP", "case_number": "10460", "year": "2023"},
        ),
        (
            "PIL/294/2025",
            {"case_type": "PIL", "case_number": "294", "year": "2025"},
        ),
        (
            "IA/500/2024",
            {"case_type": "IA", "case_number": "500", "year": "2024"},
        ),
        (
            "WP(ST)/100/2025",
            {"case_type": "WP(ST)", "case_number": "100", "year": "2025"},
        ),
        (
            "PIL(ST)/77/2024",
            {"case_type": "PIL(ST)", "case_number": "77", "year": "2024"},
        ),
    ],
)
def test_parse_case_number(case_ref, expected):
    scraper = BombayHighCourtScraper()
    assert scraper.parse_case_number(case_ref) == expected


@pytest.mark.parametrize("case_ref", ["INVALID", "WP-123-2024", "WP/123"])
def test_parse_case_number_invalid(case_ref):
    scraper = BombayHighCourtScraper()
    assert scraper.parse_case_number(case_ref) == {}


# ---------------------------------------------------------------------------
# configure_scraper
# ---------------------------------------------------------------------------


def test_configure_scraper_accepts_http_provider():
    scraper = BombayHighCourtScraper()
    updated = scraper.configure_scraper(provider="http")
    assert updated["provider"] == "http"


def test_configure_scraper_accepts_playwright_provider():
    scraper = BombayHighCourtScraper()
    updated = scraper.configure_scraper(provider="playwright")
    assert updated["provider"] == "playwright"


def test_configure_scraper_rejects_invalid_provider():
    scraper = BombayHighCourtScraper()
    with pytest.raises(ValueError):
        scraper.configure_scraper(provider="invalid_provider")


# ---------------------------------------------------------------------------
# _build_form_data
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "case_ref, options, expected_stampreg, expected_case_type",
    [
        ("WP/3373/2025", _CASE_TYPES_JSON, "R", "1"),
        ("PIL/294/2025", _CASE_TYPES_JSON, "R", "5"),
        ("IA/500/2024", _CASE_TYPES_JSON, "R", "8"),
        ("WP(ST)/100/2025", _CASE_TYPES_JSON, "S", "1"),
        ("PIL(ST)/77/2024", _CASE_TYPES_JSON, "S", "5"),
        # Unknown case type falls back to the label string
        ("OA/10/2025", _CASE_TYPES_JSON, "R", "OA"),
    ],
)
def test_build_form_data_case_type_and_stampreg(
    case_ref, options, expected_stampreg, expected_case_type
):
    scraper = BombayHighCourtScraper()
    case_parts = scraper.parse_case_number(case_ref)
    form = scraper._build_form_data(case_parts, "<html></html>", options)
    assert form["stampreg"] == expected_stampreg
    assert form["case_type"] == expected_case_type
    assert form["side"] == "1"
    assert form["case_no"] == case_parts["case_number"]
    assert form["year"] == case_parts["year"]


def test_build_form_data_extracts_hidden_fields():
    scraper = BombayHighCourtScraper()
    html = (
        '<input type="hidden" name="_token" value="csrf123">'
        '<input type="hidden" name="form_secret" value="secret1">'
    )
    case_parts = scraper.parse_case_number("WP/1/2025")
    form = scraper._build_form_data(case_parts, html, [])
    assert form["_token"] == "csrf123"
    assert form["form_secret"] == "secret1"


# ---------------------------------------------------------------------------
# _extract_orders_from_html
# ---------------------------------------------------------------------------


def test_extract_orders_from_html_parses_table():
    scraper = BombayHighCourtScraper()
    base = "https://bombayhighcourt.gov.in/bhc/casestatus/casenumber"
    orders = scraper._extract_orders_from_html(_ORDERS_TABLE_HTML, base)
    assert len(orders) == 2
    assert orders[0]["listing_date"] == "09/04/2025"
    assert (
        orders[0]["download_url"] == "https://bombayhighcourt.gov.in/orders/order1.pdf"
    )
    assert orders[1]["listing_date"] == "10/05/2025"


def test_extract_orders_from_html_no_table_returns_empty():
    scraper = BombayHighCourtScraper()
    orders = scraper._extract_orders_from_html(
        "<html><body>no table</body></html>", "https://example.com/"
    )
    assert orders == []


def test_extract_orders_from_html_falls_back_to_pdf_links():
    scraper = BombayHighCourtScraper()
    html = """
    <html><body>
      <a href="/dl/a.pdf">Order 01/01/2025</a>
      <a href="/dl/b.pdf">Order 02/02/2025</a>
    </body></html>
    """
    orders = scraper._extract_orders_from_html(html, "https://court.example/")
    assert len(orders) == 2
    assert all(o["download_url"].endswith(".pdf") for o in orders)


def test_extract_orders_from_html_deduplicates_urls():
    scraper = BombayHighCourtScraper()
    html = """
    <div id="cn_CaseNoOrders">
      <table><tbody>
        <tr><td></td><td></td><td>01/01/2025</td><td></td>
            <td><a href="/orders/dup.pdf">D</a></td></tr>
      </tbody></table>
    </div>
    <a href="/orders/dup.pdf">Duplicate link</a>
    """
    base = "https://bombayhighcourt.gov.in/bhc/casestatus/casenumber"
    orders = scraper._extract_orders_from_html(html, base)
    urls = [o["download_url"] for o in orders]
    assert len(urls) == len(set(urls)), "Duplicate URLs should be deduplicated"


# ---------------------------------------------------------------------------
# _fetch_with_http
# ---------------------------------------------------------------------------


def test_fetch_with_http_success():
    scraper = BombayHighCourtScraper()
    mock_session, submitted = _make_mock_session(
        get_html="<html></html>",
        types_json=_CASE_TYPES_JSON,
        post_html=_FULL_RESPONSE_HTML,
    )
    scraper.session = mock_session

    result = scraper._fetch_with_http("WP/3373/2025")

    assert result is not None
    assert result["status"] == "found"
    assert result["source"] == "http"
    assert len(result["court_orders"]) == 2
    assert result["case_details"]["petitioner_name"] == "Petitioner A"


def test_fetch_with_http_json_wrapper_response():
    scraper = BombayHighCourtScraper()
    mock_session, _ = _make_mock_session(
        get_html="<html></html>",
        types_json=_CASE_TYPES_JSON,
        post_json={"status": True, "page": _FULL_RESPONSE_HTML},
    )
    scraper.session = mock_session

    result = scraper._fetch_with_http("WP/3373/2025")

    assert result is not None
    assert result["source"] == "http"


def test_fetch_with_http_json_status_false_returns_none():
    scraper = BombayHighCourtScraper()
    mock_session, _ = _make_mock_session(
        get_html="<html></html>",
        types_json=_CASE_TYPES_JSON,
        post_json={"status": False, "message": "Case not found"},
    )
    scraper.session = mock_session

    result = scraper._fetch_with_http("WP/9999/2025")
    assert result is None


def test_fetch_with_http_no_case_details_returns_none():
    scraper = BombayHighCourtScraper()
    mock_session, _ = _make_mock_session(
        get_html="<html></html>",
        types_json=_CASE_TYPES_JSON,
        post_html="<html><body>No matching content</body></html>",
    )
    scraper.session = mock_session

    result = scraper._fetch_with_http("WP/3373/2025")
    assert result is None


def test_fetch_with_http_get_error_raises():
    """Non-200 GET response raises HTTPError so _run_provider_attempts captures the status."""
    scraper = BombayHighCourtScraper()
    mock_session = Mock()
    mock_session.get = Mock(return_value=Mock(status_code=503, text=""))
    scraper.session = mock_session

    with pytest.raises(_requests.exceptions.HTTPError):
        scraper._fetch_with_http("WP/100/2025")


def test_fetch_with_http_network_exception_propagates():
    """Network errors propagate so _run_provider_attempts captures the error text."""
    scraper = BombayHighCourtScraper()
    mock_session = Mock()
    mock_session.get = Mock(side_effect=_requests.exceptions.ConnectionError("timeout"))
    scraper.session = mock_session

    with pytest.raises(_requests.exceptions.ConnectionError):
        scraper._fetch_with_http("WP/100/2025")


def test_fetch_with_http_invalid_case_ref_returns_none():
    scraper = BombayHighCourtScraper()
    result = scraper._fetch_with_http("INVALID")
    assert result is None


# ---------------------------------------------------------------------------
# _provider_attempt_sequence
# ---------------------------------------------------------------------------


def test_provider_attempt_sequence_http_uses_both():
    scraper = BombayHighCourtScraper()
    assert scraper._provider_attempt_sequence("http") == ["http", "playwright"]


def test_provider_attempt_sequence_playwright_only():
    scraper = BombayHighCourtScraper()
    assert scraper._provider_attempt_sequence("playwright") == ["playwright"]


def test_provider_attempt_sequence_default_is_http():
    scraper = BombayHighCourtScraper()
    assert scraper._provider_attempt_sequence("anything") == ["http", "playwright"]


# ---------------------------------------------------------------------------
# _run_provider_attempts — provider orchestration
# ---------------------------------------------------------------------------


def test_run_provider_attempts_http_succeeds_playwright_not_called(monkeypatch):
    """When HTTP succeeds, Playwright must never be invoked."""
    scraper = BombayHighCourtScraper()
    http_result = {
        "status": "found",
        "source": "http",
        "case_details": {},
        "court_orders": [
            {"listing_date": "09/04/2025", "download_url": "https://x.pdf"}
        ],
    }
    monkeypatch.setattr(scraper, "_fetch_with_http", lambda *a, **kw: http_result)
    monkeypatch.setattr(
        scraper,
        "_fetch_with_playwright_new",
        lambda *a, **kw: (_ for _ in ()).throw(
            AssertionError("Playwright must not be called")
        ),
    )

    run = scraper._run_provider_attempts("WP/1/2025", None, "mumbai", "http")
    assert run["result"]["source"] == "http"
    assert any(
        a["step"] == "http" and a["status"] == "success"
        for a in run["provider_attempts"]
    )


def test_run_provider_attempts_http_fails_uses_playwright(monkeypatch):
    """When HTTP returns None, Playwright fallback should return its result."""
    scraper = BombayHighCourtScraper()
    pw_result = {
        "status": "found",
        "source": "playwright",
        "case_details": {},
        "court_orders": [],
    }
    monkeypatch.setattr(scraper, "_fetch_with_http", lambda *a, **kw: None)
    monkeypatch.setattr(
        scraper, "_fetch_with_playwright_new", lambda *a, **kw: pw_result
    )

    run = scraper._run_provider_attempts("WP/1/2025", None, "mumbai", "http")
    assert run["result"]["source"] == "playwright"
    steps = [a["step"] for a in run["provider_attempts"]]
    assert "http" in steps
    assert "playwright" in steps


def test_run_provider_attempts_both_fail_returns_none(monkeypatch):
    scraper = BombayHighCourtScraper()
    monkeypatch.setattr(scraper, "_fetch_with_http", lambda *a, **kw: None)
    monkeypatch.setattr(scraper, "_fetch_with_playwright_new", lambda *a, **kw: None)
    scraper.playwright_retry_count = 1

    run = scraper._run_provider_attempts("WP/1/2025", None, "mumbai", "http")
    assert run["result"] is None


def test_run_provider_attempts_playwright_only_skips_http(monkeypatch):
    """Explicitly requesting playwright skips HTTP entirely."""
    scraper = BombayHighCourtScraper()
    pw_result = {
        "status": "found",
        "source": "playwright",
        "case_details": {},
        "court_orders": [],
    }
    monkeypatch.setattr(
        scraper,
        "_fetch_with_http",
        lambda *a, **kw: (_ for _ in ()).throw(
            AssertionError("HTTP must not be called")
        ),
    )
    monkeypatch.setattr(
        scraper, "_fetch_with_playwright_new", lambda *a, **kw: pw_result
    )

    run = scraper._run_provider_attempts("WP/1/2025", None, "mumbai", "playwright")
    assert run["result"]["source"] == "playwright"
    assert all(a["step"] == "playwright" for a in run["provider_attempts"])


# ---------------------------------------------------------------------------
# get_case_details / get_case_orders — provider integration
# ---------------------------------------------------------------------------


def test_get_case_details_invalid_case_ref_returns_error():
    scraper = BombayHighCourtScraper()
    result = scraper.get_case_details("INVALID")
    assert result["error"] == "Invalid case reference format"


def test_get_case_details_uses_provider_result(monkeypatch):
    scraper = BombayHighCourtScraper()
    monkeypatch.setattr(
        scraper,
        "_fetch_with_provider",
        lambda case_ref, date=None, bench="mumbai": {
            "status": "found",
            "source": "http",
            "case_details": {
                "case_number": case_ref,
                "petitioner_name": "Petitioner A",
                "respondent_name": "Respondent B",
                "case_status_url": "https://example.com/case-status",
            },
            "court_orders": [{"listing_date": "09/04/2025"}],
        },
    )

    result = scraper.get_case_details("WP/3373/2025")

    assert result["status"] == "found"
    assert result["source"] == "http"
    assert result["petitioner"] == "Petitioner A"
    assert result["respondent"] == "Respondent B"
    assert result["case_status_url"] == "https://example.com/case-status"
    assert len(result["court_orders"]) == 1


def test_get_case_orders_invalid_case_ref_returns_error():
    scraper = BombayHighCourtScraper()
    result = scraper.get_case_orders("INVALID")
    assert result["status"] == "error"
    assert result["court_orders"] == []


def test_debug_case_orders_invalid_case_ref_returns_ok_false():
    scraper = BombayHighCourtScraper()
    result = scraper.debug_case_orders("INVALID", None, "mumbai")
    assert result["ok"] is False
    assert result["error"] == "Invalid case reference format"


# ---------------------------------------------------------------------------
# _build_short_title / _enrich_case_orders_result
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "petitioner, respondent, expected",
    [
        ("Alice", "Bob", "Alice against Bob"),
        ("Alice", None, "Alice"),
        (None, "Bob", "Bob"),
        (None, None, None),
    ],
)
def test_build_short_title(petitioner, respondent, expected):
    scraper = BombayHighCourtScraper()
    assert scraper._build_short_title(petitioner, respondent) == expected


def test_enrich_case_orders_result_uses_title_from_case_details():
    scraper = BombayHighCourtScraper()
    provider_result = {
        "case_details": {
            "petitioner_name": "Alice",
            "respondent_name": "Bob",
            "case_summary": "Summary text",
            "title": "Explicit Title",
        },
        "court_orders": [],
    }
    enriched = scraper._enrich_case_orders_result(provider_result)
    assert enriched["title"] == "Explicit Title"
    assert enriched["petitioner"] == "Alice"
    assert enriched["respondent"] == "Bob"
    assert enriched["case_summary"] == "Summary text"
    assert enriched["case_orders"] == []


def test_enrich_case_orders_result_builds_title_when_missing():
    scraper = BombayHighCourtScraper()
    provider_result = {
        "case_details": {
            "petitioner_name": "Alice",
            "respondent_name": "Bob",
            "case_summary": None,
            "title": None,
        },
        "court_orders": [
            {
                "listing_date": "01/01/2025",
                "download_url": "http://example.com/order.pdf",
            },
            {"listing_date": "02/01/2025", "download_url": None},
        ],
    }
    enriched = scraper._enrich_case_orders_result(provider_result)
    assert enriched["title"] == "Alice against Bob"
    assert enriched["case_orders"] == [
        {"date": "01/01/2025", "download_link": "http://example.com/order.pdf"}
    ]

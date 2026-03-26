from unittest.mock import Mock

import pytest

from billingonaire_backend.CourtScraper import BombayHighCourtScraper


def test_scraper_initialization_defaults_to_direct_api():
    scraper = BombayHighCourtScraper()
    assert scraper.scraper_provider == "direct_api"
    assert scraper.get_scraper_config()["supported_providers"] == [
        "direct_api",
        "playwright",
    ]


def test_parse_case_number():
    scraper = BombayHighCourtScraper()
    result = scraper.parse_case_number("WP/10460/2023")
    assert result == {
        "case_type": "WP",
        "case_number": "10460",
        "year": "2023",
    }


@pytest.mark.parametrize("case_ref", ["INVALID", "WP-123-2024", "WP/123"])
def test_parse_case_number_invalid(case_ref):
    scraper = BombayHighCourtScraper()
    assert scraper.parse_case_number(case_ref) == {}


def test_configure_scraper_accepts_supported_provider():
    scraper = BombayHighCourtScraper()
    updated = scraper.configure_scraper(provider="playwright")
    assert updated["provider"] == "playwright"


def test_configure_scraper_rejects_invalid_provider():
    scraper = BombayHighCourtScraper()
    with pytest.raises(ValueError):
        scraper.configure_scraper(provider="invalid_provider")


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
            "source": "direct_api",
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
    assert result["source"] == "direct_api"
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


def test_fetch_with_direct_api_parses_json_success_response(monkeypatch):
    scraper = BombayHighCourtScraper()

    mock_session = Mock()
    mock_initial_response = Mock()
    mock_initial_response.status_code = 200
    mock_initial_response.text = (
        '<input type="hidden" name="_token" value="csrf123">'
        '<input type="hidden" name="form_secret" value="secret1">'
    )

    mock_ajax_response = Mock()
    mock_ajax_response.status_code = 200
    mock_ajax_response.json.return_value = [
        {
            "case_type": 1,
            "type_name": "WP",
            "type_flag": "1",
            "full_form": "Writ Petition",
        }
    ]

    mock_post_response = Mock()
    mock_post_response.status_code = 200
    mock_post_response.url = "https://bombayhighcourt.gov.in/bhc/casestatus/casenumber"
    mock_post_response.json.return_value = {
        "status": True,
        "page": """
        <section>
            <div class="tab-content">
                <div class="card tab-pane active" id="cn_CaseNoUpdates">
                    <div class="card-header">
                        Case No. <b>WP/3373/2025</b>
                        was filed on <b>26/02/2025</b>
                        by <b>MOTILAL OSWAL HOME FINANCE LTD</b>
                        against <b>THE STATE OF MAHARASHTRA</b>
                    </div>
                </div>
                <div class="tab-pane fade" id="cn_CaseNoOrders">
                    <div class="card-body">
                        <table class="table">
                            <tbody>
                                <tr>
                                    <td>1</td>
                                    <td>HON'BLE JUSTICE A.S. CHANDURKAR</td>
                                    <td>09/04/2025</td>
                                    <td>Interim Order</td>
                                    <td>
                                        <a href="https://bombayhighcourt.gov.in/bhc/file/download/order1.pdf">View</a>
                                    </td>
                                </tr>
                            </tbody>
                        </table>
                    </div>
                </div>
            </div>
        </section>
        """,
    }

    mock_session.get.side_effect = [mock_initial_response, mock_ajax_response]
    mock_session.post.return_value = mock_post_response

    monkeypatch.setattr(
        "billingonaire_backend.CourtScraper.requests.Session", lambda: mock_session
    )

    result = scraper._fetch_with_direct_api("WP/3373/2025")

    assert result is not None
    assert result["status"] == "found"
    assert result["source"] == "direct_api"
    assert result["case_details"]["case_number"] == "WP/3373/2025"
    assert result["case_details"]["petitioner_name"] == "MOTILAL OSWAL HOME FINANCE LTD"
    assert result["case_details"]["respondent_name"] == "THE STATE OF MAHARASHTRA"
    assert result["case_details"]["filing_date"] == "26/02/2025"
    assert result["court_orders"] == [
        {
            "listing_date": "09/04/2025",
            "download_url": "https://bombayhighcourt.gov.in/bhc/file/download/order1.pdf",
        }
    ]


def test_extract_orders_from_html_prefers_orders_table_links():
    scraper = BombayHighCourtScraper()

    html_content = """
    <section>
        <div class="content-header">
            <a href="/bhc/file/download/cause-list.pdf">Download Cause List</a>
        </div>
        <div class="tab-content">
            <div class="tab-pane fade" id="cn_CaseNoOrders">
                <div class="card-body">
                    <table class="table">
                        <tbody>
                            <tr>
                                <td>1</td>
                                <td>HON'BLE JUSTICE A.S. CHANDURKAR</td>
                                <td>09/04/2025</td>
                                <td>Interim Order</td>
                                <td><a href="/bhc/file/download/order1.pdf">View</a></td>
                            </tr>
                            <tr>
                                <td>2</td>
                                <td>HON'BLE JUSTICE M.S. KARNIK</td>
                                <td>10/04/2025</td>
                                <td>Final Order</td>
                                <td><a href="https://bombayhighcourt.gov.in/bhc/file/download/order2.pdf">View</a></td>
                            </tr>
                        </tbody>
                    </table>
                </div>
            </div>
        </div>
        <footer>
            <a href="https://bombayhighcourt.gov.in/bhc/file/download/order1.pdf">Duplicate footer link</a>
        </footer>
    </section>
    """

    result = scraper._extract_orders_from_html(
        html_content,
        "https://bombayhighcourt.gov.in/bhc/casestatus/casenumber",
    )

    assert result == [
        {
            "listing_date": "09/04/2025",
            "download_url": "https://bombayhighcourt.gov.in/bhc/file/download/order1.pdf",
        },
        {
            "listing_date": "10/04/2025",
            "download_url": "https://bombayhighcourt.gov.in/bhc/file/download/order2.pdf",
        },
    ]


def test_fetch_with_direct_api_handles_not_found_json(monkeypatch):
    scraper = BombayHighCourtScraper()

    mock_session = Mock()
    mock_initial_response = Mock()
    mock_initial_response.status_code = 200
    mock_initial_response.text = (
        '<input type="hidden" name="_token" value="csrf123">'
        '<input type="hidden" name="form_secret" value="secret1">'
    )

    mock_ajax_response = Mock()
    mock_ajax_response.status_code = 200
    mock_ajax_response.json.return_value = []

    mock_post_response = Mock()
    mock_post_response.status_code = 200
    mock_post_response.json.return_value = {
        "status": False,
        "message": "Case not found",
    }

    mock_session.get.side_effect = [mock_initial_response, mock_ajax_response]
    mock_session.post.return_value = mock_post_response

    monkeypatch.setattr(
        "billingonaire_backend.CourtScraper.requests.Session", lambda: mock_session
    )

    result = scraper._fetch_with_direct_api("WP/9999/2025")
    assert result is None


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

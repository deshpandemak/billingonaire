import pytest

from billingonaire_backend.CourtScraper import BombayHighCourtScraper


def test_scraper_initialization():
    scraper = BombayHighCourtScraper()
    assert scraper is not None


def test_parse_case_number():
    scraper = BombayHighCourtScraper()
    result = scraper.parse_case_number("WP/10460/2023")
    assert isinstance(result, dict)
    assert "case_type" in result
    assert "case_number" in result
    assert "year" in result


def test_parse_case_number_invalid():
    scraper = BombayHighCourtScraper()
    result = scraper.parse_case_number("INVALID")
    assert isinstance(result, dict)
    # Should be empty dict for invalid input
    assert result == {}


def test_get_case_details_error():
    scraper = BombayHighCourtScraper()
    # Should not raise, just return empty dict or error info
    result = scraper.get_case_details("INVALID")
    assert isinstance(result, dict)


def test_get_case_details_uses_firecrawl_result(monkeypatch):
    scraper = BombayHighCourtScraper()
    mocked = {
        "status": "found",
        "source": "firecrawl",
        "case_details": {
            "case_number": "WP/3373/2025",
            "petitioner_name": "Petitioner A",
            "respondent_name": "Respondent B",
            "case_status_url": "https://example.com/case-status",
        },
        "court_orders": [{"listing_date": "09/04/2025"}],
    }
    monkeypatch.setattr(
        scraper, "_fetch_with_firecrawl", lambda case_ref, date=None: mocked
    )

    result = scraper.get_case_details("WP/3373/2025")

    assert result["status"] == "found"
    assert result["source"] == "firecrawl"
    assert result["case_number"] == "WP/3373/2025"
    assert result["petitioner"] == "Petitioner A"
    assert result["respondent"] == "Respondent B"
    assert result["case_status_url"] == "https://example.com/case-status"
    assert isinstance(result["court_orders"], list)


def test_normalize_firecrawl_payload_applies_defaults_and_date_filter():
    scraper = BombayHighCourtScraper()
    payload = {
        "case_details": {
            "petitioner_name": "Petitioner A",
            "respondent_name": "Respondent B",
            "case_number": "WP/3373/2025",
        },
        "court_orders": [
            {
                "listing_date": "09/04/2025",
                "download_url": "https://example.com/order-1.pdf",
            },
            {
                "listing_date": "08/04/2025",
                "download_url": "https://example.com/order-2.pdf",
            },
        ],
    }

    result = scraper._normalize_firecrawl_payload(
        payload,
        case_ref="WP/3373/2025",
        date="2025-04-09",
    )

    assert result["status"] == "found"
    assert result["source"] == "firecrawl"
    assert result["case_details"]["petitioner_name"] == "Petitioner A"
    assert (
        result["case_details"]["petitioner_name_citation"]
        == scraper.bombay_high_court_url
    )
    assert len(result["court_orders"]) == 1
    assert (
        result["court_orders"][0]["download_url"] == "https://example.com/order-1.pdf"
    )
    assert result["court_orders"][0]["order_description"] == "Order/Judg-1"


def test_get_case_orders_uses_firecrawl_result(monkeypatch):
    scraper = BombayHighCourtScraper()
    mocked = {
        "status": "found",
        "source": "firecrawl",
        "case_details": {"case_number": "WP/3373/2025"},
        "court_orders": [{"listing_date": "09/04/2025"}],
    }
    monkeypatch.setattr(
        scraper, "_fetch_with_firecrawl", lambda case_ref, date=None: mocked
    )

    result = scraper.get_case_orders("WP/3373/2025", "2025-04-09", "mumbai")
    assert result == mocked


def test_get_case_orders_fallback_shape_when_firecrawl_unavailable(monkeypatch):
    scraper = BombayHighCourtScraper()
    monkeypatch.setattr(
        scraper, "_fetch_with_firecrawl", lambda case_ref, date=None: None
    )

    result = scraper.get_case_orders("WP/3373/2025", "2025-04-09", "mumbai")

    assert isinstance(result, dict)
    assert result["status"] == "captcha_required"
    assert "case_details" in result
    assert "court_orders" in result
    assert isinstance(result["court_orders"], list)


def test_fetch_with_firecrawl_extract_sdk_compat(monkeypatch):
    scraper = BombayHighCourtScraper()
    scraper.firecrawl_api_key = "test-key"
    scraper.firecrawl_model = "spark-1-mini"

    class FakeExtractResponse:
        def model_dump(self):
            return {
                "data": {
                    "case_details": {
                        "petitioner_name": "Petitioner A",
                        "respondent_name": "Respondent B",
                        "case_number": "WP/3373/2025",
                    },
                    "court_orders": [
                        {
                            "listing_date": "09/04/2025",
                            "download_url": "https://example.com/order.pdf",
                        }
                    ],
                }
            }

    class FakeFirecrawlApp:
        def __init__(self, api_key):
            self.api_key = api_key

        def extract(self, **kwargs):
            assert kwargs.get("prompt")
            assert kwargs.get("schema")
            assert kwargs.get("agent", {}).get("model") == "spark-1-mini"
            return FakeExtractResponse()

    monkeypatch.setattr(
        "billingonaire_backend.CourtScraper.FirecrawlApp", FakeFirecrawlApp
    )

    result = scraper._fetch_with_firecrawl("WP/3373/2025", date="2025-04-09")

    assert isinstance(result, dict)
    assert result["source"] == "firecrawl"
    assert result["status"] == "found"
    assert result["case_details"]["case_number"] == "WP/3373/2025"
    assert len(result["court_orders"]) == 1

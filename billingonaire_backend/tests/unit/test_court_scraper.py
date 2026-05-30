from unittest.mock import Mock

import pytest

from billingonaire_backend.CourtScraper import BombayHighCourtScraper


def test_scraper_initialization_defaults_to_playwright():
    scraper = BombayHighCourtScraper()
    assert scraper.scraper_provider == "playwright"
    assert scraper.get_scraper_config()["supported_providers"] == ["playwright"]


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
            "source": "playwright",
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
    assert result["source"] == "playwright"
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

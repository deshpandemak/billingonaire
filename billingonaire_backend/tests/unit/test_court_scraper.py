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


# ...existing code...

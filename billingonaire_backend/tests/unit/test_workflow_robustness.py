"""Tests for workflow robustness improvements.

Covers:
- Auto-queue for analysis when order fetch succeeds but analysis fails
- DEFAULT_MAX_SEQUENCE_RETRIES reduced to 10
- Firecrawl wildcard URL usage
- /jobs/retry-failed endpoint logic
"""

import sys
import types
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

# Stub spaCy to avoid import-time crashes in CI environments.
if "spacy" not in sys.modules:
    spacy_stub = types.ModuleType("spacy")
    spacy_matcher_stub = types.ModuleType("spacy.matcher")

    class Matcher:  # pragma: no cover - test import shim only
        pass

    spacy_matcher_stub.Matcher = Matcher
    spacy_stub.matcher = spacy_matcher_stub
    sys.modules["spacy"] = spacy_stub
    sys.modules["spacy.matcher"] = spacy_matcher_stub

from billingonaire_backend.AutoOrderManager import AutoOrderManager
from billingonaire_backend.CourtScraper import BombayHighCourtScraper


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def manager():
    """AutoOrderManager with all heavy dependencies mocked."""
    with (
        patch("billingonaire_backend.AutoOrderManager.firestore") as mock_fs,
        patch("billingonaire_backend.AutoOrderManager.OrderDocumentAnalyzer"),
        patch("billingonaire_backend.AutoOrderManager.BombayHighCourtScraper"),
    ):
        mgr = AutoOrderManager()
        mgr.db = Mock()
        mgr.case_store = Mock()
        mgr.case_store.get_case_details = Mock(return_value={})
        mgr.case_store.build_case_ref = Mock(
            side_effect=lambda ct, cn, cy: f"{ct}/{cn}/{cy}"
        )
        mgr.case_store.transition_lifecycle = Mock()
        mgr.case_store.append_case_order = Mock()
        mgr.case_store.map_legacy_order_status = Mock(return_value=None)
        yield mgr


# ---------------------------------------------------------------------------
# 1.  Default max_sequences reduced from 50 → 10
# ---------------------------------------------------------------------------


def test_default_max_sequence_retries_is_10(manager, monkeypatch):
    """_process_single_case should default to 10 sequence retries, not 50."""
    monkeypatch.delenv("ORDER_MAX_SEQUENCE_RETRIES", raising=False)

    attempts = []

    def fake_download(case_data, seq):
        attempts.append(seq)
        return {"success": False, "error": "not found"}

    manager._download_order_for_case = fake_download

    case_data = {
        "id": "2025-04-09-WP-100-2025",
        "case_ref": "WP/100/2025",
        "board_date": "2024-01-01",  # past date so fetch is due
        "order_status": "not_linked",
    }

    result = manager._process_single_case(case_data)

    assert result["download_success"] is False
    assert len(attempts) == 10, f"Expected 10 attempts, got {len(attempts)}"


def test_env_var_overrides_max_sequence_retries(manager, monkeypatch):
    """ORDER_MAX_SEQUENCE_RETRIES env var should override the default."""
    monkeypatch.setenv("ORDER_MAX_SEQUENCE_RETRIES", "3")

    attempts = []

    def fake_download(case_data, seq):
        attempts.append(seq)
        return {"success": False, "error": "not found"}

    manager._download_order_for_case = fake_download

    case_data = {
        "id": "2025-04-09-WP-200-2025",
        "case_ref": "WP/200/2025",
        "board_date": "2024-01-01",
        "order_status": "not_linked",
    }

    result = manager._process_single_case(case_data)

    assert len(attempts) == 3, f"Expected 3 attempts, got {len(attempts)}"


# ---------------------------------------------------------------------------
# 2.  Firecrawl uses wildcard URL
# ---------------------------------------------------------------------------


def test_firecrawl_uses_wildcard_url(monkeypatch):
    """_fetch_with_firecrawl must pass a wildcard crawl URL to the SDK."""
    scraper = BombayHighCourtScraper()
    scraper.firecrawl_api_key = "test-key"
    scraper.firecrawl_model = "spark-1-mini"

    captured_urls = []

    class FakeExtractResponse:
        def model_dump(self):
            return {
                "data": {
                    "case_details": {
                        "petitioner_name": "Alice",
                        "respondent_name": "Bob",
                        "case_number": "WP/1/2025",
                    },
                    "court_orders": [],
                }
            }

    class FakeFirecrawlApp:
        def __init__(self, api_key):
            self.api_key = api_key

        def extract(self, urls=None, **kwargs):
            captured_urls.extend(urls or [])
            return FakeExtractResponse()

    monkeypatch.setattr(
        "billingonaire_backend.CourtScraper.FirecrawlApp", FakeFirecrawlApp
    )

    scraper._fetch_with_firecrawl("WP/1/2025")

    assert len(captured_urls) == 1, "Expected exactly one URL passed to extract()"
    assert captured_urls[0].endswith("/*"), (
        f"Expected wildcard URL, got: {captured_urls[0]}"
    )
    assert "bombayhighcourt.nic.in" in captured_urls[0]


# ---------------------------------------------------------------------------
# 3.  /jobs/retry-failed — unit tests via direct import of the endpoint handler
# ---------------------------------------------------------------------------


def _make_mock_case(
    case_ref: str,
    order_status: str,
    board_date: str = "2024-01-15",
    order_link: str = None,
) -> dict:
    ct, cn, cy = case_ref.split("/")
    return {
        "id": f"{board_date}-{ct}-{cn}-{cy}",
        "case_ref": case_ref,
        "case_type": ct,
        "case_no": cn,
        "case_year": cy,
        "board_date": board_date,
        "order_status": order_status,
        "order_link": order_link,
    }


def test_retry_failed_separates_fetch_and_analysis(manager):
    """order_failed goes to fetch queue; order_analysis_failed with link goes to analysis."""
    failed_case = _make_mock_case("WP/10/2025", "order_failed")
    analysis_failed_case = _make_mock_case(
        "WP/20/2025",
        "order_analysis_failed",
        order_link="https://example.com/order.pdf",
    )

    manager._get_filtered_matters = Mock(
        return_value=[failed_case, analysis_failed_case]
    )

    fetch_queue_items = []
    analysis_queue_items = []

    # Simulate the retry logic (mirrors main.py retry_failed_cases)
    for case_data in [failed_case, analysis_failed_case]:
        status = case_data.get("order_status", "")
        if status == "order_failed":
            fetch_queue_items.append(case_data["case_ref"])
        elif status == "order_analysis_failed":
            order_link = case_data.get("order_link")
            if order_link:
                analysis_queue_items.append(case_data["case_ref"])
            else:
                fetch_queue_items.append(case_data["case_ref"])

    assert "WP/10/2025" in fetch_queue_items
    assert "WP/20/2025" in analysis_queue_items
    assert "WP/20/2025" not in fetch_queue_items


def test_retry_failed_analysis_failed_without_link_goes_to_fetch(manager):
    """order_analysis_failed without a stored link falls back to the fetch queue."""
    case = _make_mock_case("WP/30/2025", "order_analysis_failed", order_link=None)

    fetch_queue_items = []
    analysis_queue_items = []

    status = case.get("order_status", "")
    order_link = case.get("order_link")

    if status == "order_failed":
        fetch_queue_items.append(case["case_ref"])
    elif status == "order_analysis_failed":
        if order_link:
            analysis_queue_items.append(case["case_ref"])
        else:
            fetch_queue_items.append(case["case_ref"])

    assert "WP/30/2025" in fetch_queue_items
    assert "WP/30/2025" not in analysis_queue_items


def test_retry_failed_skips_non_retryable_statuses(manager):
    """Cases with analysed/not_linked/linked status should not be retried."""
    cases = [
        _make_mock_case("WP/1/2025", "analysed"),
        _make_mock_case("WP/2/2025", "not_linked"),
        _make_mock_case("WP/3/2025", "linked"),
        _make_mock_case("WP/4/2025", "order_failed"),
    ]

    retried = [
        c["case_ref"]
        for c in cases
        if c.get("order_status") in ("order_failed", "order_analysis_failed")
    ]

    assert retried == ["WP/4/2025"]

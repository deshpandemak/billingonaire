import sys
import types
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

# Test-only fallback to avoid spaCy import-time crashes in environments where
# spaCy and pydantic versions are temporarily incompatible.
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


@pytest.fixture
def manager_with_mocks():
    with (
        patch("billingonaire_backend.AutoOrderManager.firestore") as mock_fs,
        patch(
            "billingonaire_backend.AutoOrderManager.OrderDocumentAnalyzer"
        ) as mock_analyzer,
        patch(
            "billingonaire_backend.AutoOrderManager.BombayHighCourtScraper"
        ) as mock_scraper,
    ):
        manager = AutoOrderManager()

        manager.db = Mock()
        boards_collection = Mock()
        case_details_collection = Mock()
        search_index_collection = Mock()

        def get_collection(name):
            if name == manager.boards_collection:
                return boards_collection
            if name == manager.case_store.case_collection:
                return case_details_collection
            if name == manager.search_index_collection:
                return search_index_collection
            return Mock()

        manager.db.collection.side_effect = get_collection

        board_doc_ref = Mock()
        board_snapshot = Mock()
        board_snapshot.exists = True
        board_snapshot.to_dict.return_value = {}
        board_doc_ref.get.return_value = board_snapshot
        boards_collection.document.return_value = board_doc_ref

        case_doc_ref = Mock()
        case_snapshot = Mock()
        case_snapshot.exists = False
        case_snapshot.to_dict.return_value = {}
        case_doc_ref.get.return_value = case_snapshot
        case_details_collection.document.return_value = case_doc_ref

        manager.case_store.db = manager.db

        manager.order_analyzer = mock_analyzer.return_value
        manager.court_scraper = mock_scraper.return_value
        yield manager


def test_process_single_case_playwright_success(manager_with_mocks):
    """Playwright returns an order; download and analysis complete successfully."""
    manager = manager_with_mocks
    case_data = {
        "id": "case_3373",
        "case_ref": "WP/3373/2025",
        "case_type": "WP",
        "case_no": 3373,
        "case_year": 2025,
        "board_date": "2025-04-09",
        "order_status": "not_linked",
    }

    manager.court_scraper._fetch_with_provider.return_value = {
        "result": {"_dummy": True},
        "provider_sequence": ["http"],
        "provider_attempts": [{"step": "http", "status": "success", "duration_ms": 100}],
    }
    manager.court_scraper._enrich_case_orders_result.return_value = {
        "status": "found",
        "source": "playwright",
        "petitioner": "MOTILAL OSWAL HOME FINANCE LTD",
        "respondent": "THE STATE OF MAHARASHTRA AND ORS",
        "case_orders": [
            {
                "date": "2025-04-09",
                "download_link": "https://example.com/order.pdf",
            }
        ],
    }

    manager._is_order_already_analysed = Mock(return_value=False)
    manager._upload_order_to_gcs = Mock(return_value=None)
    manager._analyze_order_with_api_metadata = Mock(
        return_value={"success": True, "data": {"order_category": "ADJOURNED"}}
    )
    manager.case_store.update_case_party_names = Mock()

    with patch("billingonaire_backend.AutoOrderManager.requests.get") as mock_get:
        mock_resp = Mock()
        mock_resp.status_code = 200
        mock_resp.headers = {"Content-Type": "application/pdf"}
        mock_resp.content = b"%PDF-1.7 test"
        mock_get.return_value = mock_resp

        result = manager._process_single_case(case_data)

    assert result["download_success"] is True
    manager.court_scraper._fetch_with_provider.assert_called_once_with(
        case_ref="WP/3373/2025", date="2025-04-09", bench="mumbai", include_diagnostics=True
    )


def test_process_single_case_playwright_no_orders(manager_with_mocks):
    """When Playwright finds no orders, download fails gracefully."""
    manager = manager_with_mocks
    case_data = {
        "id": "case_3374",
        "case_ref": "WP/3374/2025",
        "case_type": "WP",
        "case_no": 3374,
        "case_year": 2025,
        "board_date": "2025-04-09",
        "order_status": "not_linked",
    }

    manager.court_scraper._fetch_with_provider.return_value = {
        "result": None,
        "provider_sequence": ["http", "playwright"],
        "provider_attempts": [
            {"step": "http", "status": "no_result", "duration_ms": 200},
            {"step": "playwright", "status": "no_result", "duration_ms": 5000},
        ],
    }

    result = manager._process_single_case(case_data)

    assert result["download_success"] is False
    manager.court_scraper._fetch_with_provider.assert_called_once_with(
        case_ref="WP/3374/2025", date="2025-04-09", bench="mumbai", include_diagnostics=True
    )

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

        # Explicit DB mock chain to validate persisted updates.
        manager.db = Mock()
        manager.db.collection.return_value.document.return_value.update = Mock()

        manager.order_analyzer = mock_analyzer.return_value
        manager.court_scraper = mock_scraper.return_value
        yield manager


def test_process_single_case_uses_structured_scraper_workflow(manager_with_mocks):
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

    manager.court_scraper.get_case_orders.return_value = {
        "status": "found",
        "source": "firecrawl",
        "case_details": {
            "case_number": "WP/3373/2025",
            "petitioner_name": "MOTILAL OSWAL HOME FINANCE LTD",
            "respondent_name": "THE STATE OF MAHARASHTRA AND ORS",
        },
        "court_orders": [
            {
                "listing_date": "09/04/2025",
                "download_url": "https://example.com/structured-order.pdf",
                "order_description": "Order/Judg-1",
            }
        ],
    }

    # Ensure no legacy sequence-based URL generation is needed on structured success.
    manager._download_pdf_bombay_hc_simple = Mock(
        side_effect=AssertionError("Legacy sequence downloader should not be called")
    )

    manager.order_analyzer.analyze_order_document.return_value = SimpleNamespace(
        order_date="2025-04-09"
    )

    manager._analyze_order_with_date_validation = Mock(
        return_value={"success": True, "data": {"order_category": "final"}}
    )
    manager._create_search_index_entry = Mock()
    manager._link_order_to_additional_cases = Mock(return_value=[])

    with patch("billingonaire_backend.AutoOrderManager.requests.get") as mock_get:
        mock_get.return_value = SimpleNamespace(
            status_code=200,
            headers={"Content-Type": "application/pdf"},
            content=b"%PDF-1.7 test",
        )

        result = manager._process_single_case(case_data, max_sequences=2)

    assert result["download_success"] is True
    assert result["analysis_success"] is True
    assert result["order_link"] == "https://example.com/structured-order.pdf"

    persisted_updates = (
        manager.db.collection.return_value.document.return_value.update.call_args_list
    )
    assert persisted_updates
    assert any(
        call.args
        and isinstance(call.args[0], dict)
        and call.args[0].get("order_status") == "linked"
        and call.args[0].get("order_link") == "https://example.com/structured-order.pdf"
        and call.args[0].get("order_source") == "firecrawl_structured"
        for call in persisted_updates
    )


def test_process_single_case_falls_back_to_legacy_when_structured_unavailable(
    manager_with_mocks,
):
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

    manager.court_scraper.get_case_orders.return_value = {
        "status": "not_found",
        "source": "ecourts_fallback",
        "court_orders": [],
        "message": "Court order lookup did not yield downloadable links via configured scraper provider",
    }

    manager._download_pdf_bombay_hc_simple = Mock(
        return_value={
            "success": True,
            "download_url": "https://example.com/legacy-sequence-order.pdf",
            "pdf_content": b"%PDF-1.7 legacy",
            "filename": "WP-3374-2025-09042025.pdf",
            "sequence_number": 1,
        }
    )

    manager.order_analyzer.analyze_order_document.return_value = SimpleNamespace(
        order_date="2025-04-09"
    )

    manager._analyze_order_with_date_validation = Mock(
        return_value={"success": True, "data": {"order_category": "final"}}
    )
    manager._create_search_index_entry = Mock()
    manager._link_order_to_additional_cases = Mock(return_value=[])

    result = manager._process_single_case(case_data, max_sequences=2)

    assert result["download_success"] is True
    assert result["analysis_success"] is True
    assert result["order_link"] == "https://example.com/legacy-sequence-order.pdf"
    manager.court_scraper.get_case_orders.assert_called_once_with(
        case_ref="WP/3374/2025", date="2025-04-09", bench="mumbai"
    )
    manager._download_pdf_bombay_hc_simple.assert_called_once()

    persisted_updates = (
        manager.db.collection.return_value.document.return_value.update.call_args_list
    )
    assert any(
        call.args
        and isinstance(call.args[0], dict)
        and call.args[0].get("order_status") == "linked"
        and call.args[0].get("order_link")
        == "https://example.com/legacy-sequence-order.pdf"
        and call.args[0].get("order_source") == "bombay_hc_api"
        for call in persisted_updates
    )

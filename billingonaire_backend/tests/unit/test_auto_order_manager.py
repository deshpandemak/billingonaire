import sys
import types
from datetime import datetime
from unittest.mock import MagicMock, Mock, patch

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
def mock_firestore():
    """Mock Firestore client"""
    with patch("billingonaire_backend.AutoOrderManager.firestore") as mock_fs:
        yield mock_fs


@pytest.fixture
def auto_order_manager(mock_firestore):
    """Create AutoOrderManager instance with mocked dependencies"""
    with (
        patch(
            "billingonaire_backend.AutoOrderManager.OrderDocumentAnalyzer"
        ) as mock_analyzer,
        patch(
            "billingonaire_backend.AutoOrderManager.BombayHighCourtScraper"
        ) as mock_scraper,
    ):
        manager = AutoOrderManager()
        manager.order_analyzer = mock_analyzer.return_value
        manager.court_scraper = mock_scraper.return_value
        yield manager


def test_auto_order_manager_initialization():
    """Test that AutoOrderManager initializes correctly"""
    with (
        patch("billingonaire_backend.AutoOrderManager.firestore"),
        patch("billingonaire_backend.AutoOrderManager.OrderDocumentAnalyzer"),
        patch("billingonaire_backend.AutoOrderManager.BombayHighCourtScraper"),
    ):
        manager = AutoOrderManager()
        assert manager is not None
        assert manager.boards_collection == "daily-boards"
        # orders_collection removed - order status now consolidated in daily-boards
        assert manager.search_index_collection == "order-search-index"


def test_process_single_case_download_success_analysis_success(auto_order_manager):
    """Test successful order download and analysis"""
    # Setup test data
    case_id = "test_case_123"
    case_ref = "WP/123/2024"
    case_data = {
        "id": case_id,
        "case_ref": case_ref,
        "case_type": "WP",
        "case_no": 123,
        "case_year": 2024,
        "board_date": "2024-01-15",
        "order_status": "not_linked",
    }

    # Mock successful download
    download_result = {
        "success": True,
        "order_link": "http://example.com/order.pdf",
        "pdf_content": b"PDF content here",
        "filename": "order.pdf",
        "source": "bombay_hc_api",
    }

    # Mock successful analysis
    analysis_result = {
        "success": True,
        "data": {
            "order_category": "final",
            "order_date": "2024-01-15",
            "order_cases": [],
        },
    }

    # Mock date validation (matching dates)
    auto_order_manager._download_order_for_case = Mock(return_value=download_result)
    auto_order_manager._analyze_order_with_date_validation = Mock(
        return_value=analysis_result
    )
    auto_order_manager._validate_order_date = Mock(
        return_value={
            "valid": True,
            "extracted_date": "2024-01-15",
            "expected_date": "2024-01-15",
        }
    )
    auto_order_manager._create_order_link = Mock()
    auto_order_manager._create_search_index_entry = Mock()
    auto_order_manager._link_order_to_additional_cases = Mock(return_value=[])

    # Mock order analyzer for quick analysis
    auto_order_manager.order_analyzer.analyze_order_document = Mock(
        return_value=Mock(order_date="2024-01-15")
    )

    # Execute
    result = auto_order_manager._process_single_case(case_data)

    # Verify
    assert result["download_success"] is True
    assert result["analysis_success"] is True
    assert result["order_link"] == "http://example.com/order.pdf"
    assert result["error"] is None
    auto_order_manager._create_order_link.assert_called_once()
    auto_order_manager._analyze_order_with_date_validation.assert_called_once()


def test_process_single_case_download_success_analysis_failure(auto_order_manager):
    """Test order download succeeds but analysis fails - should keep the order link"""
    # Setup test data
    case_id = "test_case_456"
    case_ref = "WP/456/2024"
    case_data = {
        "id": case_id,
        "case_ref": case_ref,
        "case_type": "WP",
        "case_no": 456,
        "case_year": 2024,
        "board_date": "2024-01-20",
        "order_status": "not_linked",
    }

    # Mock successful download
    download_result = {
        "success": True,
        "order_link": "http://example.com/order456.pdf",
        "pdf_content": b"PDF content here",
        "filename": "order456.pdf",
        "source": "bombay_hc_api",
    }

    # Mock failed analysis
    analysis_result = {
        "success": False,
        "error": "Failed to extract order details",
    }

    # Mock date validation (matching dates so download is accepted)
    auto_order_manager._download_order_for_case = Mock(return_value=download_result)
    auto_order_manager._analyze_order_with_date_validation = Mock(
        return_value=analysis_result
    )
    auto_order_manager._validate_order_date = Mock(
        return_value={
            "valid": True,
            "extracted_date": "2024-01-20",
            "expected_date": "2024-01-20",
        }
    )

    # Mock order analyzer for quick analysis
    auto_order_manager.order_analyzer.analyze_order_document = Mock(
        return_value=Mock(order_date="2024-01-20")
    )

    # Mock database operations
    mock_doc = Mock()
    auto_order_manager.db = Mock()
    auto_order_manager.db.collection().document().update = Mock()

    # Mock _create_order_link to succeed
    auto_order_manager._create_order_link = Mock()

    # Execute
    result = auto_order_manager._process_single_case(case_data)

    # Verify
    assert result["download_success"] is True, "Download should succeed"
    assert result["analysis_success"] is False, "Analysis should fail"
    assert result["order_link"] == "http://example.com/order456.pdf"
    assert "analysis failed" in result["error"].lower()

    # Verify order link was created despite analysis failure
    auto_order_manager._create_order_link.assert_called_once()

    # Verify status was updated to order_analysis_failed
    auto_order_manager.db.collection().document().update.assert_called()
    update_call_args = auto_order_manager.db.collection().document().update.call_args
    if update_call_args:
        update_data = update_call_args[0][0]
        assert (
            update_data.get("order_status") == "order_analysis_failed"
        ), "Status should be order_analysis_failed"


def test_process_single_case_download_failure(auto_order_manager):
    """Test order download fails - should retry other sequences"""
    # Setup test data
    case_id = "test_case_789"
    case_ref = "WP/789/2024"
    case_data = {
        "id": case_id,
        "case_ref": case_ref,
        "case_type": "WP",
        "case_no": 789,
        "case_year": 2024,
        "board_date": "2024-01-25",
        "order_status": "not_linked",
    }

    # Mock failed download for all attempts
    download_result = {
        "success": False,
        "error": "PDF not found",
    }

    auto_order_manager._download_order_for_case = Mock(return_value=download_result)

    # Mock database for final status update
    mock_doc = Mock()
    auto_order_manager.db = Mock()
    auto_order_manager.db.collection().document().update = Mock()

    # Execute with limited retries for faster test
    with patch.dict("os.environ", {"ORDER_MAX_SEQUENCE_RETRIES": "3"}):
        result = auto_order_manager._process_single_case(case_data)

    # Verify
    assert result["download_success"] is False
    assert result["analysis_success"] is False
    assert "error" in result
    assert len(result["retry_attempts"]) > 0

    # Verify final status update to order_failed
    auto_order_manager.db.collection().document().update.assert_called()
    update_call_args = auto_order_manager.db.collection().document().update.call_args
    if update_call_args:
        update_data = update_call_args[0][0]
        assert (
            update_data.get("order_status") == "order_failed"
        ), "Status should be order_failed when download fails"


def test_process_single_case_date_mismatch_retries(auto_order_manager):
    """Test date mismatch causes retry to next sequence"""
    # Setup test data
    case_id = "test_case_999"
    case_ref = "WP/999/2024"
    case_data = {
        "id": case_id,
        "case_ref": case_ref,
        "case_type": "WP",
        "case_no": 999,
        "case_year": 2024,
        "board_date": "2024-02-01",
        "order_status": "not_linked",
    }

    # Mock download that succeeds
    download_result = {
        "success": True,
        "order_link": "http://example.com/order999.pdf",
        "pdf_content": b"PDF content",
        "filename": "order999.pdf",
    }

    # Mock date validation with mismatch (so it continues to next sequence)
    auto_order_manager._download_order_for_case = Mock(return_value=download_result)
    auto_order_manager._validate_order_date = Mock(
        return_value={
            "valid": False,
            "extracted_date": "2024-01-30",
            "expected_date": "2024-02-01",
            "reason": "Date mismatch",
        }
    )

    # Mock order analyzer
    auto_order_manager.order_analyzer.analyze_order_document = Mock(
        return_value=Mock(order_date="2024-01-30")
    )

    # Mock database
    mock_doc = Mock()
    auto_order_manager.db = Mock()
    auto_order_manager.db.collection().document().update = Mock()

    # Execute with limited retries
    with patch.dict("os.environ", {"ORDER_MAX_SEQUENCE_RETRIES": "3"}):
        result = auto_order_manager._process_single_case(case_data)

    # Verify it tried multiple sequences
    assert len(result["retry_attempts"]) > 1, "Should retry multiple sequences"
    assert any(
        "date_mismatch" in str(attempt.get("status", ""))
        for attempt in result["retry_attempts"]
    ), "Should have date mismatch attempts"


def test_process_single_case_analysis_exception_keeps_order(auto_order_manager):
    """Test analysis exception keeps the order link and marks as analysis_failed"""
    # Setup test data
    case_id = "test_case_exc"
    case_ref = "WP/111/2024"
    case_data = {
        "id": case_id,
        "case_ref": case_ref,
        "case_type": "WP",
        "case_no": 111,
        "case_year": 2024,
        "board_date": "2024-02-05",
        "order_status": "not_linked",
    }

    # Mock successful download
    download_result = {
        "success": True,
        "order_link": "http://example.com/order_exc.pdf",
        "pdf_content": b"PDF content",
        "filename": "order_exc.pdf",
    }

    # Mock date validation (valid)
    auto_order_manager._download_order_for_case = Mock(return_value=download_result)
    auto_order_manager._validate_order_date = Mock(
        return_value={
            "valid": True,
            "extracted_date": "2024-02-05",
            "expected_date": "2024-02-05",
        }
    )

    # Mock order analyzer for quick analysis
    auto_order_manager.order_analyzer.analyze_order_document = Mock(
        return_value=Mock(order_date="2024-02-05")
    )

    # Mock analysis that throws exception
    auto_order_manager._analyze_order_with_date_validation = Mock(
        side_effect=Exception("Analysis crashed")
    )

    # Mock database
    mock_doc = Mock()
    auto_order_manager.db = Mock()
    auto_order_manager.db.collection().document().update = Mock()

    # Mock _create_order_link
    auto_order_manager._create_order_link = Mock()

    # Execute
    result = auto_order_manager._process_single_case(case_data)

    # Verify
    assert result["download_success"] is True, "Download should succeed"
    assert result["analysis_success"] is False, "Analysis should fail"
    assert "exception" in result["error"].lower()

    # Verify order link was created
    auto_order_manager._create_order_link.assert_called_once()

    # Verify status was updated to order_analysis_failed
    auto_order_manager.db.collection().document().update.assert_called()
    update_call_args = auto_order_manager.db.collection().document().update.call_args
    if update_call_args:
        update_data = update_call_args[0][0]
        assert update_data.get("order_status") == "order_analysis_failed"


def test_download_order_for_case_prefers_structured_scraper(auto_order_manager):
    case_data = {
        "case_ref": "WP/123/2024",
        "board_date": "2024-01-15",
    }

    auto_order_manager.court_scraper.get_case_orders.return_value = {
        "status": "found",
        "court_orders": [
            {
                "listing_date": "15/01/2024",
                "download_url": "https://example.com/order-structured.pdf",
                "order_description": "Order/Judg-1",
            }
        ],
    }

    auto_order_manager._download_pdf_bombay_hc_simple = Mock(
        return_value={"success": False, "error": "should not be called"}
    )

    with patch("billingonaire_backend.AutoOrderManager.requests.get") as mock_get:
        response = Mock()
        response.status_code = 200
        response.headers = {"Content-Type": "application/pdf"}
        response.content = b"%PDF-1.4 test"
        mock_get.return_value = response

        result = auto_order_manager._download_order_for_case(
            case_data, sequence_number=1
        )

    assert result["success"] is True
    assert result["source"] == "firecrawl_structured"
    assert result["order_link"] == "https://example.com/order-structured.pdf"
    auto_order_manager._download_pdf_bombay_hc_simple.assert_not_called()


def test_download_order_for_case_falls_back_to_legacy_sequence(auto_order_manager):
    case_data = {
        "case_ref": "WP/124/2024",
        "board_date": "2024-01-16",
    }

    auto_order_manager.court_scraper.get_case_orders.return_value = {
        "status": "captcha_required",
        "court_orders": [],
    }

    auto_order_manager._download_pdf_bombay_hc_simple = Mock(
        return_value={
            "success": True,
            "download_url": "https://example.com/order-legacy.pdf",
            "pdf_content": b"%PDF-1.4 legacy",
        }
    )

    result = auto_order_manager._download_order_for_case(case_data, sequence_number=1)

    assert result["success"] is True
    assert result["source"] == "bombay_hc_api"
    assert result["order_link"] == "https://example.com/order-legacy.pdf"
    auto_order_manager._download_pdf_bombay_hc_simple.assert_called_once()

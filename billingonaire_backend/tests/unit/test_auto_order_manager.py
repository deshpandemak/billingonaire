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

    # No existing order link — force Path 3 (brute-force sequences)
    auto_order_manager._get_case_order_context = Mock(
        return_value={
            "order_status": "not_linked",
            "order_link": None,
            "latest_order": {},
            "case_detail": {},
        }
    )
    # Direct API returns nothing so Path 1 fails and test falls through to Path 3
    auto_order_manager.court_scraper.get_case_orders = Mock(return_value={})

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

    # Mock _create_order_link to succeed
    auto_order_manager._create_order_link = Mock()
    auto_order_manager._record_case_order_status = Mock()

    # No existing order link — force Path 3 (brute-force sequences)
    auto_order_manager._get_case_order_context = Mock(
        return_value={
            "order_status": "not_linked",
            "order_link": None,
            "latest_order": {},
            "case_detail": {},
        }
    )
    auto_order_manager.court_scraper.get_case_orders = Mock(return_value={})

    # Execute
    result = auto_order_manager._process_single_case(case_data)

    # Verify
    assert result["download_success"] is True, "Download should succeed"
    assert result["analysis_success"] is False, "Analysis should fail"
    assert result["order_link"] == "http://example.com/order456.pdf"
    assert "analysis failed" in result["error"].lower()

    # Verify order link was created despite analysis failure
    auto_order_manager._create_order_link.assert_called_once()

    # Verify status was updated to order_analysis_failed in normalized store
    auto_order_manager._record_case_order_status.assert_called_with(
        case_ref,
        "order_analysis_failed",
        result["error"],
    )


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

    # Mock normalized status persistence
    auto_order_manager._record_case_order_status = Mock()

    # No existing order link — force Path 3 (brute-force sequences)
    auto_order_manager._get_case_order_context = Mock(
        return_value={
            "order_status": "not_linked",
            "order_link": None,
            "latest_order": {},
            "case_detail": {},
        }
    )
    auto_order_manager.court_scraper.get_case_orders = Mock(return_value={})

    # Execute with limited retries for faster test
    with patch.dict("os.environ", {"ORDER_MAX_SEQUENCE_RETRIES": "3"}):
        result = auto_order_manager._process_single_case(case_data)

    # Verify
    assert result["download_success"] is False
    assert result["analysis_success"] is False
    assert "error" in result
    assert len(result["retry_attempts"]) > 0

    # Verify final status update to order_failed
    auto_order_manager._record_case_order_status.assert_called_with(
        case_ref,
        "order_failed",
        result["error"],
    )


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

    # No existing order link — force Path 3 (brute-force sequences)
    auto_order_manager._get_case_order_context = Mock(
        return_value={
            "order_status": "not_linked",
            "order_link": None,
            "latest_order": {},
            "case_detail": {},
        }
    )
    auto_order_manager.court_scraper.get_case_orders = Mock(return_value={})

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

    # Mock _create_order_link
    auto_order_manager._create_order_link = Mock()
    auto_order_manager._record_case_order_status = Mock()

    # No existing order link — force Path 3 (brute-force sequences)
    auto_order_manager._get_case_order_context = Mock(
        return_value={
            "order_status": "not_linked",
            "order_link": None,
            "latest_order": {},
            "case_detail": {},
        }
    )
    auto_order_manager.court_scraper.get_case_orders = Mock(return_value={})

    # Execute
    result = auto_order_manager._process_single_case(case_data)

    # Verify
    assert result["download_success"] is True, "Download should succeed"
    assert result["analysis_success"] is False, "Analysis should fail"
    assert "exception" in result["error"].lower()

    # Verify order link was created
    auto_order_manager._create_order_link.assert_called_once()

    # Verify status was updated to order_analysis_failed
    auto_order_manager._record_case_order_status.assert_called_with(
        case_ref,
        "order_analysis_failed",
        result["error"],
    )


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
    assert result["source"] == "direct_api_structured"
    assert result["order_link"] == "https://example.com/order-structured.pdf"
    auto_order_manager._download_pdf_bombay_hc_simple.assert_not_called()


def test_download_order_for_case_uses_playwright_structured_source(auto_order_manager):
    case_data = {
        "case_ref": "WP/125/2024",
        "board_date": "2024-01-15",
    }

    auto_order_manager.court_scraper.get_case_orders.return_value = {
        "status": "found",
        "source": "playwright",
        "court_orders": [
            {
                "listing_date": "15/01/2024",
                "download_url": "https://example.com/order-playwright.pdf",
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
    assert result["source"] == "playwright_structured"
    assert result["order_link"] == "https://example.com/order-playwright.pdf"
    auto_order_manager._download_pdf_bombay_hc_simple.assert_not_called()


def test_download_order_for_case_falls_back_to_legacy_sequence(auto_order_manager):
    case_data = {
        "case_ref": "WP/124/2024",
        "board_date": "2024-01-16",
    }

    auto_order_manager.court_scraper.get_case_orders.return_value = {
        "status": "not_found",
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


def test_download_order_for_case_uses_cached_board_date_link(auto_order_manager):
    case_data = {
        "case_ref": "WP/200/2024",
        "board_date": "2024-01-15",
        "case_detail": {
            "petitioner": "ABC Ltd",
            "respondent": "State",
            "orders": [
                {
                    "board_date": "2024-01-15",
                    "order_link": "https://example.com/order-cached.pdf",
                }
            ],
        },
    }

    auto_order_manager.court_scraper.get_case_orders = Mock()
    auto_order_manager._download_pdf_bombay_hc_simple = Mock()

    with patch("billingonaire_backend.AutoOrderManager.requests.get") as mock_get:
        response = Mock()
        response.status_code = 200
        response.headers = {"Content-Type": "application/pdf"}
        response.content = b"%PDF-1.4 cached"
        mock_get.return_value = response

        result = auto_order_manager._download_order_for_case(
            case_data, sequence_number=1
        )

    assert result["success"] is True
    assert result["source"] == "case_store_cached"
    assert result["order_link"] == "https://example.com/order-cached.pdf"
    auto_order_manager.court_scraper.get_case_orders.assert_not_called()
    auto_order_manager._download_pdf_bombay_hc_simple.assert_not_called()


def test_download_order_for_case_cached_link_failure_uses_scraper(auto_order_manager):
    case_data = {
        "case_ref": "WP/201/2024",
        "board_date": "2024-01-16",
        "case_detail": {
            "petitioner": "ABC Ltd",
            "respondent": "State",
            "orders": [
                {
                    "board_date": "2024-01-16",
                    "order_link": "https://example.com/order-cached-bad.pdf",
                }
            ],
        },
    }

    auto_order_manager._download_order_via_scraper = Mock(
        return_value={
            "success": True,
            "order_link": "https://example.com/order-structured.pdf",
            "pdf_content": b"%PDF-1.4 structured",
            "filename": "dummy.pdf",
            "source": "direct_api_structured",
        }
    )

    auto_order_manager._download_pdf_bombay_hc_simple = Mock()

    with patch("billingonaire_backend.AutoOrderManager.requests.get") as mock_get:
        response = Mock()
        response.status_code = 404
        response.headers = {"Content-Type": "text/html"}
        response.content = b"not found"
        mock_get.return_value = response

        result = auto_order_manager._download_order_for_case(
            case_data, sequence_number=1
        )

    assert result["success"] is True
    assert result["source"] == "direct_api_structured"
    auto_order_manager._download_order_via_scraper.assert_called_once()
    auto_order_manager._download_pdf_bombay_hc_simple.assert_not_called()


# ---------------------------------------------------------------------------
# Tests for new API-driven order processing (order downloads & management)
# ---------------------------------------------------------------------------


def test_is_order_already_analysed_true(auto_order_manager):
    """Return True when an analysed order for the same date already exists."""
    auto_order_manager.case_store.get_case_details = Mock(
        return_value={
            "orders": [
                {"order_status": "analysed", "order_date": "2025-03-01"},
                {"order_status": "linked", "order_date": "2025-03-02"},
            ]
        }
    )
    assert (
        auto_order_manager._is_order_already_analysed("WP/123/2025", "2025-03-01")
        is True
    )


def test_is_order_already_analysed_false_different_date(auto_order_manager):
    """Return False when no analysed order exists for that date."""
    auto_order_manager.case_store.get_case_details = Mock(
        return_value={
            "orders": [
                {"order_status": "analysed", "order_date": "2025-03-02"},
            ]
        }
    )
    assert (
        auto_order_manager._is_order_already_analysed("WP/123/2025", "2025-03-01")
        is False
    )


def test_is_order_already_analysed_no_orders(auto_order_manager):
    """Return False when case has no orders at all."""
    auto_order_manager.case_store.get_case_details = Mock(return_value={"orders": []})
    assert (
        auto_order_manager._is_order_already_analysed("WP/123/2025", "2025-03-01")
        is False
    )


def test_upload_order_to_gcs_disabled_when_no_bucket(auto_order_manager):
    """Return None when ORDER_PDF_BUCKET is not set."""
    auto_order_manager._gcs_bucket_name = ""
    result = auto_order_manager._upload_order_to_gcs(
        b"%PDF-1.4", "WP/123/2025", "2025-03-01"
    )
    assert result is None


def test_upload_order_to_gcs_success(auto_order_manager):
    """Upload PDF and return a public HTTPS URL when GCS is configured."""
    auto_order_manager._gcs_bucket_name = "test-bucket"

    mock_blob = Mock()
    mock_bucket = Mock()
    mock_bucket.blob.return_value = mock_blob
    mock_client = Mock()
    mock_client.bucket.return_value = mock_bucket

    with patch("billingonaire_backend.AutoOrderManager.gcs_storage") as mock_gcs:
        mock_gcs.Client.return_value = mock_client
        result = auto_order_manager._upload_order_to_gcs(
            b"%PDF-1.4", "WP/123/2025", "2025-03-01"
        )

    assert result == (
        "https://storage.googleapis.com/test-bucket"
        "/court-orders/WP-123-2025/2025-03-01.pdf"
    )
    mock_blob.upload_from_string.assert_called_once_with(
        b"%PDF-1.4", content_type="application/pdf"
    )


def test_upload_order_to_gcs_failure_returns_none(auto_order_manager):
    """Return None (not raise) when GCS upload fails."""
    auto_order_manager._gcs_bucket_name = "test-bucket"

    with patch("billingonaire_backend.AutoOrderManager.gcs_storage") as mock_gcs:
        mock_gcs.Client.side_effect = Exception("connection refused")
        result = auto_order_manager._upload_order_to_gcs(
            b"%PDF-1.4", "WP/123/2025", "2025-03-01"
        )

    assert result is None


def test_analyze_order_with_api_metadata_success(auto_order_manager):
    """Persist order using API-provided date and party names."""
    auto_order_manager.case_store.transition_lifecycle = Mock(
        return_value={"applied": True}
    )
    auto_order_manager.case_store.append_case_order = Mock()
    auto_order_manager.order_analyzer.analyze_order_document = Mock(
        return_value=Mock(
            order_category="interim",
            category_confidence=0.9,
            analysis_metadata={},
            cases=[],
        )
    )

    # Use an HTTPS URL (as returned by _upload_order_to_gcs after the fix)
    https_url = (
        "https://storage.googleapis.com/test-bucket"
        "/court-orders/WP-123-2025/2025-03-01.pdf"
    )
    result = auto_order_manager._analyze_order_with_api_metadata(
        case_id="board-abc",
        case_ref="WP/123/2025",
        pdf_content=b"%PDF-1.4",
        api_order_date="2025-03-01",
        api_petitioner="Petitioner Co",
        api_respondent="State of Maharashtra",
        order_link=https_url,
    )

    assert result["success"] is True
    data = result["data"]
    assert data["order_date"] == "2025-03-01"
    assert data["order_petitioner"] == "Petitioner Co"
    assert data["order_respondent"] == "State of Maharashtra"
    assert data["date_source"] == "api"
    assert data["order_category"] == "interim"
    # Party names must NOT come from PDF - verify append_case_order received API values
    call_kwargs = auto_order_manager.case_store.append_case_order.call_args[0][1]
    assert call_kwargs["petitioner"] == "Petitioner Co"
    assert call_kwargs["respondent"] == "State of Maharashtra"
    assert call_kwargs["order_date"] == "2025-03-01"


def test_process_all_orders_from_api_success(auto_order_manager):
    """Download and analyse all orders returned by the direct API that have board entries."""
    auto_order_manager.court_scraper.get_case_orders = Mock(
        return_value={
            "status": "found",
            "petitioner": "ABC Corp",
            "respondent": "Govt of MH",
            "case_orders": [
                {"date": "2025-02-01", "download_link": "https://court.example/o1.pdf"},
                {"date": "2025-03-01", "download_link": "https://court.example/o2.pdf"},
            ],
        }
    )
    # No orders already analysed; board entries exist for both dates
    auto_order_manager._is_order_already_analysed = Mock(return_value=False)
    auto_order_manager._board_entry_exists_for_date = Mock(return_value=True)
    auto_order_manager._upload_order_to_gcs = Mock(return_value=None)
    auto_order_manager._analyze_order_with_api_metadata = Mock(
        return_value={"success": True, "data": {"order_category": "interim"}}
    )
    # Mock the public update_case_party_names method
    auto_order_manager.case_store.update_case_party_names = Mock()

    with patch("billingonaire_backend.AutoOrderManager.requests.get") as mock_get:
        mock_resp = Mock()
        mock_resp.status_code = 200
        mock_resp.headers = {"Content-Type": "application/pdf"}
        mock_resp.content = b"%PDF-1.4"
        mock_get.return_value = mock_resp

        result = auto_order_manager._process_all_orders_from_api(
            case_ref="WP/123/2025",
            case_id="board-abc",
            board_date="2025-03-01",
        )

    assert result["success"] is True
    assert result["orders_processed"] == 2
    assert result["orders_skipped"] == 0
    # Party names written via the encapsulated public method, NOT via append_case_order
    auto_order_manager.case_store.update_case_party_names.assert_called_once_with(
        "WP/123/2025", "ABC Corp", "Govt of MH"
    )
    assert auto_order_manager._analyze_order_with_api_metadata.call_count == 2


def test_process_all_orders_from_api_skips_already_analysed(auto_order_manager):
    """Already-analysed orders are skipped without re-downloading."""
    auto_order_manager.court_scraper.get_case_orders = Mock(
        return_value={
            "status": "found",
            "petitioner": "P",
            "respondent": "R",
            "case_orders": [
                {"date": "2025-03-01", "download_link": "https://court.example/o1.pdf"},
            ],
        }
    )
    auto_order_manager._is_order_already_analysed = Mock(return_value=True)
    auto_order_manager._board_entry_exists_for_date = Mock(return_value=True)
    auto_order_manager._analyze_order_with_api_metadata = Mock()
    # Mock the public update_case_party_names method
    auto_order_manager.case_store.update_case_party_names = Mock()
    # Provide a latest_order_link so the skipped-only result has an order_link
    auto_order_manager.case_store.get_case_details = Mock(
        return_value={
            "latest_order_link": "https://storage.googleapis.com/b/court-orders/WP-123-2025/2025-03-01.pdf"
        }
    )

    result = auto_order_manager._process_all_orders_from_api(
        case_ref="WP/123/2025",
        case_id="board-abc",
    )

    assert result["success"] is True
    assert result["orders_skipped"] == 1
    assert result["orders_processed"] == 0
    # order_link surfaced from case-details when all orders were skipped
    assert result["order_link"] is not None
    auto_order_manager._analyze_order_with_api_metadata.assert_not_called()


def test_process_all_orders_from_api_no_orders_returns_failure(auto_order_manager):
    """Return failure when API returns an empty order list."""
    auto_order_manager.court_scraper.get_case_orders = Mock(
        return_value={
            "status": "not_found",
            "message": "No orders found",
            "case_orders": [],
        }
    )

    result = auto_order_manager._process_all_orders_from_api(
        case_ref="WP/999/2025",
        case_id="board-xyz",
    )

    assert result["success"] is False
    assert result["orders_processed"] == 0


def test_process_single_case_uses_direct_api_first(auto_order_manager):
    """_process_single_case returns early when the direct-API path succeeds."""
    case_data = {
        "id": "board-abc",
        "case_ref": "WP/123/2025",
        "case_type": "WP",
        "case_no": 123,
        "case_year": 2025,
        "board_date": "2025-03-01",
    }

    https_url = (
        "https://storage.googleapis.com/bucket"
        "/court-orders/WP-123-2025/2025-03-01.pdf"
    )
    auto_order_manager._process_all_orders_from_api = Mock(
        return_value={
            "success": True,
            "orders_processed": 2,
            "orders_skipped": 0,
            "order_link": https_url,
        }
    )
    auto_order_manager._download_order_for_case = Mock(
        return_value={"success": False, "error": "should not be called"}
    )

    result = auto_order_manager._process_single_case(case_data)

    assert result["download_success"] is True
    assert result["analysis_success"] is True
    assert result["order_link"] == https_url
    # Sequence-number fallback must NOT be invoked
    auto_order_manager._download_order_for_case.assert_not_called()


def test_process_all_orders_from_api_uses_gcs_url_when_available(auto_order_manager):
    """When GCS upload succeeds, the HTTPS GCS URL is persisted instead of the expiring API link."""
    auto_order_manager.court_scraper.get_case_orders = Mock(
        return_value={
            "status": "found",
            "petitioner": "P",
            "respondent": "R",
            "case_orders": [
                {
                    "date": "2025-03-01",
                    "download_link": "https://court.example/o1.pdf?token=abc",
                },
            ],
        }
    )
    auto_order_manager._is_order_already_analysed = Mock(return_value=False)
    auto_order_manager._board_entry_exists_for_date = Mock(return_value=True)
    https_url = (
        "https://storage.googleapis.com/test-bucket"
        "/court-orders/WP-123-2025/2025-03-01.pdf"
    )
    auto_order_manager._upload_order_to_gcs = Mock(return_value=https_url)
    capture = {}
    auto_order_manager._analyze_order_with_api_metadata = Mock(
        side_effect=lambda **kw: capture.update(kw) or {"success": True, "data": {}}
    )
    # Mock the public update_case_party_names method
    auto_order_manager.case_store.update_case_party_names = Mock()

    with patch("billingonaire_backend.AutoOrderManager.requests.get") as mock_get:
        mock_resp = Mock()
        mock_resp.status_code = 200
        mock_resp.headers = {"Content-Type": "application/pdf"}
        mock_resp.content = b"%PDF-1.4"
        mock_get.return_value = mock_resp

        result = auto_order_manager._process_all_orders_from_api(
            case_ref="WP/123/2025",
            case_id="board-abc",
        )

    assert result["success"] is True
    # order_link must be the HTTPS GCS URL, not the expiring API link or a gs:// URI
    assert result["order_link"] == https_url
    assert result["order_link"].startswith("https://")
    # _analyze_order_with_api_metadata must receive the HTTPS GCS URL
    assert capture.get("order_link") == https_url


def test_normalise_order_date_iso_format(auto_order_manager):
    """ISO dates are returned unchanged."""
    assert auto_order_manager._normalise_order_date("2025-03-01") == "2025-03-01"


def test_normalise_order_date_ddmmyyyy(auto_order_manager):
    """DD/MM/YYYY format is converted to YYYY-MM-DD."""
    assert auto_order_manager._normalise_order_date("09/04/2025") == "2025-04-09"


def test_normalise_order_date_none(auto_order_manager):
    """None input returns None."""
    assert auto_order_manager._normalise_order_date(None) is None


def test_normalise_order_date_unparseable(auto_order_manager):
    """Unparseable value returns None."""
    assert auto_order_manager._normalise_order_date("not-a-date") is None


def test_is_order_already_analysed_normalises_date_formats(auto_order_manager):
    """An API date in DD/MM/YYYY matches an ISO-stored analysed order."""
    auto_order_manager.case_store.get_case_details = Mock(
        return_value={
            "orders": [
                # Stored as ISO in Firestore
                {"order_status": "analysed", "order_date": "2025-04-09"},
            ]
        }
    )
    # API emits DD/MM/YYYY — should still match
    assert (
        auto_order_manager._is_order_already_analysed("WP/123/2025", "09/04/2025")
        is True
    )


def test_process_all_orders_from_api_normalises_ddmmyyyy_dates(auto_order_manager):
    """Dates in DD/MM/YYYY from the API are normalised to YYYY-MM-DD before use."""
    auto_order_manager.court_scraper.get_case_orders = Mock(
        return_value={
            "status": "found",
            "petitioner": "P",
            "respondent": "R",
            "case_orders": [
                {
                    "date": "09/04/2025",  # DD/MM/YYYY from court scraper
                    "download_link": "https://court.example/o1.pdf",
                }
            ],
        }
    )
    auto_order_manager._is_order_already_analysed = Mock(return_value=False)
    auto_order_manager._board_entry_exists_for_date = Mock(return_value=True)
    auto_order_manager._upload_order_to_gcs = Mock(return_value=None)
    captured_args: dict = {}
    auto_order_manager._analyze_order_with_api_metadata = Mock(
        side_effect=lambda **kw: captured_args.update(kw)
        or {"success": True, "data": {}}
    )
    auto_order_manager.case_store.update_case_party_names = Mock()

    with patch("billingonaire_backend.AutoOrderManager.requests.get") as mock_get:
        mock_resp = Mock()
        mock_resp.status_code = 200
        mock_resp.headers = {"Content-Type": "application/pdf"}
        mock_resp.content = b"%PDF-1.4"
        mock_get.return_value = mock_resp

        result = auto_order_manager._process_all_orders_from_api(
            case_ref="WP/123/2025",
            case_id="board-abc",
        )

    assert result["success"] is True
    # The normalised ISO date must be passed to the analyser and used for GCS naming
    assert captured_args.get("api_order_date") == "2025-04-09"
    # Skip check must have been called with the normalised date
    auto_order_manager._is_order_already_analysed.assert_called_with(
        "WP/123/2025", "2025-04-09"
    )


def test_process_all_orders_from_api_skips_orders_without_board_entry(
    auto_order_manager,
):
    """Orders for which no daily-boards entry exists are silently skipped.

    Guards against the court API returning all historical orders and the wrong
    one (e.g. July 2025 when the board date is May 2026) being linked because
    no board entry exists for that old date.
    """
    auto_order_manager.court_scraper.get_case_orders = Mock(
        return_value={
            "status": "found",
            "petitioner": "P",
            "respondent": "R",
            "case_orders": [
                # Old order — no board entry for July 2025
                {
                    "date": "2025-07-10",
                    "download_link": "https://court.example/old.pdf",
                },
                # Current order — board entry exists for May 2026
                {
                    "date": "2026-05-15",
                    "download_link": "https://court.example/new.pdf",
                },
            ],
        }
    )
    auto_order_manager._is_order_already_analysed = Mock(return_value=False)
    # Only the May 2026 date has a board entry
    auto_order_manager._board_entry_exists_for_date = Mock(
        side_effect=lambda cr, d: d == "2026-05-15"
    )
    auto_order_manager._upload_order_to_gcs = Mock(return_value=None)
    captured_dates: list = []
    auto_order_manager._analyze_order_with_api_metadata = Mock(
        side_effect=lambda **kw: captured_dates.append(kw.get("api_order_date"))
        or {"success": True, "data": {}}
    )
    auto_order_manager.case_store.update_case_party_names = Mock()

    with patch("billingonaire_backend.AutoOrderManager.requests.get") as mock_get:
        mock_resp = Mock()
        mock_resp.status_code = 200
        mock_resp.headers = {"Content-Type": "application/pdf"}
        mock_resp.content = b"%PDF-1.4"
        mock_get.return_value = mock_resp

        result = auto_order_manager._process_all_orders_from_api(
            case_ref="WP/9146/2025",
            case_id="board-xyz",
            board_date="2026-05-15",
        )

    assert result["success"] is True
    assert result["orders_processed"] == 1
    # Only the May 2026 order (which has a board entry) must be analysed
    assert captured_dates == ["2026-05-15"]
    assert "2025-07-10" not in captured_dates


def test_process_all_orders_from_api_processes_multiple_dates_with_board_entries(
    auto_order_manager,
):
    """Orders for multiple distinct hearing dates are all processed when board entries exist.

    A case may appear on the board more than once (different hearings). All
    such appearances should be downloaded and linked independently.
    """
    auto_order_manager.court_scraper.get_case_orders = Mock(
        return_value={
            "status": "found",
            "petitioner": "P",
            "respondent": "R",
            "case_orders": [
                # First hearing — board entry exists
                {"date": "2026-03-10", "download_link": "https://court.example/o1.pdf"},
                # Second hearing — board entry exists
                {"date": "2026-05-15", "download_link": "https://court.example/o2.pdf"},
                # Old order with no board entry — must be skipped
                {
                    "date": "2025-01-20",
                    "download_link": "https://court.example/old.pdf",
                },
            ],
        }
    )
    auto_order_manager._is_order_already_analysed = Mock(return_value=False)
    # Board entries exist for March and May 2026 but not January 2025
    auto_order_manager._board_entry_exists_for_date = Mock(
        side_effect=lambda cr, d: d in ("2026-03-10", "2026-05-15")
    )
    auto_order_manager._upload_order_to_gcs = Mock(return_value=None)
    captured_dates: list = []
    auto_order_manager._analyze_order_with_api_metadata = Mock(
        side_effect=lambda **kw: captured_dates.append(kw.get("api_order_date"))
        or {"success": True, "data": {}}
    )
    auto_order_manager.case_store.update_case_party_names = Mock()

    with patch("billingonaire_backend.AutoOrderManager.requests.get") as mock_get:
        mock_resp = Mock()
        mock_resp.status_code = 200
        mock_resp.headers = {"Content-Type": "application/pdf"}
        mock_resp.content = b"%PDF-1.4"
        mock_get.return_value = mock_resp

        result = auto_order_manager._process_all_orders_from_api(
            case_ref="WP/100/2025",
            case_id="board-abc",
            board_date="2026-05-15",
        )

    assert result["success"] is True
    assert result["orders_processed"] == 2
    assert "2026-03-10" in captured_dates
    assert "2026-05-15" in captured_dates
    assert "2025-01-20" not in captured_dates


def test_process_all_orders_from_api_no_board_date_uses_board_entry_check(
    auto_order_manager,
):
    """When no board_date is supplied the board-entry check still governs which orders are processed."""
    auto_order_manager.court_scraper.get_case_orders = Mock(
        return_value={
            "status": "found",
            "petitioner": "P",
            "respondent": "R",
            "case_orders": [
                {"date": "2024-01-01", "download_link": "https://court.example/o1.pdf"},
                {"date": "2025-07-10", "download_link": "https://court.example/o2.pdf"},
            ],
        }
    )
    auto_order_manager._is_order_already_analysed = Mock(return_value=False)
    # Both dates have board entries
    auto_order_manager._board_entry_exists_for_date = Mock(return_value=True)
    auto_order_manager._upload_order_to_gcs = Mock(return_value=None)
    auto_order_manager._analyze_order_with_api_metadata = Mock(
        return_value={"success": True, "data": {}}
    )
    auto_order_manager.case_store.update_case_party_names = Mock()

    with patch("billingonaire_backend.AutoOrderManager.requests.get") as mock_get:
        mock_resp = Mock()
        mock_resp.status_code = 200
        mock_resp.headers = {"Content-Type": "application/pdf"}
        mock_resp.content = b"%PDF-1.4"
        mock_get.return_value = mock_resp

        result = auto_order_manager._process_all_orders_from_api(
            case_ref="WP/200/2025",
            case_id="board-no-date",
            board_date=None,
        )

    assert result["success"] is True
    assert result["orders_processed"] == 2


def test_board_entry_exists_for_date_queries_with_datetime_not_string(
    auto_order_manager,
):
    """board_date in daily-boards is a Firestore Timestamp (Python datetime), not a string.

    Board.py saves: row["board_date"] = datetime.strptime(row["board_date"], "%Y-%m-%d")
    before calling doc_ref.set(row), so the field is a datetime in Firestore.
    The WHERE clause must use a datetime object — a string comparison always returns
    zero results, causing every order to be silently skipped.
    """
    mock_query = Mock()
    mock_query.where.return_value = mock_query
    mock_query.limit.return_value = mock_query
    # Simulate one matching document
    mock_query.stream.return_value = iter([Mock()])
    auto_order_manager.db.collection = Mock(return_value=mock_query)

    result = auto_order_manager._board_entry_exists_for_date("WP/9146/2025", "2026-05-15")

    assert result is True
    # The WHERE clause on board_date must use a datetime object, not the raw string
    where_calls = mock_query.where.call_args_list
    board_date_calls = [c for c in where_calls if c[0][0] == "board_date"]
    assert board_date_calls, "No WHERE clause on board_date found"
    for call in board_date_calls:
        _, value = call[0][1], call[0][2]
        assert isinstance(value, datetime), (
            f"board_date WHERE value must be datetime, got {type(value).__name__!r}. "
            "String comparison against a Firestore Timestamp always returns 0 results."
        )


def test_board_entry_exists_for_date_returns_false_when_no_match(auto_order_manager):
    """Returns False when no daily-boards record exists for the given case and date."""
    mock_query = Mock()
    mock_query.where.return_value = mock_query
    mock_query.limit.return_value = mock_query
    mock_query.stream.return_value = iter([])  # empty result
    auto_order_manager.db.collection = Mock(return_value=mock_query)

    result = auto_order_manager._board_entry_exists_for_date("WP/999/2025", "2025-07-10")

    assert result is False


def test_process_single_case_analysis_success_when_all_orders_skipped(
    auto_order_manager,
):
    """analysis_success is True even when all orders were already analysed (no-op run)."""
    case_data = {
        "id": "board-abc",
        "case_ref": "WP/123/2025",
        "case_type": "WP",
        "case_no": 123,
        "case_year": 2025,
        "board_date": "2025-03-01",
    }

    auto_order_manager._process_all_orders_from_api = Mock(
        return_value={
            "success": True,
            "orders_processed": 0,
            "orders_skipped": 1,
            "order_link": "https://storage.googleapis.com/b/o.pdf",
        }
    )

    result = auto_order_manager._process_single_case(case_data)

    assert result["download_success"] is True
    # Must be True even though orders_processed == 0 because success is True
    assert result["analysis_success"] is True


# ---------------------------------------------------------------------------
# Tests for IA(ST) case type mapping and parsing (Issue: IA code not mapped)
# ---------------------------------------------------------------------------


def test_casetype_dict_contains_ia_st(auto_order_manager):
    """IA(ST) must map to the same code as plain IA for court downloads."""
    assert "IA(ST)" in auto_order_manager.casetype_dict
    assert (
        auto_order_manager.casetype_dict["IA(ST)"]
        == auto_order_manager.casetype_dict["IA"]
    )


def test_parse_case_reference_ia_st(auto_order_manager):
    """_parse_case_reference should correctly parse IA(ST)/123/2025."""
    result = auto_order_manager._parse_case_reference("IA(ST)/123/2025")
    assert result is not None
    case_type, case_no, case_year = result
    assert case_type == "IA(ST)"
    assert case_no == 123
    assert case_year == 2025


def test_parse_case_reference_plain_ia(auto_order_manager):
    """_parse_case_reference should still parse plain IA/456/2024."""
    result = auto_order_manager._parse_case_reference("IA/456/2024")
    assert result is not None
    case_type, case_no, case_year = result
    assert case_type == "IA"
    assert case_no == 456
    assert case_year == 2024


def test_download_order_for_case_ia_st_not_unsupported(auto_order_manager):
    """IA(ST) cases should not be rejected as unsupported case type."""
    case_data = {
        "id": "board-ia-st",
        "case_ref": "IA(ST)/100/2025",
        "case_type": "IA(ST)",
        "case_no": 100,
        "case_year": 2025,
        "board_date": "2025-01-01",
    }
    # Structured scraper returns failure so we fall through to legacy path
    auto_order_manager._download_order_via_structured_scraper = Mock(
        return_value={"success": False, "error": "not found"}
    )
    # Make the legacy PDF download succeed
    auto_order_manager._download_pdf_bombay_hc_simple = Mock(
        return_value={"success": True, "download_url": "https://example.com/order.pdf"}
    )
    auto_order_manager._upload_order_to_gcs = Mock(return_value=None)

    result = auto_order_manager._download_order_for_case(case_data, sequence_number=1)

    # Must NOT return the "Case type not supported" error
    assert (
        result.get("error") != "Case type IA(ST) not supported for automated download"
    )
    # Legacy download path should have been attempted
    auto_order_manager._download_pdf_bombay_hc_simple.assert_called()

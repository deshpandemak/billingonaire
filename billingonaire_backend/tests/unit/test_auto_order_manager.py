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


# ---------------------------------------------------------------------------
# Tests for API-driven order processing (order downloads & management)
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
    """Only the order matching board_date is downloaded and analysed; others are skipped."""
    auto_order_manager.court_scraper.get_case_orders = Mock(
        return_value={
            "status": "found",
            "petitioner": "ABC Corp",
            "respondent": "Govt of MH",
            "case_orders": [
                # Old historical order — must be skipped (doesn't match board_date)
                {"date": "2025-02-01", "download_link": "https://court.example/o1.pdf"},
                # Matches board_date — must be processed
                {"date": "2025-03-01", "download_link": "https://court.example/o2.pdf"},
            ],
        }
    )
    auto_order_manager._is_order_already_analysed = Mock(return_value=False)
    auto_order_manager._upload_order_to_gcs = Mock(return_value=None)
    auto_order_manager._analyze_order_with_api_metadata = Mock(
        return_value={"success": True, "data": {"order_category": "interim"}}
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
            board_date="2025-03-01",
        )

    assert result["success"] is True
    # Only the order matching board_date is processed; the Feb order is skipped
    assert result["orders_processed"] == 1
    assert result["orders_skipped"] == 0
    auto_order_manager.case_store.update_case_party_names.assert_called_once_with(
        "WP/123/2025", "ABC Corp", "Govt of MH"
    )
    assert auto_order_manager._analyze_order_with_api_metadata.call_count == 1


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


def test_process_single_case_normalises_firestore_datetime_board_date(
    auto_order_manager,
):
    """When board_date is a Firestore Timestamp (datetime object), _process_single_case
    must pass a clean 'YYYY-MM-DD' string to _process_all_orders_from_api — NOT
    the str() representation '2026-05-15 00:00:00' which would break date comparison."""
    dt_board_date = datetime(2026, 5, 15, 0, 0, 0)
    case_data = {
        "id": "board-dt",
        "case_ref": "WP/9146/2025",
        "case_type": "WP",
        "case_no": 9146,
        "case_year": 2025,
        "board_date": dt_board_date,  # datetime object as returned by Firestore
    }

    captured_args = {}
    auto_order_manager._process_all_orders_from_api = Mock(
        side_effect=lambda **kw: captured_args.update(kw)
        or {
            "success": True,
            "orders_processed": 1,
            "orders_skipped": 0,
            "order_link": "https://storage.googleapis.com/b/court-orders/WP-9146-2025/2026-05-15.pdf",
        }
    )
    auto_order_manager._download_order_for_case = Mock(
        return_value={"success": False, "error": "should not be called"}
    )

    auto_order_manager._process_single_case(case_data)

    # board_date must be the clean ISO string "2026-05-15", NOT "2026-05-15 00:00:00"
    assert captured_args.get("board_date") == "2026-05-15", (
        f"Expected board_date='2026-05-15' but got {captured_args.get('board_date')!r} — "
        "str(datetime) produces a space-separated string that breaks date comparison"
    )


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


def test_normalise_order_date_space_separated_datetime(auto_order_manager):
    """str(datetime_object) produces '2026-05-15 00:00:00' — must strip time part."""
    assert (
        auto_order_manager._normalise_order_date("2026-05-15 00:00:00") == "2026-05-15"
    )


def test_normalise_order_date_t_separated_datetime(auto_order_manager):
    """ISO datetime with T separator is stripped to date."""
    assert (
        auto_order_manager._normalise_order_date("2026-05-15T14:30:00") == "2026-05-15"
    )


def test_parse_board_date_handles_datetime_object():
    """_parse_board_date extracts .date() from a Python datetime object (Firestore Timestamp)."""
    from datetime import date

    dt = datetime(2026, 5, 15, 0, 0, 0)
    result = AutoOrderManager._parse_board_date(dt)
    assert result == date(2026, 5, 15)


def test_parse_board_date_handles_space_separated_string():
    """_parse_board_date handles str(datetime) output '2026-05-15 00:00:00'."""
    from datetime import date

    result = AutoOrderManager._parse_board_date("2026-05-15 00:00:00")
    assert result == date(2026, 5, 15)


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


def test_process_all_orders_from_api_skips_order_not_matching_board_date(
    auto_order_manager,
):
    """Only the order whose date matches board_date is processed; all others are skipped.

    The court API returns ALL historical orders for a case. Without this filter,
    an old order (e.g. July 2025 for a May 2026 board trigger) would be linked
    to the current hearing, corrupting the case record.
    """
    auto_order_manager.court_scraper.get_case_orders = Mock(
        return_value={
            "status": "found",
            "petitioner": "P",
            "respondent": "R",
            "case_orders": [
                # Old order — must be skipped (doesn't match board_date)
                {
                    "date": "2025-07-10",
                    "download_link": "https://court.example/old.pdf",
                },
                # Matches board_date — must be processed
                {
                    "date": "2026-05-15",
                    "download_link": "https://court.example/new.pdf",
                },
            ],
        }
    )
    auto_order_manager._is_order_already_analysed = Mock(return_value=False)
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
    assert captured_dates == ["2026-05-15"]
    assert "2025-07-10" not in captured_dates


def test_process_all_orders_from_api_different_hearing_date_triggers_own_download(
    auto_order_manager,
):
    """Each board entry triggers a separate download for its specific date.

    When this run is for board_date 2026-03-10, only that date's order is processed.
    The May 2026 order will be handled when that board entry is processed separately.
    """
    auto_order_manager.court_scraper.get_case_orders = Mock(
        return_value={
            "status": "found",
            "petitioner": "P",
            "respondent": "R",
            "case_orders": [
                # Matches board_date
                {"date": "2026-03-10", "download_link": "https://court.example/o1.pdf"},
                # Different hearing — skipped here, handled by its own board entry
                {"date": "2026-05-15", "download_link": "https://court.example/o2.pdf"},
                # Old order — skipped
                {
                    "date": "2025-01-20",
                    "download_link": "https://court.example/old.pdf",
                },
            ],
        }
    )
    auto_order_manager._is_order_already_analysed = Mock(return_value=False)
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
            board_date="2026-03-10",
        )

    assert result["success"] is True
    assert result["orders_processed"] == 1
    assert captured_dates == ["2026-03-10"]
    assert "2026-05-15" not in captured_dates
    assert "2025-01-20" not in captured_dates


def test_process_all_orders_from_api_no_board_date_processes_all_orders(
    auto_order_manager,
):
    """When no board_date is supplied (back-fill), all orders from the API are processed."""
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

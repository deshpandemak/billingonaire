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


def test_upload_order_text_to_gcs_disabled_when_no_bucket(auto_order_manager):
    auto_order_manager._gcs_bucket_name = ""
    result = auto_order_manager._upload_order_text_to_gcs(
        "Some order text", "WP/123/2025", "2025-03-01"
    )
    assert result is None


def test_upload_order_text_to_gcs_returns_none_for_empty_text(auto_order_manager):
    """No point uploading (and no crash from) an empty extraction result."""
    auto_order_manager._gcs_bucket_name = "test-bucket"
    result = auto_order_manager._upload_order_text_to_gcs(
        "", "WP/123/2025", "2025-03-01"
    )
    assert result is None


def test_upload_order_text_to_gcs_success(auto_order_manager):
    """Upload text alongside the PDF at the same stable key, .txt extension."""
    auto_order_manager._gcs_bucket_name = "test-bucket"

    mock_blob = Mock()
    mock_bucket = Mock()
    mock_bucket.blob.return_value = mock_blob
    mock_client = Mock()
    mock_client.bucket.return_value = mock_bucket

    with patch("billingonaire_backend.AutoOrderManager.gcs_storage") as mock_gcs:
        mock_gcs.Client.return_value = mock_client
        result = auto_order_manager._upload_order_text_to_gcs(
            "Heard and adjourned.", "WP/123/2025", "2025-03-01"
        )

    assert result == (
        "https://storage.googleapis.com/test-bucket"
        "/court-orders/WP-123-2025/2025-03-01.txt"
    )
    mock_blob.upload_from_string.assert_called_once_with(
        "Heard and adjourned.", content_type="text/plain"
    )


def test_upload_order_text_to_gcs_failure_returns_none(auto_order_manager):
    """A text-upload failure must never raise -- the already-computed
    category/confidence result still has to be saved."""
    auto_order_manager._gcs_bucket_name = "test-bucket"

    with patch("billingonaire_backend.AutoOrderManager.gcs_storage") as mock_gcs:
        mock_gcs.Client.side_effect = Exception("connection refused")
        result = auto_order_manager._upload_order_text_to_gcs(
            "Heard and adjourned.", "WP/123/2025", "2025-03-01"
        )

    assert result is None


def test_analyze_order_with_api_metadata_persists_order_text_url(
    auto_order_manager,
):
    """The order_text_url returned by _upload_order_text_to_gcs must flow
    through to both the returned data and the append_case_order payload --
    this is what lets /admin/orders/{doc_id}/ai-suggestion skip
    re-downloading and re-analysing the PDF a second time."""
    auto_order_manager.case_store.transition_lifecycle = Mock(
        return_value={"applied": True}
    )
    auto_order_manager.case_store.append_case_order = Mock()
    auto_order_manager.order_analyzer.analyze_order_document = Mock(
        return_value=Mock(
            order_category="ADJOURNED",
            category_confidence=0.9,
            order_text="Heard and adjourned.",
            analysis_metadata={},
            cases=[],
        )
    )
    text_url = (
        "https://storage.googleapis.com/test-bucket"
        "/court-orders/WP-123-2025/2025-03-01.txt"
    )
    auto_order_manager._upload_order_text_to_gcs = Mock(return_value=text_url)

    result = auto_order_manager._analyze_order_with_api_metadata(
        case_id="board-abc",
        case_ref="WP/123/2025",
        pdf_content=b"%PDF-1.4",
        api_order_date="2025-03-01",
        api_petitioner="Petitioner Co",
        api_respondent="State of Maharashtra",
        order_link="https://example.com/order.pdf",
    )

    auto_order_manager._upload_order_text_to_gcs.assert_called_once_with(
        "Heard and adjourned.", "WP/123/2025", "2025-03-01"
    )
    assert result["data"]["order_text_url"] == text_url
    call_kwargs = auto_order_manager.case_store.append_case_order.call_args[0][1]
    assert call_kwargs["order_text_url"] == text_url


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


def test_analyze_order_with_api_metadata_llm_agreement_avoids_manual_review(
    auto_order_manager, monkeypatch
):
    """Integration of roadmap #2 into the real analysis path: a low-confidence
    regex result that the LLM independently agrees with must clear the
    review gate (transition to "analysed", not "manual_review_required"),
    and the LLM's read must be attached to the stored metadata."""
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    auto_order_manager.case_store.transition_lifecycle = Mock(
        return_value={"applied": True}
    )
    auto_order_manager.case_store.append_case_order = Mock()
    auto_order_manager.order_analyzer.analyze_order_document = Mock(
        return_value=Mock(
            order_category="ADJOURNED",
            category_confidence=0.4,
            order_text="Due to paucity of time, stand over to 15/03/2025.",
            analysis_metadata={},
            cases=[],
        )
    )

    with patch(
        "review_copilot.call_gemini",
        return_value={
            "category": "ADJOURNED",
            "confidence": 0.9,
            "rationale": 'Explicitly "paucity of time" with no hearing.',
        },
    ):
        result = auto_order_manager._analyze_order_with_api_metadata(
            case_id="board-abc",
            case_ref="WP/123/2025",
            pdf_content=b"%PDF-1.4",
            api_order_date="2025-03-01",
            api_petitioner="Petitioner Co",
            api_respondent="State of Maharashtra",
            order_link="https://example.com/order.pdf",
        )

    assert result["success"] is True
    data = result["data"]
    assert data["order_category"] == "ADJOURNED"
    assert data["order_category_confidence"] == 0.9
    assert (
        data["order_analysis_metadata"]["llm_suggestion"]["agreed_with_regex"] is True
    )

    # The lifecycle transition actually taken must reflect the boosted
    # confidence -- this is what keeps the case out of manual review.
    transition_call = auto_order_manager.case_store.transition_lifecycle.call_args
    assert transition_call.args[1] == "analysed"


def test_process_all_orders_from_api_success(auto_order_manager):
    """All portal orders are downloaded, analysed, and linked to their board entries."""
    auto_order_manager.court_scraper._fetch_with_provider = Mock(
        return_value={
            "result": {"_dummy": True},
            "provider_sequence": ["http"],
            "provider_attempts": [
                {"step": "http", "status": "success", "duration_ms": 100}
            ],
        }
    )
    auto_order_manager.court_scraper._enrich_case_orders_result = Mock(
        return_value={
            "status": "found",
            "petitioner": "ABC Corp",
            "respondent": "Govt of MH",
            "case_orders": [
                # Historical order — processed and linked to its own board entry
                {"date": "2025-02-01", "download_link": "https://court.example/o1.pdf"},
                # Matches board_date — also processed and linked
                {"date": "2025-03-01", "download_link": "https://court.example/o2.pdf"},
            ],
        }
    )
    auto_order_manager._is_order_already_analysed = Mock(return_value=False)
    auto_order_manager._get_analysed_order_for_date = Mock(return_value=None)
    auto_order_manager._update_board_entries_for_case_date = Mock(return_value=0)
    auto_order_manager._upload_order_to_gcs = Mock(return_value=None)
    auto_order_manager._analyze_order_with_api_metadata = Mock(
        return_value={"success": True, "data": {"order_category": "interim"}}
    )
    auto_order_manager.case_store.update_case_party_names = Mock()

    with patch("billingonaire_backend.AutoOrderManager.court_get") as mock_get:
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
    # Both orders are processed — historical orders are now linked to their own board entries
    assert result["orders_processed"] == 2
    assert result["orders_skipped"] == 0
    auto_order_manager.case_store.update_case_party_names.assert_called_once_with(
        "WP/123/2025", "ABC Corp", "Govt of MH"
    )
    assert auto_order_manager._analyze_order_with_api_metadata.call_count == 2
    # _update_board_entries_for_case_date called once per analysed order
    assert auto_order_manager._update_board_entries_for_case_date.call_count == 2


def test_process_all_orders_from_api_skips_already_analysed(auto_order_manager):
    """Already-analysed orders are skipped without re-downloading."""
    auto_order_manager.court_scraper._fetch_with_provider = Mock(
        return_value={
            "result": {"_dummy": True},
            "provider_sequence": ["http"],
            "provider_attempts": [
                {"step": "http", "status": "success", "duration_ms": 100}
            ],
        }
    )
    auto_order_manager.court_scraper._enrich_case_orders_result = Mock(
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
    auto_order_manager.court_scraper._fetch_with_provider = Mock(
        return_value={
            "result": {"_dummy": True},
            "provider_sequence": ["http"],
            "provider_attempts": [
                {"step": "http", "status": "success", "duration_ms": 100}
            ],
        }
    )
    auto_order_manager.court_scraper._enrich_case_orders_result = Mock(
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

    with patch("billingonaire_backend.AutoOrderManager.court_get") as mock_get:
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
    auto_order_manager.court_scraper._fetch_with_provider = Mock(
        return_value={
            "result": {"_dummy": True},
            "provider_sequence": ["http"],
            "provider_attempts": [
                {"step": "http", "status": "success", "duration_ms": 100}
            ],
        }
    )
    auto_order_manager.court_scraper._enrich_case_orders_result = Mock(
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

    with patch("billingonaire_backend.AutoOrderManager.court_get") as mock_get:
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


def test_process_all_orders_from_api_links_each_order_to_its_own_board_entry(
    auto_order_manager,
):
    """All portal orders are processed; each is linked to its own board entry by date.

    The court API returns ALL historical orders for a case.  Each order is now
    analysed and linked to the daily-boards document(s) whose board_date matches
    the order's signing date.  The triggering board entry (board_date=2026-05-15)
    is covered by the matching order; the old order is linked to its own entry.
    """
    auto_order_manager.court_scraper._fetch_with_provider = Mock(
        return_value={
            "result": {"_dummy": True},
            "provider_sequence": ["http"],
            "provider_attempts": [
                {"step": "http", "status": "success", "duration_ms": 100}
            ],
        }
    )
    auto_order_manager.court_scraper._enrich_case_orders_result = Mock(
        return_value={
            "status": "found",
            "petitioner": "P",
            "respondent": "R",
            "case_orders": [
                # Old order — processed and linked to its own board entry (2025-07-10)
                {
                    "date": "2025-07-10",
                    "download_link": "https://court.example/old.pdf",
                },
                # Matches board_date — processed and linked to the triggering entry
                {
                    "date": "2026-05-15",
                    "download_link": "https://court.example/new.pdf",
                },
            ],
        }
    )
    auto_order_manager._is_order_already_analysed = Mock(return_value=False)
    auto_order_manager._get_analysed_order_for_date = Mock(return_value=None)
    auto_order_manager._update_board_entries_for_case_date = Mock(return_value=0)
    auto_order_manager._upload_order_to_gcs = Mock(return_value=None)
    captured_dates: list = []
    auto_order_manager._analyze_order_with_api_metadata = Mock(
        side_effect=lambda **kw: captured_dates.append(kw.get("api_order_date"))
        or {"success": True, "data": {}}
    )
    auto_order_manager.case_store.update_case_party_names = Mock()

    with patch("billingonaire_backend.AutoOrderManager.court_get") as mock_get:
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
    # Both orders analysed; each linked to its own board entry
    assert result["orders_processed"] == 2
    assert set(captured_dates) == {"2025-07-10", "2026-05-15"}
    # Board entries updated for each order's own date (not the triggering board_date)
    update_dates = {
        call.args[1]
        for call in auto_order_manager._update_board_entries_for_case_date.call_args_list
    }
    assert update_dates == {"2025-07-10", "2026-05-15"}


def test_process_all_orders_from_api_processes_all_dates_in_one_portal_call(
    auto_order_manager,
):
    """One portal call processes all orders and links each to its own board entry.

    When the portal returns 3 orders for different dates, all are downloaded and
    analysed.  Each order is linked to board entries matching its own signing date,
    not the board_date that triggered the call.  Future analyses for the other dates
    will skip the portal call (fast-path) because the orders are already in
    case-details.
    """
    auto_order_manager.court_scraper._fetch_with_provider = Mock(
        return_value={
            "result": {"_dummy": True},
            "provider_sequence": ["http"],
            "provider_attempts": [
                {"step": "http", "status": "success", "duration_ms": 100}
            ],
        }
    )
    auto_order_manager.court_scraper._enrich_case_orders_result = Mock(
        return_value={
            "status": "found",
            "petitioner": "P",
            "respondent": "R",
            "case_orders": [
                # Matches board_date — primary order
                {"date": "2026-03-10", "download_link": "https://court.example/o1.pdf"},
                # Future hearing — also processed and linked to its own board entry
                {"date": "2026-05-15", "download_link": "https://court.example/o2.pdf"},
                # Old order — processed and linked to its own (past) board entry
                {
                    "date": "2025-01-20",
                    "download_link": "https://court.example/old.pdf",
                },
            ],
        }
    )
    auto_order_manager._is_order_already_analysed = Mock(return_value=False)
    auto_order_manager._get_analysed_order_for_date = Mock(return_value=None)
    auto_order_manager._update_board_entries_for_case_date = Mock(return_value=0)
    auto_order_manager._upload_order_to_gcs = Mock(return_value=None)
    captured_dates: list = []
    auto_order_manager._analyze_order_with_api_metadata = Mock(
        side_effect=lambda **kw: captured_dates.append(kw.get("api_order_date"))
        or {"success": True, "data": {}}
    )
    auto_order_manager.case_store.update_case_party_names = Mock()

    with patch("billingonaire_backend.AutoOrderManager.court_get") as mock_get:
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
    # All 3 orders processed in one portal call
    assert result["orders_processed"] == 3
    assert set(captured_dates) == {"2026-03-10", "2026-05-15", "2025-01-20"}
    # Each order linked to its own board entry by date
    update_dates = {
        call.args[1]
        for call in auto_order_manager._update_board_entries_for_case_date.call_args_list
    }
    assert update_dates == {"2026-03-10", "2026-05-15", "2025-01-20"}


def test_process_all_orders_from_api_no_board_date_processes_all_orders(
    auto_order_manager,
):
    """When no board_date is supplied (back-fill), all orders from the API are processed."""
    auto_order_manager.court_scraper._fetch_with_provider = Mock(
        return_value={
            "result": {"_dummy": True},
            "provider_sequence": ["http"],
            "provider_attempts": [
                {"step": "http", "status": "success", "duration_ms": 100}
            ],
        }
    )
    auto_order_manager.court_scraper._enrich_case_orders_result = Mock(
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

    with patch("billingonaire_backend.AutoOrderManager.court_get") as mock_get:
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


class TestBoardDateQueryCoercion:
    """`board_date` is written to Firestore by Board.saveData as a midnight
    datetime.  Query values must therefore be datetimes — comparing the field
    against a raw "YYYY-MM-DD" string matches nothing, because Firestore sorts
    all timestamps before all strings.  This silently returned zero candidates
    for every date-filtered fetch job.
    """

    def test_iso_string_is_coerced_to_midnight_datetime(self):
        assert AutoOrderManager._to_board_date_query_value("2026-07-24") == datetime(
            2026, 7, 24
        )

    def test_datetime_passes_through_unchanged(self):
        value = datetime(2026, 7, 24, 10, 30)
        assert AutoOrderManager._to_board_date_query_value(value) is value

    def test_date_is_promoted_to_datetime(self):
        from datetime import date as _date

        assert AutoOrderManager._to_board_date_query_value(_date(2026, 7, 24)) == (
            datetime(2026, 7, 24)
        )

    @pytest.mark.parametrize("value", [None, "", "   ", "not-a-date"])
    def test_unusable_values_return_none(self, value):
        assert AutoOrderManager._to_board_date_query_value(value) is None

    def test_timestamp_string_is_truncated_to_date(self):
        assert AutoOrderManager._to_board_date_query_value(
            "2026-07-24 00:00:00"
        ) == datetime(2026, 7, 24)


class TestAnalyzeExistingOrder:
    """`main._run_case_analysis_job` (main.py:620) calls
    `_analyze_existing_order`, which did not exist. Every job queued by
    POST /jobs/analyze-orders therefore raised AttributeError inside the
    worker, got swallowed, and was marked analysis_failed_retryable — the
    whole analysis queue was a silent no-op.
    """

    def _template(self):
        return {
            "case_id": "board-1",
            "case_ref": "WP/123/2025",
            "download_success": True,
            "analysis_success": False,
            "order_link": "https://example.test/o.pdf",
            "analysis_data": None,
            "error": None,
            "retry_attempts": [],
            "has_existing_order": True,
        }

    def _case(self, **over):
        base = {
            "id": "board-1",
            "case_ref": "WP/123/2025",
            "order_link": "https://example.test/o.pdf",
            "board_date": "2025-03-01",
            "order_status": "linked",
        }
        base.update(over)
        return base

    def test_method_exists_on_the_manager(self, auto_order_manager):
        """Regression guard for the AttributeError itself."""
        assert callable(getattr(auto_order_manager, "_analyze_existing_order", None))

    def test_happy_path_analyses_and_updates_boards(self, auto_order_manager):
        auto_order_manager._get_case_order_context = Mock(
            return_value={
                "latest_order": {
                    "order_date": "2025-03-01",
                    "petitioner": "P Ltd",
                    "respondent": "State",
                }
            }
        )
        auto_order_manager._is_order_already_analysed = Mock(return_value=False)
        auto_order_manager._analyze_order_with_api_metadata = Mock(
            return_value={"success": True, "data": {"order_category": "ADJOURNED"}}
        )
        auto_order_manager._update_board_entries_for_case_date = Mock(return_value=2)

        resp = Mock(
            status_code=200,
            content=b"%PDF-1.4 x",
            headers={"Content-Type": "application/pdf"},
        )
        with patch(
            "billingonaire_backend.AutoOrderManager.court_get", return_value=resp
        ):
            result = auto_order_manager._analyze_existing_order(
                self._case(), self._template()
            )

        assert result["analysis_success"] is True
        assert result["analysis_data"]["order_category"] == "ADJOURNED"
        # party metadata from the stored order entry must be passed through
        kwargs = auto_order_manager._analyze_order_with_api_metadata.call_args.kwargs
        assert kwargs["api_order_date"] == "2025-03-01"
        assert kwargs["api_petitioner"] == "P Ltd"
        # daily-boards must be updated for the case+date
        auto_order_manager._update_board_entries_for_case_date.assert_called_once()

    def test_order_entry_is_tagged_with_the_orders_own_date_not_the_latest_board_date(
        self, auto_order_manager
    ):
        """The stored order entry's board_date decides which board row Search
        Orders shows this order against (Board._hydrate_with_case_details
        matches orders[].board_date to each row's own date).

        This used to be passed straight through from case_info["board_date"],
        which the analysis poll loop reads off a case-details doc -- and
        case-details has no board_date field, only latest_board_date. So for
        any case listed on the board more than once, an older order was
        tagged with the case's MOST RECENT hearing date and surfaced against
        the wrong board row, with nothing shown against the right one.
        """
        auto_order_manager._get_case_order_context = Mock(
            return_value={"latest_order": {"order_date": "2025-03-01"}}
        )
        auto_order_manager._is_order_already_analysed = Mock(return_value=False)
        auto_order_manager._analyze_order_with_api_metadata = Mock(
            return_value={"success": True, "data": {"order_category": "ADJOURNED"}}
        )
        auto_order_manager._update_board_entries_for_case_date = Mock(return_value=1)

        resp = Mock(
            status_code=200,
            content=b"%PDF-1.4 x",
            headers={"Content-Type": "application/pdf"},
        )
        with patch(
            "billingonaire_backend.AutoOrderManager.court_get", return_value=resp
        ):
            # The case is being processed off a case-details row whose
            # latest_board_date is a LATER appearance than this order.
            auto_order_manager._analyze_existing_order(
                self._case(board_date="2025-11-20"), self._template()
            )

        kwargs = auto_order_manager._analyze_order_with_api_metadata.call_args.kwargs
        assert kwargs["board_date"] == "2025-03-01", (
            "order entry must be tagged with the hearing the order belongs to "
            "(its own date), not the case's most recent board date"
        )
        # ...and must agree with the date used to link the daily-boards rows,
        # otherwise case-details and daily-boards disagree about the same order.
        assert (
            auto_order_manager._update_board_entries_for_case_date.call_args.args[1]
            == kwargs["board_date"]
        )

    def test_already_analysed_is_idempotent_and_does_not_refetch(
        self, auto_order_manager
    ):
        """Re-queues and the fetch worker's auto-retry must not re-download."""
        auto_order_manager._get_case_order_context = Mock(
            return_value={"latest_order": {"order_date": "2025-03-01"}}
        )
        auto_order_manager._is_order_already_analysed = Mock(return_value=True)
        auto_order_manager._get_analysed_order_for_date = Mock(
            return_value={"order_category": "DISPOSED_OFF"}
        )

        with patch("billingonaire_backend.AutoOrderManager.court_get") as mock_get:
            result = auto_order_manager._analyze_existing_order(
                self._case(), self._template()
            )

        assert result["analysis_success"] is True
        assert result["analysis_data"]["order_category"] == "DISPOSED_OFF"
        mock_get.assert_not_called()

    def test_missing_order_link_reports_error(self, auto_order_manager):
        result = auto_order_manager._analyze_existing_order(
            self._case(order_link=None), self._template()
        )
        assert result["analysis_success"] is False
        assert "No order link" in result["error"]

    def test_non_pdf_response_reports_error(self, auto_order_manager):
        auto_order_manager._get_case_order_context = Mock(
            return_value={"latest_order": {"order_date": "2025-03-01"}}
        )
        auto_order_manager._is_order_already_analysed = Mock(return_value=False)
        resp = Mock(
            status_code=200,
            content=b"<html>nope",
            headers={"Content-Type": "text/html"},
        )
        with patch(
            "billingonaire_backend.AutoOrderManager.court_get", return_value=resp
        ):
            result = auto_order_manager._analyze_existing_order(
                self._case(), self._template()
            )
        assert result["analysis_success"] is False
        assert "did not return a PDF" in result["error"]

    def test_download_exception_is_caught(self, auto_order_manager):
        import requests as _rq

        auto_order_manager._get_case_order_context = Mock(
            return_value={"latest_order": {"order_date": "2025-03-01"}}
        )
        auto_order_manager._is_order_already_analysed = Mock(return_value=False)
        with patch(
            "billingonaire_backend.AutoOrderManager.court_get",
            side_effect=_rq.exceptions.ConnectionError("boom"),
        ):
            result = auto_order_manager._analyze_existing_order(
                self._case(), self._template()
            )
        assert result["analysis_success"] is False
        assert "Could not download" in result["error"]


class TestGetFilteredMattersDoesNotSwallowErrors:
    """_get_filtered_matters used to wrap its entire Firestore query in
    except Exception: return []. Any real failure (a missing composite
    index, anything) was silently turned into "0 candidates", and every
    caller (/jobs/fetch-orders, /jobs/retry-failed, get_orders_for_cases)
    reported that as a confident, false "already up to date" / "no cases
    found" success. The fix is to let the exception propagate -- every
    caller already has its own outer exception handler that turns it into a
    real error response.
    """

    def test_a_firestore_query_error_propagates_instead_of_returning_empty(
        self, auto_order_manager, mock_firestore
    ):
        mock_firestore.client.return_value.collection.side_effect = RuntimeError(
            "boom: composite index required"
        )
        with pytest.raises(RuntimeError, match="composite index required"):
            auto_order_manager._get_filtered_matters(filters={}, limit=10)

    def test_a_stream_error_propagates_instead_of_returning_empty(
        self, auto_order_manager, mock_firestore
    ):
        mock_query = MagicMock()
        mock_query.limit.return_value.stream.side_effect = RuntimeError(
            "boom: transient Firestore error"
        )
        mock_firestore.client.return_value.collection.return_value = mock_query
        with pytest.raises(RuntimeError, match="transient Firestore error"):
            auto_order_manager._get_filtered_matters(filters={}, limit=10)


class TestGetFilteredMattersScope:
    """scope narrows candidate selection by order_status: "missing_only" is
    only not_linked cases; "actionable" (the default, unchanged historical
    behavior) is not_linked/linked/order_failed/order_analysis_failed;
    "all" is every case matched by the board-level filters, including
    already-analysed ones, for a deliberate full re-fetch/re-analyse."""

    def _make_docs(self):
        statuses_by_ref = {
            "WP/1/2026": "not_linked",
            "WP/2/2026": "linked",
            "WP/3/2026": "order_failed",
            "WP/4/2026": "analysed",
        }

        docs = []
        for i, case_ref in enumerate(statuses_by_ref, start=1):
            doc = MagicMock()
            doc.id = f"2026-01-01-WP-{i}-2026"
            doc.to_dict.return_value = {
                "case_type": "WP",
                "case_no": str(i),
                "case_year": "2026",
            }
            docs.append(doc)
        return docs, statuses_by_ref

    def _wire(self, auto_order_manager, mock_firestore):
        docs, statuses_by_ref = self._make_docs()
        mock_query = MagicMock()
        mock_query.limit.return_value.stream.return_value = docs
        mock_firestore.client.return_value.collection.return_value = mock_query
        auto_order_manager._get_case_order_context = Mock(
            side_effect=lambda case_ref: {
                "order_status": statuses_by_ref[case_ref],
                "order_link": None,
            }
        )
        return statuses_by_ref

    def test_missing_only_returns_only_not_linked(
        self, auto_order_manager, mock_firestore
    ):
        self._wire(auto_order_manager, mock_firestore)
        cases = auto_order_manager._get_filtered_matters(
            filters={}, limit=10, scope="missing_only"
        )
        assert {c["case_ref"] for c in cases} == {"WP/1/2026"}

    def test_actionable_excludes_analysed(self, auto_order_manager, mock_firestore):
        self._wire(auto_order_manager, mock_firestore)
        cases = auto_order_manager._get_filtered_matters(
            filters={}, limit=10, scope="actionable"
        )
        assert {c["case_ref"] for c in cases} == {
            "WP/1/2026",
            "WP/2/2026",
            "WP/3/2026",
        }

    def test_all_includes_analysed(self, auto_order_manager, mock_firestore):
        self._wire(auto_order_manager, mock_firestore)
        cases = auto_order_manager._get_filtered_matters(
            filters={}, limit=10, scope="all"
        )
        assert {c["case_ref"] for c in cases} == {
            "WP/1/2026",
            "WP/2/2026",
            "WP/3/2026",
            "WP/4/2026",
        }

    def test_default_scope_is_actionable(self, auto_order_manager, mock_firestore):
        """Existing callers (e.g. /jobs/retry-failed) don't pass scope and
        must keep getting the pre-scope-toggle behavior unchanged."""
        self._wire(auto_order_manager, mock_firestore)
        cases = auto_order_manager._get_filtered_matters(filters={}, limit=10)
        assert {c["case_ref"] for c in cases} == {
            "WP/1/2026",
            "WP/2/2026",
            "WP/3/2026",
        }

    def test_explicit_order_statuses_overrides_scope(
        self, auto_order_manager, mock_firestore
    ):
        """admin bulk processing's status checkboxes are a free multi-select,
        not one of the named scopes -- an explicit order_statuses set must
        win over whatever scope (even the default) would otherwise pick."""
        self._wire(auto_order_manager, mock_firestore)
        cases = auto_order_manager._get_filtered_matters(
            filters={},
            limit=10,
            scope="missing_only",
            order_statuses={"linked", "analysed"},
        )
        assert {c["case_ref"] for c in cases} == {"WP/2/2026", "WP/4/2026"}

    def test_order_statuses_none_defers_to_scope(
        self, auto_order_manager, mock_firestore
    ):
        self._wire(auto_order_manager, mock_firestore)
        cases = auto_order_manager._get_filtered_matters(
            filters={}, limit=10, scope="missing_only", order_statuses=None
        )
        assert {c["case_ref"] for c in cases} == {"WP/1/2026"}


class TestMaybeLlmAssist:
    """Roadmap #2: route only ambiguous (low-confidence) cases to an LLM,
    and only ever auto-resolve on agreement between the regex and the LLM
    -- disagreement always still goes to manual review, unchanged."""

    def _analysis_result(self, category="ADJOURNED", confidence=0.4, text="Order text"):
        return types.SimpleNamespace(
            order_category=category, category_confidence=confidence, order_text=text
        )

    def test_no_op_without_gemini_api_key(self, auto_order_manager, monkeypatch):
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        result = auto_order_manager._maybe_llm_assist(self._analysis_result())
        assert result == {
            "category": "ADJOURNED",
            "confidence": 0.4,
            "llm_suggestion": None,
        }

    def test_no_op_when_confidence_already_above_review_threshold(
        self, auto_order_manager, monkeypatch
    ):
        """Not ambiguous -- the whole point is to route only the cases a
        human would otherwise have to look at, not every order."""
        monkeypatch.setenv("GEMINI_API_KEY", "test-key")
        called = Mock()
        with patch("review_copilot.call_gemini", called):
            result = auto_order_manager._maybe_llm_assist(
                self._analysis_result(confidence=0.9)
            )
        called.assert_not_called()
        assert result["confidence"] == 0.9
        assert result["llm_suggestion"] is None

    def test_no_op_when_order_text_is_empty(self, auto_order_manager, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "test-key")
        called = Mock()
        with patch("review_copilot.call_gemini", called):
            result = auto_order_manager._maybe_llm_assist(
                self._analysis_result(text="   ")
            )
        called.assert_not_called()
        assert result["llm_suggestion"] is None

    def test_raises_confidence_when_llm_agrees_with_regex(
        self, auto_order_manager, monkeypatch
    ):
        monkeypatch.setenv("GEMINI_API_KEY", "test-key")
        with patch(
            "review_copilot.call_gemini",
            return_value={
                "category": "ADJOURNED",
                "confidence": 0.9,
                "rationale": "Stand over to next date, no hearing.",
            },
        ):
            result = auto_order_manager._maybe_llm_assist(
                self._analysis_result(category="ADJOURNED", confidence=0.4)
            )

        assert result["category"] == "ADJOURNED"
        assert result["confidence"] == 0.9  # raised, agreement is the trustworthy case
        assert result["llm_suggestion"]["agreed_with_regex"] is True

    def test_never_lowers_confidence_even_if_llm_is_less_confident(
        self, auto_order_manager, monkeypatch
    ):
        monkeypatch.setenv("GEMINI_API_KEY", "test-key")
        with patch(
            "review_copilot.call_gemini",
            return_value={"category": "ADJOURNED", "confidence": 0.3, "rationale": "x"},
        ):
            result = auto_order_manager._maybe_llm_assist(
                self._analysis_result(category="ADJOURNED", confidence=0.4)
            )
        assert result["confidence"] == 0.4

    def test_disagreement_leaves_regex_result_completely_unchanged(
        self, auto_order_manager, monkeypatch
    ):
        """The case must still go to manual review exactly as it would have
        without this feature -- disagreement never auto-resolves."""
        monkeypatch.setenv("GEMINI_API_KEY", "test-key")
        with patch(
            "review_copilot.call_gemini",
            return_value={
                "category": "HEARD_AND_ADJOURNED",
                "confidence": 0.9,
                "rationale": "Notice was issued.",
            },
        ):
            result = auto_order_manager._maybe_llm_assist(
                self._analysis_result(category="ADJOURNED", confidence=0.4)
            )

        assert result["category"] == "ADJOURNED"
        assert result["confidence"] == 0.4
        assert result["llm_suggestion"]["category"] == "HEARD_AND_ADJOURNED"
        assert result["llm_suggestion"]["agreed_with_regex"] is False

    def test_llm_call_failure_falls_back_to_regex_result_unchanged(
        self, auto_order_manager, monkeypatch
    ):
        monkeypatch.setenv("GEMINI_API_KEY", "test-key")
        with patch("review_copilot.call_gemini", side_effect=RuntimeError("timeout")):
            result = auto_order_manager._maybe_llm_assist(
                self._analysis_result(category="ADJOURNED", confidence=0.4)
            )
        assert result["category"] == "ADJOURNED"
        assert result["confidence"] == 0.4
        assert result["llm_suggestion"] is None

    def test_disagreement_is_logged_with_the_case_ref(
        self, auto_order_manager, monkeypatch, caplog
    ):
        """Regression guard: before this log line existed, a disagreement
        was completely invisible in Cloud Logging -- only the "agree"
        branch logged anything, so a disagreement and "the LLM was never
        called" looked identical from the logs alone. Confirmed live: a
        production case (WP/16083/2022) went to manual review with no LLM
        log output at all and no WARNING either, meaning it had silently
        disagreed. This is the fix -- disagreement must produce a log line
        an operator can find and act on, carrying the case_ref so it's
        traceable back to the case."""
        monkeypatch.setenv("GEMINI_API_KEY", "test-key")
        with patch(
            "review_copilot.call_gemini",
            return_value={
                "category": "HEARD_AND_ADJOURNED",
                "confidence": 0.9,
                "rationale": "Notice was issued.",
            },
        ):
            with caplog.at_level("INFO"):
                auto_order_manager._maybe_llm_assist(
                    self._analysis_result(category="ADJOURNED", confidence=0.4),
                    case_ref="WP/16083/2022",
                )

        disagreement_logs = [
            r.message for r in caplog.records if "DISAGREE" in r.message
        ]
        assert len(disagreement_logs) == 1
        assert "WP/16083/2022" in disagreement_logs[0]
        assert "ADJOURNED" in disagreement_logs[0]
        assert "HEARD_AND_ADJOURNED" in disagreement_logs[0]

    def test_agreement_is_logged_with_the_case_ref(
        self, auto_order_manager, monkeypatch, caplog
    ):
        monkeypatch.setenv("GEMINI_API_KEY", "test-key")
        with patch(
            "review_copilot.call_gemini",
            return_value={
                "category": "ADJOURNED",
                "confidence": 0.9,
                "rationale": "Stand over, no hearing.",
            },
        ):
            with caplog.at_level("INFO"):
                auto_order_manager._maybe_llm_assist(
                    self._analysis_result(category="ADJOURNED", confidence=0.4),
                    case_ref="WP/1/2026",
                )

        agree_logs = [r.message for r in caplog.records if "agree" in r.message]
        assert len(agree_logs) == 1
        assert "WP/1/2026" in agree_logs[0]

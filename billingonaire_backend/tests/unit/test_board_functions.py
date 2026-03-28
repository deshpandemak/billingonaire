"""Functional tests for Board.py - Actual function calls with mocked dependencies"""

import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))


@pytest.fixture(autouse=True)
def mock_firebase():
    """Mock Firebase before any imports"""
    with patch("firebase_admin.firestore"):
        with patch("google.cloud.firestore.Client") as mock_client:
            yield mock_client


@patch("Board.firestore.client")
@patch("Board.pdfplumber")
def test_readfile_with_valid_pdf(mock_pdfplumber, mock_firestore):
    """Test Board.readFile method with valid PDF"""
    from Board import Board

    mock_pdf = MagicMock()
    mock_page = MagicMock()
    mock_page.extract_text.return_value = (
        "01/10/2024 HON'BLE COURT  1 WP/12345/2024 Test SHRI LAWYER"
    )
    mock_pdf.pages = [mock_page]
    mock_pdfplumber.open.return_value.__enter__.return_value = mock_pdf

    board = Board()
    mock_file = MagicMock()
    mock_file.read.return_value = b"%PDF-test"
    mock_file.seek = MagicMock()

    result = board.readFile("board_2024_10_01.pdf", mock_file)
    assert result is not None


@patch("Board.firestore.client")
@patch("Board.pdfplumber")
def test_read_board_function(mock_pdfplumber, mock_firestore):
    """Test Board.read_board method"""
    from Board import Board

    mock_pdf = MagicMock()
    mock_page = MagicMock()
    mock_page.extract_text.return_value = "01/10/2024 HON'BLE COURT  1 WP/1/2024 Test"
    mock_pdf.pages = [mock_page]
    mock_pdfplumber.open.return_value.__enter__.return_value = mock_pdf

    board = Board()
    mock_file = MagicMock()
    result = board.read_board("board.pdf", mock_file)
    assert result is not None


@patch("Board.firestore.client")
def test_get_all_boards(mock_firestore):
    """Test Board.getData method for retrieving all boards"""
    from Board import Board

    mock_docs = [
        MagicMock(to_dict=lambda: {"board_date": "2024-10-01", "case_type": "WP"}),
        MagicMock(to_dict=lambda: {"board_date": "2024-10-02", "case_type": "WP"}),
    ]
    mock_firestore.return_value.collection.return_value.limit.return_value.stream.return_value = (
        mock_docs
    )

    board = Board()
    result = board.getData({})
    assert isinstance(result, list)


@patch("Board.firestore.client")
def test_parse_case_ref(mock_firestore):
    """Test case reference parsing via create_record"""
    from Board import Board

    board = Board()
    result = board.create_record(
        court_details="Test",
        file_name="test.pdf",
        board_date="2024-10-01",
        serial_no="1",
        case_type="WP",
        case_no="12345",
        case_year="2024",
    )
    assert result is not None
    assert result.get("case_type") == "WP"
    assert result.get("case_no") == "12345"
    assert result.get("case_year") == "2024"


@patch("Board.firestore.client")
def test_normalize_case_ref(mock_firestore):
    """Test case reference normalization in Board operations"""
    from Board import Board

    board = Board()
    # Test that Board handles case refs properly
    result = board.create_record(
        court_details="Test",
        file_name="test.pdf",
        board_date="2024-10-01",
        serial_no="1",
        case_type="WP",
        case_no="12345",
        case_year="2024",
    )
    # Verify case reference fields are present
    assert "case_type" in result
    assert "case_no" in result
    assert "case_year" in result


@patch("Board.firestore.client")
@patch("Board.pdfplumber")
def test_process_enhanced_text(mock_pdfplumber, mock_firestore):
    """Test Board.process_enhanced_text method"""
    from Board import Board

    board = Board()
    ml_result = MagicMock()
    ml_result.text = "01/10/2024 HON'BLE COURT  1 WP/1/2024 Test SHRI JOSHI"
    ml_result.entities = []
    ml_result.name_mappings = []
    ml_result.extraction_method = "ml"
    ml_result.quality_score = 0.9

    result = board.process_enhanced_text("test.pdf", ml_result)
    assert result is not None


@patch("Board.firestore.client")
def test_extract_date_from_filename(mock_firestore):
    """Test date extraction from board operations"""
    from Board import Board

    # Board class doesn't have a standalone extract_date function
    # But it handles dates in create_record
    board = Board()
    result = board.create_record(
        court_details="Test",
        file_name="board_2024_10_01.pdf",
        board_date="2024-10-01",
        serial_no="1",
        case_type="WP",
        case_no="12345",
        case_year="2024",
    )
    assert "2024" in str(result["board_date"])


@patch("Board.firestore.client")
def test_clean_agp_name(mock_firestore):
    """Test AGP name handling in create_record"""
    from Board import Board

    board = Board()
    # create_record extracts and cleans AGP names from court details
    result = board.create_record(
        court_details="Test SHRI P.M.JOSHI, AGP WITH",
        file_name="test.pdf",
        board_date="2024-10-01",
        serial_no="1",
        case_type="WP",
        case_no="12345",
        case_year="2024",
    )
    # Verify respondent lawyer extraction (AGP name)
    assert "respondent_lawyer" in result


@patch("Board.firestore.client")
def test_get_cases_by_date_range(mock_firestore):
    """Test Board.getData with date range"""
    from Board import Board

    mock_docs = [
        MagicMock(
            to_dict=lambda: {
                "board_date": "2024-10-01",
                "case_type": "WP",
                "case_no": "1",
                "case_year": "2024",
            }
        )
    ]
    mock_query = MagicMock()
    mock_query.stream.return_value = mock_docs
    mock_firestore.return_value.collection.return_value.where.return_value = mock_query

    board = Board()
    result = board.getData({"startDate": "2024-10-01", "endDate": "2024-10-07"})
    assert isinstance(result, list)


@patch("Board.firestore.client")
@patch("Board.pdfplumber")
def test_extract_tables_from_pdf(mock_pdfplumber, mock_firestore):
    """Test table extraction via read_board"""
    from Board import Board

    mock_pdf = MagicMock()
    mock_page = MagicMock()
    mock_page.extract_text.return_value = "01/10/2024 HON'BLE COURT  1 WP/1/2024 Test"
    mock_pdf.pages = [mock_page]
    mock_pdfplumber.open.return_value.__enter__.return_value = mock_pdf

    board = Board()
    mock_file = MagicMock()
    result = board.read_board("test.pdf", mock_file)
    assert result is not None


@patch("Board.firestore.client")
def test_validate_case_format(mock_firestore):
    """Test case format validation via create_record"""
    from Board import Board

    board = Board()
    # Valid case format
    result = board.create_record(
        court_details="Test",
        file_name="test.pdf",
        board_date="2024-10-01",
        serial_no="1",
        case_type="WP",
        case_no="12345",
        case_year="2024",
    )
    assert result["case_type"] == "WP"
    assert result["case_no"] == "12345"
    assert result["case_year"] == "2024"


# ---------------------------------------------------------------------------
# Tests for order_status filtering fix and AGP filter alignment
# ---------------------------------------------------------------------------


@patch("Board.firestore.client")
def test_hydrate_order_status_defaults_to_not_linked_when_none(mock_firestore):
    """
    When a case-details document exists but both latest_order_status and
    latest_order.order_status are None, order_status must be 'not_linked'
    rather than None so that status-based filtering works correctly.
    """
    from Board import Board

    board = Board()

    # Case detail with no order status set
    board.case_store = MagicMock()
    board.case_store.build_case_ref.return_value = "WP/1/2024"
    board.case_store.get_case_details_map.return_value = {
        "WP/1/2024": {
            "latest_order_status": None,
            "orders": [],
        }
    }

    records = [
        {
            "case_ref": "WP/1/2024",
            "case_type": "WP",
            "case_no": "1",
            "case_year": "2024",
        }
    ]
    result = board._hydrate_with_case_details(records)
    assert result[0]["order_status"] == "not_linked"


@patch("Board.firestore.client")
def test_getData_order_status_filter_matches_not_linked_correctly(mock_firestore):
    """
    Filtering by orderStatus='not_linked' must include records where
    order_status resolved to None in the case-details (treated as not_linked).
    """
    from Board import Board

    board = Board()

    # Firestore returns one record
    mock_doc = MagicMock()
    mock_doc.id = "2024-10-01-WP-1-2024"
    mock_doc.to_dict.return_value = {
        "board_date": "2024-10-01",
        "case_type": "WP",
        "case_no": "1",
        "case_year": "2024",
        "respondent_lawyer": "Test Lawyer",
    }
    mock_query = MagicMock()
    mock_query.stream.return_value = [mock_doc]
    mock_firestore.return_value.collection.return_value.limit.return_value.stream.return_value = [
        mock_doc
    ]
    mock_firestore.return_value.collection.return_value.stream.return_value = [mock_doc]
    mock_firestore.return_value.collection.return_value.where.return_value = mock_query

    # Case detail has no order status (None → should be treated as not_linked)
    board.case_store = MagicMock()
    board.case_store.build_case_ref.return_value = "WP/1/2024"
    board.case_store.get_case_details_map.return_value = {
        "WP/1/2024": {"latest_order_status": None, "orders": []}
    }

    result = board.getData({"orderStatus": "not_linked"})
    assert len(result) == 1
    assert result[0]["order_status"] == "not_linked"


@patch("Board.firestore.client")
def test_record_matches_agp_checks_government_pleader(mock_firestore):
    """
    _record_matches_agp should return True when agp name is found in
    government_pleader (case-details field) even if not in respondent_lawyer.
    """
    from Board import Board

    board = Board()

    record = {
        "respondent_lawyer": "Some Other Lawyer",
        "government_pleader": ["Pooja Joshi Deshpande"],
        "additional_respondent_lawyers": [],
    }
    # Variation that is a substring of the government_pleader value
    assert board._record_matches_agp(record, ["Pooja Joshi Deshpande"]) is True


@patch("Board.firestore.client")
def test_record_matches_agp_checks_additional_respondent_lawyers(mock_firestore):
    """
    _record_matches_agp should return True when agp name is in
    additional_respondent_lawyers.
    """
    from Board import Board

    board = Board()

    record = {
        "respondent_lawyer": "Primary Lawyer",
        "government_pleader": [],
        "additional_respondent_lawyers": ["Pooja Deshpande"],
    }
    assert board._record_matches_agp(record, ["Pooja Deshpande"]) is True


@patch("Board.firestore.client")
def test_record_matches_agp_returns_false_no_match(mock_firestore):
    """
    _record_matches_agp should return False when agp name is not found
    in any of the three priority fields.
    """
    from Board import Board

    board = Board()

    record = {
        "respondent_lawyer": "Different Lawyer",
        "government_pleader": ["Another AGP"],
        "additional_respondent_lawyers": ["Third Lawyer"],
    }
    assert board._record_matches_agp(record, ["Pooja Deshpande"]) is False


@patch("Board.firestore.client")
def test_getData_with_agp_name_variations_filters_by_all_fields(mock_firestore):
    """
    When agp_name_variations is supplied, getData filters records using
    government_pleader, respondent_lawyer, and additional_respondent_lawyers
    (same algorithm as bill generation).
    """
    from Board import Board

    board = Board()

    # Two board records: one with matching government_pleader, one unrelated
    matching_doc = MagicMock()
    matching_doc.id = "match-doc"
    matching_doc.to_dict.return_value = {
        "board_date": "2024-10-01",
        "case_type": "WP",
        "case_no": "1",
        "case_year": "2024",
        "respondent_lawyer": "Other Lawyer",
    }
    unrelated_doc = MagicMock()
    unrelated_doc.id = "unrelated-doc"
    unrelated_doc.to_dict.return_value = {
        "board_date": "2024-10-01",
        "case_type": "WP",
        "case_no": "2",
        "case_year": "2024",
        "respondent_lawyer": "Unrelated Lawyer",
    }

    # Wire up the mock collection chain; no limit(10) is applied when an AGP
    # filter is active (regardless of whether search criteria are empty).
    mock_firestore.return_value.collection.return_value.stream.return_value = [
        matching_doc,
        unrelated_doc,
    ]
    # Also wire the limit path so the initial collection-size probe doesn't fail
    mock_firestore.return_value.collection.return_value.limit.return_value.stream.return_value = [
        matching_doc,
        unrelated_doc,
    ]

    # Hydration: matching case has government_pleader set; unrelated does not
    board.case_store = MagicMock()

    def build_ref_side_effect(case_type, case_no, case_year):
        return f"{case_type}/{case_no}/{case_year}"

    board.case_store.build_case_ref.side_effect = build_ref_side_effect
    board.case_store.get_case_details_map.return_value = {
        "WP/1/2024": {
            "government_pleader": ["Pooja M. Joshi Deshpande"],
            "latest_order_status": "analysed",
            "orders": [],
        },
        "WP/2/2024": {
            "government_pleader": [],
            "latest_order_status": None,
            "orders": [],
        },
    }

    result = board.getData(
        {},
        agp_filter="Pooja Deshpande",
        agp_name_variations=["Pooja Deshpande", "P. Deshpande", "Pooja M. Joshi Deshpande"],
    )

    # Only the matching record should remain
    assert len(result) == 1
    assert result[0]["case_no"] == "1"


@patch("Board.firestore.client")
def test_record_matches_agp_single_token_variation_not_over_broad(mock_firestore):
    """
    Single-token variations (e.g. first name only) should NOT match records
    where a different lawyer shares the same first name.
    """
    from Board import Board

    board = Board()

    record = {
        "respondent_lawyer": "Pooja Kumbhakarna",  # Different lawyer, same first name
        "government_pleader": [],
        "additional_respondent_lawyers": [],
    }
    # Single-token "pooja" must NOT cause a match
    assert board._record_matches_agp(record, ["Pooja"]) is False


@patch("Board.firestore.client")
def test_record_matches_agp_multi_token_still_matches(mock_firestore):
    """
    Multi-token variations (e.g. first + last name) should still match correctly.
    """
    from Board import Board

    board = Board()

    record = {
        "respondent_lawyer": "Pooja Joshi Deshpande",
        "government_pleader": [],
        "additional_respondent_lawyers": [],
    }
    assert board._record_matches_agp(record, ["Pooja Deshpande", "Pooja Joshi Deshpande"]) is True

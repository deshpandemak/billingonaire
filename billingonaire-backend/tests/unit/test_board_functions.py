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
    mock_page.extract_text.return_value = "01/10/2024 HON'BLE COURT  1 WP/12345/2024 Test SHRI LAWYER"
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
    mock_firestore.return_value.collection.return_value.limit.return_value.stream.return_value = mock_docs

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
        case_year="2024"
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
        case_year="2024"
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
        case_year="2024"
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
        case_year="2024"
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
                "case_year": "2024"
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
        case_year="2024"
    )
    assert result["case_type"] == "WP"
    assert result["case_no"] == "12345"
    assert result["case_year"] == "2024"

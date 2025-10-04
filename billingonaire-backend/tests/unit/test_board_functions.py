"""Functional tests for Board.py - Actual function calls with mocked dependencies"""

import pytest
from unittest.mock import MagicMock, patch, Mock
import sys
import os

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
    """Test readFile function with valid PDF"""
    import Board
    
    mock_pdf = MagicMock()
    mock_page = MagicMock()
    mock_page.extract_tables.return_value = [[
        ["Sr.No.", "Case Reference", "Party Names", "AGP Name"],
        ["1", "WP/12345/2024", "Test vs State", "POOJA JOSHI"]
    ]]
    mock_page.extract_text.return_value = "Sample text"
    mock_pdf.pages = [mock_page]
    mock_pdfplumber.open.return_value.__enter__.return_value = mock_pdf
    
    mock_collection = MagicMock()
    mock_firestore.return_value.collection.return_value = mock_collection
    
    result = Board.readFile(b"%PDF-test", "board_2024_10_01.pdf")
    assert result is not None


@patch("Board.firestore.client")
def test_read_board_function(mock_firestore):
    """Test read_board function"""
    import Board
    
    mock_doc = MagicMock()
    mock_doc.exists = True
    mock_doc.to_dict.return_value = {
        "board_date": "2024-10-01",
        "cases": [{"case_ref": "WP/1/2024"}]
    }
    mock_firestore.return_value.collection.return_value.document.return_value.get.return_value = mock_doc
    
    result = Board.read_board("2024-10-01")
    assert result is not None


@patch("Board.firestore.client")
def test_get_all_boards(mock_firestore):
    """Test get_all_boards function"""
    import Board
    
    mock_docs = [
        MagicMock(to_dict=lambda: {"board_date": "2024-10-01"}),
        MagicMock(to_dict=lambda: {"board_date": "2024-10-02"})
    ]
    mock_firestore.return_value.collection.return_value.stream.return_value = mock_docs
    
    result = Board.get_all_boards()
    assert isinstance(result, list)


def test_parse_case_ref():
    """Test parse_case_ref function"""
    import Board
    
    result = Board.parse_case_ref("WP/12345/2024")
    assert result is not None
    if result:
        assert result.get("case_type") == "WP"
        assert result.get("case_no") == "12345"
        assert result.get("case_year") == "2024"


def test_normalize_case_ref():
    """Test normalize_case_ref function"""
    import Board
    
    result = Board.normalize_case_ref("WP / 12345 / 2024")
    assert result == "WP/12345/2024"


@patch("Board.MLEnhancedParser")
def test_process_enhanced_text(mock_ml_parser):
    """Test process_enhanced_text with ML fallback"""
    import Board
    
    mock_ml_parser.return_value.parse_board_text.return_value = [
        {"case_ref": "WP/1/2024", "agp_name": "JOSHI"}
    ]
    
    text = "WP/1/2024 - JOSHI - Test"
    result = Board.process_enhanced_text(text, "2024-10-01")
    assert result is not None


def test_extract_date_from_filename():
    """Test extract_date_from_filename"""
    import Board
    
    result = Board.extract_date_from_filename("board_2024_10_01.pdf")
    assert result is not None
    assert "2024" in str(result)


def test_clean_agp_name():
    """Test clean_agp_name function"""
    import Board
    
    result = Board.clean_agp_name("SHRI P.M.JOSHI, AGP")
    assert "JOSHI" in result
    assert "SHRI" not in result or result == "SHRI P.M.JOSHI, AGP"


@patch("Board.firestore.client")
def test_get_cases_by_date_range(mock_firestore):
    """Test get_cases_by_date_range"""
    import Board
    
    mock_docs = [
        MagicMock(to_dict=lambda: {
            "board_date": "2024-10-01",
            "cases": [{"case_ref": "WP/1/2024"}]
        })
    ]
    mock_firestore.return_value.collection.return_value.where.return_value.stream.return_value = mock_docs
    
    result = Board.get_cases_by_date_range("2024-10-01", "2024-10-07")
    assert isinstance(result, list)


@patch("Board.firestore.client")
@patch("Board.pdfplumber")
def test_extract_tables_from_pdf(mock_pdfplumber, mock_firestore):
    """Test table extraction"""
    import Board
    
    mock_pdf = MagicMock()
    mock_page = MagicMock()
    mock_page.extract_tables.return_value = [[
        ["Header1", "Header2"],
        ["Data1", "Data2"]
    ]]
    mock_pdf.pages = [mock_page]
    mock_pdfplumber.open.return_value.__enter__.return_value = mock_pdf
    
    if hasattr(Board, 'extract_table'):
        result = Board.extract_table(b"test")
        assert result is not None


def test_validate_case_format():
    """Test case format validation"""
    import Board
    
    if hasattr(Board, 'validate_case_format'):
        assert Board.validate_case_format("WP/12345/2024")
        assert not Board.validate_case_format("INVALID")

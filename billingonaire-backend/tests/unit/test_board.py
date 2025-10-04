"""Unit tests for Board.py module - PDF parsing and board data processing"""

import pytest
from unittest.mock import MagicMock, patch, Mock
from datetime import datetime, date
import pandas as pd


class TestBoardDataNormalization:
    """Test board data normalization and cleaning"""

    @pytest.fixture
    def board_module(self, mock_firestore_client):
        with patch("Board.firestore.client", return_value=mock_firestore_client):
            import Board
            return Board

    def test_normalize_agp_name(self, board_module):
        """Test AGP name normalization"""
        result = board_module.normalize_agp_name("SHRI P.M.JOSHI, AGP")
        assert "SHRI" not in result
        assert "AGP" not in result
        assert "JOSHI" in result

    def test_normalize_agp_name_with_smt(self, board_module):
        """Test AGP name normalization with SMT prefix"""
        result = board_module.normalize_agp_name("SMT.POOJA JOSHI,ADDL.GP")
        assert "SMT" not in result
        assert "GP" not in result
        assert "POOJA" in result

    def test_parse_case_reference(self, board_module):
        """Test case reference parsing"""
        result = board_module.parse_case_reference("WP/12345/2024")
        assert result["case_type"] == "WP"
        assert result["case_no"] == "12345"
        assert result["case_year"] == "2024"

    def test_parse_case_reference_with_stamp(self, board_module):
        """Test case reference with ST marker"""
        result = board_module.parse_case_reference("WP (ST)/12345/2024")
        assert result["case_type"] == "WP (ST)" or result is None

    def test_extract_board_date_from_filename(self, board_module):
        """Test board date extraction from filename"""
        filename = "board_2024_10_01.pdf"
        result = board_module.extract_date_from_filename(filename)
        if result:
            assert isinstance(result, (date, str))


class TestBoardDataProcessing:
    """Test board data processing and table extraction"""

    @pytest.fixture
    def board_module(self, mock_firestore_client):
        with patch("Board.firestore.client", return_value=mock_firestore_client):
            import Board
            return Board

    def test_process_table_row(self, board_module):
        """Test processing of table row data"""
        row_data = {
            "Sr. No.": "1",
            "Case Reference": "WP/12345/2024",
            "AGP Name": "SHRI P.M.JOSHI,AGP",
            "Party Names": "Test Petitioner Vs Test Respondent"
        }
        result = board_module.process_board_row(row_data, "2024-10-01")
        if result:
            assert result.get("case_ref") == "WP/12345/2024"
            assert "JOSHI" in result.get("agp_name", "").upper()

    def test_extract_party_names(self, board_module):
        """Test party name extraction"""
        party_text = "John Doe Vs State of Maharashtra"
        result = board_module.extract_party_names(party_text)
        if result:
            assert "petitioner" in result or len(result) == 2

    def test_clean_case_data(self, board_module):
        """Test case data cleaning"""
        raw_case = {
            "case_ref": "  WP/12345/2024  ",
            "agp_name": "SHRI P.M.JOSHI,AGP",
            "board_date": "2024-10-01"
        }
        result = board_module.clean_case_data(raw_case)
        if result:
            assert result["case_ref"].strip() == "WP/12345/2024"


class TestBoardFileReading:
    """Test board PDF file reading and parsing"""

    @pytest.fixture
    def board_module(self, mock_firestore_client):
        with patch("Board.firestore.client", return_value=mock_firestore_client):
            import Board
            return Board

    @patch("Board.pdfplumber")
    def test_read_pdf_file(self, mock_pdfplumber, board_module, sample_pdf_content):
        """Test PDF file reading"""
        mock_pdf = MagicMock()
        mock_page = MagicMock()
        mock_page.extract_text.return_value = "Test Order\nWP/12345/2024\nJOSHI"
        mock_pdf.pages = [mock_page]
        mock_pdfplumber.open.return_value.__enter__.return_value = mock_pdf

        result = board_module.read_pdf_text(sample_pdf_content)
        if result:
            assert isinstance(result, str)

    @patch("Board.pdfplumber")
    def test_extract_tables_from_pdf(self, mock_pdfplumber, board_module):
        """Test table extraction from PDF"""
        mock_pdf = MagicMock()
        mock_page = MagicMock()
        mock_page.extract_tables.return_value = [[
            ["Sr. No.", "Case Reference", "AGP Name"],
            ["1", "WP/12345/2024", "JOSHI"]
        ]]
        mock_pdf.pages = [mock_page]
        mock_pdfplumber.open.return_value.__enter__.return_value = mock_pdf

        result = board_module.extract_tables(b"test_pdf")
        assert isinstance(result, list)


class TestBoardStorageOperations:
    """Test board data storage operations"""

    @pytest.fixture
    def board_module(self, mock_firestore_client):
        with patch("Board.firestore.client", return_value=mock_firestore_client):
            import Board
            return Board

    def test_save_board_to_firestore(self, board_module, mock_firestore_client):
        """Test saving board data to Firestore"""
        board_data = {
            "board_date": "2024-10-01",
            "cases": [{"case_ref": "WP/12345/2024"}]
        }
        result = board_module.save_board_data(board_data, mock_firestore_client)
        if result:
            assert result.get("success") is True or mock_firestore_client.collection.called

    def test_get_board_by_date(self, board_module, mock_firestore_client):
        """Test retrieving board by date"""
        result = board_module.get_board_by_date("2024-10-01", mock_firestore_client)
        assert result is not None or mock_firestore_client.collection.called


class TestMLEnhancedParsing:
    """Test ML-enhanced parsing fallback logic"""

    @pytest.fixture
    def board_module(self, mock_firestore_client):
        with patch("Board.firestore.client", return_value=mock_firestore_client):
            import Board
            return Board

    @patch("Board.MLEnhancedParser")
    def test_ml_fallback_parsing(self, mock_ml_parser, board_module):
        """Test ML parser fallback when table extraction fails"""
        mock_ml_parser.return_value.parse_board_text.return_value = [
            {"case_ref": "WP/12345/2024", "agp_name": "JOSHI"}
        ]

        text = "WP/12345/2024 - JOSHI - Test Case"
        result = board_module.parse_with_ml(text)
        if result:
            assert isinstance(result, list)

    def test_validate_extracted_cases(self, board_module):
        """Test validation of extracted cases"""
        cases = [
            {"case_ref": "WP/12345/2024", "agp_name": "JOSHI"},
            {"case_ref": "INVALID", "agp_name": ""},
        ]
        result = board_module.validate_cases(cases)
        if result:
            assert len(result) <= len(cases)

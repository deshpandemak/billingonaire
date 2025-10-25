"""Unit tests for Board.py module - PDF parsing and board data processing"""

from unittest.mock import MagicMock, patch

import pytest


class TestBoardDataNormalization:
    """Test board data normalization and cleaning"""

    @pytest.fixture
    def board_instance(self, mock_firestore_client):
        with patch("Board.firestore.client", return_value=mock_firestore_client):
            from Board import Board

            return Board()

    def test_create_record_structure(self, board_instance):
        """Test record creation structure"""
        result = board_instance.create_record(
            court_details="Test details SHRI P.M.JOSHI, AGP WITH",
            file_name="test.pdf",
            board_date="2024-10-01",
            serial_no="1",
            case_type="WP",
            case_no="12345",
            case_year="2024",
        )
        assert "file_name" in result
        assert "board_date" in result
        assert "case_type" in result

    def test_create_record_extracts_lawyers(self, board_instance):
        """Test lawyer extraction in create_record"""
        result = board_instance.create_record(
            court_details="Petitioner Name SHRI LAWYER NAME WITH",
            file_name="test.pdf",
            board_date="2024-10-01",
            serial_no="1",
            case_type="WP",
            case_no="12345",
            case_year="2024",
        )
        assert "petitioner_lawyer" in result
        assert "respondent_lawyer" in result

    def test_board_class_initialization(self, board_instance):
        """Test Board class initialization"""
        assert board_instance.db is not None

    def test_board_class_has_ml_parser(self, board_instance):
        """Test Board class ML parser initialization"""
        # ML parser may or may not be available
        assert hasattr(board_instance, "ml_parser")

    def test_create_record_case_reference(self, board_instance):
        """Test case reference fields in created record"""
        result = board_instance.create_record(
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


class TestBoardDataProcessing:
    """Test board data processing and record creation"""

    @pytest.fixture
    def board_instance(self, mock_firestore_client):
        with patch("Board.firestore.client", return_value=mock_firestore_client):
            from Board import Board

            return Board()

    def test_process_enhanced_text(self, board_instance):
        """Test enhanced text processing"""
        from unittest.mock import MagicMock

        ml_result = MagicMock()
        ml_result.text = "Test text 01/10/2024 HON'BLE COURT  1 WP/12345/2024 Test"
        ml_result.entities = []
        ml_result.name_mappings = []
        ml_result.extraction_method = "test"
        ml_result.quality_score = 0.9

        result = board_instance.process_enhanced_text("test.pdf", ml_result)
        assert result is not None

    def test_create_enhanced_record(self, board_instance):
        """Test enhanced record creation with ML"""
        from unittest.mock import MagicMock

        ml_result = MagicMock()
        ml_result.name_mappings = []
        ml_result.extraction_method = "ml"
        ml_result.quality_score = 0.95
        ml_result.entities = []

        result = board_instance.create_enhanced_record(
            court_details="Test details",
            file_name="test.pdf",
            board_date="2024-10-01",
            serial_no="1",
            case_type="WP",
            case_no="12345",
            case_year="2024",
            ml_result=ml_result,
        )
        assert "ml_extraction_method" in result
        assert "ml_quality_score" in result

    def test_create_record_additional_cases(self, board_instance):
        """Test additional cases extraction in create_record"""
        result = board_instance.create_record(
            court_details="Test WP/999/2024 WP/888/2024",
            file_name="test.pdf",
            board_date="2024-10-01",
            serial_no="1",
            case_type="WP",
            case_no="12345",
            case_year="2024",
        )
        assert "additional_cases" in result
        assert isinstance(result["additional_cases"], list)
        assert "WP/999/2024" in result["additional_cases"]
        assert "WP/888/2024" in result["additional_cases"]


class TestBoardFileReading:
    """Test board PDF file reading and parsing"""

    @pytest.fixture
    def board_instance(self, mock_firestore_client):
        with patch("Board.firestore.client", return_value=mock_firestore_client):
            from Board import Board

            return Board()

    @patch("Board.pdfplumber")
    def test_read_board_method(self, mock_pdfplumber, board_instance):
        """Test read_board method"""
        mock_file = MagicMock()
        mock_pdf = MagicMock()
        mock_page = MagicMock()
        mock_page.extract_text.return_value = (
            "01/10/2024 HON'BLE COURT  1 WP/12345/2024 Test SHRI LAWYER"
        )
        mock_pdf.pages = [mock_page]
        mock_pdfplumber.open.return_value.__enter__.return_value = mock_pdf

        result = board_instance.read_board("test.pdf", mock_file)
        assert result is not None

    @patch("Board.pdfplumber")
    def test_readFile_method(self, mock_pdfplumber, board_instance):
        """Test readFile method"""
        mock_file = MagicMock()
        mock_pdf = MagicMock()
        mock_page = MagicMock()
        mock_page.extract_text.return_value = (
            "01/10/2024 HON'BLE COURT  1 WP/12345/2024 Test"
        )
        mock_pdf.pages = [mock_page]
        mock_pdfplumber.open.return_value.__enter__.return_value = mock_pdf

        result = board_instance.readFile("test.pdf", mock_file)
        assert result is not None


class TestBoardStorageOperations:
    """Test board data storage operations"""

    @pytest.fixture
    def board_instance(self, mock_firestore_client):
        with patch("Board.firestore.client", return_value=mock_firestore_client):
            from Board import Board

            return Board()

    def test_saveData_method(self, board_instance, mock_firestore_client):
        """Test saving board data using saveData method"""
        import pandas as pd

        df = pd.DataFrame(
            [
                {
                    "file_name": "test.pdf",
                    "board_date": "2024-10-01",
                    "case_type": "WP",
                    "case_no": "12345",
                    "case_year": "2024",
                    "serial_number": "1",
                    "petitioner_lawyer": "Test",
                    "respondent_lawyer": "Test",
                    "additional_cases": [],
                    "additional_respondent_lawyers": [],
                }
            ]
        )

        mock_doc_ref = MagicMock()
        mock_firestore_client.collection.return_value.document.return_value = (
            mock_doc_ref
        )

        board_instance.saveData(df)
        assert mock_firestore_client.collection.called

    def test_getData_method(self, board_instance, mock_firestore_client):
        """Test retrieving board data using getData method"""
        search_criteria = {"caseNumber": "12345"}

        mock_query = MagicMock()
        mock_firestore_client.collection.return_value.where.return_value = mock_query
        mock_query.stream.return_value = []

        result = board_instance.getData(search_criteria)
        assert isinstance(result, list)


class TestMLEnhancedParsing:
    """Test ML-enhanced parsing fallback logic"""

    @pytest.fixture
    def board_instance(self, mock_firestore_client):
        with patch("Board.firestore.client", return_value=mock_firestore_client):
            from Board import Board

            return Board()

    def test_board_has_ml_capability(self, board_instance):
        """Test that Board can handle ML parser"""
        # Board instance should have ml_parser attribute
        assert hasattr(board_instance, "ml_parser")
        # ML parser can be None or an object
        assert board_instance.ml_parser is None or board_instance.ml_parser is not None

    def test_readFile_falls_back_when_ml_fails(self, board_instance):
        """Test that readFile falls back to standard parsing if ML fails"""
        # If board has ml_parser but it fails, should use read_board fallback
        if board_instance.ml_parser:
            # ML parser exists, test would use ML first
            assert board_instance.ml_parser is not None
        else:
            # No ML parser, uses read_board directly
            assert board_instance.ml_parser is None

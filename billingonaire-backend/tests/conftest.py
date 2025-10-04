"""Pytest fixtures and configuration for all tests"""

import os
import sys
from typing import Any, Dict
from unittest.mock import MagicMock, Mock

import pytest

# Add parent directory to path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


@pytest.fixture
def mock_firestore_client():
    """Mock Firestore client for testing"""
    mock_client = MagicMock()
    mock_collection = MagicMock()
    mock_document = MagicMock()
    mock_doc_ref = MagicMock()

    # Setup mock chain
    mock_client.collection.return_value = mock_collection
    mock_collection.document.return_value = mock_document
    mock_collection.where.return_value = mock_collection
    mock_collection.limit.return_value = mock_collection
    mock_collection.stream.return_value = []

    # Document operations
    mock_document.get.return_value = mock_doc_ref
    mock_doc_ref.exists = True
    mock_doc_ref.to_dict.return_value = {}

    return mock_client


@pytest.fixture
def sample_case_data() -> Dict[str, Any]:
    """Sample case data for testing"""
    return {
        "id": "test_case_123",
        "case_ref": "WP/12345/2024",
        "case_type": "WP",
        "case_no": "12345",
        "case_year": "2024",
        "board_date": "2024-10-01",
        "agp_name": "Pooja Joshi Deshpande",
        "order_status": "not_linked",
    }


@pytest.fixture
def sample_case_with_order_link(sample_case_data) -> Dict[str, Any]:
    """Sample case data with existing order link"""
    return {
        **sample_case_data,
        "order_status": "order_linked",
        "order_link": "https://example.com/order.pdf",
    }


@pytest.fixture
def sample_pdf_content() -> bytes:
    """Sample PDF content for testing"""
    # Minimal valid PDF structure
    pdf_content = b"""%PDF-1.4
1 0 obj
<< /Type /Catalog /Pages 2 0 R >>
endobj
2 0 obj
<< /Type /Pages /Kids [3 0 R] /Count 1 >>
endobj
3 0 obj
<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>
endobj
4 0 obj
<< /Length 44 >>
stream
BT
/F1 12 Tf
100 700 Td
(Test Order) Tj
ET
endstream
endobj
5 0 obj
<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>
endobj
xref
0 6
0000000000 65535 f
0000000009 00000 n
0000000058 00000 n
0000000115 00000 n
0000000262 00000 n
0000000357 00000 n
trailer
<< /Size 6 /Root 1 0 R >>
startxref
439
%%EOF"""
    return pdf_content


@pytest.fixture
def mock_requests_get(monkeypatch):
    """Mock requests.get for testing external API calls"""

    class MockResponse:
        def __init__(self, content, status_code=200, headers=None):
            self.content = content
            self.status_code = status_code
            self.headers = headers or {"Content-Type": "application/pdf"}

    def mock_get(url, **kwargs):
        # Default to successful PDF response
        return MockResponse(b"%PDF-test-content", 200)

    import requests

    monkeypatch.setattr(requests, "get", mock_get)
    return mock_get


@pytest.fixture
def mock_order_analyzer():
    """Mock OrderDocumentAnalyzer for testing"""
    from dataclasses import dataclass
    from typing import List

    @dataclass
    class MockAnalysisResult:
        order_category: str = "HEARD & ADJOURNED"
        category_confidence: float = 0.95
        order_date: str = "01/10/2024"
        petitioners: List[str] = None
        respondents: List[str] = None
        agp_names: List[str] = None
        tabular_data: Dict = None
        key_phrases: List[str] = None
        next_hearing_date: str = None
        disposal_reason: str = None
        order_text: str = "Test order text"
        cases: List = None

        def __post_init__(self):
            if self.petitioners is None:
                self.petitioners = ["Test Petitioner"]
            if self.respondents is None:
                self.respondents = ["Test Respondent"]
            if self.agp_names is None:
                self.agp_names = ["Pooja Joshi Deshpande"]
            if self.tabular_data is None:
                self.tabular_data = {}
            if self.key_phrases is None:
                self.key_phrases = ["Test phrase"]
            if self.cases is None:
                self.cases = []

    mock_analyzer = MagicMock()
    mock_analyzer.analyze_order_document.return_value = MockAnalysisResult()
    return mock_analyzer


@pytest.fixture(autouse=True)
def setup_test_env(monkeypatch):
    """Setup test environment variables"""
    monkeypatch.setenv("TESTING", "true")
    monkeypatch.setenv("ORDER_MAX_SEQUENCE_RETRIES", "5")  # Reduce for faster tests

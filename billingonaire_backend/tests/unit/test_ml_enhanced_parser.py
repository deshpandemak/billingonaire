import pytest
from billingonaire_backend.ml_enhanced_parser import MLEnhancedParser
from fastapi import HTTPException

def test_parser_initialization():
    parser = MLEnhancedParser()
    assert parser is not None

def test_enhance_pdf_extraction():
    parser = MLEnhancedParser()
    with pytest.raises(HTTPException):
        parser.enhance_pdf_extraction("dummy.pdf", b"PDF content")

def test_extract_entities_regex_empty():
    parser = MLEnhancedParser()
    result = parser._extract_entities_regex('')
    assert isinstance(result, list)
    assert len(result) == 0

def test_normalize_legal_name_empty():
    parser = MLEnhancedParser()
    result = parser._normalize_legal_name('')
    assert result == ''

# Add more tests for _extract_with_pdfplumber, get_enhancement_status, learn_from_correction

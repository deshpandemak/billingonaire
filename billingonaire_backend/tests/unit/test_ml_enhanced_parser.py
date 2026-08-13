import pytest

from billingonaire_backend.ml_enhanced_parser import MLEnhancedParser


def test_parser_initialization():
    parser = MLEnhancedParser()
    assert parser is not None


def test_enhance_pdf_extraction():
    parser = MLEnhancedParser()
    with pytest.raises(ValueError):
        parser.enhance_pdf_extraction("dummy.pdf", b"PDF content")


def test_extract_entities_regex_empty():
    parser = MLEnhancedParser()
    result = parser._extract_entities_regex("")
    assert isinstance(result, list)
    assert len(result) == 0


def test_normalize_legal_name_empty():
    parser = MLEnhancedParser()
    result = parser._normalize_legal_name("")
    assert result == ""


def test_get_enhancement_status_has_no_spacy_or_learning_claims():
    """spaCy NER and the write-only ml_learning_data/ml_corrections
    "learning" path were removed (dead weight: spaCy shipped a ~50MB model
    to produce entity matches that were strictly worse than -- and
    outranked -- the regex path's own matches; the learning collections
    were written to on every parse and never read by anything). The status
    endpoint must not keep claiming either capability exists."""
    parser = MLEnhancedParser()
    status = parser.get_enhancement_status()
    assert "spacy_available" not in status
    assert "spacy_model" not in status
    assert "ner" not in status["capabilities"]
    assert "learning" not in status["capabilities"]


def test_enhance_pdf_extraction_does_not_double_extract(monkeypatch):
    """A second "enhanced preprocessing" pdfplumber pass used to run in
    parallel and always lose a hardcoded-confidence comparison (0.85 vs
    0.95) -- pure wasted work on every single PDF parse. Assert the
    now-removed method is never called."""
    parser = MLEnhancedParser()
    assert not hasattr(parser, "_extract_with_advanced_preprocessing")
    assert not hasattr(parser, "_preprocess_legal_text")

    monkeypatch.setattr(
        parser, "_extract_with_pdfplumber", lambda content: ("Some order text", 0.95)
    )
    result = parser.enhance_pdf_extraction("dummy.pdf", b"irrelevant")
    assert result.extraction_method == "pdfplumber"
    assert result.text == "Some order text"

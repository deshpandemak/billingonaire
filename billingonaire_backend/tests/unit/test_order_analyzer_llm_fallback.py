import sys
import types
from types import SimpleNamespace
from unittest.mock import patch

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

from billingonaire_backend.order_analyzer import (
    CaseInfo,
    OrderAnalysisResult,
    OrderDocumentAnalyzer,
)


def _build_base_result() -> OrderAnalysisResult:
    return OrderAnalysisResult(
        order_category="ADJOURNED",
        category_confidence=0.55,
        order_date=None,
        cases=[],
        order_text="sample text",
        analysis_metadata={
            "llm_fallback_enabled": True,
            "used_llm_fallback": False,
            "fallback_reason": [],
        },
    )


def test_llm_fallback_disabled_keeps_primary_result(monkeypatch):
    with (
        patch("billingonaire_backend.order_analyzer.firestore") as mock_fs,
        patch("billingonaire_backend.order_analyzer.MLEnhancedParser"),
    ):
        analyzer = OrderDocumentAnalyzer()

    analyzer.enable_llm_fallback = False

    result = _build_base_result()
    extraction_result = SimpleNamespace(quality_score=0.40, confidence=0.50)

    updated = analyzer._apply_confidence_gated_fallback(
        result=result,
        extraction_result=extraction_result,
        text="input text",
    )

    assert updated.order_category == "ADJOURNED"
    assert updated.analysis_metadata["used_llm_fallback"] is False
    metrics = analyzer.get_fallback_metrics()
    assert metrics["total_documents"] == 1
    assert metrics["fallback_triggered"] == 0


def test_llm_fallback_triggered_and_applied(monkeypatch):
    with (
        patch("billingonaire_backend.order_analyzer.firestore") as mock_fs,
        patch("billingonaire_backend.order_analyzer.MLEnhancedParser"),
    ):
        analyzer = OrderDocumentAnalyzer()

    analyzer.enable_llm_fallback = True
    analyzer.min_extraction_quality = 0.90
    analyzer.min_category_confidence = 0.90
    analyzer.min_cases_count = 1

    result = _build_base_result()
    extraction_result = SimpleNamespace(quality_score=0.45, confidence=0.60)

    llm_payload = {
        "order_category": "HEARD_AND_ADJOURNED",
        "category_confidence": 0.88,
        "order_date": "2025-04-09",
        "cases": [
            {
                "case_type": "WP",
                "case_number": 3373,
                "case_year": 2025,
                "petitioner": "MOTILAL",
                "respondent": "STATE",
                "government_pleader": ["P.P. KAKADE"],
            }
        ],
    }

    with patch.object(analyzer, "_run_ollama_fallback", return_value=llm_payload):
        updated = analyzer._apply_confidence_gated_fallback(
            result=result,
            extraction_result=extraction_result,
            text="input text",
        )

    assert updated.order_category == "HEARD_AND_ADJOURNED"
    assert updated.order_date == "2025-04-09"
    assert updated.category_confidence == 0.88
    assert len(updated.cases) == 1
    assert isinstance(updated.cases[0], CaseInfo)
    assert updated.analysis_metadata["used_llm_fallback"] is True

    metrics = analyzer.get_fallback_metrics()
    assert metrics["total_documents"] == 1
    assert metrics["fallback_triggered"] == 1
    assert metrics["fallback_succeeded"] == 1

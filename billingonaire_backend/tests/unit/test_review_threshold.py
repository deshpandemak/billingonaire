"""Low-confidence classifications must go to a human, not to a bill.

Nothing in the codebase ever set manual_review_required, so the review queue
was structurally always empty while the classifier's guesses — it returns 0.50
for "no patterns matched, defaulting to ADJOURNED" — were billed as if certain.
"""

import sys
import types
from unittest.mock import MagicMock, Mock, patch

import pytest

if "spacy" not in sys.modules:
    spacy_stub = types.ModuleType("spacy")
    matcher_stub = types.ModuleType("spacy.matcher")

    class Matcher:  # pragma: no cover
        pass

    matcher_stub.Matcher = Matcher
    spacy_stub.matcher = matcher_stub
    sys.modules["spacy"] = spacy_stub
    sys.modules["spacy.matcher"] = matcher_stub

from billingonaire_backend.AutoOrderManager import AutoOrderManager


@pytest.fixture
def manager():
    with patch("billingonaire_backend.AutoOrderManager.firestore"):
        with (
            patch("billingonaire_backend.AutoOrderManager.OrderDocumentAnalyzer"),
            patch("billingonaire_backend.AutoOrderManager.BombayHighCourtScraper"),
            patch("billingonaire_backend.AutoOrderManager.CaseDataStore"),
        ):
            mgr = AutoOrderManager()
    mgr.case_store = MagicMock()
    return mgr


def _run(manager, confidence):
    """Analyse a PDF whose classification lands at the given confidence."""
    analysis_result = Mock()
    analysis_result.order_category = "ADJOURNED"
    analysis_result.category_confidence = confidence
    analysis_result.cases = []
    analysis_result.analysis_metadata = {}
    manager.order_analyzer.analyze_order_document = Mock(return_value=analysis_result)

    return manager._analyze_order_with_api_metadata(
        case_id="board-1",
        case_ref="WP/123/2025",
        pdf_content=b"%PDF-1.4",
        api_order_date="2025-03-01",
        api_petitioner="P",
        api_respondent="R",
        order_link="https://example.test/o.pdf",
        board_date="2025-03-01",
    )


def _final_status(manager):
    """The lifecycle state the analysis settled on."""
    return manager.case_store.transition_lifecycle.call_args_list[-1][0][1]


def test_threshold_matches_the_documented_value():
    assert AutoOrderManager.REVIEW_CONFIDENCE_THRESHOLD == 0.55


def test_confident_classification_is_accepted(manager):
    out = _run(manager, 0.95)
    assert out["success"] is True
    assert _final_status(manager) == "analysed"


def test_low_confidence_goes_to_review_not_to_a_bill(manager):
    out = _run(manager, 0.50)  # the "no patterns matched" fallback score
    assert out["success"] is True
    assert _final_status(manager) == "manual_review_required"


def test_boundary_is_inclusive_of_accept(manager):
    """At exactly the threshold the result is accepted."""
    _run(manager, 0.55)
    assert _final_status(manager) == "analysed"
    manager.case_store.reset_mock()
    _run(manager, 0.54)
    assert _final_status(manager) == "manual_review_required"


def test_review_transition_records_the_confidence_for_the_reviewer(manager):
    _run(manager, 0.40)
    kwargs = manager.case_store.transition_lifecycle.call_args_list[-1][1]
    assert kwargs["event_type"] == "analysis_low_confidence"
    assert kwargs["metadata"]["order_category_confidence"] == 0.40
    assert "confidence" in (kwargs["reason"] or "").lower()


def test_analysis_still_succeeds_so_the_order_is_stored(manager):
    """Review is a flag on an analysed order, not a failure — the extracted
    data must still be saved so the reviewer has something to look at."""
    out = _run(manager, 0.30)
    assert out["success"] is True
    assert out["data"]["order_category"] == "ADJOURNED"
    manager.case_store.append_case_order.assert_called_once()

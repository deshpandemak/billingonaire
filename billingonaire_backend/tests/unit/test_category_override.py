"""A reviewer's correction must reach the bill and leave an audit trail.

The old override wrote a *top-level* `order_category` on the case document with
a raw update(). Billing reads the category from inside the orders[] entry
(calculate_case_fee) and the rest of the app reads the latest_order_category
rollup, so the correction never reached the bill — and because
transition_lifecycle was bypassed, the human decision left no trace.
"""

from unittest.mock import MagicMock, patch

import pytest

from case_data_store import CaseDataStore


@pytest.fixture
def store_and_doc():
    db = MagicMock()
    doc_ref = MagicMock()
    snapshot = MagicMock()
    snapshot.exists = True
    snapshot.to_dict.return_value = {
        "case_ref": "WP/123/2025",
        "orders": [
            {
                "order_link": "https://example.test/o.pdf",
                "order_date": "2025-03-01",
                "board_date": "2025-03-01",
                "order_status": "analysed",
                "order_category": "ADJOURNED",
            }
        ],
        "latest_order_category": "ADJOURNED",
    }
    doc_ref.get.return_value = snapshot
    db.collection.return_value.document.return_value = doc_ref
    store = CaseDataStore(db)
    store.transition_lifecycle = MagicMock(return_value={"success": True})
    return store, doc_ref


def _written(doc_ref):
    """The payload passed to set(..., merge=True)."""
    assert doc_ref.set.called, "override must persist the correction"
    return doc_ref.set.call_args[0][0]


def test_correction_is_written_into_the_orders_entry(store_and_doc):
    """calculate_case_fee reads target_order['order_category'] — the correction
    must land there, not on a top-level field nothing reads."""
    store, doc_ref = store_and_doc
    result = store.apply_category_override("WP/123/2025", "DISPOSED_OFF", "uid-1")

    assert result["success"] is True
    payload = _written(doc_ref)
    assert payload["orders"][0]["order_category"] == "DISPOSED_OFF"


def test_rollup_is_kept_in_step(store_and_doc):
    store, doc_ref = store_and_doc
    store.apply_category_override("WP/123/2025", "DISPOSED_OFF", "uid-1")
    assert _written(doc_ref)["latest_order_category"] == "DISPOSED_OFF"


def test_emits_a_lifecycle_event_for_audit(store_and_doc):
    store, doc_ref = store_and_doc
    store.apply_category_override(
        "WP/123/2025", "DISPOSED_OFF", "uid-1", notes="reviewed"
    )

    store.transition_lifecycle.assert_called_once()
    args, kwargs = store.transition_lifecycle.call_args
    assert args[1] == "analysed"
    assert kwargs["event_type"] == "manual_override"
    assert kwargs["metadata"]["actor_uid"] == "uid-1"
    assert kwargs["metadata"]["previous_category"] == "ADJOURNED"


def test_review_ai_suggestion_is_recorded_alongside_previous_category(store_and_doc):
    """Every reviewed case should carry the full (regex, LLM, human) triple:
    previous_category is the regex's read, review_ai_suggestion is what the
    review screen's "Get AI read" button returned, order_category is the
    human's final call."""
    store, doc_ref = store_and_doc
    suggestion = {
        "category": "DISPOSED_OFF",
        "confidence": 0.85,
        "rationale": "Rule made absolute.",
    }
    store.apply_category_override(
        "WP/123/2025",
        "DISPOSED_OFF",
        "uid-1",
        review_ai_suggestion=suggestion,
    )

    args, kwargs = store.transition_lifecycle.call_args
    assert kwargs["metadata"]["review_ai_suggestion"] == suggestion
    assert kwargs["metadata"]["previous_category"] == "ADJOURNED"


def test_review_ai_suggestion_omitted_when_not_provided(store_and_doc):
    """No 'Get AI read' click -> no review_ai_suggestion key at all, not a
    None placeholder cluttering every override that never used it."""
    store, doc_ref = store_and_doc
    store.apply_category_override("WP/123/2025", "DISPOSED_OFF", "uid-1")

    args, kwargs = store.transition_lifecycle.call_args
    assert "review_ai_suggestion" not in kwargs["metadata"]


def test_returns_the_date_so_daily_boards_can_be_updated(store_and_doc):
    store, _ = store_and_doc
    result = store.apply_category_override("WP/123/2025", "DISPOSED_OFF", "uid-1")
    assert result["order_date"] == "2025-03-01"
    assert result["previous_category"] == "ADJOURNED"


def test_marks_the_entry_as_human_overridden(store_and_doc):
    store, doc_ref = store_and_doc
    store.apply_category_override("WP/123/2025", "DISPOSED_OFF", "uid-9")
    entry = _written(doc_ref)["orders"][0]
    assert entry["order_manual_override"] is True
    assert entry["order_manual_override_by"] == "uid-9"
    assert entry["order_status"] == "analysed"


def test_missing_case_reports_failure_without_writing():
    db = MagicMock()
    doc_ref = MagicMock()
    snapshot = MagicMock()
    snapshot.exists = False
    doc_ref.get.return_value = snapshot
    db.collection.return_value.document.return_value = doc_ref
    store = CaseDataStore(db)

    result = store.apply_category_override("WP/999/2025", "ADJOURNED", "uid-1")
    assert result["success"] is False
    doc_ref.set.assert_not_called()


def test_stays_manual_review_required_when_another_date_is_still_pending():
    """A case can have several hearing dates flagged for review at once
    (see CaseDataStore.add_pending_review_date). Resolving one of them must
    not silently clear the flag for the others -- that is exactly how an
    unrelated low-confidence order used to disappear from the queue before
    a human ever saw it."""
    db = MagicMock()
    doc_ref = MagicMock()
    snapshot = MagicMock()
    snapshot.exists = True
    snapshot.to_dict.return_value = {
        "case_ref": "WP/123/2025",
        "pending_review_order_dates": ["2025-03-01", "2025-06-01"],
        "orders": [
            {
                "order_link": "https://example.test/march.pdf",
                "order_date": "2025-03-01",
                "board_date": "2025-03-01",
                "order_status": "analysed",
                "order_category": "ADJOURNED",
            },
            {
                "order_link": "https://example.test/june.pdf",
                "order_date": "2025-06-01",
                "board_date": "2025-06-01",
                "order_status": "analysed",
                "order_category": "ADJOURNED",
            },
        ],
    }
    doc_ref.get.return_value = snapshot
    db.collection.return_value.document.return_value = doc_ref
    store = CaseDataStore(db)
    store.transition_lifecycle = MagicMock(return_value={"success": True})

    result = store.apply_category_override(
        "WP/123/2025", "DISPOSED_OFF", "uid-1", order_date="2025-03-01"
    )

    assert result["success"] is True
    # Only the March order was corrected -- June is untouched.
    orders = _written(doc_ref)["orders"]
    assert orders[0]["order_category"] == "DISPOSED_OFF"
    assert orders[1]["order_category"] == "ADJOURNED"

    args, kwargs = store.transition_lifecycle.call_args
    assert args[1] == "manual_review_required"


def test_returns_to_analysed_once_the_last_pending_date_is_resolved():
    db = MagicMock()
    doc_ref = MagicMock()
    snapshot = MagicMock()
    snapshot.exists = True
    snapshot.to_dict.return_value = {
        "case_ref": "WP/123/2025",
        "pending_review_order_dates": ["2025-03-01"],
        "orders": [
            {
                "order_link": "https://example.test/march.pdf",
                "order_date": "2025-03-01",
                "board_date": "2025-03-01",
                "order_status": "analysed",
                "order_category": "ADJOURNED",
            }
        ],
    }
    doc_ref.get.return_value = snapshot
    db.collection.return_value.document.return_value = doc_ref
    store = CaseDataStore(db)
    store.transition_lifecycle = MagicMock(return_value={"success": True})

    store.apply_category_override(
        "WP/123/2025", "DISPOSED_OFF", "uid-1", order_date="2025-03-01"
    )

    args, kwargs = store.transition_lifecycle.call_args
    assert args[1] == "analysed"


def test_order_date_targets_the_matching_entry_not_the_last_one_appended():
    """Without order_date, the override used to always land on the most
    recently appended order -- wrong when an OLDER flagged date is the one
    actually being reviewed and a newer, unrelated order has since been
    appended for the same case."""
    db = MagicMock()
    doc_ref = MagicMock()
    snapshot = MagicMock()
    snapshot.exists = True
    snapshot.to_dict.return_value = {
        "case_ref": "WP/123/2025",
        "pending_review_order_dates": ["2025-03-01"],
        "orders": [
            {
                "order_link": "https://example.test/march.pdf",
                "order_date": "2025-03-01",
                "board_date": "2025-03-01",
                "order_status": "analysed",
                "order_category": "ADJOURNED",
            },
            {
                "order_link": "https://example.test/june.pdf",
                "order_date": "2025-06-01",
                "board_date": "2025-06-01",
                "order_status": "analysed",
                "order_category": "HEARD_AND_ADJOURNED",
            },
        ],
    }
    doc_ref.get.return_value = snapshot
    db.collection.return_value.document.return_value = doc_ref
    store = CaseDataStore(db)
    store.transition_lifecycle = MagicMock(return_value={"success": True})

    store.apply_category_override(
        "WP/123/2025", "DISPOSED_OFF", "uid-1", order_date="2025-03-01"
    )

    orders = _written(doc_ref)["orders"]
    assert orders[0]["order_category"] == "DISPOSED_OFF"
    # The June order, never mentioned by order_date, must be untouched.
    assert orders[1]["order_category"] == "HEARD_AND_ADJOURNED"
    assert "order_manual_override" not in orders[1]


def test_case_with_no_orders_still_records_the_decision():
    db = MagicMock()
    doc_ref = MagicMock()
    snapshot = MagicMock()
    snapshot.exists = True
    snapshot.to_dict.return_value = {"case_ref": "WP/5/2025", "orders": []}
    doc_ref.get.return_value = snapshot
    db.collection.return_value.document.return_value = doc_ref
    store = CaseDataStore(db)
    store.transition_lifecycle = MagicMock(return_value={"success": True})

    result = store.apply_category_override("WP/5/2025", "DISPOSED_OFF", "uid-1")
    assert result["success"] is True
    orders = doc_ref.set.call_args[0][0]["orders"]
    assert len(orders) == 1
    assert orders[0]["order_category"] == "DISPOSED_OFF"

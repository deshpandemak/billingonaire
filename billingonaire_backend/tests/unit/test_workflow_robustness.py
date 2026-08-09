"""Tests for workflow robustness improvements.

Covers:
- Auto-queue for analysis when order fetch succeeds but analysis fails
- DEFAULT_MAX_SEQUENCE_RETRIES reduced to 10
- /jobs/retry-failed endpoint logic
"""

import sys
import types
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

# Stub spaCy to avoid import-time crashes in CI environments.
if "spacy" not in sys.modules:
    spacy_stub = types.ModuleType("spacy")
    spacy_matcher_stub = types.ModuleType("spacy.matcher")

    class Matcher:  # pragma: no cover - test import shim only
        pass

    spacy_matcher_stub.Matcher = Matcher
    spacy_stub.matcher = spacy_matcher_stub
    sys.modules["spacy"] = spacy_stub
    sys.modules["spacy.matcher"] = spacy_matcher_stub

import main
from billingonaire_backend.AutoOrderManager import AutoOrderManager
from billingonaire_backend.CourtScraper import BombayHighCourtScraper

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def manager():
    """AutoOrderManager with all heavy dependencies mocked."""
    with (
        patch("billingonaire_backend.AutoOrderManager.firestore") as mock_fs,
        patch("billingonaire_backend.AutoOrderManager.OrderDocumentAnalyzer"),
        patch("billingonaire_backend.AutoOrderManager.BombayHighCourtScraper"),
    ):
        mgr = AutoOrderManager()
        mgr.db = Mock()
        mgr.case_store = Mock()
        mgr.case_store.get_case_details = Mock(return_value={})
        mgr.case_store.build_case_ref = Mock(
            side_effect=lambda ct, cn, cy: f"{ct}/{cn}/{cy}"
        )
        mgr.case_store.transition_lifecycle = Mock()
        mgr.case_store.append_case_order = Mock()
        mgr.case_store.map_legacy_order_status = Mock(return_value=None)
        yield mgr


# ---------------------------------------------------------------------------
# 1.  /jobs/retry-failed — tests via the actual retry_failed_cases handler
# ---------------------------------------------------------------------------


def _make_mock_case(
    case_ref: str,
    order_status: str,
    board_date: str = "2024-01-15",
    order_link: str = None,
) -> dict:
    ct, cn, cy = case_ref.split("/")
    return {
        "id": f"{board_date}-{ct}-{cn}-{cy}",
        "case_ref": case_ref,
        "case_type": ct,
        "case_no": cn,
        "case_year": cy,
        "board_date": board_date,
        "order_status": order_status,
        "order_link": order_link,
    }


def _make_request(body: dict):
    """Return a minimal async mock of a FastAPI Request that yields body as JSON."""
    req = MagicMock()
    req.json = AsyncMock(return_value=body)
    return req


def _make_manager(cases: list):
    """Return a mock AutoOrderManager pre-loaded with the given candidate cases."""
    from datetime import date

    mgr = MagicMock()
    mgr._get_filtered_matters = Mock(return_value=cases)
    mgr.case_store = MagicMock()
    mgr.case_store.transition_lifecycle = Mock()
    # _parse_board_date just needs to return a date (or None) so filtering works
    mgr._parse_board_date = Mock(side_effect=lambda v: date(2024, 1, 15) if v else None)
    return mgr


@pytest.mark.asyncio
async def test_retry_failed_order_failed_goes_to_fetch_queue(monkeypatch):
    """order_failed case is marked fetch_queued for the fetch poll loop."""
    case = _make_mock_case("WP/10/2025", "order_failed")
    mgr = _make_manager([case])

    monkeypatch.setattr(main, "get_auto_order_manager", lambda: mgr)
    wake_fetch = Mock()
    monkeypatch.setattr(main, "_wake_fetch_poll", SimpleNamespace(set=wake_fetch))

    response = await main.retry_failed_cases(
        _make_request({"limit": 200}), current_user=None
    )
    body = response.body
    import json

    data = json.loads(body)

    assert data["fetch_queued"] == 1
    assert data["analysis_queued"] == 0
    assert "WP/10/2025" in data["fetch_queued_refs"]
    wake_fetch.assert_called_once()

    mgr.case_store.transition_lifecycle.assert_called_once_with(
        "WP/10/2025",
        "fetch_queued",
        metadata={"source": "jobs.retry-failed", "case_id": case["id"]},
        event_type="retry_fetch_queued",
    )


@pytest.mark.asyncio
async def test_retry_failed_linked_with_link_goes_to_analysis_queue(monkeypatch):
    """linked case with stored order_link is marked analysis_queued."""
    case = _make_mock_case(
        "WP/50/2025", "linked", order_link="https://example.com/order.pdf"
    )
    mgr = _make_manager([case])

    monkeypatch.setattr(main, "get_auto_order_manager", lambda: mgr)
    wake_analysis = Mock()
    monkeypatch.setattr(main, "_wake_fetch_poll", SimpleNamespace(set=Mock()))
    monkeypatch.setattr(main, "_wake_analysis_poll", SimpleNamespace(set=wake_analysis))

    response = await main.retry_failed_cases(
        _make_request({"limit": 200}), current_user=None
    )
    import json

    data = json.loads(response.body)

    assert data["analysis_queued"] == 1
    assert data["fetch_queued"] == 0
    assert "WP/50/2025" in data["analysis_queued_refs"]
    wake_analysis.assert_called_once()

    mgr.case_store.transition_lifecycle.assert_called_once_with(
        "WP/50/2025",
        "analysis_queued",
        metadata={"source": "jobs.retry-failed", "case_id": case["id"]},
        event_type="retry_analysis_queued",
    )


@pytest.mark.asyncio
async def test_retry_failed_linked_without_link_falls_back_to_fetch_queue(monkeypatch):
    """linked case without a stored order_link falls back to fetch_queued."""
    case = _make_mock_case("WP/60/2025", "linked", order_link=None)
    mgr = _make_manager([case])

    monkeypatch.setattr(main, "get_auto_order_manager", lambda: mgr)
    monkeypatch.setattr(main, "_wake_fetch_poll", SimpleNamespace(set=Mock()))
    monkeypatch.setattr(main, "_wake_analysis_poll", SimpleNamespace(set=Mock()))

    response = await main.retry_failed_cases(
        _make_request({"limit": 200}), current_user=None
    )
    import json

    data = json.loads(response.body)

    assert data["fetch_queued"] == 1
    assert data["analysis_queued"] == 0
    assert "WP/60/2025" in data["fetch_queued_refs"]


@pytest.mark.asyncio
async def test_retry_failed_skips_non_retryable_statuses(monkeypatch):
    """analysed and not_linked cases are skipped; linked and order_failed are retried."""
    cases = [
        _make_mock_case("WP/1/2025", "analysed"),
        _make_mock_case("WP/2/2025", "not_linked"),
        _make_mock_case(
            "WP/3/2025", "linked", order_link="https://example.com/order.pdf"
        ),
        _make_mock_case("WP/4/2025", "order_failed"),
    ]
    mgr = _make_manager(cases)

    monkeypatch.setattr(main, "get_auto_order_manager", lambda: mgr)
    monkeypatch.setattr(main, "_wake_fetch_poll", SimpleNamespace(set=Mock()))
    monkeypatch.setattr(main, "_wake_analysis_poll", SimpleNamespace(set=Mock()))

    response = await main.retry_failed_cases(
        _make_request({"limit": 200}), current_user=None
    )
    import json

    data = json.loads(response.body)

    # WP/3 (linked+link) → analysis; WP/4 (order_failed) → fetch
    assert data["analysis_queued"] == 1
    assert data["fetch_queued"] == 1
    assert "WP/3/2025" in data["analysis_queued_refs"]
    assert "WP/4/2025" in data["fetch_queued_refs"]
    # Skipped statuses not in either queue
    assert "WP/1/2025" not in data["fetch_queued_refs"]
    assert "WP/1/2025" not in data["analysis_queued_refs"]
    assert "WP/2/2025" not in data["fetch_queued_refs"]
    assert "WP/2/2025" not in data["analysis_queued_refs"]


@pytest.mark.asyncio
async def test_retry_failed_analysis_failed_without_link_goes_to_fetch_queue(
    monkeypatch,
):
    """order_analysis_failed without a stored link falls back to fetch_queued."""
    case = _make_mock_case("WP/30/2025", "order_analysis_failed", order_link=None)
    mgr = _make_manager([case])

    monkeypatch.setattr(main, "get_auto_order_manager", lambda: mgr)
    monkeypatch.setattr(main, "_wake_fetch_poll", SimpleNamespace(set=Mock()))
    monkeypatch.setattr(main, "_wake_analysis_poll", SimpleNamespace(set=Mock()))

    response = await main.retry_failed_cases(
        _make_request({"limit": 200}), current_user=None
    )
    import json

    data = json.loads(response.body)

    assert data["fetch_queued"] == 1
    assert data["analysis_queued"] == 0
    assert "WP/30/2025" in data["fetch_queued_refs"]


# ---------------------------------------------------------------------------
# 2.  Enqueue sites that used to write nothing to Firestore at all --
#     work pushed straight into the in-memory queue was silently lost if it
#     landed on a Cloud Run instance that scaled to zero before a worker
#     drained it. They must now durably mark every matched case
#     fetch_queued so any instance's poll loop can pick it up.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_admin_bulk_order_processing_marks_cases_fetch_queued(monkeypatch):
    fake_doc = SimpleNamespace(
        id="2026-01-05-WP-77-2026",
        to_dict=lambda: {
            "case_type": "WP",
            "case_no": "77",
            "case_year": "2026",
            "board_date": "2026-01-05",
        },
    )
    mock_db = MagicMock()
    mock_db.collection.return_value.limit.return_value.stream.return_value = [fake_doc]

    mgr = MagicMock()
    mgr._get_case_order_context = Mock(return_value={"order_status": "not_linked"})
    mgr.case_store = MagicMock()
    mgr.case_store._to_iso_date = Mock(side_effect=lambda v: v)

    monkeypatch.setattr(main, "firestore", SimpleNamespace(client=lambda: mock_db))
    monkeypatch.setattr(main, "get_auto_order_manager", lambda: mgr)
    wake_fetch = Mock()
    monkeypatch.setattr(main, "_wake_fetch_poll", SimpleNamespace(set=wake_fetch))

    response = await main.admin_bulk_order_processing(
        _make_request({"order_statuses": ["not_linked"], "limit": 10}),
        current_user=None,
    )
    import json

    data = json.loads(response.body)

    assert data["success"] is True
    assert data["cases_queued"] == 1
    mgr.case_store.transition_lifecycle.assert_called_once()
    call = mgr.case_store.transition_lifecycle.call_args
    assert call.args[0] == "WP/77/2026"
    assert call.args[1] == "fetch_queued"
    wake_fetch.assert_called_once()


@pytest.mark.asyncio
async def test_scheduled_retry_orders_marks_cases_fetch_queued(monkeypatch):
    fake_doc = SimpleNamespace(
        id="2026-01-05-WP-88-2026",
        to_dict=lambda: {
            "case_type": "WP",
            "case_no": "88",
            "case_year": "2026",
            "board_date": "2026-01-05",
        },
    )
    mock_db = MagicMock()
    mock_query = mock_db.collection.return_value.where.return_value.where.return_value
    mock_query.limit.return_value.get.return_value = [fake_doc]

    mgr = MagicMock()
    mgr._get_case_order_context = Mock(return_value={"order_status": "not_linked"})
    mgr.case_store = MagicMock()
    mgr.case_store._to_iso_date = Mock(side_effect=lambda v: v)

    monkeypatch.setattr(main, "firestore", SimpleNamespace(client=lambda: mock_db))
    monkeypatch.setattr(main, "get_auto_order_manager", lambda: mgr)
    wake_fetch = Mock()
    monkeypatch.setattr(main, "_wake_fetch_poll", SimpleNamespace(set=wake_fetch))

    response = await main.scheduled_retry_orders(
        days_back=7, limit=100, current_user=None
    )
    import json

    data = json.loads(response.body)

    assert data["success"] is True
    assert data["cases_queued"] == 1
    mgr.case_store.transition_lifecycle.assert_called_once()
    call = mgr.case_store.transition_lifecycle.call_args
    assert call.args[0] == "WP/88/2026"
    assert call.args[1] == "fetch_queued"
    wake_fetch.assert_called_once()


# ---------------------------------------------------------------------------
# 3.  GET /queue/detail -- the actual per-case list, not just aggregate
#     counts. This is the concrete fix for "very little transparency".
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_queue_detail_returns_per_case_list_oldest_first(monkeypatch):
    from datetime import datetime, timedelta

    now = datetime.now()
    old_ts = (now - timedelta(minutes=30)).isoformat()
    new_ts = (now - timedelta(minutes=1)).isoformat()

    def make_doc(doc_id, case_ref, updated_at):
        return SimpleNamespace(
            id=doc_id,
            to_dict=lambda: {
                "case_ref": case_ref,
                "latest_board_date": "2026-01-05",
                "lifecycle_status_updated_at": updated_at,
            },
        )

    docs_by_status = {
        "fetch_queued": [make_doc("d1", "WP/1/2026", new_ts)],
        "fetch_in_progress": [make_doc("d2", "WP/2/2026", old_ts)],
        "analysis_queued": [],
        "analysis_in_progress": [],
    }

    def where_side_effect(field, op, value):
        mock_query = MagicMock()
        mock_query.limit.return_value.stream.return_value = docs_by_status.get(
            value, []
        )
        return mock_query

    mock_db = MagicMock()
    mock_db.collection.return_value.where.side_effect = where_side_effect

    monkeypatch.setattr(main, "firestore", SimpleNamespace(client=lambda: mock_db))

    response = await main.get_queue_detail(limit=50, current_user=None)
    import json

    data = json.loads(response.body)

    assert data["total_returned"] == 2
    refs = [c["case_ref"] for c in data["cases"]]
    # Oldest (stuck longest) first
    assert refs[0] == "WP/2/2026"
    assert refs[1] == "WP/1/2026"

    stale_flags = {c["case_ref"]: c["stale"] for c in data["cases"]}
    assert (
        stale_flags["WP/2/2026"] is True
    )  # fetch_in_progress past the staleness window
    assert stale_flags["WP/1/2026"] is False  # fetch_queued is never "stale"


# ---------------------------------------------------------------------------
# 4.  /jobs/analyze-orders scope toggle -- "missing_only" (default) skips
#     cases already analysed or awaiting manual review; "all" re-queues
#     everything with a link regardless of current status.
# ---------------------------------------------------------------------------


def _make_board_row(doc_id, case_no):
    return SimpleNamespace(
        id=doc_id,
        to_dict=lambda: {
            "case_type": "WP",
            "case_no": case_no,
            "case_year": "2026",
            "board_date": "2026-01-05",
        },
    )


def _wire_analyze_orders(monkeypatch, order_statuses_by_ref):
    rows = [
        _make_board_row(f"row-{i}", str(i))
        for i in range(1, len(order_statuses_by_ref) + 1)
    ]
    mock_db = MagicMock()
    mock_db.collection.return_value.limit.return_value.stream.return_value = rows

    mgr = MagicMock()
    mgr.case_store = MagicMock()
    mgr.case_store.build_case_ref = Mock(
        side_effect=lambda ct, cn, cy: f"{ct}/{cn}/{cy}"
    )
    mgr._parse_board_date = Mock(return_value=None)
    mgr._get_case_order_context = Mock(
        side_effect=lambda case_ref: {
            "order_status": order_statuses_by_ref[case_ref],
            "order_link": "https://example.com/order.pdf",
        }
    )

    monkeypatch.setattr(main, "firestore", SimpleNamespace(client=lambda: mock_db))
    monkeypatch.setattr(main, "get_auto_order_manager", lambda: mgr)
    monkeypatch.setattr(main, "_wake_analysis_poll", SimpleNamespace(set=Mock()))
    return mgr


@pytest.mark.asyncio
async def test_analyze_orders_missing_only_skips_analysed_and_review_cases(
    monkeypatch,
):
    order_statuses_by_ref = {
        "WP/1/2026": "linked",
        "WP/2/2026": "analysed",
        "WP/3/2026": "manual_review_required",
    }
    _wire_analyze_orders(monkeypatch, order_statuses_by_ref)

    response = await main.queue_analysis_jobs(
        _make_request({"limit": 10}), current_user=None
    )
    import json

    data = json.loads(response.body)

    assert data["scope"] == "missing_only"
    assert data["queued_case_refs"] == ["WP/1/2026"]
    assert data["skipped"] == 2


@pytest.mark.asyncio
async def test_analyze_orders_scope_all_includes_analysed_cases(monkeypatch):
    order_statuses_by_ref = {
        "WP/1/2026": "linked",
        "WP/2/2026": "analysed",
    }
    _wire_analyze_orders(monkeypatch, order_statuses_by_ref)

    response = await main.queue_analysis_jobs(
        _make_request({"limit": 10, "scope": "all"}), current_user=None
    )
    import json

    data = json.loads(response.body)

    assert data["scope"] == "all"
    assert set(data["queued_case_refs"]) == {"WP/1/2026", "WP/2/2026"}


# ---------------------------------------------------------------------------
# 5.  POST /admin/orders/{doc_id}/ai-suggestion -- the review-copilot
#     endpoint. Offered alongside the regex result, never applied
#     automatically; the queue works fully without GEMINI_API_KEY set.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ai_suggestion_returns_501_without_swallowing_when_unconfigured(
    monkeypatch,
):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    response = await main.admin_ai_review_suggestion("WP-1-2026", current_user=None)
    assert response.status_code == 501
    import json

    assert "GEMINI_API_KEY" in json.loads(response.body)["error"]


@pytest.mark.asyncio
async def test_ai_suggestion_404s_when_case_has_no_order_link(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    mgr = MagicMock()
    mgr._get_case_order_context = Mock(return_value={"order_link": None})
    monkeypatch.setattr(main, "get_auto_order_manager", lambda: mgr)

    response = await main.admin_ai_review_suggestion("WP-1-2026", current_user=None)
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_ai_suggestion_returns_category_confidence_and_rationale(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    mgr = MagicMock()
    mgr._get_case_order_context = Mock(
        return_value={"order_link": "https://example.com/order.pdf"}
    )
    mgr.order_analyzer.analyze_order_document = Mock(
        return_value=SimpleNamespace(order_text="Heard and adjourned text")
    )
    monkeypatch.setattr(main, "get_auto_order_manager", lambda: mgr)
    monkeypatch.setattr(
        main.requests,
        "get",
        Mock(
            return_value=SimpleNamespace(content=b"%PDF-fake", raise_for_status=Mock())
        ),
    )

    import review_copilot

    monkeypatch.setattr(
        review_copilot,
        "call_gemini",
        Mock(
            return_value={
                "category": "HEARD_AND_ADJOURNED",
                "confidence": 0.9,
                "rationale": "Notice was issued to the respondent.",
            }
        ),
    )

    response = await main.admin_ai_review_suggestion("WP-1-2026", current_user=None)
    import json

    data = json.loads(response.body)
    assert data["case_ref"] == "WP/1/2026"
    assert data["category"] == "HEARD_AND_ADJOURNED"
    assert data["confidence"] == 0.9
    assert "Notice was issued" in data["rationale"]


@pytest.mark.asyncio
async def test_ai_suggestion_returns_502_when_gemini_call_fails(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    mgr = MagicMock()
    mgr._get_case_order_context = Mock(
        return_value={"order_link": "https://example.com/order.pdf"}
    )
    mgr.order_analyzer.analyze_order_document = Mock(
        return_value=SimpleNamespace(order_text="Some order text")
    )
    monkeypatch.setattr(main, "get_auto_order_manager", lambda: mgr)
    monkeypatch.setattr(
        main.requests,
        "get",
        Mock(
            return_value=SimpleNamespace(content=b"%PDF-fake", raise_for_status=Mock())
        ),
    )

    import review_copilot

    monkeypatch.setattr(
        review_copilot,
        "call_gemini",
        Mock(side_effect=review_copilot.ReviewCopilotError("boom")),
    )

    response = await main.admin_ai_review_suggestion("WP-1-2026", current_user=None)
    assert response.status_code == 502


# ---------------------------------------------------------------------------
# 6.  GET /admin/queue-health -- diagnosis (systemic failure patterns,
#     flapping cases), not just the stuck-count badge /queue/status shows.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_queue_health_flags_a_systemic_pattern_across_failed_cases(monkeypatch):
    def make_doc(case_ref, reason):
        return SimpleNamespace(
            id=case_ref.replace("/", "-"),
            to_dict=lambda: {
                "case_ref": case_ref,
                "lifecycle_status_reason": reason,
                "lifecycle_events": [{"event_type": "x"}],
            },
        )

    docs_by_status = {
        "fetch_failed_retryable": [
            make_doc("WP/1/2026", "Read timed out after 30s"),
            make_doc("WP/2/2026", "Read timed out after 30s"),
            make_doc("WP/3/2026", "Read timed out after 30s"),
        ],
        "fetch_failed_terminal": [],
        "analysis_failed_retryable": [],
        "analysis_failed_terminal": [],
    }

    def where_side_effect(field, op, value):
        mock_query = MagicMock()
        mock_query.limit.return_value.stream.return_value = docs_by_status.get(
            value, []
        )
        return mock_query

    mock_db = MagicMock()
    mock_db.collection.return_value.where.side_effect = where_side_effect
    monkeypatch.setattr(main, "firestore", SimpleNamespace(client=lambda: mock_db))

    response = await main.get_queue_health(current_user=None)
    import json

    data = json.loads(response.body)

    assert data["total_failed"] == 3
    assert data["failed_count_by_status"]["fetch_failed_retryable"] == 3
    assert data["signature_groups"][0]["systemic"] is True
    assert any("systemic" in line for line in data["summary_lines"])


# ---------------------------------------------------------------------------
# 7.  /user-matters/pending-confirmations -- roadmap #9, "ask, don't
#     silently threshold" on ambiguous AGP name matches.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pending_confirmations_only_returns_current_users_own(monkeypatch):
    mine = SimpleNamespace(
        id="conf-1",
        to_dict=lambda: {
            "user_id": "user-1",
            "case_ref": "WP/1/2026",
            "status": "pending",
        },
    )

    def where_side_effect(field, op, value):
        mock_query = MagicMock()
        if field == "user_id":
            mock_query.where.return_value.stream.return_value = (
                [mine] if value == "user-1" else []
            )
        return mock_query

    mock_db = MagicMock()
    mock_db.collection.return_value.where.side_effect = where_side_effect
    monkeypatch.setattr(main, "firestore", SimpleNamespace(client=lambda: mock_db))

    response = await main.get_pending_matter_confirmations(
        current_user={"uid": "user-1"}
    )
    import json

    data = json.loads(response.body)
    assert data["total"] == 1
    assert data["pending"][0]["case_ref"] == "WP/1/2026"


@pytest.mark.asyncio
async def test_confirm_pending_matter_creates_mapping_and_marks_confirmed(
    monkeypatch,
):
    pending_doc = SimpleNamespace(
        exists=True,
        to_dict=lambda: {
            "user_id": "user-1",
            "case_id": "board-doc-1",
            "case_ref": "WP/1/2026",
            "match_source": "board_data",
            "match_field": "respondent_lawyer",
            "matched_text": "P. Deshpande",
            "confidence_score": 0.42,
            "role_type": "AGP",
            "board_date": "2026-01-15",
        },
    )
    mock_doc_ref = MagicMock()
    mock_doc_ref.get.return_value = pending_doc
    mock_mapping_ref = MagicMock()

    def collection_side_effect(name):
        col = MagicMock()
        if name == "user-matter-pending-confirmations":
            col.document.return_value = mock_doc_ref
        elif name == "user-case-mappings":
            col.document.return_value = mock_mapping_ref
        return col

    mock_db = MagicMock()
    mock_db.collection.side_effect = collection_side_effect
    monkeypatch.setattr(
        main,
        "firestore",
        SimpleNamespace(client=lambda: mock_db, SERVER_TIMESTAMP="ts"),
    )

    response = await main.confirm_pending_matter(
        "conf-1", current_user={"uid": "user-1"}
    )
    import json

    data = json.loads(response.body)
    assert data["success"] is True

    mapping_call = mock_mapping_ref.set.call_args
    assert mapping_call.args[0]["confirmed_by_user"] is True
    assert mapping_call.args[0]["case_ref"] == "WP/1/2026"

    status_call = mock_doc_ref.set.call_args
    assert status_call.args[0]["status"] == "confirmed"


@pytest.mark.asyncio
async def test_reject_pending_matter_marks_rejected_without_creating_a_mapping(
    monkeypatch,
):
    pending_doc = SimpleNamespace(
        exists=True,
        to_dict=lambda: {"user_id": "user-1", "case_id": "board-doc-1"},
    )
    mock_doc_ref = MagicMock()
    mock_doc_ref.get.return_value = pending_doc
    mock_mapping_ref = MagicMock()

    def collection_side_effect(name):
        col = MagicMock()
        if name == "user-matter-pending-confirmations":
            col.document.return_value = mock_doc_ref
        elif name == "user-case-mappings":
            col.document.return_value = mock_mapping_ref
        return col

    mock_db = MagicMock()
    mock_db.collection.side_effect = collection_side_effect
    monkeypatch.setattr(
        main,
        "firestore",
        SimpleNamespace(client=lambda: mock_db, SERVER_TIMESTAMP="ts"),
    )

    response = await main.reject_pending_matter(
        "conf-1", current_user={"uid": "user-1"}
    )
    import json

    assert json.loads(response.body)["success"] is True
    mock_doc_ref.set.assert_called_once()
    assert mock_doc_ref.set.call_args.args[0]["status"] == "rejected"
    mock_mapping_ref.set.assert_not_called()


@pytest.mark.asyncio
async def test_confirm_pending_matter_404s_when_confirmation_does_not_exist(
    monkeypatch,
):
    missing_doc = SimpleNamespace(exists=False, to_dict=lambda: {})
    mock_doc_ref = MagicMock()
    mock_doc_ref.get.return_value = missing_doc
    mock_db = MagicMock()
    mock_db.collection.return_value.document.return_value = mock_doc_ref
    monkeypatch.setattr(main, "firestore", SimpleNamespace(client=lambda: mock_db))

    response = await main.confirm_pending_matter(
        "does-not-exist", current_user={"uid": "user-1"}
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_confirm_pending_matter_404s_not_403s_for_someone_elses_confirmation(
    monkeypatch,
):
    """A user must not be able to confirm/reject another user's pending
    match, and the failure must look identical to "not found" -- a 403
    would leak that the confirmation_id exists at all."""
    someone_elses_doc = SimpleNamespace(
        exists=True, to_dict=lambda: {"user_id": "someone-else", "case_id": "x"}
    )
    mock_doc_ref = MagicMock()
    mock_doc_ref.get.return_value = someone_elses_doc
    mock_db = MagicMock()
    mock_db.collection.return_value.document.return_value = mock_doc_ref
    monkeypatch.setattr(main, "firestore", SimpleNamespace(client=lambda: mock_db))

    response = await main.confirm_pending_matter(
        "conf-1", current_user={"uid": "user-1"}
    )
    assert response.status_code == 404
    mock_doc_ref.set.assert_not_called()


@pytest.mark.asyncio
async def test_auto_map_case_to_users_writes_near_misses_as_pending(monkeypatch):
    """Integration of roadmap #9 into the real auto-mapping path: a near-miss
    match must be written to user-matter-pending-confirmations, and the
    UserRole built for matching must default to 0.50 (not the stale 0.75
    this call site had drifted to) when a user has no explicit threshold
    stored."""
    user_doc = SimpleNamespace(
        id="user-1",
        to_dict=lambda: {"role_type": "AGP", "full_name": "Pooja Deshpande"},
    )
    mock_users_collection = MagicMock()
    mock_users_collection.stream.return_value = [user_doc]

    near_miss = SimpleNamespace(
        match_source="board_data",
        match_field="respondent_lawyer",
        matched_text="P. Deshpande",
        confidence_score=0.42,
        role_type="AGP",
        board_date="2026-01-15",
    )
    mock_matcher = MagicMock()
    mock_matcher.find_user_matters_for_case.return_value = []
    mock_matcher.find_near_miss_matters_for_case.return_value = [near_miss]
    monkeypatch.setattr(main, "get_user_matter_matcher", lambda: mock_matcher)

    mock_pending_doc_ref = MagicMock()

    def collection_side_effect(name):
        col = MagicMock()
        if name == "user-roles":
            col.stream.return_value = [user_doc]
        elif name == "user-matter-pending-confirmations":
            col.document.return_value = mock_pending_doc_ref
        return col

    mock_db = MagicMock()
    mock_db.collection.side_effect = collection_side_effect
    monkeypatch.setattr(
        main,
        "firestore",
        SimpleNamespace(client=lambda: mock_db, SERVER_TIMESTAMP="ts"),
    )

    await main.auto_map_case_to_users("board-doc-1", {"case_ref": "WP/1/2026"})

    # UserRole built with no explicit confidence_threshold in user_data must
    # default to 0.50, matching UserMatterMatcher's own canonical default.
    call_args = mock_matcher.find_user_matters_for_case.call_args
    user_role_arg = call_args.args[1]
    assert user_role_arg.confidence_threshold == 0.50

    pending_write = mock_pending_doc_ref.set.call_args.args[0]
    assert pending_write["status"] == "pending"
    assert pending_write["matched_text"] == "P. Deshpande"
    assert pending_write["case_ref"] == "WP/1/2026"


# ---------------------------------------------------------------------------
# 7b. _resolve_board_doc_id / poll-loop auto-mapping -- the poll loops key
#     candidates off case-details ("TYPE-NO-YEAR"), but auto_map_case_to_users
#     (and everything it writes -- user-case-mappings, pending-confirmations,
#     and the bill-generation read path) expects a daily-boards doc id
#     ("YYYY-MM-DD-TYPE-NO-YEAR"). Passing the case-details id straight
#     through made UserMatterMatcher's daily-boards lookup miss every time,
#     silently: no mapping was ever written for any case processed by the
#     poll loops.
# ---------------------------------------------------------------------------


class TestResolveBoardDocId:
    def test_picks_the_entry_matching_the_current_board_date(self):
        case_info = {
            "board_date": "2026-01-15",
            "board_assignment_ids": [
                "2026-01-01-WP-123-2026",
                "2026-01-15-WP-123-2026",
            ],
        }
        assert main._resolve_board_doc_id(case_info) == "2026-01-15-WP-123-2026"

    def test_falls_back_to_the_most_recent_id_when_no_date_matches(self):
        case_info = {
            "board_date": "2026-02-01",
            "board_assignment_ids": [
                "2026-01-01-WP-123-2026",
                "2026-01-15-WP-123-2026",
            ],
        }
        assert main._resolve_board_doc_id(case_info) == "2026-01-15-WP-123-2026"

    def test_falls_back_to_the_most_recent_id_when_board_date_missing(self):
        case_info = {"board_assignment_ids": ["a", "b", "c"]}
        assert main._resolve_board_doc_id(case_info) == "c"

    def test_returns_none_when_there_are_no_board_assignment_ids(self):
        assert main._resolve_board_doc_id({"board_date": "2026-01-15"}) is None
        assert (
            main._resolve_board_doc_id(
                {"board_date": "2026-01-15", "board_assignment_ids": []}
            )
            is None
        )


@pytest.mark.asyncio
async def test_process_claimed_fetch_case_maps_users_with_the_resolved_board_doc_id(
    monkeypatch,
):
    monkeypatch.setattr(
        main, "_run_fetch_case", lambda case_info: {"analysis_success": True}
    )
    captured = {}

    async def fake_auto_map(case_id, case_info):
        captured["case_id"] = case_id

    monkeypatch.setattr(main, "auto_map_case_to_users", fake_auto_map)

    case_info = {
        "id": "WP-123-2026",
        "case_ref": "WP/123/2026",
        "board_date": "2026-01-15",
        "board_assignment_ids": ["2026-01-01-WP-123-2026", "2026-01-15-WP-123-2026"],
    }
    await main._process_claimed_fetch_case(case_info)

    # Must be the real daily-boards id, never the case-details id
    # (case_info["id"]) that UserMatterMatcher can't look up.
    assert captured["case_id"] == "2026-01-15-WP-123-2026"


@pytest.mark.asyncio
async def test_process_claimed_fetch_case_skips_mapping_without_board_assignment_ids(
    monkeypatch,
):
    monkeypatch.setattr(
        main, "_run_fetch_case", lambda case_info: {"analysis_success": True}
    )
    mock_auto_map = AsyncMock()
    monkeypatch.setattr(main, "auto_map_case_to_users", mock_auto_map)

    case_info = {
        "id": "WP-123-2026",
        "case_ref": "WP/123/2026",
        "board_date": "2026-01-15",
        "board_assignment_ids": [],
    }
    await main._process_claimed_fetch_case(case_info)

    mock_auto_map.assert_not_called()


@pytest.mark.asyncio
async def test_process_claimed_analysis_case_maps_users_with_the_resolved_board_doc_id(
    monkeypatch,
):
    monkeypatch.setattr(
        main, "_run_case_analysis_job", lambda case_info: {"analysis_success": True}
    )
    captured = {}

    async def fake_auto_map(case_id, case_info):
        captured["case_id"] = case_id

    monkeypatch.setattr(main, "auto_map_case_to_users", fake_auto_map)

    case_info = {
        "id": "WP-123-2026",
        "case_ref": "WP/123/2026",
        "board_date": "2026-01-15",
        "board_assignment_ids": ["2026-01-01-WP-123-2026", "2026-01-15-WP-123-2026"],
    }
    await main._process_claimed_analysis_case(case_info)

    assert captured["case_id"] == "2026-01-15-WP-123-2026"


# ---------------------------------------------------------------------------
# 7c. GET /admin/order-status-overview -- the Pipeline tab's top card spun
#     forever because this endpoint streamed every daily-boards row and did
#     one extra synchronous case-details read per row (N+1), all blocking
#     I/O with no await -- on a production-sized collection this could tie
#     up the single event loop thread for minutes, stalling every other
#     request (including the poll loops) on top of the request that asked
#     for it. Replaced with cheap .count() aggregations.
# ---------------------------------------------------------------------------


def _count_result(n):
    """Shape of a Firestore .count().get() aggregation response: a
    list-of-lists of results, each with a .value attribute."""
    return [[SimpleNamespace(value=n)]]


@pytest.mark.asyncio
async def test_order_status_overview_uses_count_aggregations_not_a_full_scan(
    monkeypatch,
):
    counts_by_status = {
        "linked": 2,
        "analysed": 5,
        "order_failed": 1,
        "order_analysis_failed": 1,
    }

    mock_collection = MagicMock()
    mock_collection.count.return_value.get.return_value = _count_result(10)
    mock_collection.stream.side_effect = AssertionError(
        "must not stream the full collection -- that's the N+1 bug being fixed"
    )

    def where_side_effect(field, op, value):
        assert field == "latest_order_status"
        assert op == "=="
        where_mock = MagicMock()
        where_mock.count.return_value.get.return_value = _count_result(
            counts_by_status.get(value, 0)
        )
        return where_mock

    mock_collection.where.side_effect = where_side_effect

    mock_db = MagicMock()
    mock_db.collection.return_value = mock_collection
    monkeypatch.setattr(main, "firestore", SimpleNamespace(client=lambda: mock_db))

    response = await main.get_order_status_overview(current_user={"uid": "admin-1"})

    import json

    data = json.loads(response.body)
    assert data["success"] is True
    assert data["total_cases"] == 10
    assert data["status_counts"] == {
        "not_linked": 1,  # 10 - 2 - 5 - 1 - 1
        "linked": 2,
        "analysed": 5,
        "order_failed": 1,
        "order_analysis_failed": 1,
    }
    assert data["pending_processing"] == 2  # not_linked(1) + order_failed(1)


@pytest.mark.asyncio
async def test_order_status_overview_never_goes_negative_on_uncounted_statuses(
    monkeypatch,
):
    """If the explicit buckets somehow summed to more than total_cases (e.g.
    a status value outside the known set), not_linked must clamp at 0
    rather than go negative and produce a nonsensical percentage."""
    mock_collection = MagicMock()
    mock_collection.count.return_value.get.return_value = _count_result(2)

    def where_side_effect(field, op, value):
        where_mock = MagicMock()
        where_mock.count.return_value.get.return_value = _count_result(5)
        return where_mock

    mock_collection.where.side_effect = where_side_effect
    mock_db = MagicMock()
    mock_db.collection.return_value = mock_collection
    monkeypatch.setattr(main, "firestore", SimpleNamespace(client=lambda: mock_db))

    response = await main.get_order_status_overview(current_user={"uid": "admin-1"})

    import json

    data = json.loads(response.body)
    assert data["status_counts"]["not_linked"] == 0


# ---------------------------------------------------------------------------
# 8.  POST /admin/portal-health-check -- roadmap #3, diagnosing court-portal
#     drift from the dual-provider attempt matrix instead of a bare error.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_portal_health_check_flags_drift_when_both_providers_find_nothing(
    monkeypatch,
):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    mock_scraper = MagicMock()
    mock_scraper._probe_provider_matrix.return_value = [
        {
            "provider": "http",
            "orders_found": 0,
            "provider_attempts": [{"step": "http", "status": "no_orders_in_html"}],
        },
        {
            "provider": "playwright",
            "orders_found": 0,
            "provider_attempts": [{"step": "playwright", "status": "no_orders_found"}],
        },
    ]
    monkeypatch.setattr(main, "get_court_scraper", lambda: mock_scraper)

    response = await main.portal_health_check(
        _make_request(
            {"case_ref": "WP/1/2026", "date": "2026-01-15", "expected_min_orders": 1}
        ),
        current_user=None,
    )
    import json

    data = json.loads(response.body)

    assert data["likely_drift"] is True
    assert data["case_ref"] == "WP/1/2026"
    assert "llm_diagnosis" not in data  # no GEMINI_API_KEY configured


@pytest.mark.asyncio
async def test_portal_health_check_400s_without_a_case_ref(monkeypatch):
    response = await main.portal_health_check(_make_request({}), current_user=None)
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_portal_health_check_adds_llm_diagnosis_only_when_drift_detected(
    monkeypatch,
):
    """Cost control: the LLM must not be called for the common, unremarkable
    case where at least one provider found orders."""
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    mock_scraper = MagicMock()
    mock_scraper._probe_provider_matrix.return_value = [
        {"provider": "http", "orders_found": 0, "provider_attempts": []},
        {"provider": "playwright", "orders_found": 2, "provider_attempts": []},
    ]
    monkeypatch.setattr(main, "get_court_scraper", lambda: mock_scraper)

    with patch("portal_health.call_llm_for_diagnosis") as mock_llm:
        response = await main.portal_health_check(
            _make_request({"case_ref": "WP/1/2026"}), current_user=None
        )
    import json

    data = json.loads(response.body)
    assert data["likely_drift"] is False
    mock_llm.assert_not_called()


# ---------------------------------------------------------------------------
# 9.  POST /bills/qa-check -- roadmap #5, a second pair of eyes before a
#     bill (the one artifact that leaves the building) is saved.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bill_qa_check_flags_fee_mismatch(monkeypatch):
    mock_db = MagicMock()
    mock_db.collection.return_value.where.return_value.stream.return_value = []
    monkeypatch.setattr(main, "firestore", SimpleNamespace(client=lambda: mock_db))

    response = await main.bill_qa_check(
        _make_request(
            {
                "bill_entries": [
                    {
                        "case_detail": "WP/1/2026",
                        "date": "2026-01-15",
                        "results": "ADJOURNED",
                        "fees_rs": 1875,
                    }
                ]
            }
        ),
        current_user={"uid": "user-1"},
    )
    import json

    data = json.loads(response.body)
    assert data["ok"] is False
    assert len(data["fee_mismatches"]) == 1


@pytest.mark.asyncio
async def test_bill_qa_check_flags_case_billed_in_a_prior_saved_bill(monkeypatch):
    prior_bill_doc = SimpleNamespace(
        to_dict=lambda: {
            "user_id": "user-1",
            "entries": [{"case_detail": "WP/1/2026", "date": "2026-01-15"}],
        }
    )
    mock_db = MagicMock()
    mock_db.collection.return_value.where.return_value.stream.return_value = [
        prior_bill_doc
    ]
    monkeypatch.setattr(main, "firestore", SimpleNamespace(client=lambda: mock_db))

    response = await main.bill_qa_check(
        _make_request(
            {
                "bill_entries": [
                    {
                        "case_detail": "WP/1/2026",
                        "date": "2026-01-15",
                        "results": "ADJOURNED",
                        "fees_rs": 1250,
                    }
                ]
            }
        ),
        current_user={"uid": "user-1"},
    )
    import json

    data = json.loads(response.body)
    assert data["ok"] is False
    assert len(data["duplicates_across_bills"]) == 1


@pytest.mark.asyncio
async def test_bill_qa_check_ok_for_a_clean_bill(monkeypatch):
    mock_db = MagicMock()
    mock_db.collection.return_value.where.return_value.stream.return_value = []
    monkeypatch.setattr(main, "firestore", SimpleNamespace(client=lambda: mock_db))

    response = await main.bill_qa_check(
        _make_request(
            {
                "bill_entries": [
                    {
                        "case_detail": "WP/1/2026",
                        "date": "2026-01-15",
                        "results": "WP DISPOSED OF",
                        "fees_rs": 2500,
                        "order_category_confidence": 0.95,
                    }
                ]
            }
        ),
        current_user={"uid": "user-1"},
    )
    import json

    data = json.loads(response.body)
    assert data["ok"] is True
    assert data["summary_lines"] == ["No issues found."]

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

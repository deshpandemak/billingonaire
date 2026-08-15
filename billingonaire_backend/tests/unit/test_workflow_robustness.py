"""Tests for workflow robustness improvements.

Covers:
- Auto-queue for analysis when order fetch succeeds but analysis fails
- DEFAULT_MAX_SEQUENCE_RETRIES reduced to 10
- /jobs/retry-failed endpoint logic
"""

import sys
import types
from datetime import datetime
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
from billingonaire_backend.case_data_store import CaseDataStore
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
#
#     Was previously drawn from AutoOrderManager._get_filtered_matters, an
#     unfiltered daily-boards scan (no orderBy -> Firestore defaults to
#     document-ID order -> date-prefixed ids -> deterministically the OLDEST
#     slice of the entire collection, every call, regardless of where the
#     actually-stuck cases currently were). Now queries case-details by
#     lifecycle_status directly -- the same STUCK_LIFECYCLE_STATUSES
#     /queue/status's needs_attention_count counts, so the "N cases could
#     not be completed automatically" banner and the button meant to clear
#     it target the same population.
# ---------------------------------------------------------------------------


def _stuck_case_doc(case_ref, board_date="2024-01-15", order_link=None):
    doc = MagicMock()
    doc.id = f"{board_date}-{case_ref.replace('/', '-')}"
    doc.to_dict.return_value = {
        "case_ref": case_ref,
        "latest_board_date": board_date,
        "latest_order_link": order_link,
    }
    return doc


def _wire_stuck_query(monkeypatch, docs_by_status):
    """docs_by_status: {lifecycle_status: [doc, ...]}. Mocks
    db.collection("case-details").where("lifecycle_status", "==", status)
    per status, matching _query_stuck_candidates' one-query-per-status loop."""
    mock_db = MagicMock()

    def where_side_effect(field, op, value):
        assert field == "lifecycle_status"
        assert op == "=="
        where_mock = MagicMock()
        where_mock.limit.return_value.stream.return_value = docs_by_status.get(
            value, []
        )
        return where_mock

    mock_db.collection.return_value.where.side_effect = where_side_effect
    monkeypatch.setattr(main, "firestore", SimpleNamespace(client=lambda: mock_db))
    return mock_db


def _mock_manager_for_retry():
    mgr = MagicMock()
    mgr.case_store._to_iso_date = Mock(side_effect=lambda v: v)
    mgr.case_store.transition_lifecycle = Mock()
    return mgr


@pytest.mark.asyncio
async def test_retry_failed_fetch_failed_retryable_goes_to_fetch_queue(monkeypatch):
    _wire_stuck_query(
        monkeypatch, {"fetch_failed_retryable": [_stuck_case_doc("WP/10/2025")]}
    )
    mgr = _mock_manager_for_retry()
    monkeypatch.setattr(main, "get_auto_order_manager", lambda: mgr)
    wake_fetch = Mock()
    monkeypatch.setattr(main, "_wake_fetch_poll", SimpleNamespace(set=wake_fetch))
    monkeypatch.setattr(main, "_wake_analysis_poll", SimpleNamespace(set=Mock()))

    response = await main.retry_failed_cases(
        _make_request({"limit": 200}), current_user=None
    )
    import json

    data = json.loads(response.body)

    assert data["fetch_queued"] == 1
    assert data["analysis_queued"] == 0
    assert "WP/10/2025" in data["fetch_queued_refs"]
    wake_fetch.assert_called_once()
    mgr.case_store.transition_lifecycle.assert_called_once_with(
        "WP/10/2025",
        "fetch_queued",
        metadata={
            "source": "jobs.retry-failed",
            "case_id": "2024-01-15-WP-10-2025",
        },
        event_type="retry_fetch_queued",
    )


@pytest.mark.asyncio
async def test_retry_failed_fetch_failed_terminal_also_goes_to_fetch_queue(
    monkeypatch,
):
    """Terminal, not just retryable, failures must still be retriable by
    this button -- it's the only thing that ever moves either state."""
    _wire_stuck_query(
        monkeypatch, {"fetch_failed_terminal": [_stuck_case_doc("WP/11/2025")]}
    )
    mgr = _mock_manager_for_retry()
    monkeypatch.setattr(main, "get_auto_order_manager", lambda: mgr)
    monkeypatch.setattr(main, "_wake_fetch_poll", SimpleNamespace(set=Mock()))
    monkeypatch.setattr(main, "_wake_analysis_poll", SimpleNamespace(set=Mock()))

    response = await main.retry_failed_cases(
        _make_request({"limit": 200}), current_user=None
    )
    import json

    data = json.loads(response.body)
    assert data["fetch_queued"] == 1
    assert "WP/11/2025" in data["fetch_queued_refs"]


@pytest.mark.asyncio
async def test_retry_failed_analysis_failed_with_link_goes_to_analysis_queue(
    monkeypatch,
):
    """analysis_failed_retryable with a stored order link is re-analysed,
    not re-downloaded."""
    _wire_stuck_query(
        monkeypatch,
        {
            "analysis_failed_retryable": [
                _stuck_case_doc(
                    "WP/50/2025", order_link="https://example.com/order.pdf"
                )
            ]
        },
    )
    mgr = _mock_manager_for_retry()
    monkeypatch.setattr(main, "get_auto_order_manager", lambda: mgr)
    monkeypatch.setattr(main, "_wake_fetch_poll", SimpleNamespace(set=Mock()))
    wake_analysis = Mock()
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
        metadata={
            "source": "jobs.retry-failed",
            "case_id": "2024-01-15-WP-50-2025",
        },
        event_type="retry_analysis_queued",
    )


@pytest.mark.asyncio
async def test_retry_failed_analysis_failed_without_link_falls_back_to_fetch_queue(
    monkeypatch,
):
    _wire_stuck_query(
        monkeypatch,
        {"analysis_failed_terminal": [_stuck_case_doc("WP/30/2025", order_link=None)]},
    )
    mgr = _mock_manager_for_retry()
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


@pytest.mark.asyncio
async def test_retry_failed_covers_every_stuck_status_in_one_call(monkeypatch):
    """All four STUCK_LIFECYCLE_STATUSES must be candidates in a single
    call -- not just the first one queried."""
    _wire_stuck_query(
        monkeypatch,
        {
            "fetch_failed_retryable": [_stuck_case_doc("WP/1/2025")],
            "fetch_failed_terminal": [_stuck_case_doc("WP/2/2025")],
            "analysis_failed_retryable": [
                _stuck_case_doc("WP/3/2025", order_link="https://x/o.pdf")
            ],
            "analysis_failed_terminal": [
                _stuck_case_doc("WP/4/2025", order_link="https://x/o.pdf")
            ],
        },
    )
    mgr = _mock_manager_for_retry()
    monkeypatch.setattr(main, "get_auto_order_manager", lambda: mgr)
    monkeypatch.setattr(main, "_wake_fetch_poll", SimpleNamespace(set=Mock()))
    monkeypatch.setattr(main, "_wake_analysis_poll", SimpleNamespace(set=Mock()))

    response = await main.retry_failed_cases(
        _make_request({"limit": 200}), current_user=None
    )
    import json

    data = json.loads(response.body)

    assert data["fetch_queued"] == 2
    assert data["analysis_queued"] == 2
    assert set(data["fetch_queued_refs"]) == {"WP/1/2025", "WP/2/2025"}
    assert set(data["analysis_queued_refs"]) == {"WP/3/2025", "WP/4/2025"}


@pytest.mark.asyncio
async def test_retry_failed_respects_the_overall_limit_across_statuses(monkeypatch):
    """_query_stuck_candidates must stop once `limit` total candidates are
    collected, not apply `limit` separately to each of the four statuses."""
    _wire_stuck_query(
        monkeypatch,
        {
            "fetch_failed_retryable": [
                _stuck_case_doc("WP/1/2025"),
                _stuck_case_doc("WP/2/2025"),
            ],
            "fetch_failed_terminal": [_stuck_case_doc("WP/3/2025")],
        },
    )
    mgr = _mock_manager_for_retry()
    monkeypatch.setattr(main, "get_auto_order_manager", lambda: mgr)
    monkeypatch.setattr(main, "_wake_fetch_poll", SimpleNamespace(set=Mock()))
    monkeypatch.setattr(main, "_wake_analysis_poll", SimpleNamespace(set=Mock()))

    response = await main.retry_failed_cases(
        _make_request({"limit": 2}), current_user=None
    )
    import json

    data = json.loads(response.body)
    # Only the 2 from fetch_failed_retryable -- the query for
    # fetch_failed_terminal must never even run once the limit is hit.
    assert data["fetch_queued"] == 2
    assert "WP/3/2025" not in data["fetch_queued_refs"]


@pytest.mark.asyncio
async def test_retry_failed_board_dates_filter_uses_latest_board_date(monkeypatch):
    _wire_stuck_query(
        monkeypatch,
        {
            "fetch_failed_retryable": [
                _stuck_case_doc("WP/1/2025", board_date="2025-01-01"),
                _stuck_case_doc("WP/2/2025", board_date="2025-06-01"),
            ]
        },
    )
    mgr = _mock_manager_for_retry()
    monkeypatch.setattr(main, "get_auto_order_manager", lambda: mgr)
    monkeypatch.setattr(main, "_wake_fetch_poll", SimpleNamespace(set=Mock()))
    monkeypatch.setattr(main, "_wake_analysis_poll", SimpleNamespace(set=Mock()))

    response = await main.retry_failed_cases(
        _make_request({"limit": 200, "board_dates": ["2025-06-01"]}),
        current_user=None,
    )
    import json

    data = json.loads(response.body)

    assert data["fetch_queued"] == 1
    assert data["fetch_queued_refs"] == ["WP/2/2025"]
    assert data["skipped"] == 1


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


# ---------------------------------------------------------------------------
# 2.  Enqueue sites that used to write nothing to Firestore at all --
#     work pushed straight into the in-memory queue was silently lost if it
#     landed on a Cloud Run instance that scaled to zero before a worker
#     drained it. They must now durably mark every matched case
#     fetch_queued so any instance's poll loop can pick it up.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_admin_bulk_order_processing_marks_cases_fetch_queued(monkeypatch):
    """Was previously its own daily-boards scan with a blocking per-candidate
    case-details read (N+1) and no upper bound on limit -- against a large
    historical backlog this could take a very long time per request and
    block the whole event loop while it ran, the same class of bug fixed in
    /admin/order-status-overview. Now delegates to _get_filtered_matters,
    the same limit-bounded selector /jobs/fetch-orders already uses."""
    case = _make_mock_case("WP/77/2026", "not_linked", board_date="2026-01-05")
    mgr = _make_manager([case])

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
    mgr._get_filtered_matters.assert_called_once_with(
        {}, 10, order_statuses={"not_linked"}
    )
    mgr.case_store.transition_lifecycle.assert_called_once()
    call = mgr.case_store.transition_lifecycle.call_args
    assert call.args[0] == "WP/77/2026"
    assert call.args[1] == "fetch_queued"
    wake_fetch.assert_called_once()


@pytest.mark.asyncio
async def test_admin_bulk_order_processing_maps_days_back_to_date_from(monkeypatch):
    mgr = _make_manager([])
    monkeypatch.setattr(main, "get_auto_order_manager", lambda: mgr)
    monkeypatch.setattr(main, "_wake_fetch_poll", SimpleNamespace(set=Mock()))

    await main.admin_bulk_order_processing(
        _make_request({"order_statuses": ["not_linked"], "limit": 50, "days_back": 7}),
        current_user=None,
    )

    call = mgr._get_filtered_matters.call_args
    assert "date_from" in call.args[0]


@pytest.mark.asyncio
async def test_admin_bulk_order_processing_rejects_limit_outside_1_to_1000(
    monkeypatch,
):
    mgr = _make_manager([])
    monkeypatch.setattr(main, "get_auto_order_manager", lambda: mgr)

    for bad_limit in (0, 1001, -5):
        response = await main.admin_bulk_order_processing(
            _make_request({"order_statuses": ["not_linked"], "limit": bad_limit}),
            current_user=None,
        )
        assert response.status_code == 400
        mgr._get_filtered_matters.assert_not_called()


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

    # Sync handler (runs in FastAPI's threadpool) -- not awaited.
    response = main.get_queue_detail(limit=50, current_user=None)
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


# ---------------------------------------------------------------------------
# _fetch_stored_bytes -- the one place that decides whether a stored-order
# URL needs GCS-authenticated download (private bucket, anonymous requests
# 403 regardless of TLS) or the court_get session (legacy TLS renegotiation,
# no auth). Three call sites shared this logic before it was factored out
# here: get_order_pdf's inline GCS branch (already correct), and
# admin_ai_review_suggestion / _download_pdf_from_url (both were calling
# court_get unconditionally, 403ing on any GCS URL).
# ---------------------------------------------------------------------------


def test_fetch_stored_bytes_uses_gcs_client_for_a_storage_googleapis_url(monkeypatch):
    mock_blob = MagicMock()
    mock_blob.download_as_bytes.return_value = b"order text content"
    mock_bucket = MagicMock()
    mock_bucket.blob.return_value = mock_blob
    mock_client = MagicMock()
    mock_client.bucket.return_value = mock_bucket

    court_get_mock = Mock(
        side_effect=AssertionError("must not call court_get for a GCS URL")
    )
    monkeypatch.setattr(main, "court_get", court_get_mock)

    with patch("google.cloud.storage.Client", return_value=mock_client):
        content, content_type, resolved_url = main._fetch_stored_bytes(
            "https://storage.googleapis.com/my-bucket/court-orders/WP-1-2025/order.txt"
        )

    assert content == b"order text content"
    assert content_type is None
    assert resolved_url is None
    mock_client.bucket.assert_called_once_with("my-bucket")
    mock_bucket.blob.assert_called_once_with("court-orders/WP-1-2025/order.txt")
    court_get_mock.assert_not_called()


def test_fetch_stored_bytes_uses_court_get_for_a_non_gcs_url(monkeypatch):
    fake_response = SimpleNamespace(
        content=b"%PDF-fake",
        raise_for_status=Mock(),
        headers={"content-type": "application/pdf"},
        url="https://bombayhighcourt.gov.in/final/order.pdf",
    )
    court_get_mock = Mock(return_value=fake_response)
    monkeypatch.setattr(main, "court_get", court_get_mock)

    content, content_type, resolved_url = main._fetch_stored_bytes(
        "https://bombayhighcourt.gov.in/final/order.pdf", timeout=20
    )

    assert content == b"%PDF-fake"
    assert content_type == "application/pdf"
    assert resolved_url == "https://bombayhighcourt.gov.in/final/order.pdf"
    court_get_mock.assert_called_once_with(
        "https://bombayhighcourt.gov.in/final/order.pdf", timeout=20
    )


def test_download_pdf_from_url_routes_a_gcs_link_through_the_authenticated_path(
    monkeypatch,
):
    """/admin/order-analysis/from-link accepts an admin-supplied URL, which
    can itself be one of our own archived GCS links -- this must not 403."""
    fetch_mock = Mock(return_value=(b"%PDF-fake-content", None, None))
    monkeypatch.setattr(main, "_fetch_stored_bytes", fetch_mock)

    result = main._download_pdf_from_url(
        "https://storage.googleapis.com/billingonaire-court-orders/court-orders/WP-1-2025/order.pdf"
    )

    assert result["file_content"] == b"%PDF-fake-content"
    fetch_mock.assert_called_once_with(
        "https://storage.googleapis.com/billingonaire-court-orders/court-orders/WP-1-2025/order.pdf",
        timeout=60,
    )


@pytest.mark.asyncio
async def test_ai_suggestion_404s_when_case_has_no_order_link(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    mgr = MagicMock()
    mgr._get_case_order_context = Mock(return_value={"order_link": None})
    monkeypatch.setattr(main, "get_auto_order_manager", lambda: mgr)

    response = await main.admin_ai_review_suggestion("WP-1-2026", current_user=None)
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_ai_suggestion_uses_persisted_text_without_redownloading_pdf(
    monkeypatch,
):
    """When order_text_url is present (text persisted at analysis time),
    the endpoint must fetch that blob directly and skip re-downloading the
    PDF and re-running the full analyzer a second time.

    order_text_url is always a private GCS blob (see
    AutoOrderManager._upload_order_text_to_gcs) -- this must go through
    _fetch_stored_bytes' GCS-authenticated path, not court_get, which is
    an anonymous request and 403s on a private bucket regardless of TLS
    handling. Confirmed live: this was exactly the "Get AI read" 500 --
    "403 Client Error: Forbidden for url: https://storage.googleapis.com/
    .../order.txt" -- before this endpoint was fixed to use it."""
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    mgr = MagicMock()
    mgr._get_case_order_context = Mock(
        return_value={
            "order_link": "https://example.com/order.pdf",
            "order_text_url": "https://storage.googleapis.com/bucket/order.txt",
        }
    )
    monkeypatch.setattr(main, "get_auto_order_manager", lambda: mgr)
    fetch_mock = Mock(return_value=(b"Persisted order text", None, None))
    monkeypatch.setattr(main, "_fetch_stored_bytes", fetch_mock)
    court_get_mock = Mock(
        side_effect=AssertionError("must not call court_get for a GCS URL")
    )
    monkeypatch.setattr(main, "court_get", court_get_mock)

    import review_copilot

    monkeypatch.setattr(
        review_copilot,
        "call_gemini",
        Mock(
            return_value={
                "category": "ADJOURNED",
                "confidence": 0.8,
                "rationale": "No hearing indicators.",
            }
        ),
    )

    response = await main.admin_ai_review_suggestion("WP-1-2026", current_user=None)
    assert response.status_code == 200

    fetch_mock.assert_called_once_with(
        "https://storage.googleapis.com/bucket/order.txt", timeout=15
    )
    court_get_mock.assert_not_called()
    mgr.order_analyzer.analyze_order_document.assert_not_called()
    call_gemini_text = review_copilot.call_gemini.call_args[0][0]
    assert call_gemini_text == "Persisted order text"


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
        main,
        "court_get",
        Mock(
            return_value=SimpleNamespace(
                content=b"%PDF-fake",
                raise_for_status=Mock(),
                headers={},
                url="https://example.com/order.pdf",
            )
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
        main,
        "court_get",
        Mock(
            return_value=SimpleNamespace(
                content=b"%PDF-fake",
                raise_for_status=Mock(),
                headers={},
                url="https://example.com/order.pdf",
            )
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
# 5a. GET / -- reports whether GEMINI_API_KEY is actually mounted, so a
#     deploy that's silently missing the secret is visible without poking
#     every LLM-backed feature individually.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_root_reports_ai_enabled_when_key_present(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    response = await main.read_root()
    assert response["ai_features_enabled"] is True


@pytest.mark.asyncio
async def test_root_reports_ai_disabled_when_key_absent(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    response = await main.read_root()
    assert response["ai_features_enabled"] is False


# ---------------------------------------------------------------------------
# 5b. GET /admin/review-queue -- must return the exact field names
#     ManualReviewQueue.jsx reads (order_category, order_link, board_date,
#     confidence_score), mapped from the raw case-details doc's latest_*
#     rollups and orders[]. It used to return the raw doc verbatim, whose
#     field names (latest_order_category, latest_order_link, ...) don't
#     match what the UI reads -- every column silently rendered "--".
# ---------------------------------------------------------------------------


def _review_queue_doc(doc_id, **fields):
    data = {
        "case_ref": doc_id.replace("-", "/"),
        "latest_board_date": "2026-01-05",
        "petitioner": "ABC Corp",
        "respondent": "State of Maharashtra",
        "latest_order_category": "ADJOURNED",
        "latest_order_link": "https://storage.googleapis.com/bucket/order.pdf",
        "orders": [
            {
                "order_link": "https://storage.googleapis.com/bucket/order.pdf",
                "order_category_confidence": 0.42,
            }
        ],
        **fields,
    }
    return SimpleNamespace(id=doc_id, to_dict=lambda: data)


@pytest.mark.asyncio
async def test_review_queue_maps_to_the_fields_the_ui_actually_reads(monkeypatch):
    mock_db = MagicMock()
    mock_db.collection.return_value.where.return_value.limit.return_value.stream.return_value = [
        _review_queue_doc("WP-1-2026")
    ]
    monkeypatch.setattr(main, "firestore", SimpleNamespace(client=lambda: mock_db))

    response = await main.get_admin_review_queue(limit=200, current_user=None)
    import json

    cases = json.loads(response.body)
    assert len(cases) == 1
    case = cases[0]
    assert case["id"] == "WP-1-2026"
    assert case["case_ref"] == "WP/1/2026"
    assert case["board_date"] == "2026-01-05"
    assert case["petitioner"] == "ABC Corp"
    assert case["respondent"] == "State of Maharashtra"
    assert case["order_category"] == "ADJOURNED"
    assert case["confidence_score"] == 0.42
    assert case["order_link"] == "https://storage.googleapis.com/bucket/order.pdf"


@pytest.mark.asyncio
async def test_review_queue_sources_board_date_from_the_same_order_as_the_link(
    monkeypatch,
):
    """A case with multiple hearing dates has latest_board_date (written by
    board ingestion) and latest_order_link/latest_order_category (written by
    append_case_order whenever ANY date's analysis completes) drift apart --
    each is last-write-wins from an unsynchronised process. Confirmed live:
    CP/416/2024 showed board_date=2025-04-02 next to a category/confidence
    that belonged to a 2026-04-22 order and a PDF link from a 2025-12-24
    order. The fix sources all four fields from the same orders[] entry, so
    the PDF the reviewer opens always matches the date and category shown."""
    doc = _review_queue_doc(
        "CP-416-2024",
        latest_board_date="2025-04-02",
        latest_order_category="ADJOURNED",
        latest_order_link="https://storage.googleapis.com/bucket/2025-12-24.pdf",
        orders=[
            {
                "order_link": "https://storage.googleapis.com/bucket/2026-04-22.pdf",
                "order_category": "ADJOURNED",
                "order_category_confidence": 0.5,
                "board_date": "2026-04-22",
            }
        ],
    )
    mock_db = MagicMock()
    mock_db.collection.return_value.where.return_value.limit.return_value.stream.return_value = [
        doc
    ]
    monkeypatch.setattr(main, "firestore", SimpleNamespace(client=lambda: mock_db))

    response = await main.get_admin_review_queue(limit=200, current_user=None)
    import json

    case = json.loads(response.body)[0]
    assert case["board_date"] == "2026-04-22"
    assert case["order_link"] == "https://storage.googleapis.com/bucket/2026-04-22.pdf"
    assert case["order_category"] == "ADJOURNED"
    assert case["confidence_score"] == 0.5


@pytest.mark.asyncio
async def test_review_queue_surfaces_the_stored_llm_suggestion(monkeypatch):
    """Once _maybe_llm_assist has recorded a suggestion during analysis, the
    review queue must surface it directly instead of the UI needing to
    call /admin/orders/{doc_id}/ai-suggestion (a second Gemini call) just
    to show what the pipeline already knows."""
    doc = _review_queue_doc(
        "WP-2-2026",
        orders=[
            {
                "order_link": "https://storage.googleapis.com/bucket/order.pdf",
                "order_category_confidence": 0.3,
                "order_analysis_metadata": {
                    "llm_suggestion": {
                        "category": "HEARD_AND_ADJOURNED",
                        "confidence": 0.9,
                        "rationale": "Notice was issued.",
                        "agreed_with_regex": False,
                    }
                },
            }
        ],
    )
    mock_db = MagicMock()
    mock_db.collection.return_value.where.return_value.limit.return_value.stream.return_value = [
        doc
    ]
    monkeypatch.setattr(main, "firestore", SimpleNamespace(client=lambda: mock_db))

    response = await main.get_admin_review_queue(limit=200, current_user=None)
    import json

    case = json.loads(response.body)[0]
    assert case["llm_suggestion"]["category"] == "HEARD_AND_ADJOURNED"
    assert case["llm_suggestion"]["agreed_with_regex"] is False


@pytest.mark.asyncio
async def test_review_queue_handles_a_case_with_no_orders_yet(monkeypatch):
    """A manual_review_required doc with an empty/missing orders[] (e.g. a
    corrupted or partially-written doc) must not 500 the whole queue."""
    doc = _review_queue_doc("WP-3-2026", orders=[])
    mock_db = MagicMock()
    mock_db.collection.return_value.where.return_value.limit.return_value.stream.return_value = [
        doc
    ]
    monkeypatch.setattr(main, "firestore", SimpleNamespace(client=lambda: mock_db))

    response = await main.get_admin_review_queue(limit=200, current_user=None)
    import json

    case = json.loads(response.body)[0]
    assert case["confidence_score"] is None
    assert case["llm_suggestion"] is None


@pytest.mark.asyncio
async def test_review_queue_emits_one_row_per_pending_hearing_date(monkeypatch):
    """A case can have several hearing dates pending review at once (see
    CaseDataStore.add_pending_review_date). Before this, a case with, say,
    two flagged dates collapsed into a single row built from whichever
    order finished analysis last -- which might not even be a flagged
    date. Each pending date must now be its own, independently-identified
    row."""
    doc = _review_queue_doc(
        "CP-416-2024",
        pending_review_order_dates=["2026-04-22", "2025-12-24"],
        orders=[
            {
                "order_link": "https://storage.googleapis.com/bucket/2026-04-22.pdf",
                "order_category": "ADJOURNED",
                "order_category_confidence": 0.5,
                "board_date": "2026-04-22",
                "order_date": "2026-04-22",
            },
            {
                "order_link": "https://storage.googleapis.com/bucket/2025-12-24.pdf",
                "order_category": "DISPOSED_OFF",
                "order_category_confidence": 0.3,
                "board_date": "2025-12-24",
                "order_date": "2025-12-24",
            },
        ],
    )
    mock_db = MagicMock()
    mock_db.collection.return_value.where.return_value.limit.return_value.stream.return_value = [
        doc
    ]
    monkeypatch.setattr(main, "firestore", SimpleNamespace(client=lambda: mock_db))

    response = await main.get_admin_review_queue(limit=200, current_user=None)
    import json

    cases = json.loads(response.body)
    assert len(cases) == 2
    by_date = {c["order_date"]: c for c in cases}
    assert by_date["2026-04-22"]["order_category"] == "ADJOURNED"
    assert by_date["2026-04-22"]["confidence_score"] == 0.5
    assert (
        by_date["2026-04-22"]["order_link"]
        == "https://storage.googleapis.com/bucket/2026-04-22.pdf"
    )
    assert by_date["2025-12-24"]["order_category"] == "DISPOSED_OFF"
    assert by_date["2025-12-24"]["confidence_score"] == 0.3
    assert (
        by_date["2025-12-24"]["order_link"]
        == "https://storage.googleapis.com/bucket/2025-12-24.pdf"
    )


@pytest.mark.asyncio
async def test_override_endpoint_forwards_order_date_to_the_store(monkeypatch):
    """A case can have several hearing dates pending review at once, so the
    override endpoint must tell CaseDataStore.apply_category_override
    exactly which one is being resolved -- otherwise the correction always
    lands on whichever order was appended most recently."""
    mgr = MagicMock()
    mgr.case_store.apply_category_override = Mock(
        return_value={
            "success": True,
            "case_ref": "CP/416/2024",
            "order_date": "2026-04-22",
            "previous_category": "ADJOURNED",
        }
    )
    mgr._update_board_entries_for_case_date = Mock()
    monkeypatch.setattr(main, "get_auto_order_manager", lambda: mgr)

    request = _make_request(
        {"order_category": "DISPOSED_OFF", "order_date": "2026-04-22"}
    )
    response = await main.admin_override_order_category(
        "CP-416-2024", request, current_user={"uid": "u1"}
    )

    assert response.status_code == 200
    mgr.case_store.apply_category_override.assert_called_once_with(
        "CP/416/2024",
        "DISPOSED_OFF",
        actor_uid="u1",
        notes=None,
        review_ai_suggestion=None,
        order_date="2026-04-22",
    )


@pytest.mark.asyncio
async def test_ai_suggestion_forwards_order_date_to_the_order_context_lookup(
    monkeypatch,
):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    mgr = MagicMock()
    mgr._get_case_order_context = Mock(
        return_value={
            "order_link": "https://storage.googleapis.com/b/2026-04-22.pdf",
            "order_text_url": "https://storage.googleapis.com/b/2026-04-22.txt",
        }
    )
    monkeypatch.setattr(main, "get_auto_order_manager", lambda: mgr)
    monkeypatch.setattr(
        main,
        "_fetch_stored_bytes",
        Mock(return_value=(b"Order text.", None, None)),
    )
    with patch(
        "review_copilot.call_gemini",
        return_value={
            "category": "ADJOURNED",
            "confidence": 0.9,
            "rationale": "Stand over.",
        },
    ):
        response = await main.admin_ai_review_suggestion(
            "CP-416-2024", order_date="2026-04-22", current_user=None
        )

    assert response.status_code == 200
    mgr._get_case_order_context.assert_called_once_with(
        "CP/416/2024", order_date="2026-04-22"
    )


@pytest.mark.asyncio
async def test_review_queue_limit_is_passed_to_the_query_and_clamped(monkeypatch):
    mock_db = MagicMock()
    limit_mock = mock_db.collection.return_value.where.return_value.limit
    limit_mock.return_value.stream.return_value = []
    monkeypatch.setattr(main, "firestore", SimpleNamespace(client=lambda: mock_db))

    await main.get_admin_review_queue(limit=10_000, current_user=None)

    limit_mock.assert_called_once_with(500)  # clamped to the max


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


@pytest.mark.asyncio
async def test_auto_map_case_to_users_routes_initials_collisions_to_review(
    monkeypatch,
):
    """Modern boards print government lawyers as bare initials ("P M J, AGP"
    -- see Board.py's _GP_INITIALS_PATTERN). When two different registered
    AGPs both accept-match the same bare-initials board text (a real
    collision, not a hypothetical one -- e.g. "Pooja Makarand Joshi
    Deshpande" and "Priya Manoj Jadhav" both being "P M J"), neither must be
    auto-mapped: both go to user-matter-pending-confirmations instead of
    user-case-mappings, so a human confirms which one actually appeared."""
    user_a = SimpleNamespace(
        id="user-a",
        to_dict=lambda: {"role_type": "AGP", "full_name": "Pooja Makarand Joshi"},
    )
    user_b = SimpleNamespace(
        id="user-b",
        to_dict=lambda: {"role_type": "AGP", "full_name": "Priya Manoj Jadhav"},
    )

    match_a = SimpleNamespace(
        match_source="board_data",
        match_field="respondent_lawyer",
        matched_text="P M J",
        confidence_score=0.80,
        role_type="AGP",
        board_date="2026-07-24",
    )
    match_b = SimpleNamespace(
        match_source="board_data",
        match_field="respondent_lawyer",
        matched_text="P M J",
        confidence_score=0.80,
        role_type="AGP",
        board_date="2026-07-24",
    )

    def fake_matches_for_case(user_id, user_role, case_id):
        return [match_a] if user_id == "user-a" else [match_b]

    mock_matcher = MagicMock()
    mock_matcher.find_user_matters_for_case.side_effect = fake_matches_for_case
    mock_matcher.find_near_miss_matters_for_case.return_value = []
    monkeypatch.setattr(main, "get_user_matter_matcher", lambda: mock_matcher)

    mock_pending_doc_ref = MagicMock()
    mock_mapping_doc_ref = MagicMock()

    def collection_side_effect(name):
        col = MagicMock()
        if name == "user-roles":
            col.stream.return_value = [user_a, user_b]
        elif name == "user-matter-pending-confirmations":
            col.document.return_value = mock_pending_doc_ref
        elif name == "user-case-mappings":
            col.document.return_value = mock_mapping_doc_ref
        return col

    mock_db = MagicMock()
    mock_db.collection.side_effect = collection_side_effect
    monkeypatch.setattr(
        main,
        "firestore",
        SimpleNamespace(client=lambda: mock_db, SERVER_TIMESTAMP="ts"),
    )

    await main.auto_map_case_to_users("board-doc-1", {"case_ref": "WP/8923/2026"})

    # Neither colliding match is auto-accepted into user-case-mappings.
    mock_mapping_doc_ref.set.assert_not_called()

    # Both users' matches are routed to pending-confirmations for review.
    assert mock_pending_doc_ref.set.call_count == 2
    written_users = {
        call.args[0]["user_id"] for call in mock_pending_doc_ref.set.call_args_list
    }
    assert written_users == {"user-a", "user-b"}
    for call in mock_pending_doc_ref.set.call_args_list:
        assert call.args[0]["matched_text"] == "P M J"
        assert call.args[0]["status"] == "pending"


@pytest.mark.asyncio
async def test_auto_map_case_to_users_still_auto_maps_a_unique_initials_match(
    monkeypatch,
):
    """A bare-initials match with no colliding second user must still be
    auto-mapped as before -- the collision check must not demote every
    initials-format match indiscriminately."""
    user_a = SimpleNamespace(
        id="user-a",
        to_dict=lambda: {"role_type": "AGP", "full_name": "Nitin Shashikant Bansode"},
    )

    match_a = SimpleNamespace(
        match_source="board_data",
        match_field="respondent_lawyer",
        matched_text="N S B",
        confidence_score=0.80,
        role_type="AGP",
        board_date="2026-07-24",
    )

    mock_matcher = MagicMock()
    mock_matcher.find_user_matters_for_case.return_value = [match_a]
    mock_matcher.find_near_miss_matters_for_case.return_value = []
    monkeypatch.setattr(main, "get_user_matter_matcher", lambda: mock_matcher)

    mock_mapping_doc_ref = MagicMock()

    def collection_side_effect(name):
        col = MagicMock()
        if name == "user-roles":
            col.stream.return_value = [user_a]
        elif name == "user-case-mappings":
            col.document.return_value = mock_mapping_doc_ref
        return col

    mock_db = MagicMock()
    mock_db.collection.side_effect = collection_side_effect
    monkeypatch.setattr(
        main,
        "firestore",
        SimpleNamespace(client=lambda: mock_db, SERVER_TIMESTAMP="ts"),
    )

    await main.auto_map_case_to_users("board-doc-1", {"case_ref": "WP/318/2026"})

    mock_mapping_doc_ref.set.assert_called_once()
    assert mock_mapping_doc_ref.set.call_args.args[0]["matched_text"] == "N S B"


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
#     for it. Replaced with cheap .count() aggregations, and later
#     rebucketed from the legacy order_status vocabulary to the same
#     waiting/working/ready/attention buckets Search Orders and the
#     Dashboard already use (Board.simple_status_for), so this table can't
#     present a different status language from the rest of the app.
# ---------------------------------------------------------------------------


def _count_result(n):
    """Shape of a Firestore .count().get() aggregation response: a
    list-of-lists of results, each with a .value attribute."""
    return [[SimpleNamespace(value=n)]]


def _wire_order_status_overview_db(monkeypatch, *, total_cases, counts_by_status=None):
    counts_by_status = counts_by_status or {}
    mock_collection = MagicMock()
    mock_collection.count.return_value.get.return_value = _count_result(total_cases)
    mock_collection.stream.side_effect = AssertionError(
        "must not stream the full collection -- that's the N+1 bug being fixed"
    )

    def where_side_effect(field, op, value):
        assert field == "lifecycle_status"
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
    return mock_db


@pytest.mark.asyncio
async def test_order_status_overview_uses_count_aggregations_not_a_full_scan(
    monkeypatch,
):
    _wire_order_status_overview_db(
        monkeypatch,
        total_cases=10,
        counts_by_status={
            "fetch_succeeded": 2,  # working
            "analysed": 5,  # ready
            "fetch_failed_terminal": 1,  # attention
            "analysis_failed_retryable": 1,  # attention
        },
    )

    response = await main.get_order_status_overview(current_user={"uid": "admin-1"})

    import json

    data = json.loads(response.body)
    assert data["success"] is True
    assert data["total_cases"] == 10
    assert data["status_counts"] == {
        "waiting": 1,  # 10 - 2 - 5 - 1 - 1 (uncounted/absent lifecycle_status)
        "working": 2,
        "ready": 5,
        "attention": 2,
    }
    assert data["pending_processing"] == 3  # waiting(1) + attention(2)


@pytest.mark.asyncio
async def test_order_status_overview_matches_boards_simple_status_for(monkeypatch):
    """Regression guard against the two ever drifting apart: every raw
    lifecycle_status this endpoint counts must land in the same bucket
    Board.simple_status_for (Search Orders' status column, the Dashboard's
    filter) would put it in."""
    from Board import simple_status_for

    counts_by_status = {status: 1 for status in main.ALL_LIFECYCLE_STATUSES}
    _wire_order_status_overview_db(
        monkeypatch,
        total_cases=len(counts_by_status),
        counts_by_status=counts_by_status,
    )

    response = await main.get_order_status_overview(current_user={"uid": "admin-1"})

    import json

    data = json.loads(response.body)
    expected = {k: 0 for k in ("waiting", "working", "ready", "attention")}
    for status in main.ALL_LIFECYCLE_STATUSES:
        expected[simple_status_for(status)] += 1

    assert data["status_counts"] == expected


@pytest.mark.asyncio
async def test_order_status_overview_never_goes_negative_on_uncounted_statuses(
    monkeypatch,
):
    """If the explicit buckets somehow summed to more than total_cases,
    "waiting" (the catch-all for absent lifecycle_status) must clamp at 0
    rather than go negative and produce a nonsensical percentage."""
    _wire_order_status_overview_db(
        monkeypatch,
        total_cases=2,
        counts_by_status={status: 5 for status in main.ALL_LIFECYCLE_STATUSES},
    )

    response = await main.get_order_status_overview(current_user={"uid": "admin-1"})

    import json

    data = json.loads(response.body)
    assert all(v >= 0 for v in data["status_counts"].values())


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


# ---------------------------------------------------------------------------
# 9.  POST /bills/save -- server-side validation. This endpoint used to persist
#     whatever the browser posted, summing client-supplied fees_rs into
#     total_fees with no check at all, on the one artifact that leaves the
#     building for a government body.
# ---------------------------------------------------------------------------


def _save_request(entries, **extra):
    return _make_request(
        {
            "bill_entries": entries,
            "metadata": {
                "date_range": {"startDate": "2026-01-01", "endDate": "2026-01-31"}
            },
            **extra,
        }
    )


def _wire_bills_db(monkeypatch, saved_bills=None):
    """Firestore double: user-bills stream returns saved_bills, and the new
    bill document write is captured for assertions."""
    written = {}

    bill_doc_ref = MagicMock()
    bill_doc_ref.id = "new-bill-1"
    bill_doc_ref.set = Mock(side_effect=lambda data: written.update(data))

    bills_collection = MagicMock()
    bills_collection.where.return_value.stream.return_value = saved_bills or []
    bills_collection.document.return_value = bill_doc_ref

    mock_db = MagicMock()
    mock_db.collection.return_value = bills_collection
    monkeypatch.setattr(
        main,
        "firestore",
        SimpleNamespace(client=lambda: mock_db, SERVER_TIMESTAMP="ts"),
    )
    monkeypatch.setattr(
        main, "generate_bill_number_safe", lambda db, uid, yr: ("B/1/2026", 1)
    )
    return written


@pytest.mark.asyncio
async def test_bills_save_rejects_a_fee_that_does_not_match_the_schedule(monkeypatch):
    written = _wire_bills_db(monkeypatch)
    bad = {
        "case_detail": "WP/1/2026",
        "date": "2026-01-15",
        "results": "ADJOURNED",
        "fees_rs": 99999,
    }

    response = await main.save_bill_entries(
        _save_request([bad]), current_user={"uid": "u1"}
    )

    assert response.status_code == 400
    import json

    data = json.loads(response.body)
    assert data["qa_report"]["ok"] is False
    assert data["qa_report"]["fee_mismatches"]
    # Nothing may be persisted on a rejected save.
    assert written == {}


@pytest.mark.asyncio
async def test_bills_save_recomputes_fees_from_the_schedule_not_the_request(
    monkeypatch,
):
    """Even on an accepted bill, the persisted fee must come from the server's
    schedule -- a correct-looking request must not be able to smuggle a total
    through by matching the category but inflating an unrelated field."""
    written = _wire_bills_db(monkeypatch)
    entries = [
        {
            "case_detail": "WP/1/2026",
            "date": "2026-01-15",
            "results": "ADJOURNED",
            "fees_rs": 1250,
        },
        {
            "case_detail": "WP/2/2026",
            "date": "2026-01-16",
            "results": "WP DISPOSED OF",
            "fees_rs": 2500,
        },
    ]

    response = await main.save_bill_entries(
        _save_request(entries), current_user={"uid": "u1"}
    )

    assert response.status_code == 200
    assert written["total_fees"] == 3750
    assert [e["fees_rs"] for e in written["entries"]] == [1250, 2500]


@pytest.mark.asyncio
async def test_bills_save_blocks_double_billing_against_an_earlier_saved_bill(
    monkeypatch,
):
    earlier = SimpleNamespace(
        to_dict=lambda: {
            "entries": [{"case_detail": "WP/1/2026", "date": "2026-01-15"}]
        }
    )
    written = _wire_bills_db(monkeypatch, saved_bills=[earlier])
    entry = {
        "case_detail": "WP/1/2026",
        "date": "2026-01-15",
        "results": "ADJOURNED",
        "fees_rs": 1250,
    }

    response = await main.save_bill_entries(
        _save_request([entry]), current_user={"uid": "u1"}
    )

    assert response.status_code == 400
    import json

    assert json.loads(response.body)["qa_report"]["duplicates_across_bills"]
    assert written == {}


@pytest.mark.asyncio
async def test_bills_save_override_persists_and_records_the_override(monkeypatch):
    written = _wire_bills_db(monkeypatch)
    bad = {
        "case_detail": "WP/1/2026",
        "date": "2026-01-15",
        "results": "ADJOURNED",
        "fees_rs": 99999,
    }

    response = await main.save_bill_entries(
        _save_request([bad], override_qa=True), current_user={"uid": "u1"}
    )

    assert response.status_code == 200
    assert written["qa_override"]["overridden_by"] == "u1"
    assert written["qa_override"]["report"]["fee_mismatches"]
    # The override lets it save, but the fee is STILL corrected to the schedule --
    # overriding the warning is not permission to bill an arbitrary number.
    assert written["total_fees"] == 1250


@pytest.mark.asyncio
async def test_bills_save_accepts_a_clean_bill_without_an_override(monkeypatch):
    written = _wire_bills_db(monkeypatch)
    entry = {
        "case_detail": "WP/1/2026",
        "date": "2026-01-15",
        "results": "ADJOURNED",
        "fees_rs": 1250,
    }

    response = await main.save_bill_entries(
        _save_request([entry]), current_user={"uid": "u1"}
    )

    assert response.status_code == 200
    assert "qa_override" not in written
    assert written["total_fees"] == 1250


# ---------------------------------------------------------------------------
# 10. POST /admin/repair-order-board-dates -- write-side fix for order
#     entries whose stored board_date disagrees with their own order_date
#     (Search Orders matches orders[].board_date to each board row's own
#     date, so a wrong value here is why an order shows against the wrong
#     hearing, or doesn't show at all).
# ---------------------------------------------------------------------------


def _order_entry(order_date, board_date):
    return {"order_date": order_date, "board_date": board_date, "order_link": "x"}


def _case_doc(doc_id, orders):
    doc = MagicMock()
    doc.id = doc_id
    doc.to_dict.return_value = {"orders": orders}
    doc.reference = MagicMock()
    return doc


@pytest.mark.asyncio
async def test_repair_order_board_dates_fixes_mismatched_entries(monkeypatch):
    good = _order_entry("2026-01-15", "2026-01-15")
    bad = _order_entry("2026-03-01", "2026-11-20")  # tagged with a later hearing
    doc = _case_doc("WP-123-2026", [good, bad])

    mock_db = MagicMock()
    mock_db.collection.return_value.order_by.return_value.limit.return_value.stream.return_value = [
        doc
    ]
    monkeypatch.setattr(main, "firestore", SimpleNamespace(client=lambda: mock_db))

    response = await main.admin_repair_order_board_dates(
        limit=200, start_after=None, current_user=None
    )
    import json

    data = json.loads(response.body)

    assert data["success"] is True
    assert data["docs_scanned"] == 1
    assert data["docs_updated"] == 1
    assert data["entries_fixed"] == 1

    updated_orders = doc.reference.update.call_args.args[0]["orders"]
    assert updated_orders[0]["board_date"] == "2026-01-15"  # already correct
    assert updated_orders[1]["board_date"] == "2026-03-01"  # corrected


@pytest.mark.asyncio
async def test_repair_order_board_dates_skips_docs_with_no_mismatch(monkeypatch):
    good = _order_entry("2026-01-15", "2026-01-15")
    doc = _case_doc("WP-1-2026", [good])

    mock_db = MagicMock()
    mock_db.collection.return_value.order_by.return_value.limit.return_value.stream.return_value = [
        doc
    ]
    monkeypatch.setattr(main, "firestore", SimpleNamespace(client=lambda: mock_db))

    response = await main.admin_repair_order_board_dates(
        limit=200, start_after=None, current_user=None
    )
    import json

    data = json.loads(response.body)

    assert data["docs_updated"] == 0
    assert data["entries_fixed"] == 0
    doc.reference.update.assert_not_called()


@pytest.mark.asyncio
async def test_repair_order_board_dates_leaves_entries_with_no_order_date_alone(
    monkeypatch,
):
    """No order_date means there's nothing reliable to correct board_date
    to -- must not guess."""
    unresolved = _order_entry(None, "2026-11-20")
    doc = _case_doc("WP-1-2026", [unresolved])

    mock_db = MagicMock()
    mock_db.collection.return_value.order_by.return_value.limit.return_value.stream.return_value = [
        doc
    ]
    monkeypatch.setattr(main, "firestore", SimpleNamespace(client=lambda: mock_db))

    response = await main.admin_repair_order_board_dates(
        limit=200, start_after=None, current_user=None
    )
    import json

    data = json.loads(response.body)

    assert data["entries_fixed"] == 0
    doc.reference.update.assert_not_called()


@pytest.mark.asyncio
async def test_repair_order_board_dates_returns_next_cursor_on_a_full_page(
    monkeypatch,
):
    docs = [_case_doc(f"WP-{i}-2026", []) for i in range(3)]

    mock_db = MagicMock()
    mock_db.collection.return_value.order_by.return_value.limit.return_value.stream.return_value = (
        docs
    )
    monkeypatch.setattr(main, "firestore", SimpleNamespace(client=lambda: mock_db))

    response = await main.admin_repair_order_board_dates(
        limit=3, start_after=None, current_user=None
    )
    import json

    data = json.loads(response.body)
    assert data["next_start_after"] == "WP-2-2026"


@pytest.mark.asyncio
async def test_repair_order_board_dates_no_next_cursor_on_the_final_page(monkeypatch):
    docs = [_case_doc("WP-1-2026", [])]

    mock_db = MagicMock()
    mock_db.collection.return_value.order_by.return_value.limit.return_value.stream.return_value = (
        docs
    )
    monkeypatch.setattr(main, "firestore", SimpleNamespace(client=lambda: mock_db))

    response = await main.admin_repair_order_board_dates(
        limit=200, start_after=None, current_user=None
    )
    import json

    data = json.loads(response.body)
    assert data["next_start_after"] is None


@pytest.mark.asyncio
async def test_repair_order_board_dates_resumes_from_the_given_start_after(monkeypatch):
    resumed_docs = [_case_doc("WP-9-2026", [])]

    mock_db = MagicMock()
    start_snapshot = MagicMock(exists=True)
    mock_db.collection.return_value.document.return_value.get.return_value = (
        start_snapshot
    )
    query = mock_db.collection.return_value.order_by.return_value.limit.return_value
    query.start_after.return_value.stream.return_value = resumed_docs
    monkeypatch.setattr(main, "firestore", SimpleNamespace(client=lambda: mock_db))

    response = await main.admin_repair_order_board_dates(
        limit=200, start_after="WP-8-2026", current_user=None
    )
    import json

    data = json.loads(response.body)

    query.start_after.assert_called_once_with(start_snapshot)
    assert data["docs_scanned"] == 1


# ---------------------------------------------------------------------------
# 11. GET /orders/overview-stats -- the Dashboard workflow strip's "Fetch
#     orders" and "Analyse" steps were showing the same underlying number in
#     two different units.
#
#     "Fetch orders" (cases_with_orders) used to be total_case_details minus
#     not_linked -- which counted order_failed cases (download itself
#     failed) as "downloaded".
#
#     "Analyse" (analysis_completion_rate) used to be cases_with_orders /
#     total_cases -- the exact same numerator as "Fetch orders" (so the two
#     steps tracked each other almost exactly instead of measuring different
#     things), divided by a daily-boards board-ROW count while the numerator
#     was a case-details unique-CASE count -- mismatched units whenever any
#     case is listed more than once.
# ---------------------------------------------------------------------------


def _wire_overview_stats_db(monkeypatch, *, total_cases, counts_by_status):
    """counts_by_status: {latest_order_status: count}. total_cases is the
    daily-boards count(); the case-details count() (no where clause) is
    derived as the sum of counts_by_status, matching total_case_details in
    the real implementation."""
    total_case_details = sum(counts_by_status.values())

    case_details_collection = MagicMock()
    case_details_collection.count.return_value.get.return_value = _count_result(
        total_case_details
    )

    def where_side_effect(field, op, value):
        assert field == "latest_order_status"
        where_mock = MagicMock()
        where_mock.count.return_value.get.return_value = _count_result(
            counts_by_status.get(value, 0)
        )
        return where_mock

    case_details_collection.where.side_effect = where_side_effect

    daily_boards_collection = MagicMock()
    daily_boards_collection.count.return_value.get.return_value = _count_result(
        total_cases
    )

    def collection_side_effect(name):
        return (
            case_details_collection
            if name == "case-details"
            else daily_boards_collection
        )

    mock_db = MagicMock()
    mock_db.collection.side_effect = collection_side_effect
    monkeypatch.setattr(main, "firestore", SimpleNamespace(client=lambda: mock_db))
    # Fresh cache each test -- this is a module-level global shared across
    # the whole test session and would otherwise serve a stale response.
    monkeypatch.setattr(main, "_overview_stats_cache", {"ts": 0.0, "data": None})
    monkeypatch.setattr(main, "ensure_firebase", lambda: None)
    return mock_db


@pytest.mark.asyncio
async def test_overview_stats_fetched_excludes_download_failures(monkeypatch):
    """order_failed means the download itself failed -- it must not count
    toward "order PDFs downloaded"."""
    _wire_overview_stats_db(
        monkeypatch,
        total_cases=100,
        counts_by_status={
            "analysed": 30,
            "linked": 10,
            "order_analysis_failed": 5,  # downloaded, only the READ failed
            "order_failed": 8,  # download itself failed
            "not_linked": 47,
        },
    )

    response = await main.get_order_overview_stats(current_user={"uid": "u1"})
    import json

    data = json.loads(response.body)

    # downloaded = analysed + linked + order_analysis_failed = 45, NOT
    # total_case_details(53) - not_linked(47) = 53 (which would wrongly
    # include the 8 order_failed cases as "downloaded").
    assert data["cases_with_orders"] == 45
    assert data["cases_without_orders"] == 55  # not_linked(47) + order_failed(8)


@pytest.mark.asyncio
async def test_overview_stats_analysis_rate_is_a_case_level_percentage(monkeypatch):
    """analysis_completion_rate must be analysed / total_case_details, not
    cases_with_orders / total_cases (which conflated "downloaded" with
    "analysed" and divided a case-details numerator by a daily-boards
    board-row denominator)."""
    _wire_overview_stats_db(
        monkeypatch,
        total_cases=1000,  # deliberately far from total_case_details, so a
        # units mix-up would produce an obviously wrong percentage
        counts_by_status={
            "analysed": 25,
            "linked": 50,
            "order_failed": 5,
            "not_linked": 20,
        },
    )

    response = await main.get_order_overview_stats(current_user={"uid": "u1"})
    import json

    data = json.loads(response.body)

    # total_case_details = 25+50+5+20 = 100; analysed/total_case_details = 25%
    assert data["analysis_completion_rate"] == 25.0
    # NOT the old formula: cases_with_orders(70) / total_cases(1000) = 7.0
    assert data["analysis_completion_rate"] != 7.0


@pytest.mark.asyncio
async def test_overview_stats_fetch_and_analyse_are_independent_numbers(monkeypatch):
    """Regression guard for the reported symptom: "Fetch orders" and
    "Analyse" must not track each other -- a case that downloaded but
    hasn't been analysed yet must move the fetched count without moving
    the analysis rate."""
    _wire_overview_stats_db(
        monkeypatch,
        total_cases=100,
        counts_by_status={
            "analysed": 10,
            "linked": 40,  # downloaded, NOT yet analysed
            "not_linked": 50,
        },
    )

    response = await main.get_order_overview_stats(current_user={"uid": "u1"})
    import json

    data = json.loads(response.body)

    assert data["cases_with_orders"] == 50  # analysed(10) + linked(40)
    # total_case_details = 10+40+50 = 100 -> analysed(10)/100 = 10%
    assert data["analysis_completion_rate"] == 10.0


# ---------------------------------------------------------------------------
# 12. Poll-loop heartbeat -- /queue/status's "processing_active" used to read
#     an in-process global (_last_fetch_poll_tick/_last_analysis_poll_tick)
#     that only the ONE Cloud Run instance whose loop had just ticked could
#     see. /queue/status can be answered by any of up to 10 instances, so it
#     reported "inactive" almost unconditionally regardless of whether the
#     pipeline was actually running. Replaced with a shared Firestore doc any
#     instance can write and any instance can read.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_poll_heartbeat_write_ensures_firebase_is_initialized_first(monkeypatch):
    """Regression guard: both poll loops called _write_poll_heartbeat before
    their own ensure_firebase() call, so on a cold-started instance this was
    the very first Firestore touch of the process -- "the default Firebase
    app does not exist" on every instance's first tick (confirmed across 10
    concurrently cold-started Cloud Run instances in production logs).
    _write_poll_heartbeat and _poll_loop_is_active must not depend on being
    called after some other code path's ensure_firebase()."""
    mock_db = MagicMock()
    monkeypatch.setattr(main, "firestore", SimpleNamespace(client=lambda: mock_db))
    ensure_mock = Mock()
    monkeypatch.setattr(main, "ensure_firebase", ensure_mock)

    main._write_poll_heartbeat("fetch_last_tick")
    ensure_mock.assert_called_once()

    ensure_mock.reset_mock()
    main._poll_loop_is_active("fetch_last_tick")
    ensure_mock.assert_called_once()


@pytest.mark.asyncio
async def test_poll_heartbeat_write_and_read_round_trips(monkeypatch):
    mock_db = MagicMock()
    stored = {}
    mock_db.collection.return_value.document.return_value.set.side_effect = (
        lambda data, merge=False: stored.update(data)
    )
    mock_db.collection.return_value.document.return_value.get.return_value = (
        SimpleNamespace(to_dict=lambda: stored)
    )
    monkeypatch.setattr(main, "firestore", SimpleNamespace(client=lambda: mock_db))

    assert main._poll_loop_is_active("fetch_last_tick") is False  # nothing written yet

    main._write_poll_heartbeat("fetch_last_tick")

    assert main._poll_loop_is_active("fetch_last_tick") is True
    # A DIFFERENT field (as if only the analysis loop had ticked) must not
    # be considered active by proxy.
    assert main._poll_loop_is_active("analysis_last_tick") is False


@pytest.mark.asyncio
async def test_poll_loop_is_active_false_for_a_stale_heartbeat(monkeypatch):
    from datetime import timedelta

    mock_db = MagicMock()
    old_tick = (datetime.now() - timedelta(hours=1)).isoformat()
    mock_db.collection.return_value.document.return_value.get.return_value = (
        SimpleNamespace(to_dict=lambda: {"fetch_last_tick": old_tick})
    )
    monkeypatch.setattr(main, "firestore", SimpleNamespace(client=lambda: mock_db))

    assert main._poll_loop_is_active("fetch_last_tick") is False


@pytest.mark.asyncio
async def test_poll_loop_is_active_survives_a_read_failure(monkeypatch):
    """Must degrade to "not active" rather than raise -- a Firestore hiccup
    here must never turn into a 500 on /queue/status."""
    mock_db = MagicMock()
    mock_db.collection.return_value.document.return_value.get.side_effect = Exception(
        "boom"
    )
    monkeypatch.setattr(main, "firestore", SimpleNamespace(client=lambda: mock_db))

    assert main._poll_loop_is_active("fetch_last_tick") is False


def _wire_queue_status_db(
    monkeypatch, *, heartbeat=None, counts=None, in_progress_docs=None
):
    """heartbeat: dict merged into the poll-heartbeat doc (e.g.
    {"fetch_last_tick": iso}). counts: {lifecycle_status: count} for
    .count() aggregations. in_progress_docs: {lifecycle_status: [doc_dict,
    ...]} streamed for _count_stale_in_progress's fetch_in_progress /
    analysis_in_progress scan."""
    counts = counts or {}
    in_progress_docs = in_progress_docs or {}

    heartbeat_collection = MagicMock()
    heartbeat_collection.document.return_value.get.return_value = SimpleNamespace(
        to_dict=lambda: heartbeat or {}
    )

    def where_side_effect(field, op, value):
        assert field == "lifecycle_status"
        w = MagicMock()
        w.count.return_value.get.return_value = [
            [SimpleNamespace(value=counts.get(value, 0))]
        ]
        w.stream.return_value = [
            SimpleNamespace(to_dict=lambda d=d: d)
            for d in in_progress_docs.get(value, [])
        ]
        return w

    case_details = MagicMock()
    case_details.where.side_effect = where_side_effect

    def collection_side_effect(name):
        if name == main._POLL_HEARTBEAT_COLLECTION:
            return heartbeat_collection
        return case_details

    mock_db = MagicMock()
    mock_db.collection.side_effect = collection_side_effect
    monkeypatch.setattr(main, "firestore", SimpleNamespace(client=lambda: mock_db))

    mgr = MagicMock()
    mgr.case_store._is_stale.side_effect = CaseDataStore._is_stale
    monkeypatch.setattr(main, "get_auto_order_manager", lambda: mgr)
    return mock_db


@pytest.mark.asyncio
async def test_queue_status_pipeline_active_is_true_from_a_fresh_heartbeat_alone(
    monkeypatch,
):
    """Proves the fix is cross-instance-safe: pipeline_active becomes True
    purely from what's in Firestore, with zero reliance on any local/
    in-process state -- exactly the condition that was broken before (a
    fresh heartbeat written by "another instance" is indistinguishable here
    from one written by this process, which is the point)."""
    monkeypatch.setattr(main, "_queue_status_cache", {"ts": 0.0, "data": None})
    _wire_queue_status_db(
        monkeypatch, heartbeat={"fetch_last_tick": datetime.now().isoformat()}
    )

    response = await main.get_queue_status(current_user={"uid": "u1"})
    import json

    data = json.loads(response.body)

    assert data["fetch_processing_active"] is True
    assert data["pipeline_active"] is True
    assert data["status"] == "active"


@pytest.mark.asyncio
async def test_queue_status_in_progress_alone_is_not_reported_as_active(monkeypatch):
    """A case sitting at fetch_in_progress does NOT by itself mean a worker
    is touching it right now -- that's exactly what an orphaned case (one
    claimed by an instance the was then CPU-throttled or torn down before
    finishing) looks like. Without a fresh heartbeat, pipeline_active must
    be False even with real, fresh in-progress work -- the honest signal
    for "something is happening" is the heartbeat, not merely a status
    value that could just as easily mean "abandoned"."""
    monkeypatch.setattr(main, "_queue_status_cache", {"ts": 0.0, "data": None})
    _wire_queue_status_db(
        monkeypatch,
        counts={"fetch_in_progress": 5},
        in_progress_docs={
            "fetch_in_progress": [
                {"lifecycle_status_updated_at": datetime.now().isoformat()}
                for _ in range(5)
            ]
        },
    )

    response = await main.get_queue_status(current_user={"uid": "u1"})
    import json

    data = json.loads(response.body)

    assert data["fetch_queue_size"] == 0
    assert data["fetch_in_progress_count"] == 5
    assert data["total_in_progress"] == 5
    assert data["pipeline_active"] is False


@pytest.mark.asyncio
async def test_queue_status_flags_stale_in_progress_cases(monkeypatch):
    """The honest signal for "stuck, not moving": cases sitting at
    fetch_in_progress/analysis_in_progress past STALE_IN_PROGRESS_MINUTES
    with no fresh timestamp -- almost always a worker that claimed a case
    and never got to finish it."""
    from datetime import timedelta

    monkeypatch.setattr(main, "_queue_status_cache", {"ts": 0.0, "data": None})
    old_iso = (datetime.now() - timedelta(hours=1)).isoformat()
    fresh_iso = datetime.now().isoformat()
    _wire_queue_status_db(
        monkeypatch,
        counts={"fetch_in_progress": 2, "analysis_in_progress": 1},
        in_progress_docs={
            "fetch_in_progress": [
                {"lifecycle_status_updated_at": old_iso},
                {"lifecycle_status_updated_at": fresh_iso},
            ],
            "analysis_in_progress": [{"lifecycle_status_updated_at": old_iso}],
        },
    )

    response = await main.get_queue_status(current_user={"uid": "u1"})
    import json

    data = json.loads(response.body)

    assert data["stale_in_progress_count"] == 2


@pytest.mark.asyncio
async def test_queue_status_wakes_the_poll_loops_when_there_is_pending_work(
    monkeypatch,
):
    """Every request here is a chance to nudge the loops awake -- if the
    process is CPU-throttled between requests, the loops' own timer can't
    reliably fire, but handling this request already means the process has
    CPU right now."""
    monkeypatch.setattr(main, "_queue_status_cache", {"ts": 0.0, "data": None})
    _wire_queue_status_db(monkeypatch, counts={"fetch_queued": 3})
    wake_fetch = Mock()
    wake_analysis = Mock()
    monkeypatch.setattr(main, "_wake_fetch_poll", SimpleNamespace(set=wake_fetch))
    monkeypatch.setattr(main, "_wake_analysis_poll", SimpleNamespace(set=wake_analysis))

    await main.get_queue_status(current_user={"uid": "u1"})

    wake_fetch.assert_called_once()
    wake_analysis.assert_called_once()


@pytest.mark.asyncio
async def test_queue_status_does_not_wake_the_poll_loops_when_nothing_is_pending(
    monkeypatch,
):
    monkeypatch.setattr(main, "_queue_status_cache", {"ts": 0.0, "data": None})
    _wire_queue_status_db(monkeypatch)
    wake_fetch = Mock()
    wake_analysis = Mock()
    monkeypatch.setattr(main, "_wake_fetch_poll", SimpleNamespace(set=wake_fetch))
    monkeypatch.setattr(main, "_wake_analysis_poll", SimpleNamespace(set=wake_analysis))

    await main.get_queue_status(current_user={"uid": "u1"})

    wake_fetch.assert_not_called()
    wake_analysis.assert_not_called()


# ---------------------------------------------------------------------------
# 8. _query_claim_candidates backlog tier -- self-feeding the poll loops from
#    board_ingested/fetch_succeeded cases that were never explicitly queued
#    (e.g. bulk-imported board rows), once the primary queue and the stale-
#    reclaim tier both run dry. Without this, cases sitting in those states
#    are invisible to the poll loops no matter how idle they are.
# ---------------------------------------------------------------------------


def _claim_candidates_db(monkeypatch, docs_by_status):
    def where_side_effect(field, op, value):
        mock_query = MagicMock()
        mock_query.limit.return_value.stream.return_value = docs_by_status.get(
            value, []
        )
        return mock_query

    mock_db = MagicMock()
    mock_db.collection.return_value.where.side_effect = where_side_effect
    monkeypatch.setattr(main, "firestore", SimpleNamespace(client=lambda: mock_db))
    return mock_db


def _claim_doc(doc_id, case_ref, updated_at=None):
    return SimpleNamespace(
        id=doc_id,
        to_dict=lambda: {
            "case_ref": case_ref,
            "board_date": "2026-01-05",
            "lifecycle_status_updated_at": updated_at,
        },
    )


def test_query_claim_candidates_pulls_from_backlog_when_queue_is_empty(monkeypatch):
    """fetch_queued and stale fetch_in_progress are both empty -- the backlog
    tier (board_ingested) should fill the batch so the pipeline never goes
    idle just because nothing was ever explicitly queued."""
    _claim_candidates_db(
        monkeypatch,
        {
            "fetch_queued": [],
            "fetch_in_progress": [],
            "board_ingested": [
                _claim_doc("d1", "WP/1/2026"),
                _claim_doc("d2", "WP/2/2026"),
            ],
            "not_linked": [],
        },
    )
    case_store = CaseDataStore(MagicMock())

    candidates = main._query_claim_candidates(
        case_store,
        "fetch_queued",
        "fetch_in_progress",
        10,
        backlog_statuses=("board_ingested", "not_linked"),
    )

    assert [c["case_ref"] for c in candidates] == ["WP/1/2026", "WP/2/2026"]
    assert all(c["_claim_from_status"] == "board_ingested" for c in candidates)


def test_query_claim_candidates_skips_backlog_tier_when_batch_already_full(
    monkeypatch,
):
    """The un-queued backlog can be tens of thousands of cases -- it must
    only be consulted once there's genuinely room left in this tick's batch,
    not scanned on every tick regardless of whether it's needed."""
    mock_db = _claim_candidates_db(
        monkeypatch,
        {
            "fetch_queued": [_claim_doc(f"q{i}", f"WP/{i}/2026") for i in range(3)],
            "board_ingested": [_claim_doc("d1", "WP/99/2026")],
        },
    )
    case_store = CaseDataStore(MagicMock())

    candidates = main._query_claim_candidates(
        case_store,
        "fetch_queued",
        "fetch_in_progress",
        3,
        backlog_statuses=("board_ingested",),
    )

    assert len(candidates) == 3
    assert all(c["_claim_from_status"] == "fetch_queued" for c in candidates)
    queried_statuses = {
        call.args[2] for call in mock_db.collection.return_value.where.call_args_list
    }
    assert "board_ingested" not in queried_statuses


def test_query_claim_candidates_backlog_tops_up_remaining_room_only(monkeypatch):
    """fetch_queued supplies part of the batch; the backlog tier should only
    top up the remainder, never overshoot batch_size."""
    _claim_candidates_db(
        monkeypatch,
        {
            "fetch_queued": [_claim_doc("q1", "WP/1/2026")],
            "fetch_in_progress": [],
            "board_ingested": [
                _claim_doc(f"d{i}", f"WP/{i}/2026") for i in range(2, 6)
            ],
        },
    )
    case_store = CaseDataStore(MagicMock())

    candidates = main._query_claim_candidates(
        case_store,
        "fetch_queued",
        "fetch_in_progress",
        3,
        backlog_statuses=("board_ingested",),
    )

    assert len(candidates) == 3
    assert candidates[0]["case_ref"] == "WP/1/2026"
    assert candidates[0]["_claim_from_status"] == "fetch_queued"
    assert [c["_claim_from_status"] for c in candidates[1:]] == [
        "board_ingested",
        "board_ingested",
    ]


# ---------------------------------------------------------------------------
# 10. POST /internal/queue/tick -- the Cloud Scheduler endpoint that keeps
#     the poll loops alive when nobody has a browser tab open.
#     --min-instances=0 means the pipeline stops entirely with no HTTP
#     traffic at all; require_admin can't be used here because Cloud
#     Scheduler has no way to hold an application user's Firebase ID token.
# ---------------------------------------------------------------------------


def _fake_request(headers):
    return SimpleNamespace(headers=headers)


@pytest.mark.asyncio
async def test_scheduler_tick_503s_when_not_configured(monkeypatch):
    """No SCHEDULER_SHARED_SECRET set -> the endpoint is inert. This must
    be the default (unset) behaviour so deployments that never opted into
    the scheduler see zero change."""
    monkeypatch.setattr(main, "_SCHEDULER_SHARED_SECRET", "")
    with pytest.raises(main.HTTPException) as exc_info:
        await main.scheduler_queue_tick(_fake_request({}))
    assert exc_info.value.status_code == 503


@pytest.mark.asyncio
async def test_scheduler_tick_403s_on_wrong_secret(monkeypatch):
    monkeypatch.setattr(main, "_SCHEDULER_SHARED_SECRET", "correct-secret")
    with pytest.raises(main.HTTPException) as exc_info:
        await main.scheduler_queue_tick(
            _fake_request({"X-Scheduler-Secret": "wrong-secret"})
        )
    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_scheduler_tick_403s_on_missing_header(monkeypatch):
    monkeypatch.setattr(main, "_SCHEDULER_SHARED_SECRET", "correct-secret")
    with pytest.raises(main.HTTPException) as exc_info:
        await main.scheduler_queue_tick(_fake_request({}))
    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_scheduler_tick_wakes_both_poll_loops_on_correct_secret(monkeypatch):
    monkeypatch.setattr(main, "_SCHEDULER_SHARED_SECRET", "correct-secret")
    wake_fetch = Mock()
    wake_analysis = Mock()
    monkeypatch.setattr(main, "_wake_fetch_poll", SimpleNamespace(set=wake_fetch))
    monkeypatch.setattr(main, "_wake_analysis_poll", SimpleNamespace(set=wake_analysis))

    response = await main.scheduler_queue_tick(
        _fake_request({"X-Scheduler-Secret": "correct-secret"})
    )
    import json

    assert json.loads(response.body)["success"] is True
    wake_fetch.assert_called_once()
    wake_analysis.assert_called_once()

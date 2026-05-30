"""Tests for workflow robustness improvements.

Covers:
- Auto-queue for analysis when order fetch succeeds but analysis fails
- DEFAULT_MAX_SEQUENCE_RETRIES reduced to 10
- /jobs/retry-failed endpoint logic
"""

import asyncio
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
    """order_failed case is added to the fetch queue and lifecycle is transitioned."""
    case = _make_mock_case("WP/10/2025", "order_failed")
    mgr = _make_manager([case])

    fetch_queue = asyncio.Queue()
    analysis_queue = asyncio.Queue()

    monkeypatch.setattr(main, "get_auto_order_manager", lambda: mgr)
    monkeypatch.setattr(main, "order_processing_queue", fetch_queue)
    monkeypatch.setattr(main, "analysis_processing_queue", analysis_queue)
    monkeypatch.setattr(main, "ensure_background_processing_active", AsyncMock())
    monkeypatch.setattr(
        main, "ensure_background_analysis_processing_active", AsyncMock()
    )

    response = await main.retry_failed_cases(
        _make_request({"limit": 200}), current_user=None
    )
    body = response.body
    import json

    data = json.loads(body)

    assert data["fetch_queued"] == 1
    assert data["analysis_queued"] == 0
    assert "WP/10/2025" in data["fetch_queued_refs"]
    assert fetch_queue.qsize() == 1
    assert analysis_queue.qsize() == 0

    mgr.case_store.transition_lifecycle.assert_called_once_with(
        "WP/10/2025",
        "fetch_queued",
        metadata={"source": "jobs.retry-failed", "case_id": case["id"]},
        event_type="retry_fetch_queued",
    )


@pytest.mark.asyncio
async def test_retry_failed_linked_with_link_goes_to_analysis_queue(monkeypatch):
    """linked case with stored order_link is routed to the analysis queue."""
    case = _make_mock_case(
        "WP/50/2025", "linked", order_link="https://example.com/order.pdf"
    )
    mgr = _make_manager([case])

    fetch_queue = asyncio.Queue()
    analysis_queue = asyncio.Queue()

    monkeypatch.setattr(main, "get_auto_order_manager", lambda: mgr)
    monkeypatch.setattr(main, "order_processing_queue", fetch_queue)
    monkeypatch.setattr(main, "analysis_processing_queue", analysis_queue)
    monkeypatch.setattr(main, "ensure_background_processing_active", AsyncMock())
    monkeypatch.setattr(
        main, "ensure_background_analysis_processing_active", AsyncMock()
    )

    response = await main.retry_failed_cases(
        _make_request({"limit": 200}), current_user=None
    )
    import json

    data = json.loads(response.body)

    assert data["analysis_queued"] == 1
    assert data["fetch_queued"] == 0
    assert "WP/50/2025" in data["analysis_queued_refs"]
    assert analysis_queue.qsize() == 1
    assert fetch_queue.qsize() == 0

    mgr.case_store.transition_lifecycle.assert_called_once_with(
        "WP/50/2025",
        "analysis_queued",
        metadata={"source": "jobs.retry-failed", "case_id": case["id"]},
        event_type="retry_analysis_queued",
    )


@pytest.mark.asyncio
async def test_retry_failed_linked_without_link_falls_back_to_fetch_queue(monkeypatch):
    """linked case without a stored order_link falls back to the fetch queue."""
    case = _make_mock_case("WP/60/2025", "linked", order_link=None)
    mgr = _make_manager([case])

    fetch_queue = asyncio.Queue()
    analysis_queue = asyncio.Queue()

    monkeypatch.setattr(main, "get_auto_order_manager", lambda: mgr)
    monkeypatch.setattr(main, "order_processing_queue", fetch_queue)
    monkeypatch.setattr(main, "analysis_processing_queue", analysis_queue)
    monkeypatch.setattr(main, "ensure_background_processing_active", AsyncMock())
    monkeypatch.setattr(
        main, "ensure_background_analysis_processing_active", AsyncMock()
    )

    response = await main.retry_failed_cases(
        _make_request({"limit": 200}), current_user=None
    )
    import json

    data = json.loads(response.body)

    assert data["fetch_queued"] == 1
    assert data["analysis_queued"] == 0
    assert "WP/60/2025" in data["fetch_queued_refs"]
    assert fetch_queue.qsize() == 1
    assert analysis_queue.qsize() == 0


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

    fetch_queue = asyncio.Queue()
    analysis_queue = asyncio.Queue()

    monkeypatch.setattr(main, "get_auto_order_manager", lambda: mgr)
    monkeypatch.setattr(main, "order_processing_queue", fetch_queue)
    monkeypatch.setattr(main, "analysis_processing_queue", analysis_queue)
    monkeypatch.setattr(main, "ensure_background_processing_active", AsyncMock())
    monkeypatch.setattr(
        main, "ensure_background_analysis_processing_active", AsyncMock()
    )

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
    """order_analysis_failed without a stored link falls back to the fetch queue."""
    case = _make_mock_case("WP/30/2025", "order_analysis_failed", order_link=None)
    mgr = _make_manager([case])

    fetch_queue = asyncio.Queue()
    analysis_queue = asyncio.Queue()

    monkeypatch.setattr(main, "get_auto_order_manager", lambda: mgr)
    monkeypatch.setattr(main, "order_processing_queue", fetch_queue)
    monkeypatch.setattr(main, "analysis_processing_queue", analysis_queue)
    monkeypatch.setattr(main, "ensure_background_processing_active", AsyncMock())
    monkeypatch.setattr(
        main, "ensure_background_analysis_processing_active", AsyncMock()
    )

    response = await main.retry_failed_cases(
        _make_request({"limit": 200}), current_user=None
    )
    import json

    data = json.loads(response.body)

    assert data["fetch_queued"] == 1
    assert data["analysis_queued"] == 0
    assert "WP/30/2025" in data["fetch_queued_refs"]
    assert fetch_queue.qsize() == 1
    assert analysis_queue.qsize() == 0

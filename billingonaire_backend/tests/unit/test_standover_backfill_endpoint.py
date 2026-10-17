"""Tests for POST /admin/orders/standover-backfill (main.admin_standover_backfill)."""

import sys
import types
from unittest.mock import MagicMock

import pytest

# Stub spaCy before any main import so the import-time crash is avoided,
# same pattern as test_compliance_scan_endpoint.py.
if "spacy" not in sys.modules:
    _spacy_stub = types.ModuleType("spacy")
    _spacy_matcher_stub = types.ModuleType("spacy.matcher")

    class _Matcher:  # pragma: no cover
        pass

    _spacy_matcher_stub.Matcher = _Matcher
    _spacy_stub.matcher = _spacy_matcher_stub
    sys.modules["spacy"] = _spacy_stub
    sys.modules["spacy.matcher"] = _spacy_matcher_stub

import main


def _mock_manager(scan_result, apply_result=None):
    manager = MagicMock()
    manager.find_standover_backfill_candidates.return_value = scan_result
    if apply_result is not None:
        manager.apply_standover_backfill.return_value = apply_result
    return manager


@pytest.mark.asyncio
async def test_dry_run_scans_but_never_applies(monkeypatch):
    scan_result = {
        "scanned": 3,
        "candidates_found": 1,
        "no_stored_text": 0,
        "errors": 0,
        "candidates": [
            {
                "case_ref": "WP/1/2026",
                "order_date": "2026-09-30",
                "board_date": "2026-09-30",
                "old_category": "HEARD_AND_ADJOURNED",
                "new_confidence": 0.9,
            }
        ],
    }
    manager = _mock_manager(scan_result)
    monkeypatch.setattr(main, "get_auto_order_manager", lambda: manager)

    response = await main.admin_standover_backfill(
        start_date="2026-07-01",
        end_date="2026-09-30",
        dry_run=True,
        limit=500,
        current_user={"uid": "admin1"},
    )

    import json

    body = json.loads(response.body)
    assert body["dry_run"] is True
    assert body["scanned"] == 3
    assert body["candidates_found"] == 1
    assert "apply" not in body
    manager.find_standover_backfill_candidates.assert_called_once_with(
        "2026-07-01", "2026-09-30", 500
    )
    manager.apply_standover_backfill.assert_not_called()


@pytest.mark.asyncio
async def test_apply_writes_the_candidates_found_by_the_scan(monkeypatch):
    scan_result = {
        "scanned": 2,
        "candidates_found": 2,
        "no_stored_text": 0,
        "errors": 0,
        "candidates": [
            {"case_ref": "WP/1/2026", "order_date": "2026-09-30"},
            {"case_ref": "WP/2/2026", "order_date": "2026-09-29"},
        ],
    }
    apply_result = {
        "applied": 2,
        "unchanged": 0,
        "errors": 0,
        "results": [
            {"resolved": True, "new_category": "STAND_OVER"},
            {"resolved": True, "new_category": "STAND_OVER"},
        ],
    }
    manager = _mock_manager(scan_result, apply_result)
    monkeypatch.setattr(main, "get_auto_order_manager", lambda: manager)

    response = await main.admin_standover_backfill(
        start_date="2026-07-01",
        end_date="2026-09-30",
        dry_run=False,
        limit=500,
        current_user={"uid": "admin1"},
    )

    import json

    body = json.loads(response.body)
    assert body["dry_run"] is False
    assert body["candidates_found"] == 2
    assert body["apply"]["applied"] == 2
    manager.apply_standover_backfill.assert_called_once_with(scan_result["candidates"])


@pytest.mark.asyncio
async def test_apply_with_no_candidates_skips_the_write_call_entirely(monkeypatch):
    """dry_run=False but the scan found nothing to reclassify -- no reason
    to call apply_standover_backfill (and its own Firestore writes) at all."""
    scan_result = {
        "scanned": 5,
        "candidates_found": 0,
        "no_stored_text": 0,
        "errors": 0,
        "candidates": [],
    }
    manager = _mock_manager(scan_result)
    monkeypatch.setattr(main, "get_auto_order_manager", lambda: manager)

    response = await main.admin_standover_backfill(
        start_date="2026-07-01",
        end_date="2026-09-30",
        dry_run=False,
        limit=500,
        current_user={"uid": "admin1"},
    )

    import json

    body = json.loads(response.body)
    assert body["dry_run"] is False
    assert body["candidates_found"] == 0
    assert "apply" not in body
    manager.apply_standover_backfill.assert_not_called()


@pytest.mark.asyncio
async def test_scan_failure_returns_500_not_a_raised_exception(monkeypatch):
    manager = MagicMock()
    manager.find_standover_backfill_candidates.side_effect = RuntimeError("boom")
    monkeypatch.setattr(main, "get_auto_order_manager", lambda: manager)

    response = await main.admin_standover_backfill(
        start_date="2026-07-01",
        end_date="2026-09-30",
        dry_run=True,
        limit=500,
        current_user={"uid": "admin1"},
    )

    assert response.status_code == 500

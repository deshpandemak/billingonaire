"""Tests for POST /compliance/scan (main.compliance_scan)."""

import sys
import types
from unittest.mock import MagicMock, Mock, patch

import pytest
from fastapi import HTTPException

# Stub spaCy before any main import so the import-time crash is avoided,
# same pattern as test_order_pdf_endpoints.py.
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


def _row(
    case_ref="WP/1/2026",
    board_date="2026-07-08",
    order_date="2026-07-08",
    order_category="HEARD_AND_ADJOURNED",
    order_link="https://storage.example/order.pdf",
    order_text_url="https://storage.googleapis.com/bucket/order.txt",
    cached_directives=None,
):
    order_entry = {
        "board_date": board_date,
        "order_date": order_date,
        "order_link": order_link,
        "order_text_url": order_text_url,
    }
    if cached_directives is not None:
        order_entry["compliance_directives"] = cached_directives
    return {
        "case_ref": case_ref,
        "board_date": board_date,
        "order_date": order_date,
        "order_category": order_category,
        "order_link": order_link,
        "order_history": [order_entry],
    }


def _mock_user_manager(is_admin=False, agp_filter="Pooja Deshpande"):
    um = MagicMock()
    um.is_admin.return_value = is_admin
    um.get_user_agp_filter.return_value = agp_filter
    return um


def _mock_board(rows):
    board_instance = MagicMock()
    board_instance.getData.return_value = rows
    board_cls = Mock(return_value=board_instance)
    return board_cls, board_instance


def _mock_auto_mgr(
    downloaded_text="AGP appeared. File reply affidavit by 13th August.",
):
    mgr = MagicMock()
    mgr._download_gcs_text.return_value = downloaded_text
    return mgr


@pytest.mark.asyncio
async def test_non_admin_cannot_scan_for_another_user(monkeypatch):
    monkeypatch.setattr(
        main, "get_user_manager", lambda: _mock_user_manager(is_admin=False)
    )
    with pytest.raises(HTTPException) as exc_info:
        await main.compliance_scan(
            start_date="2026-07-01",
            end_date="2026-07-31",
            user_name="Someone Else",
            current_user_with_profile={"uid": "u1"},
        )
    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_adjourned_rows_are_skipped_entirely(monkeypatch):
    rows = [_row(order_category="ADJOURNED")]
    board_cls, board_instance = _mock_board(rows)
    monkeypatch.setattr(main, "Board", board_cls)
    monkeypatch.setattr(main, "get_user_manager", lambda: _mock_user_manager())
    monkeypatch.setattr(main, "get_auto_order_manager", lambda: _mock_auto_mgr())
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")

    with patch("compliance_extractor.extract_directives") as extract:
        result = await main.compliance_scan(
            start_date="2026-07-01",
            end_date="2026-07-31",
            user_name=None,
            current_user_with_profile={"uid": "u1"},
        )

    extract.assert_not_called()
    assert result["count"] == 0
    assert result["disposed_count"] == 0


@pytest.mark.asyncio
async def test_heard_and_adjourned_order_gets_scanned_and_cached(monkeypatch):
    rows = [_row(order_category="HEARD_AND_ADJOURNED")]
    board_cls, board_instance = _mock_board(rows)
    monkeypatch.setattr(main, "Board", board_cls)
    monkeypatch.setattr(main, "get_user_manager", lambda: _mock_user_manager())
    mgr = _mock_auto_mgr()
    monkeypatch.setattr(main, "get_auto_order_manager", lambda: mgr)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")

    directives = [
        {
            "directive_type": "FILE_REPLY_AFFIDAVIT",
            "description": "file reply affidavit by 13th August",
            "deadline_date": "2026-08-13",
        }
    ]
    with patch(
        "compliance_extractor.extract_directives", return_value=directives
    ) as extract:
        result = await main.compliance_scan(
            start_date="2026-07-01",
            end_date="2026-07-31",
            user_name=None,
            current_user_with_profile={"uid": "u1"},
        )

    extract.assert_called_once()
    assert result["count"] == 1
    assert result["newly_scanned"] == 1
    assert result["results"][0]["directives"] == directives
    mgr.case_store.set_order_compliance_directives.assert_called_once_with(
        "WP/1/2026",
        "https://storage.example/order.pdf",
        "2026-07-08",
        directives,
    )


@pytest.mark.asyncio
async def test_cached_directives_skip_a_second_llm_call(monkeypatch):
    cached = [
        {
            "directive_type": "FILE_REPLY_AFFIDAVIT",
            "description": "already extracted",
            "deadline_date": "2026-08-13",
        }
    ]
    rows = [_row(order_category="HEARD_AND_ADJOURNED", cached_directives=cached)]
    board_cls, board_instance = _mock_board(rows)
    monkeypatch.setattr(main, "Board", board_cls)
    monkeypatch.setattr(main, "get_user_manager", lambda: _mock_user_manager())
    mgr = _mock_auto_mgr()
    monkeypatch.setattr(main, "get_auto_order_manager", lambda: mgr)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")

    with patch("compliance_extractor.extract_directives") as extract:
        result = await main.compliance_scan(
            start_date="2026-07-01",
            end_date="2026-07-31",
            user_name=None,
            current_user_with_profile={"uid": "u1"},
        )

    extract.assert_not_called()
    mgr.case_store.set_order_compliance_directives.assert_not_called()
    assert result["newly_scanned"] == 0
    assert result["results"][0]["directives"] == cached


@pytest.mark.asyncio
async def test_disposed_case_is_reported_even_without_a_directive(monkeypatch):
    rows = [_row(order_category="DISPOSED_OFF", cached_directives=[])]
    board_cls, board_instance = _mock_board(rows)
    monkeypatch.setattr(main, "Board", board_cls)
    monkeypatch.setattr(main, "get_user_manager", lambda: _mock_user_manager())
    monkeypatch.setattr(main, "get_auto_order_manager", lambda: _mock_auto_mgr())
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")

    result = await main.compliance_scan(
        start_date="2026-07-01",
        end_date="2026-07-31",
        user_name=None,
        current_user_with_profile={"uid": "u1"},
    )

    assert result["disposed_count"] == 1
    assert result["count"] == 1
    assert result["results"][0]["order_category"] == "DISPOSED_OFF"


@pytest.mark.asyncio
async def test_legacy_category_spelling_is_recognised(monkeypatch):
    rows = [_row(order_category="WP DISPOSED OF", cached_directives=[])]
    board_cls, board_instance = _mock_board(rows)
    monkeypatch.setattr(main, "Board", board_cls)
    monkeypatch.setattr(main, "get_user_manager", lambda: _mock_user_manager())
    monkeypatch.setattr(main, "get_auto_order_manager", lambda: _mock_auto_mgr())
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")

    result = await main.compliance_scan(
        start_date="2026-07-01",
        end_date="2026-07-31",
        user_name=None,
        current_user_with_profile={"uid": "u1"},
    )

    assert result["disposed_count"] == 1
    assert result["results"][0]["order_category"] == "DISPOSED_OFF"


@pytest.mark.asyncio
async def test_without_gemini_key_disposed_cases_still_show_but_no_extraction_runs(
    monkeypatch,
):
    rows = [
        _row(case_ref="WP/1/2026", order_category="DISPOSED_OFF"),
        _row(case_ref="WP/2/2026", order_category="HEARD_AND_ADJOURNED"),
    ]
    board_cls, board_instance = _mock_board(rows)
    monkeypatch.setattr(main, "Board", board_cls)
    monkeypatch.setattr(main, "get_user_manager", lambda: _mock_user_manager())
    monkeypatch.setattr(main, "get_auto_order_manager", lambda: _mock_auto_mgr())
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    with patch("compliance_extractor.extract_directives") as extract:
        result = await main.compliance_scan(
            start_date="2026-07-01",
            end_date="2026-07-31",
            user_name=None,
            current_user_with_profile={"uid": "u1"},
        )

    extract.assert_not_called()
    assert result["ai_available"] is False
    assert result["disposed_count"] == 1
    # DISPOSED_OFF still reported (no directive needed to show it); the
    # HEARD_AND_ADJOURNED row has no cached directives and none could be
    # extracted, so it is correctly left out of the results.
    assert result["count"] == 1
    assert result["results"][0]["order_category"] == "DISPOSED_OFF"


@pytest.mark.asyncio
async def test_extraction_failure_is_counted_and_does_not_crash_the_scan(monkeypatch):
    rows = [_row(order_category="HEARD_AND_ADJOURNED")]
    board_cls, board_instance = _mock_board(rows)
    monkeypatch.setattr(main, "Board", board_cls)
    monkeypatch.setattr(main, "get_user_manager", lambda: _mock_user_manager())
    monkeypatch.setattr(main, "get_auto_order_manager", lambda: _mock_auto_mgr())
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")

    with patch(
        "compliance_extractor.extract_directives", side_effect=RuntimeError("timeout")
    ):
        result = await main.compliance_scan(
            start_date="2026-07-01",
            end_date="2026-07-31",
            user_name=None,
            current_user_with_profile={"uid": "u1"},
        )

    assert result["llm_errors"] == 1
    assert result["count"] == 0


@pytest.mark.asyncio
async def test_admin_can_scan_for_a_named_agp(monkeypatch):
    rows = [_row(order_category="DISPOSED_OFF", cached_directives=[])]
    board_cls, board_instance = _mock_board(rows)
    monkeypatch.setattr(main, "Board", board_cls)
    monkeypatch.setattr(
        main, "get_user_manager", lambda: _mock_user_manager(is_admin=True)
    )
    monkeypatch.setattr(main, "get_auto_order_manager", lambda: _mock_auto_mgr())
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")

    await main.compliance_scan(
        start_date="2026-07-01",
        end_date="2026-07-31",
        user_name="Pooja Deshpande",
        current_user_with_profile={"uid": "admin1"},
    )

    board_instance.getData.assert_called_once_with(
        {"startDate": "2026-07-01", "endDate": "2026-07-31"}, "Pooja Deshpande"
    )


@pytest.mark.asyncio
async def test_row_with_no_date_matched_order_entry_is_skipped(monkeypatch):
    row = _row(order_category="HEARD_AND_ADJOURNED")
    # Corrupt the only order_history entry's board_date so it no longer
    # matches the row's own board_date -- simulates stale/mismatched data.
    row["order_history"][0]["board_date"] = "2020-01-01"
    board_cls, board_instance = _mock_board([row])
    monkeypatch.setattr(main, "Board", board_cls)
    monkeypatch.setattr(main, "get_user_manager", lambda: _mock_user_manager())
    monkeypatch.setattr(main, "get_auto_order_manager", lambda: _mock_auto_mgr())
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")

    with patch("compliance_extractor.extract_directives") as extract:
        result = await main.compliance_scan(
            start_date="2026-07-01",
            end_date="2026-07-31",
            user_name=None,
            current_user_with_profile={"uid": "u1"},
        )

    extract.assert_not_called()
    assert result["count"] == 0

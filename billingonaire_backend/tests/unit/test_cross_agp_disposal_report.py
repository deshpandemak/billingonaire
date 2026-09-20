"""Tests for POST /reports/cross-agp-disposals (main.cross_agp_disposal_report)."""

import sys
import types
from unittest.mock import MagicMock, Mock, patch

import pytest
from fastapi import HTTPException

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


def _order(order_date, order_category, government_pleader=None, order_link=None):
    return {
        "order_date": order_date,
        "board_date": order_date,
        "order_category": order_category,
        "government_pleader": government_pleader or [],
        "order_link": order_link or f"https://storage.example/{order_date}.pdf",
    }


def _row(case_ref, order_history):
    """A single Board.getData()-shaped row. Real rows repeat once per
    hearing date, but every one carries the SAME full order_history for
    the case -- the report only needs one row per case to see it all."""
    return {"case_ref": case_ref, "order_history": order_history}


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


def _mock_auto_mgr():
    mgr = MagicMock()
    # Real CaseDataStore._to_iso_date is a pure string-format normaliser;
    # every date in these fixtures is already YYYY-MM-DD, so a pass-through
    # is a faithful stand-in without needing a real CaseDataStore/Firestore.
    mgr.case_store._to_iso_date.side_effect = lambda v: v
    return mgr


@pytest.mark.asyncio
async def test_non_admin_cannot_run_report_for_another_user(monkeypatch):
    monkeypatch.setattr(
        main, "get_user_manager", lambda: _mock_user_manager(is_admin=False)
    )
    with pytest.raises(HTTPException) as exc_info:
        await main.cross_agp_disposal_report(
            start_date="2026-07-01",
            end_date="2026-09-30",
            user_name="Someone Else",
            current_user_with_profile={"uid": "u1"},
        )
    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_flags_a_case_disposed_under_a_different_agp(monkeypatch):
    """The example from the report: Pooja appeared HEARD_AND_ADJOURNED on
    2026-08-07, but the matter was disposed on 2026-09-08 under Rajan
    Pawar's name instead."""
    rows = [
        _row(
            "WP/1/2026",
            [
                _order(
                    "2026-08-07",
                    "HEARD_AND_ADJOURNED",
                    government_pleader=["Pooja Makarand Joshi Deshpande"],
                ),
                _order(
                    "2026-09-08",
                    "DISPOSED_OFF",
                    government_pleader=["Rajan Pawar"],
                    order_link="https://storage.example/disposal.pdf",
                ),
            ],
        )
    ]
    board_cls, _ = _mock_board(rows)
    monkeypatch.setattr(main, "Board", board_cls)
    monkeypatch.setattr(main, "get_user_manager", lambda: _mock_user_manager())
    monkeypatch.setattr(main, "get_auto_order_manager", lambda: _mock_auto_mgr())

    result = await main.cross_agp_disposal_report(
        start_date="2026-07-01",
        end_date="2026-09-30",
        user_name=None,
        current_user_with_profile={"uid": "u1"},
    )

    assert result["cases_checked"] == 1
    assert result["flagged_count"] == 1
    flagged = result["results"][0]
    assert flagged["case_ref"] == "WP/1/2026"
    assert flagged["appearances_count"] == 1
    assert flagged["appearances"][0]["date"] == "2026-08-07"
    assert flagged["appearances"][0]["category"] == "HEARD_AND_ADJOURNED"
    assert flagged["disposal_date"] == "2026-09-08"
    assert flagged["disposal_board_date"] == "2026-09-08"
    assert flagged["disposal_agp_names"] == ["Rajan Pawar"]
    assert flagged["order_link"] == "https://storage.example/disposal.pdf"


@pytest.mark.asyncio
async def test_disposal_board_date_used_for_pdf_link_can_differ_from_order_date(
    monkeypatch,
):
    """The daily-boards doc id (and so the /orders/pdf/{doc_id} proxy link)
    is keyed by board_date, not order_date -- usually the same hearing but
    not guaranteed identical, so the report must expose board_date
    separately rather than only the order's own date."""
    rows = [
        _row(
            "WP/10/2026",
            [
                _order(
                    "2026-08-07",
                    "HEARD_AND_ADJOURNED",
                    government_pleader=["Pooja Deshpande"],
                ),
                {
                    "order_date": "2026-09-10",
                    "board_date": "2026-09-08",
                    "order_category": "DISPOSED_OFF",
                    "government_pleader": ["Rajan Pawar"],
                    "order_link": "https://storage.example/disposal.pdf",
                },
            ],
        )
    ]
    board_cls, _ = _mock_board(rows)
    monkeypatch.setattr(main, "Board", board_cls)
    monkeypatch.setattr(main, "get_user_manager", lambda: _mock_user_manager())
    monkeypatch.setattr(main, "get_auto_order_manager", lambda: _mock_auto_mgr())

    result = await main.cross_agp_disposal_report(
        start_date="2026-07-01",
        end_date="2026-09-30",
        user_name=None,
        current_user_with_profile={"uid": "u1"},
    )

    flagged = result["results"][0]
    assert flagged["disposal_date"] == "2026-09-10"
    assert flagged["disposal_board_date"] == "2026-09-08"


@pytest.mark.asyncio
async def test_not_flagged_when_same_agp_disposed_it(monkeypatch):
    rows = [
        _row(
            "WP/2/2026",
            [
                _order(
                    "2026-08-07",
                    "HEARD_AND_ADJOURNED",
                    government_pleader=["Pooja Makarand Joshi Deshpande"],
                ),
                _order(
                    "2026-09-08",
                    "DISPOSED_OFF",
                    government_pleader=["Pooja Deshpande"],
                ),
            ],
        )
    ]
    board_cls, _ = _mock_board(rows)
    monkeypatch.setattr(main, "Board", board_cls)
    monkeypatch.setattr(main, "get_user_manager", lambda: _mock_user_manager())
    monkeypatch.setattr(main, "get_auto_order_manager", lambda: _mock_auto_mgr())

    result = await main.cross_agp_disposal_report(
        start_date="2026-07-01",
        end_date="2026-09-30",
        user_name=None,
        current_user_with_profile={"uid": "u1"},
    )

    assert result["flagged_count"] == 0
    assert result["already_disposed_by_same_agp"] == 1


@pytest.mark.asyncio
async def test_not_flagged_when_disposal_names_no_one(monkeypatch):
    """A terse disposal order ('Rule made absolute') with no appearance
    recorded can't be proven to be a different AGP -- excluded rather than
    guessed at, and counted separately for transparency."""
    rows = [
        _row(
            "WP/3/2026",
            [
                _order(
                    "2026-08-07",
                    "HEARD_AND_ADJOURNED",
                    government_pleader=["Pooja Deshpande"],
                ),
                _order("2026-09-08", "DISPOSED_OFF", government_pleader=[]),
            ],
        )
    ]
    board_cls, _ = _mock_board(rows)
    monkeypatch.setattr(main, "Board", board_cls)
    monkeypatch.setattr(main, "get_user_manager", lambda: _mock_user_manager())
    monkeypatch.setattr(main, "get_auto_order_manager", lambda: _mock_auto_mgr())

    result = await main.cross_agp_disposal_report(
        start_date="2026-07-01",
        end_date="2026-09-30",
        user_name=None,
        current_user_with_profile={"uid": "u1"},
    )

    assert result["flagged_count"] == 0
    assert result["disposal_agp_unnamed"] == 1


@pytest.mark.asyncio
async def test_not_flagged_when_case_not_disposed_yet(monkeypatch):
    rows = [
        _row(
            "WP/4/2026",
            [
                _order(
                    "2026-08-07",
                    "HEARD_AND_ADJOURNED",
                    government_pleader=["Pooja Deshpande"],
                ),
            ],
        )
    ]
    board_cls, _ = _mock_board(rows)
    monkeypatch.setattr(main, "Board", board_cls)
    monkeypatch.setattr(main, "get_user_manager", lambda: _mock_user_manager())
    monkeypatch.setattr(main, "get_auto_order_manager", lambda: _mock_auto_mgr())

    result = await main.cross_agp_disposal_report(
        start_date="2026-07-01",
        end_date="2026-09-30",
        user_name=None,
        current_user_with_profile={"uid": "u1"},
    )

    assert result["flagged_count"] == 0
    assert result["no_disposal_yet"] == 1


@pytest.mark.asyncio
async def test_not_flagged_when_agp_never_appeared_before_disposal(monkeypatch):
    """The selected AGP has no appearance on record before the disposal
    date -- nothing to compare the disposal against, so this must not be
    reported as a mismatch."""
    rows = [
        _row(
            "WP/5/2026",
            [
                _order(
                    "2026-09-08", "DISPOSED_OFF", government_pleader=["Rajan Pawar"]
                ),
            ],
        )
    ]
    board_cls, _ = _mock_board(rows)
    monkeypatch.setattr(main, "Board", board_cls)
    monkeypatch.setattr(main, "get_user_manager", lambda: _mock_user_manager())
    monkeypatch.setattr(main, "get_auto_order_manager", lambda: _mock_auto_mgr())

    result = await main.cross_agp_disposal_report(
        start_date="2026-07-01",
        end_date="2026-09-30",
        user_name=None,
        current_user_with_profile={"uid": "u1"},
    )

    assert result["flagged_count"] == 0


@pytest.mark.asyncio
async def test_multiple_board_rows_for_same_case_counted_once(monkeypatch):
    """A case adjourned repeatedly appears as multiple Board.getData rows
    (one per hearing date) but shares one order_history -- must be
    deduplicated to a single case in the report."""
    order_history = [
        _order(
            "2026-07-10", "HEARD_AND_ADJOURNED", government_pleader=["Pooja Deshpande"]
        ),
        _order(
            "2026-08-07", "HEARD_AND_ADJOURNED", government_pleader=["Pooja Deshpande"]
        ),
        _order("2026-09-08", "DISPOSED_OFF", government_pleader=["Rajan Pawar"]),
    ]
    rows = [
        _row("WP/6/2026", order_history),
        _row("WP/6/2026", order_history),
    ]
    board_cls, _ = _mock_board(rows)
    monkeypatch.setattr(main, "Board", board_cls)
    monkeypatch.setattr(main, "get_user_manager", lambda: _mock_user_manager())
    monkeypatch.setattr(main, "get_auto_order_manager", lambda: _mock_auto_mgr())

    result = await main.cross_agp_disposal_report(
        start_date="2026-07-01",
        end_date="2026-09-30",
        user_name=None,
        current_user_with_profile={"uid": "u1"},
    )

    assert result["cases_checked"] == 1
    assert result["flagged_count"] == 1
    assert result["results"][0]["appearances_count"] == 2


@pytest.mark.asyncio
async def test_results_sorted_by_most_recent_disposal_first(monkeypatch):
    rows = [
        _row(
            "WP/7/2026",
            [
                _order(
                    "2026-06-01",
                    "HEARD_AND_ADJOURNED",
                    government_pleader=["Pooja Deshpande"],
                ),
                _order(
                    "2026-07-01", "DISPOSED_OFF", government_pleader=["Rajan Pawar"]
                ),
            ],
        ),
        _row(
            "WP/8/2026",
            [
                _order(
                    "2026-06-01",
                    "HEARD_AND_ADJOURNED",
                    government_pleader=["Pooja Deshpande"],
                ),
                _order(
                    "2026-09-01", "DISPOSED_OFF", government_pleader=["Rajan Pawar"]
                ),
            ],
        ),
    ]
    board_cls, _ = _mock_board(rows)
    monkeypatch.setattr(main, "Board", board_cls)
    monkeypatch.setattr(main, "get_user_manager", lambda: _mock_user_manager())
    monkeypatch.setattr(main, "get_auto_order_manager", lambda: _mock_auto_mgr())

    result = await main.cross_agp_disposal_report(
        start_date="2026-06-01",
        end_date="2026-09-30",
        user_name=None,
        current_user_with_profile={"uid": "u1"},
    )

    assert [r["case_ref"] for r in result["results"]] == ["WP/8/2026", "WP/7/2026"]


@pytest.mark.asyncio
async def test_admin_can_run_report_for_a_specific_agp(monkeypatch):
    rows = [
        _row(
            "WP/9/2026",
            [
                _order(
                    "2026-08-07",
                    "HEARD_AND_ADJOURNED",
                    government_pleader=["Rajan Pawar"],
                ),
                _order(
                    "2026-09-08", "DISPOSED_OFF", government_pleader=["Someone Else"]
                ),
            ],
        )
    ]
    board_cls, board_instance = _mock_board(rows)
    monkeypatch.setattr(main, "Board", board_cls)
    monkeypatch.setattr(
        main, "get_user_manager", lambda: _mock_user_manager(is_admin=True)
    )
    monkeypatch.setattr(main, "get_auto_order_manager", lambda: _mock_auto_mgr())

    with patch.object(main, "_resolve_compliance_scan_access") as mock_resolve:
        mock_resolve.return_value = "Rajan Pawar"
        result = await main.cross_agp_disposal_report(
            start_date="2026-07-01",
            end_date="2026-09-30",
            user_name="Rajan Pawar",
            current_user_with_profile={"uid": "admin1"},
        )

    mock_resolve.assert_called_once_with("Rajan Pawar", {"uid": "admin1"})
    board_instance.getData.assert_called_once_with(
        {"startDate": "2026-07-01", "endDate": "2026-09-30"}, "Rajan Pawar"
    )
    assert result["flagged_count"] == 1

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

# Captured before the autouse fixture below can stub it out on the module --
# the tests in the "_board_assigned_names_for_case_date" section test this
# function directly and must call the real implementation.
_real_board_assigned_names_for_case_date = main._board_assigned_names_for_case_date


def _order(
    order_date,
    order_category,
    government_pleader=None,
    order_link=None,
    board_date=None,
):
    return {
        "order_date": order_date,
        "board_date": board_date or order_date,
        "order_category": order_category,
        "government_pleader": government_pleader or [],
        "order_link": order_link or f"https://storage.example/{order_date}.pdf",
    }


def _row(case_ref, board_date, order_category, order_history):
    """A single Board.getData()-shaped row for ONE hearing date where
    Board.getData has ALREADY matched the selected AGP via its own
    order-GP-or-board-GP union logic -- appearances are derived directly
    from these rows (board_date/order_category), not by re-checking
    government_pleader against order_history here. A case the selected
    AGP disposed under someone else's name never gets a row for THAT
    date, since Board.getData wouldn't have matched it."""
    return {
        "case_ref": case_ref,
        "board_date": board_date,
        "order_category": order_category,
        "order_history": order_history,
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


def _mock_auto_mgr():
    mgr = MagicMock()
    # Real CaseDataStore._to_iso_date is a pure string-format normaliser;
    # every date in these fixtures is already YYYY-MM-DD, so a pass-through
    # is a faithful stand-in without needing a real CaseDataStore/Firestore.
    mgr.case_store._to_iso_date.side_effect = lambda v: v
    return mgr


@pytest.fixture(autouse=True)
def _no_board_fallback_lookup(monkeypatch):
    """_board_assigned_names_for_case_date does a live Firestore GET --
    default it to "nothing found" for every test so a case with a genuinely
    unnamed disposal doesn't accidentally succeed via a real network call.
    Tests exercising the fallback itself override this explicitly."""
    monkeypatch.setattr(main, "_board_assigned_names_for_case_date", lambda *a, **k: [])


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
    Pawar's name instead. Board.getData never returns a row for the
    disposal hearing itself -- Pooja wasn't matched to it -- so the
    disposal is only visible via the case's order_history."""
    order_history = [
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
    ]
    rows = [_row("WP/1/2026", "2026-08-07", "HEARD_AND_ADJOURNED", order_history)]
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
async def test_query_uses_exact_selected_date_range_no_lookback(monkeypatch):
    """Board.getData is queried with exactly the user-selected range --
    no widened lookback. An appearance the selected AGP made outside that
    range simply isn't in scope; the caller should pick a wider range to
    include it."""
    order_history = [
        _order(
            "2026-07-10",
            "HEARD_AND_ADJOURNED",
            government_pleader=["Pooja Deshpande"],
        ),
        _order("2026-09-08", "DISPOSED_OFF", government_pleader=["Rajan Pawar"]),
    ]
    rows = [_row("WP/11/2026", "2026-07-10", "HEARD_AND_ADJOURNED", order_history)]
    board_cls, board_instance = _mock_board(rows)
    monkeypatch.setattr(main, "Board", board_cls)
    monkeypatch.setattr(main, "get_user_manager", lambda: _mock_user_manager())
    monkeypatch.setattr(main, "get_auto_order_manager", lambda: _mock_auto_mgr())

    result = await main.cross_agp_disposal_report(
        start_date="2026-07-01",
        end_date="2026-09-30",
        user_name=None,
        current_user_with_profile={"uid": "u1"},
    )

    search_criteria = board_instance.getData.call_args[0][0]
    assert search_criteria["startDate"] == "2026-07-01"
    assert search_criteria["endDate"] == "2026-09-30"
    assert result["flagged_count"] == 1
    assert result["results"][0]["appearances"][0]["date"] == "2026-07-10"


@pytest.mark.asyncio
async def test_disposal_outside_the_selected_range_is_excluded(monkeypatch):
    """A case's order_history can still contain a disposal entry that
    falls outside [start_date, end_date] even when Board.getData matched
    a row for it (e.g. a case with several hearings, only some of which
    are in range) -- that disposal isn't what the user asked to see, so
    it must be excluded from the flagged list (and counted separately)."""
    order_history = [
        _order(
            "2025-01-10",
            "HEARD_AND_ADJOURNED",
            government_pleader=["Pooja Deshpande"],
        ),
        _order("2025-02-01", "DISPOSED_OFF", government_pleader=["Rajan Pawar"]),
    ]
    rows = [_row("WP/12/2026", "2025-01-10", "HEARD_AND_ADJOURNED", order_history)]
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
    assert result["disposed_outside_range"] == 1


@pytest.mark.asyncio
async def test_not_flagged_when_same_agp_disposed_it(monkeypatch):
    order_history = [
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
    ]
    rows = [
        _row("WP/2/2026", "2026-08-07", "HEARD_AND_ADJOURNED", order_history),
        _row("WP/2/2026", "2026-09-08", "DISPOSED_OFF", order_history),
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
    recorded, and no board assignment on file either, can't be proven to
    be a different AGP -- excluded rather than guessed at, and counted
    separately for transparency."""
    order_history = [
        _order(
            "2026-08-07",
            "HEARD_AND_ADJOURNED",
            government_pleader=["Pooja Deshpande"],
        ),
        _order("2026-09-08", "DISPOSED_OFF", government_pleader=[]),
    ]
    rows = [_row("WP/3/2026", "2026-08-07", "HEARD_AND_ADJOURNED", order_history)]
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
async def test_falls_back_to_board_assignment_when_order_extraction_is_empty(
    monkeypatch,
):
    """When the disposal order's own text extraction found no government
    pleader, fall back to whoever the board actually assigned for that
    hearing date -- the same union-of-sources approach Board.getData
    itself already uses. This mitigates the order-text extraction
    sometimes failing outright."""
    order_history = [
        _order(
            "2026-08-07",
            "HEARD_AND_ADJOURNED",
            government_pleader=["Pooja Deshpande"],
        ),
        _order("2026-09-08", "DISPOSED_OFF", government_pleader=[]),
    ]
    rows = [_row("WP/13/2026", "2026-08-07", "HEARD_AND_ADJOURNED", order_history)]
    board_cls, _ = _mock_board(rows)
    monkeypatch.setattr(main, "Board", board_cls)
    monkeypatch.setattr(main, "get_user_manager", lambda: _mock_user_manager())
    monkeypatch.setattr(main, "get_auto_order_manager", lambda: _mock_auto_mgr())
    monkeypatch.setattr(
        main,
        "_board_assigned_names_for_case_date",
        lambda case_ref, board_date: ["Rajan Pawar"],
    )

    result = await main.cross_agp_disposal_report(
        start_date="2026-07-01",
        end_date="2026-09-30",
        user_name=None,
        current_user_with_profile={"uid": "u1"},
    )

    assert result["disposal_agp_unnamed"] == 0
    assert result["flagged_count"] == 1
    assert result["results"][0]["disposal_agp_names"] == ["Rajan Pawar"]


@pytest.mark.asyncio
async def test_not_flagged_when_case_not_disposed_yet(monkeypatch):
    order_history = [
        _order(
            "2026-08-07",
            "HEARD_AND_ADJOURNED",
            government_pleader=["Pooja Deshpande"],
        ),
    ]
    rows = [_row("WP/4/2026", "2026-08-07", "HEARD_AND_ADJOURNED", order_history)]
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
async def test_not_flagged_when_agp_never_appeared_at_all(monkeypatch):
    """If the selected AGP never matched any hearing for this case,
    Board.getData wouldn't return a row for it at all -- nothing to
    compare a disposal against, so it's simply invisible to the report."""
    board_cls, _ = _mock_board([])
    monkeypatch.setattr(main, "Board", board_cls)
    monkeypatch.setattr(main, "get_user_manager", lambda: _mock_user_manager())
    monkeypatch.setattr(main, "get_auto_order_manager", lambda: _mock_auto_mgr())

    result = await main.cross_agp_disposal_report(
        start_date="2026-07-01",
        end_date="2026-09-30",
        user_name=None,
        current_user_with_profile={"uid": "u1"},
    )

    assert result["cases_checked"] == 0
    assert result["flagged_count"] == 0


@pytest.mark.asyncio
async def test_multiple_appearance_dates_for_same_case_counted_once(monkeypatch):
    """A case adjourned repeatedly gives Board.getData multiple rows (one
    per matching hearing date) but they all share one order_history --
    must be deduplicated to a single case in the report, while still
    counting every genuine appearance date."""
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
        _row("WP/6/2026", "2026-07-10", "HEARD_AND_ADJOURNED", order_history),
        _row("WP/6/2026", "2026-08-07", "HEARD_AND_ADJOURNED", order_history),
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
    history_a = [
        _order(
            "2026-06-01", "HEARD_AND_ADJOURNED", government_pleader=["Pooja Deshpande"]
        ),
        _order("2026-07-01", "DISPOSED_OFF", government_pleader=["Rajan Pawar"]),
    ]
    history_b = [
        _order(
            "2026-06-01", "HEARD_AND_ADJOURNED", government_pleader=["Pooja Deshpande"]
        ),
        _order("2026-09-01", "DISPOSED_OFF", government_pleader=["Rajan Pawar"]),
    ]
    rows = [
        _row("WP/7/2026", "2026-06-01", "HEARD_AND_ADJOURNED", history_a),
        _row("WP/8/2026", "2026-06-01", "HEARD_AND_ADJOURNED", history_b),
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
    order_history = [
        _order(
            "2026-08-07",
            "HEARD_AND_ADJOURNED",
            government_pleader=["Rajan Pawar"],
        ),
        _order("2026-09-08", "DISPOSED_OFF", government_pleader=["Someone Else"]),
    ]
    rows = [_row("WP/9/2026", "2026-08-07", "HEARD_AND_ADJOURNED", order_history)]
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
    call_args, call_kwargs = board_instance.getData.call_args
    assert call_args[1] == "Rajan Pawar"
    # The underlying query uses exactly the caller-selected range, no
    # widening.
    assert call_args[0]["startDate"] == "2026-07-01"
    assert call_args[0]["endDate"] == "2026-09-30"
    assert result["flagged_count"] == 1


# ---------------------------------------------------------------------------
# _board_assigned_names_for_case_date
# ---------------------------------------------------------------------------


def _mock_firestore_doc(exists, data=None):
    doc = MagicMock()
    doc.exists = exists
    doc.to_dict.return_value = data or {}
    return doc


def test_board_assigned_names_combines_respondent_and_additional_lawyers():
    doc = _mock_firestore_doc(
        True,
        {
            "respondent_lawyer": "SHRI RAJAN PAWAR, AGP",
            "additional_respondent_lawyers": ["A. Kulkarni"],
        },
    )
    mock_db = MagicMock()
    mock_db.collection.return_value.document.return_value.get.return_value = doc

    with patch.object(main.firestore, "client", return_value=mock_db):
        names = _real_board_assigned_names_for_case_date("WP/1/2026", "2026-09-08")

    mock_db.collection.assert_called_once_with("daily-boards")
    mock_db.collection.return_value.document.assert_called_once_with(
        "2026-09-08-WP-1-2026"
    )
    assert names == ["SHRI RAJAN PAWAR, AGP", "A. Kulkarni"]


def test_board_assigned_names_empty_when_doc_missing():
    doc = _mock_firestore_doc(False)
    mock_db = MagicMock()
    mock_db.collection.return_value.document.return_value.get.return_value = doc

    with patch.object(main.firestore, "client", return_value=mock_db):
        names = _real_board_assigned_names_for_case_date("WP/1/2026", "2026-09-08")

    assert names == []


def test_board_assigned_names_empty_without_case_ref_or_date():
    assert _real_board_assigned_names_for_case_date("", "2026-09-08") == []
    assert _real_board_assigned_names_for_case_date("WP/1/2026", None) == []


def test_board_assigned_names_swallows_lookup_errors():
    with patch.object(main.firestore, "client", side_effect=RuntimeError("boom")):
        names = _real_board_assigned_names_for_case_date("WP/1/2026", "2026-09-08")

    assert names == []

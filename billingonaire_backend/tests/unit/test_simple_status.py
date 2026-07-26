"""The Search Orders status filter contract.

`simple_status_for` collapses the 13 lifecycle states into the four buckets the
UI shows. It must stay in step with getSimpleStatus() in
billingonaire-ui/src/lib/lifecycleUtils.js — together they are the contract
between the status dropdown and Board.getData().
"""

import pytest

from Board import (
    FAILED_LIFECYCLE_STATES,
    SIMPLE_STATUS_KEYS,
    _LEGACY_STATUS_FILTERS,
    simple_status_for,
)

ALL_LIFECYCLE_STATES = [
    "board_ingested",
    "fetch_not_due",
    "fetch_queued",
    "fetch_in_progress",
    "fetch_succeeded",
    "analysis_queued",
    "analysis_in_progress",
    "analysed",
    "fetch_failed_retryable",
    "fetch_failed_terminal",
    "analysis_failed_retryable",
    "analysis_failed_terminal",
    "manual_review_required",
]


def test_every_lifecycle_state_maps_to_a_known_bucket():
    assert len(ALL_LIFECYCLE_STATES) == 13
    for state in ALL_LIFECYCLE_STATES:
        assert simple_status_for(state) in SIMPLE_STATUS_KEYS, state


def test_only_analysed_is_billable():
    assert simple_status_for("analysed") == "ready"
    for state in ALL_LIFECYCLE_STATES:
        if state != "analysed":
            assert simple_status_for(state) != "ready", state


def test_every_failure_state_needs_attention():
    for state in FAILED_LIFECYCLE_STATES:
        assert simple_status_for(state) == "attention", state


def test_analysis_failures_are_not_reported_as_pending():
    """Regression: analysis_failed_* were previously absent from the failed set,
    so they were both missing from 'Failed' and miscounted as 'Pending'."""
    for state in ("analysis_failed_retryable", "analysis_failed_terminal"):
        assert simple_status_for(state) == "attention"


def test_future_board_dates_are_waiting_not_failed():
    assert simple_status_for("fetch_not_due") == "waiting"


@pytest.mark.parametrize(
    "state",
    ["fetch_in_progress", "fetch_succeeded", "analysis_queued", "analysis_in_progress"],
)
def test_in_flight_states_are_working(state):
    assert simple_status_for(state) == "working"


@pytest.mark.parametrize("value", [None, "", "totally_unknown_state"])
def test_unknown_values_default_to_waiting(value):
    assert simple_status_for(value) == "waiting"


def test_legacy_filter_values_still_resolve():
    """Old bookmarked links used analysed/pending/failed."""
    assert _LEGACY_STATUS_FILTERS["analysed"] == "ready"
    assert _LEGACY_STATUS_FILTERS["failed"] == "attention"
    assert _LEGACY_STATUS_FILTERS["pending"] == "waiting"
    for legacy, modern in _LEGACY_STATUS_FILTERS.items():
        assert modern in SIMPLE_STATUS_KEYS

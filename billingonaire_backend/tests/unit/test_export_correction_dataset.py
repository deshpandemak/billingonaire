import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "tools"))

from export_correction_dataset import build_row  # noqa: E402


def _case(events, orders=None, latest_order_category=None, board_date=None):
    return {
        "case_ref": "WP/1/2026",
        "latest_board_date": board_date,
        "latest_order_category": latest_order_category,
        "orders": orders or [],
        "lifecycle_events": events,
    }


def test_build_row_extracts_previous_and_corrected_category():
    case = _case(
        events=[
            {
                "event_type": "manual_override",
                "timestamp": "2026-02-01T10:00:00",
                "reason": "Regex missed the AGP appearance boilerplate collision",
                "metadata": {
                    "actor_uid": "admin-1",
                    "previous_category": "HEARD_AND_ADJOURNED",
                    "order_category": "ADJOURNED",
                },
            }
        ],
        orders=[
            {
                "order_link": "https://example.com/order.pdf",
                "order_category": "ADJOURNED",
            }
        ],
        board_date="2026-01-15",
    )

    row = build_row("WP-1-2026", case)

    assert row["case_ref"] == "WP/1/2026"
    assert row["board_date"] == "2026-01-15"
    assert row["order_link"] == "https://example.com/order.pdf"
    assert row["previous_category"] == "HEARD_AND_ADJOURNED"
    assert row["corrected_category"] == "ADJOURNED"
    assert row["was_correction"] is True
    assert row["actor_uid"] == "admin-1"
    assert "AGP appearance" in row["notes"]


def test_build_row_flags_reconfirmation_as_not_a_correction():
    """If the human picks the SAME category the regex already had, that's
    not evidence the regex was wrong -- must not be counted as a correction."""
    case = _case(
        events=[
            {
                "event_type": "manual_override",
                "timestamp": "2026-02-01T10:00:00",
                "metadata": {
                    "actor_uid": "admin-1",
                    "previous_category": "ADJOURNED",
                    "order_category": "ADJOURNED",
                },
            }
        ],
    )

    row = build_row("WP-1-2026", case)
    assert row["was_correction"] is False


def test_build_row_returns_none_when_no_override_event_on_record():
    """order_manual_override=True with no manual_override lifecycle event --
    e.g. a legacy direct write -- must be skipped, not guessed at."""
    case = _case(events=[{"event_type": "status_transition", "metadata": {}}])
    assert build_row("WP-1-2026", case) is None


def test_build_row_uses_most_recent_override_when_case_overridden_twice():
    case = _case(
        events=[
            {
                "event_type": "manual_override",
                "timestamp": "2026-01-01T10:00:00",
                "metadata": {
                    "previous_category": "ADJOURNED",
                    "order_category": "HEARD_AND_ADJOURNED",
                },
            },
            {
                "event_type": "manual_override",
                "timestamp": "2026-02-01T10:00:00",
                "metadata": {
                    "previous_category": "HEARD_AND_ADJOURNED",
                    "order_category": "DISPOSED_OFF",
                },
            },
        ],
    )

    row = build_row("WP-1-2026", case)
    assert row["previous_category"] == "HEARD_AND_ADJOURNED"
    assert row["corrected_category"] == "DISPOSED_OFF"


def test_build_row_falls_back_to_latest_order_category_rollup():
    """metadata.order_category is the primary source, but fall back to the
    case-level rollup if it's ever missing so a row isn't silently dropped."""
    case = _case(
        events=[
            {
                "event_type": "manual_override",
                "timestamp": "2026-02-01T10:00:00",
                "metadata": {"previous_category": "ADJOURNED"},
            }
        ],
        latest_order_category="DISPOSED_OFF",
    )

    row = build_row("WP-1-2026", case)
    assert row["corrected_category"] == "DISPOSED_OFF"

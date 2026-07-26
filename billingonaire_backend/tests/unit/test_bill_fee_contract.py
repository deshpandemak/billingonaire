"""The fee/outcome contract shared with the bill screen.

calculate_case_fee is the authority: the outcome comes from the analysed order
and the fee follows from the outcome. These exact strings and amounts are
written verbatim into the exported Excel bill and are mirrored in
billingonaire-ui/src/lib/billing.js — change one and you must change both.
"""

import os
from unittest.mock import MagicMock, patch

import pytest

os.environ.setdefault("TESTING", "true")

from main import calculate_case_fee  # noqa: E402

CASE = {"case_type": "WP", "case_no": "123", "case_year": "2025"}


def _with_orders(orders):
    """Patch the case store so calculate_case_fee sees these orders."""
    manager = MagicMock()
    manager.case_store.get_case_details.return_value = {"orders": orders}
    return patch("main.get_auto_order_manager", return_value=manager)


def _order(category, board_date="2025-03-01"):
    return {
        "order_status": "analysed",
        "order_category": category,
        "board_date": board_date,
        "order_link": "https://example.test/o.pdf",
    }


@pytest.mark.parametrize(
    "category,expected_result,expected_fee",
    [
        ("ADJOURNED", "ADJOURNED", 1250),
        ("HEARD_AND_ADJOURNED", "HEARD & ADJN.", 1875),
        ("DISPOSED_OFF", "WP DISPOSED OF", 2500),
    ],
)
def test_outcome_determines_fee(category, expected_result, expected_fee):
    with _with_orders([_order(category)]):
        out = calculate_case_fee(CASE, board_date="2025-03-01")
    assert out["result"] == expected_result
    assert out["fee"] == expected_fee


def test_unanalysed_case_is_marked_unverified_not_plain_adjourned():
    """No analysed order → '*ADJOURNED*' (asterisks), meaning the adjournment
    is assumed. The bill screen must preserve this rather than flattening it
    to a confirmed 'ADJOURNED'."""
    with _with_orders([]):
        out = calculate_case_fee(CASE, board_date="2025-03-01")
    assert out["result"] == "*ADJOURNED*"
    assert out["result"] != "ADJOURNED"
    assert out["fee"] == 1250
    assert out["order_link"] is None


def test_order_for_a_different_hearing_is_not_used():
    """An entry for one hearing must not borrow another date's order."""
    with _with_orders([_order("DISPOSED_OFF", board_date="2025-04-30")]):
        out = calculate_case_fee(CASE, board_date="2025-05-06")
    assert out["result"] == "*ADJOURNED*"
    assert out["fee"] == 1250


def test_the_three_fees_are_distinct_and_ordered():
    fees = {}
    for category in ("ADJOURNED", "HEARD_AND_ADJOURNED", "DISPOSED_OFF"):
        with _with_orders([_order(category)]):
            fees[category] = calculate_case_fee(CASE, board_date="2025-03-01")["fee"]
    assert fees["ADJOURNED"] < fees["HEARD_AND_ADJOURNED"] < fees["DISPOSED_OFF"]
    assert len(set(fees.values())) == 3

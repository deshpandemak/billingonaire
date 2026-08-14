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

from main import calculate_case_fee, extract_parties_info  # noqa: E402

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


def test_order_text_never_influences_the_fee():
    """order_category must be the only fee input. order_analyzer never
    persists order_text to Firestore, so stray prose in a field nobody
    writes must not be able to pick the fee -- and if order_text is ever
    persisted later, it still must not silently start driving billing."""
    order = _order("ADJOURNED")
    order["order_text"] = "the petition is disposed of and rule is made absolute"
    with _with_orders([order]):
        out = calculate_case_fee(CASE, board_date="2025-03-01")
    assert out["result"] == "ADJOURNED"
    assert out["fee"] == 1250


def test_calculation_error_is_distinguishable_from_no_order_on_file():
    """A crash inside calculate_case_fee must not be silently indistinguishable
    from the ordinary 'no order matched this hearing' case -- both bill at
    the same floor rate (there is no better fee to guess) but order_category
    must carry a distinct marker so bill_qa / a human can tell a code fault
    from a normal gap."""
    manager = MagicMock()
    manager.case_store.get_case_details.side_effect = RuntimeError("boom")
    with patch("main.get_auto_order_manager", return_value=manager):
        out = calculate_case_fee(CASE, board_date="2025-03-01")
    assert out["result"] == "*ADJOURNED*"
    assert out["fee"] == 1250
    assert out["order_category"] == "CALCULATION_ERROR"


class TestConfidenceReachesTheBill:
    """The bill screen warns about guesses only if the backend sends the
    numbers. Two separate bill-entry paths previously disagreed on the field
    name (name_match_confidence vs confidence_score) and neither sent the
    classification confidence at all, so the warning could not fire."""

    def test_fee_calculation_returns_the_classification_confidence(self):
        order = _order("ADJOURNED")
        order["order_category_confidence"] = 0.42
        with _with_orders([order]):
            out = calculate_case_fee(CASE, board_date="2025-03-01")
        assert out["order_category_confidence"] == 0.42

    @pytest.mark.parametrize(
        "category", ["ADJOURNED", "HEARD_AND_ADJOURNED", "DISPOSED_OFF"]
    )
    def test_every_classified_outcome_carries_its_confidence(self, category):
        order = _order(category)
        order["order_category_confidence"] = 0.91
        with _with_orders([order]):
            out = calculate_case_fee(CASE, board_date="2025-03-01")
        assert out["order_category_confidence"] == 0.91

    def test_absent_confidence_is_none_not_zero(self):
        """None means 'unknown' and must not be rendered as 0% confidence."""
        with _with_orders([_order("ADJOURNED")]):
            out = calculate_case_fee(CASE, board_date="2025-03-01")
        assert out["order_category_confidence"] is None


class TestCaseDetailsIsFetchedOnceAndShared:
    """/bills/generate calls calculate_case_fee and extract_parties_info for the
    same case_ref on every bill line; each used to independently re-fetch the
    identical case-details doc. Passing case_details explicitly must skip the
    fetch, and omitting it must keep working exactly as before."""

    def test_calculate_case_fee_uses_the_given_case_details_without_fetching(self):
        manager = MagicMock()
        with patch("main.get_auto_order_manager", return_value=manager):
            out = calculate_case_fee(
                CASE,
                board_date="2025-03-01",
                case_details={"orders": [_order("DISPOSED_OFF")]},
            )
        manager.case_store.get_case_details.assert_not_called()
        assert out["result"] == "WP DISPOSED OF"
        assert out["fee"] == 2500

    def test_calculate_case_fee_fetches_when_case_details_omitted(self):
        with _with_orders([_order("DISPOSED_OFF")]) as get_manager:
            out = calculate_case_fee(CASE, board_date="2025-03-01")
        get_manager.return_value.case_store.get_case_details.assert_called_once()
        assert out["result"] == "WP DISPOSED OF"

    def test_extract_parties_info_uses_the_given_case_details_without_fetching(self):
        manager = MagicMock()
        with patch("main.get_auto_order_manager", return_value=manager):
            parties = extract_parties_info(
                CASE,
                case_details={"petitioner": "Foo", "respondent": "Bar"},
            )
        manager.case_store.get_case_details.assert_not_called()
        assert parties == "Foo Versus Bar"

    def test_extract_parties_info_fetches_when_case_details_omitted(self):
        manager = MagicMock()
        manager.case_store.get_case_details.return_value = {
            "petitioner": "Foo",
            "respondent": "Bar",
        }
        with patch("main.get_auto_order_manager", return_value=manager):
            parties = extract_parties_info(CASE)
        manager.case_store.get_case_details.assert_called_once()
        assert parties == "Foo Versus Bar"

"""Pre-submission bill QA (roadmap #5).

The bill export is the one artifact that leaves the building and goes to
a government body -- a classification error, a fuzzy-match miss, or a
manual fee edit upstream can all ride silently into it with nobody the
wiser until it's already submitted.

Every check here is a deterministic computation against the bill's own
declared fee schedule and the underlying entries -- no LLM involved.
Unlike order classification (genuinely ambiguous judicial language) or
portal-drift diagnosis (interpreting an unfamiliar failure pattern), "does
this fee match this outcome category" and "does this case appear twice"
have exact answers; a model would only add cost and a new way to be wrong
about something a lookup table gets right for free.

Advisory only, per the roadmap: "not a blocker, a second pair of eyes
with specifics attached." Every check returns which entries triggered it
and why, so a human decides what (if anything) needs fixing.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Set, Tuple

# Must match calculate_case_fee's result->fee mapping in main.py. Duplicated
# rather than imported to keep this module import-light (no Firestore/
# scraper dependency chain) -- covered by a regression test that fails
# loudly if the two ever drift apart.
FEE_SCHEDULE = {
    "WP DISPOSED OF": 2500,
    "HEARD & ADJN.": 1875,
    "ADJOURNED": 1250,
    "*ADJOURNED*": 1250,
}

# Mirrors AutoOrderManager.REVIEW_CONFIDENCE_THRESHOLD's default -- imported
# live where available (see qa_check_bill's caller in main.py) so the two
# can't drift; this default only applies if that import isn't provided.
DEFAULT_REVIEW_CONFIDENCE_THRESHOLD = 0.55


def _entry_key(entry: Dict[str, Any]) -> Tuple[Optional[str], Optional[str]]:
    case_ref = entry.get("case_detail") or entry.get("case_ref")
    return case_ref, entry.get("date")


def qa_check_bill(
    bill_entries: List[Dict[str, Any]],
    previously_billed_keys: Optional[Set[Tuple[str, str]]] = None,
    review_confidence_threshold: float = DEFAULT_REVIEW_CONFIDENCE_THRESHOLD,
) -> Dict[str, Any]:
    """``previously_billed_keys``: (case_ref, date) pairs already present in
    this user's OTHER saved bills -- the caller queries Firestore for this;
    kept out of this function so the check itself has no I/O and is fully
    unit-testable. Pass None (default) to skip the cross-bill check.
    """
    previously_billed_keys = previously_billed_keys or set()

    fee_mismatches: List[Dict[str, Any]] = []
    duplicates_within_bill: List[Dict[str, Any]] = []
    duplicates_across_bills: List[Dict[str, Any]] = []
    flagged_entries: List[Dict[str, Any]] = []

    seen_in_this_bill: Dict[Tuple[Optional[str], Optional[str]], int] = {}

    for entry in bill_entries:
        case_ref, date = _entry_key(entry)
        result = entry.get("results")
        fee = entry.get("fees_rs")

        expected_fee = FEE_SCHEDULE.get(result)
        if expected_fee is not None and fee != expected_fee:
            fee_mismatches.append(
                {
                    "case_ref": case_ref,
                    "date": date,
                    "result": result,
                    "fee": fee,
                    "expected_fee": expected_fee,
                }
            )

        key = (case_ref, date)
        if key in seen_in_this_bill:
            duplicates_within_bill.append({"case_ref": case_ref, "date": date})
        seen_in_this_bill[key] = seen_in_this_bill.get(key, 0) + 1

        if key in previously_billed_keys:
            duplicates_across_bills.append({"case_ref": case_ref, "date": date})

        confidence = entry.get("order_category_confidence")
        is_assumed = result == "*ADJOURNED*"
        is_low_confidence = (
            confidence is not None and confidence < review_confidence_threshold
        )
        if is_assumed or is_low_confidence:
            flagged_entries.append(
                {
                    "case_ref": case_ref,
                    "date": date,
                    "confidence": confidence,
                    "assumed": is_assumed,
                }
            )

    summary_lines: List[str] = []

    def _plural(n: int, noun: str) -> str:
        return f"{n} {noun}{'s' if n != 1 else ''}"

    if fee_mismatches:
        summary_lines.append(
            f"{_plural(len(fee_mismatches), 'entry')} have a fee that doesn't "
            f"match their outcome category."
        )
    if duplicates_within_bill:
        summary_lines.append(
            f"{_plural(len(duplicates_within_bill), 'case')} appear more than "
            f"once for the same date in this bill."
        )
    if duplicates_across_bills:
        summary_lines.append(
            f"{_plural(len(duplicates_across_bills), 'case')} already appear "
            f"in a previously saved bill for this date -- possible double-billing."
        )
    if flagged_entries:
        summary_lines.append(
            f"{_plural(len(flagged_entries), 'entry')} are low-confidence or "
            f"have no order on file (fee assumed) -- worth a second look "
            f"before this leaves the building."
        )
    if not summary_lines:
        summary_lines.append("No issues found.")

    blocking_issue_count = (
        len(fee_mismatches) + len(duplicates_within_bill) + len(duplicates_across_bills)
    )

    return {
        "ok": blocking_issue_count == 0,
        "total_entries": len(bill_entries),
        "fee_mismatches": fee_mismatches,
        "duplicates_within_bill": duplicates_within_bill,
        "duplicates_across_bills": duplicates_across_bills,
        "flagged_entries": flagged_entries,
        "summary_lines": summary_lines,
    }

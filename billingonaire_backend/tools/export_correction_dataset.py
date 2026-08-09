#!/usr/bin/env python3
"""
Export the classifier's ground-truth correction dataset.
==========================================================

Every time an admin overrides a case's order category
(``POST /admin/orders/{doc_id}/override``), ``CaseDataStore.
apply_category_override`` records what the regex classifier originally
predicted (``previous_category``, in the ``manual_override`` lifecycle
event's metadata) alongside the human's corrected category. That is real,
growing ground truth -- and, until now, nothing ever read it back out.

This is the "build the eval set" step the AI-agent roadmap calls for
before any classifier change ships: every regex/prompt change should be
graded against this file, not just eyeballed against a handful of
examples. Growing it costs nothing extra -- it already accumulates every
time someone uses the review queue.

Requires
--------
  * Application Default Credentials for Firestore
    (``gcloud auth application-default login``, per the project README).

Usage
-----
    python tools/export_correction_dataset.py
    python tools/export_correction_dataset.py --out corrections --limit 500

Outputs ``<out>.csv`` with one row per override: case_ref, board_date,
order_link, previous_category (what the regex got), corrected_category
(what the human confirmed), whether that was an actual correction (vs. a
re-confirmation of the same category), who made the call, when, and any
notes they left.
"""

from __future__ import annotations

import argparse
import csv
from typing import Any, Dict, List, Optional


def _latest_override_event(case: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    events = [
        e
        for e in (case.get("lifecycle_events") or [])
        if isinstance(e, dict) and e.get("event_type") == "manual_override"
    ]
    return events[-1] if events else None


def build_row(doc_id: str, case: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    event = _latest_override_event(case)
    if event is None:
        # order_manual_override=True but no manual_override lifecycle event
        # on record -- data from before that event type existed, or a
        # direct write bypassing apply_category_override. Skip rather than
        # guess at a previous_category we don't actually have.
        return None

    metadata = event.get("metadata") or {}
    previous_category = metadata.get("previous_category")
    corrected_category = metadata.get("order_category") or case.get(
        "latest_order_category"
    )

    orders_with_link = [
        o
        for o in (case.get("orders") or [])
        if isinstance(o, dict) and o.get("order_link")
    ]
    order_link = orders_with_link[-1]["order_link"] if orders_with_link else None

    return {
        "doc_id": doc_id,
        "case_ref": case.get("case_ref"),
        "board_date": case.get("latest_board_date"),
        "order_link": order_link,
        "previous_category": previous_category,
        "corrected_category": corrected_category,
        "was_correction": bool(
            previous_category and previous_category != corrected_category
        ),
        "actor_uid": metadata.get("actor_uid"),
        "timestamp": event.get("timestamp"),
        "notes": event.get("reason") or "",
    }


def fetch_overridden_cases(limit: int) -> List[Dict[str, Any]]:
    from google.cloud import firestore as gcf

    db = gcf.Client()
    cases = []
    for doc in (
        db.collection("case-details")
        .where("order_manual_override", "==", True)
        .limit(limit)
        .stream()
    ):
        data = doc.to_dict() or {}
        cases.append((doc.id, data))
    return cases


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Export every human-corrected order category as a labelled dataset.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    ap.add_argument("--limit", type=int, default=1000, help="max cases to export")
    ap.add_argument("--out", default="corrections", help="output file prefix")
    args = ap.parse_args()

    print(f"Fetching up to {args.limit} overridden case(s) from Firestore ...")
    raw_cases = fetch_overridden_cases(args.limit)

    rows = []
    skipped = 0
    for doc_id, case in raw_cases:
        row = build_row(doc_id, case)
        if row is None:
            skipped += 1
            continue
        rows.append(row)

    if not rows:
        print("No overrides with a recorded manual_override event found.")
        return 0

    out_csv = f"{args.out}.csv"
    with open(out_csv, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    corrections = sum(1 for r in rows if r["was_correction"])
    print(
        f"Wrote {len(rows)} row(s) to {out_csv} ({skipped} skipped, no override event on record)"
    )
    print(
        f"{corrections}/{len(rows)} were actual corrections (regex got it wrong); "
        f"{len(rows) - corrections} re-confirmed the regex's own category."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

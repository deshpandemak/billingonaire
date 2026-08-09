#!/usr/bin/env python3
"""
Queue health check: an actual diagnosis, not just a stuck-count badge.
=======================================================================

Pulls every case currently sitting in a failed/stuck lifecycle_status
(fetch_failed_retryable, fetch_failed_terminal, analysis_failed_retryable,
analysis_failed_terminal) and groups them by a normalized failure reason,
so "12 cases failed with the same underlying cause" reads as one systemic
problem instead of 12 separate rows nobody connects. Also flags cases
stuck in a claim/retry loop (many lifecycle_events, never a terminal
status) -- the atomic-claim mechanism itself not making progress on a
specific case, distinct from an ordinary one-off failure.

Same detection logic as GET /admin/queue-health (queue_health.py) -- this
script is for manual runs or a cron job outside the deployed service;
the endpoint is for hitting on a schedule from inside it (e.g. Cloud
Scheduler) without needing separate credentials.

Requires
--------
  * Application Default Credentials for Firestore
    (``gcloud auth application-default login``, per the project README).

Usage
-----
    python tools/queue_health_check.py

Exits non-zero if anything was flagged, so it can gate a cron job or CI
step ("only page someone if there's actually something to look at").
"""

from __future__ import annotations

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from queue_health import FAILED_STATUSES, diagnose  # noqa: E402


def fetch_failed_cases(limit_per_status: int = 200):
    from google.cloud import firestore as gcf

    db = gcf.Client()
    cases = []
    for status in FAILED_STATUSES:
        for doc in (
            db.collection("case-details")
            .where("lifecycle_status", "==", status)
            .limit(limit_per_status)
            .stream()
        ):
            data = doc.to_dict() or {}
            data.setdefault("lifecycle_status", status)
            cases.append(data)
    return cases


def main() -> int:
    print("Fetching failed/stuck cases from Firestore ...")
    cases = fetch_failed_cases()
    report = diagnose(cases)

    print(f"\n{report['total_failed']} case(s) currently failed/stuck:")
    for status, count in sorted(report["failed_count_by_status"].items()):
        print(f"  {status}: {count}")

    print("\nFailure reason groups (largest first):")
    for group in report["signature_groups"]:
        flag = " ⚠️ SYSTEMIC" if group["systemic"] else ""
        print(f"  [{group['status']}] x{group['count']}{flag}  {group['signature']}")
        if group["systemic"]:
            print(f"      e.g. {', '.join(r for r in group['case_refs'][:5] if r)}")

    if report["flapping_cases"]:
        print("\nFlapping cases (claimed/retried repeatedly, never terminal):")
        for f in report["flapping_cases"]:
            print(
                f"  {f['case_ref']} — {f['event_count']} events, currently {f['status']}"
            )

    print("\nSummary:")
    for line in report["summary_lines"]:
        print(f"  - {line}")

    flagged = any(g["systemic"] for g in report["signature_groups"]) or bool(
        report["flapping_cases"]
    )
    return 1 if flagged else 0


if __name__ == "__main__":
    raise SystemExit(main())

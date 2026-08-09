#!/usr/bin/env python3
"""
Portal health check: run a canary case through both scraper providers and
diagnose whether zero-orders-found looks like drift.
=====================================================================

Same detection logic as POST /admin/portal-health-check (portal_health.py)
-- this script is for manual runs or an external cron job that doesn't
have admin auth against the deployed service; the endpoint is for hitting
on a schedule from inside it (e.g. Cloud Scheduler).

Does NOT touch CourtScraper's fetch/extraction internals -- runs the same
_probe_provider_matrix() the existing /scraper/test-case debug endpoint
uses, then diagnoses the resulting attempt matrix.

Usage
-----
    python tools/portal_health_check.py WP/3434/2026 --date 2026-05-30

    # A case genuinely expected to have no orders yet
    python tools/portal_health_check.py WP/9999/2026 --expected-min-orders 0

Set GEMINI_API_KEY to also get a plain-English LLM interpretation when
drift is detected (optional -- the rule-based diagnosis stands on its own
either way). Exits non-zero when drift is detected, so this can gate a
cron job or CI step.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from CourtScraper import BombayHighCourtScraper  # noqa: E402
from portal_health import call_llm_for_diagnosis, diagnose_probe  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Diagnose court-portal drift for a canary case.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    ap.add_argument("case_ref", help='e.g. "WP/3434/2026"')
    ap.add_argument("--date", help="board date, YYYY-MM-DD")
    ap.add_argument("--bench", default="mumbai")
    ap.add_argument(
        "--expected-min-orders",
        type=int,
        default=1,
        help="orders this case is known to have (0 if genuinely expected empty)",
    )
    args = ap.parse_args()

    print(f"Probing both providers for {args.case_ref} ...")
    scraper = BombayHighCourtScraper()
    provider_matrix = scraper._probe_provider_matrix(
        args.case_ref, args.date, args.bench
    )

    report = diagnose_probe(
        provider_matrix,
        case_ref=args.case_ref,
        expected_min_orders=args.expected_min_orders,
    )

    for provider_entry in provider_matrix:
        print(
            f"  {provider_entry['provider']}: "
            f"{provider_entry['orders_found']} order(s) found"
        )

    print()
    for line in report["summary_lines"]:
        print(f"  - {line}")

    api_key = os.environ.get("GEMINI_API_KEY")
    if report["likely_drift"] and api_key:
        llm_diagnosis = call_llm_for_diagnosis(report, api_key)
        if llm_diagnosis:
            print(f"\nLLM interpretation:\n  {llm_diagnosis}")

    return 1 if report["likely_drift"] else 0


if __name__ == "__main__":
    raise SystemExit(main())

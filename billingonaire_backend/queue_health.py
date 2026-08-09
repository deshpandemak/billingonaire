"""Ops-agent diagnosis logic for the fetch/analyse pipeline.

Turns raw lifecycle_status/lifecycle_events data into a diagnosis an admin
can act on -- "12 fetch failures since 2pm, same error signature, looks
like the portal not us" -- instead of a bare stuck-count badge.

Deliberately no LLM/agent framework: grouping by normalized failure reason
already answers "is this one flaky case or a systemic problem," which is
the question that actually matters. Reach for a model only if this stops
being enough (per the AI-agent roadmap's own guidance not to reach for one
before a simpler approach is proven insufficient).
"""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import datetime
from typing import Any, Dict, List, Optional

FAILED_STATUSES = (
    "fetch_failed_retryable",
    "fetch_failed_terminal",
    "analysis_failed_retryable",
    "analysis_failed_terminal",
)

# A group of failures sharing a normalized reason at or above this count is
# reported as likely systemic rather than per-case noise.
SYSTEMIC_GROUP_THRESHOLD = 3

# A case whose lifecycle_events history is at or above this length is
# reported as "flapping" -- claimed, failed, reclaimed, failed again,
# without ever reaching a terminal state. Distinct from a single failure:
# this is the queue's atomic-claim/retry mechanism itself not making
# progress on a specific case.
FLAPPING_EVENT_THRESHOLD = 6

_URL_RE = re.compile(r"https?://\S+")
_DATE_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
_CASE_REF_RE = re.compile(r"\b[A-Za-z]{1,6}/\d+/\d{4}\b")
_NUMBER_RE = re.compile(r"\b\d+\b")
_WHITESPACE_RE = re.compile(r"\s+")


def normalize_reason(reason: Optional[str]) -> str:
    """Strip the parts of a failure reason that vary per-case (URLs, dates,
    case numbers, other digits) so cases failing for the same underlying
    cause group together instead of each looking unique."""
    if not reason or not str(reason).strip():
        return "(no reason recorded)"
    text = str(reason)
    text = _URL_RE.sub("<url>", text)
    text = _DATE_RE.sub("<date>", text)
    text = _CASE_REF_RE.sub("<case_ref>", text)
    text = _NUMBER_RE.sub("<n>", text)
    text = _WHITESPACE_RE.sub(" ", text).strip()
    return text[:160]


def _event_count(case: Dict[str, Any]) -> int:
    events = case.get("lifecycle_events")
    return len(events) if isinstance(events, list) else 0


def diagnose(cases: List[Dict[str, Any]]) -> Dict[str, Any]:
    """``cases``: case-details records, each with at least ``case_ref``,
    ``lifecycle_status``, and ideally ``lifecycle_status_reason`` and
    ``lifecycle_events``. Only cases already in a failed/stuck status
    belong here -- callers decide what to fetch (see queue_health_report()
    for the Firestore-backed version).

    Returns a plain-data report: per-status counts, failure-reason groups
    (flagged systemic once big enough to not be one-off noise), flapping
    cases, and human-readable summary lines ready to log or notify with.
    """
    by_status: Dict[str, int] = defaultdict(int)
    groups: Dict[tuple, Dict[str, Any]] = {}
    flapping: List[Dict[str, Any]] = []

    for case in cases:
        status = case.get("lifecycle_status") or "unknown"
        by_status[status] += 1

        reason = case.get("lifecycle_status_reason")
        signature = normalize_reason(reason)
        key = (status, signature)
        group = groups.setdefault(
            key,
            {
                "status": status,
                "signature": signature,
                "count": 0,
                "case_refs": [],
                "sample_reason": reason or "",
            },
        )
        group["count"] += 1
        if len(group["case_refs"]) < 10:
            group["case_refs"].append(case.get("case_ref"))

        n_events = _event_count(case)
        if n_events >= FLAPPING_EVENT_THRESHOLD:
            flapping.append(
                {
                    "case_ref": case.get("case_ref"),
                    "status": status,
                    "event_count": n_events,
                }
            )

    signature_groups = sorted(groups.values(), key=lambda g: -g["count"])
    for group in signature_groups:
        group["systemic"] = group["count"] >= SYSTEMIC_GROUP_THRESHOLD

    flapping.sort(key=lambda f: -f["event_count"])

    summary_lines = []
    for group in signature_groups:
        if not group["systemic"]:
            continue
        summary_lines.append(
            f"{group['count']} cases failed at {group['status']} with reason "
            f"like \"{group['signature']}\" — likely a systemic issue, not "
            f"per-case noise. Examples: {', '.join(r for r in group['case_refs'][:3] if r)}"
        )
    for f in flapping[:5]:
        summary_lines.append(
            f"{f['case_ref']} has been claimed/retried {f['event_count']} times "
            f"without reaching a terminal status (currently {f['status']}) — "
            "the retry loop itself may not be making progress on this case."
        )
    if not summary_lines:
        summary_lines.append(
            "No systemic failure patterns or flapping cases detected in the "
            "current failed/stuck cases."
        )

    return {
        "generated_at": (datetime.now()).isoformat(),
        "total_failed": sum(by_status.values()),
        "failed_count_by_status": dict(by_status),
        "signature_groups": signature_groups,
        "flapping_cases": flapping,
        "summary_lines": summary_lines,
    }

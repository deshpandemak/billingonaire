"""Court-portal drift diagnosis (roadmap #3).

CourtScraper's HTTP-first/Playwright-fallback pipeline already records a
per-attempt trace (status, reason, duration, orders_found) via
_run_provider_attempts/debug_case_orders -- but nothing ever looks at that
trace as a *pattern*. A single "0 orders found" is invisible noise; the
same signature repeating across a canary case run regularly is a portal
change nobody would otherwise notice until orders silently stop flowing.

Deliberately does NOT touch CourtScraper's fetch/extraction internals or
capture raw page HTML: those are the load-bearing order-download code
path, and this module has no way to test against the live court portal
from this environment. Diagnosis works entirely from the attempt-matrix
data CourtScraper.debug_case_orders() already safely returns today.

Two-tier diagnosis, same "don't reach for a model until grouping stops
being enough" principle as queue_health.py:
  1. Rule-based: did BOTH independent providers (HTTP and Playwright) find
     zero orders for a canary case expected to have at least one? That's
     the one signal that can't be explained by "this case just has no
     orders yet" -- if it could, the canary wouldn't be a canary.
  2. Only when tier 1 flags something, optionally hand the structured
     attempt matrix (not raw HTML) to an LLM to phrase what the pattern
     suggests -- e.g. "both providers report no_orders_in_html, which
     usually means a JS-rendered page routed differently, or the static
     HTML selector target moved."
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from queue_health import normalize_reason


def diagnose_probe(
    provider_matrix: List[Dict[str, Any]],
    case_ref: str,
    expected_min_orders: int = 1,
) -> Dict[str, Any]:
    """``provider_matrix``: the list CourtScraper._probe_provider_matrix /
    debug_case_orders(compare_all=True) returns -- one entry per provider
    ("http", "playwright"), each with orders_found, final_status,
    provider_attempts (the step-by-step trace within that provider).

    Returns a plain-data report: whether this looks like drift, the
    normalized failure signatures seen, and human-readable summary lines.
    """
    providers_with_orders = [
        p for p in provider_matrix if (p.get("orders_found") or 0) >= 1
    ]
    all_zero = len(providers_with_orders) == 0 and len(provider_matrix) > 0

    signatures: List[str] = []
    for provider_entry in provider_matrix:
        for attempt in provider_entry.get("provider_attempts") or []:
            reason = attempt.get("status") or attempt.get("error") or ""
            if reason and reason != "success":
                signatures.append(
                    f"{provider_entry.get('provider')}:{normalize_reason(reason)}"
                )

    likely_drift = all_zero and expected_min_orders > 0

    summary_lines: List[str] = []
    if likely_drift:
        providers_tried = ", ".join(str(p.get("provider")) for p in provider_matrix)
        summary_lines.append(
            f"{case_ref}: every provider tried ({providers_tried}) found 0 "
            f"orders, but this canary case is expected to have at least "
            f"{expected_min_orders}. Since HTTP and Playwright are "
            f"independent extraction paths (different HTTP client, "
            f"different HTML parsing), both failing the same way "
            f"suggests the portal changed rather than this one case "
            f"having no orders."
        )
        if signatures:
            summary_lines.append(
                f"Failure signatures seen: {', '.join(sorted(set(signatures)))}"
            )
    else:
        summary_lines.append(
            f"{case_ref}: at least one provider found orders -- no drift signal."
        )

    return {
        "case_ref": case_ref,
        "expected_min_orders": expected_min_orders,
        "likely_drift": likely_drift,
        "providers_checked": len(provider_matrix),
        "providers_with_orders": len(providers_with_orders),
        "failure_signatures": sorted(set(signatures)),
        "summary_lines": summary_lines,
        "provider_matrix": provider_matrix,
    }


LLM_PROMPT_TEMPLATE = """You are diagnosing a possible web-scraper failure for an Indian court
portal (Bombay High Court eCourts). The scraper has two independent extraction paths --
a direct HTTP POST that parses the returned HTML, and a Playwright browser automation
fallback that renders the page fully before parsing.

For the canary case "{case_ref}" (expected to have at least {expected_min_orders} order(s)
on file), BOTH paths returned zero orders. Here is the raw attempt trace from each provider
(step name, status/reason, duration in ms, orders found):

{attempts_json}

In 2-3 sentences, explain the most likely cause given these specific status/reason codes, and
suggest what a developer should check first (e.g. "the no_orders_in_html status on the HTTP
path combined with a Playwright timeout suggests X"). Do not restate the data verbatim --
interpret it.
"""


def build_llm_diagnosis_prompt(report: Dict[str, Any]) -> str:
    import json

    attempts = []
    for provider_entry in report.get("provider_matrix") or []:
        for attempt in provider_entry.get("provider_attempts") or []:
            attempts.append(
                {
                    "provider": provider_entry.get("provider"),
                    "step": attempt.get("step"),
                    "status": attempt.get("status") or attempt.get("error"),
                    "duration_ms": attempt.get("duration_ms"),
                    "orders_found": attempt.get("orders_found"),
                }
            )
    return LLM_PROMPT_TEMPLATE.format(
        case_ref=report["case_ref"],
        expected_min_orders=report.get("expected_min_orders", 1),
        attempts_json=json.dumps(attempts, indent=2),
    )


def call_llm_for_diagnosis(report: Dict[str, Any], api_key: str) -> Optional[str]:
    """Best-effort: if this fails for any reason, the rule-based summary_lines
    already produced by diagnose_probe() stand on their own -- this only adds
    a plain-English interpretation on top, never replaces the finding."""
    try:
        import requests

        prompt = build_llm_diagnosis_prompt(report)
        resp = requests.post(
            "https://generativelanguage.googleapis.com/v1beta/models/gemini-flash-latest:generateContent",
            params={"key": api_key},
            json={"contents": [{"parts": [{"text": prompt}]}]},
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
    except Exception:
        return None

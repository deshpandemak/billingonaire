#!/usr/bin/env python3
"""
Review-copilot prototype: does an LLM improve on the regex classifier for
cases the regex classifier is already unsure about?
============================================================================

Pulls real cases currently sitting in ``manual_review_required`` (i.e. cases
the existing ``OrderDocumentAnalyzer`` regex scorer flagged as low-confidence),
re-runs the SAME production classification path against each one's order PDF,
and separately asks an LLM to classify the same text with a one-sentence
rationale quoting the triggering phrase. Reports where they agree/disagree so
a human can judge whether the LLM's read is trustworthy before any of that
logic is wired into the actual review queue UI.

This does not change any production state — read-only against Firestore, and
the PDFs are only downloaded into memory for classification.

Requires
--------
  * Application Default Credentials for Firestore + PDF download
    (``gcloud auth application-default login``, per the project README).
  * ``GEMINI_API_KEY`` in the environment — a Google AI Studio key
    (https://aistudio.google.com/apikey) with the Generative Language API
    enabled and billing linked (the free tier needs billing linked even
    though it doesn't charge within the free quota).

Usage
-----
    python tools/review_copilot_prototype.py --limit 20

    # A different lifecycle status, or a stronger/cheaper Gemini model
    python tools/review_copilot_prototype.py --status manual_review_required \\
        --limit 20 --model gemini-flash-latest --out review_copilot

    # No Firestore access needed -- point it at a folder of order PDFs
    # instead (same folder-of-PDFs convention as tools/evaluate_orders.py).
    # Files that look like daily board/cause-list documents rather than a
    # single case's order (multi-page "DAILY MAIN" listings) are skipped.
    python tools/review_copilot_prototype.py --dir attached_assets --limit 20

Outputs ``<out>_results.csv`` (every case, both verdicts) and, when any
disagreements exist, ``<out>_disagreements.md`` — only the cases where the
regex classifier and the LLM landed on different categories, each with both
rationales, so review time goes to the interesting cases first.
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
import types
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import requests

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

# spaCy/pydantic can be mutually incompatible in some envs; the analyzer only
# needs spaCy opportunistically, so stub it rather than hard-fail (same shim
# tools/evaluate_orders.py and the unit tests use).
if "spacy" not in sys.modules:
    try:
        import spacy  # noqa: F401
    except Exception:  # pragma: no cover - environment shim
        spacy_stub = types.ModuleType("spacy")
        matcher_stub = types.ModuleType("spacy.matcher")

        class Matcher:  # pragma: no cover
            pass

        matcher_stub.Matcher = Matcher
        spacy_stub.matcher = matcher_stub
        sys.modules["spacy"] = spacy_stub
        sys.modules["spacy.matcher"] = matcher_stub

from review_copilot import call_gemini  # noqa: E402 - after the spaCy shim above


def build_analyzer():
    """Instantiate the real OrderDocumentAnalyzer with Firestore stubbed out
    (this script talks to Firestore itself via a plain google-cloud-firestore
    client, not through the analyzer)."""
    with patch("firebase_admin.firestore.client", return_value=MagicMock()):
        from order_analyzer import OrderDocumentAnalyzer

        return OrderDocumentAnalyzer()


def fetch_flagged_cases(status: str, limit: int) -> List[Dict[str, Any]]:
    from google.cloud import firestore as gcf

    db = gcf.Client()
    cases = []
    for doc in (
        db.collection("case-details")
        .where("lifecycle_status", "==", status)
        .limit(limit)
        .stream()
    ):
        data = doc.to_dict() or {}
        data["_doc_id"] = doc.id
        cases.append(data)
    return cases


# A board/cause-list document lists many cases for one day; an order PDF is
# about one case. The former has no business going through the classifier --
# skip anything whose first page reads like a listing rather than an order.
_BOARD_MARKERS = ("DAILY MAIN", "SUPPLEMENTARY", "C.R. No", "Bench Id", "Bench ID")


def _looks_like_board_listing(first_page_text: str) -> bool:
    upper = first_page_text.upper()
    return any(marker.upper() in upper for marker in _BOARD_MARKERS)


def load_local_pdfs(directory: str, limit: Optional[int]) -> List[Dict[str, Any]]:
    import pdfplumber

    root = Path(directory).expanduser().resolve()
    if not root.is_dir():
        raise SystemExit(f"Not a directory: {root}")

    pdfs = sorted(p for p in root.rglob("*.pdf") if p.is_file())
    pdfs += sorted(p for p in root.rglob("*.PDF") if p.is_file() and p not in pdfs)

    cases: List[Dict[str, Any]] = []
    skipped: List[str] = []
    for pdf_path in pdfs:
        pdf_bytes = pdf_path.read_bytes()
        try:
            with pdfplumber.open(pdf_path) as doc:
                first_page_text = doc.pages[0].extract_text() or ""
        except Exception:
            first_page_text = ""
        if _looks_like_board_listing(first_page_text):
            skipped.append(pdf_path.name)
            continue
        cases.append(
            {
                "case_ref": pdf_path.stem,
                "latest_board_date": None,
                "order_link": f"local:{pdf_path}",
                "_bytes": pdf_bytes,
            }
        )
        if limit and len(cases) >= limit:
            break

    if skipped:
        print(f"Skipped {len(skipped)} board/cause-list PDF(s): {', '.join(skipped)}")
    return cases


def order_link_for(case: Dict[str, Any]) -> Optional[str]:
    if case.get("latest_order_link"):
        return case["latest_order_link"]
    for order in reversed(case.get("orders") or []):
        if isinstance(order, dict) and order.get("order_link"):
            return order["order_link"]
    return None


def evaluate_case(
    analyzer, api_key: str, model: str, case: Dict[str, Any]
) -> Dict[str, Any]:
    row: Dict[str, Any] = {
        "case_ref": case.get("case_ref"),
        "board_date": case.get("latest_board_date"),
        "order_link": order_link_for(case),
        "regex_category": None,
        "regex_confidence": None,
        "gemini_category": None,
        "gemini_confidence": None,
        "gemini_rationale": "",
        "agree": None,
        "error": "",
    }
    try:
        if case.get("_bytes") is not None:
            pdf_bytes = case["_bytes"]
        elif row["order_link"]:
            pdf_bytes = requests.get(row["order_link"], timeout=30).content
        else:
            row["error"] = "no order_link on file"
            return row
        result = analyzer.analyze_order_document(f"{row['case_ref']}.pdf", pdf_bytes)
    except Exception as exc:  # noqa: BLE001 - report, never abort the sweep
        row["error"] = f"regex path failed: {type(exc).__name__}: {exc}"
        return row

    row["regex_category"] = result.order_category
    row["regex_confidence"] = round(float(result.category_confidence or 0), 3)

    try:
        gemini_result = call_gemini(result.order_text, api_key, model)
    except Exception as exc:  # noqa: BLE001 - report, never abort the sweep
        row["error"] = f"gemini call failed: {type(exc).__name__}: {exc}"
        return row

    row["gemini_category"] = gemini_result.get("category")
    row["gemini_confidence"] = gemini_result.get("confidence")
    row["gemini_rationale"] = gemini_result.get("rationale", "")
    row["agree"] = row["regex_category"] == row["gemini_category"]
    return row


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Compare the regex classifier against an LLM on real manual-review cases.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    ap.add_argument(
        "--status",
        default="manual_review_required",
        help="lifecycle_status to pull cases from (default: manual_review_required); "
        "ignored when --dir is given",
    )
    ap.add_argument(
        "--dir",
        dest="directory",
        help="evaluate a local folder of order PDFs instead of Firestore "
        "(no GCP credentials needed)",
    )
    ap.add_argument("--limit", type=int, default=20, help="max cases to evaluate")
    ap.add_argument("--model", default="gemini-flash-latest", help="Gemini model name")
    ap.add_argument("--out", default="review_copilot", help="output file prefix")
    args = ap.parse_args()

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise SystemExit("Set GEMINI_API_KEY in the environment before running this.")

    if args.directory:
        print(f"Loading up to {args.limit} order PDF(s) from {args.directory} ...")
        cases = load_local_pdfs(args.directory, args.limit)
        if not cases:
            raise SystemExit(f"No usable order PDFs found under {args.directory}.")
    else:
        print(
            f"Fetching up to {args.limit} cases at lifecycle_status={args.status} ..."
        )
        cases = fetch_flagged_cases(args.status, args.limit)
        if not cases:
            raise SystemExit(f"No cases found at lifecycle_status={args.status}.")
    print(f"Found {len(cases)} case(s). Evaluating ...\n")

    analyzer = build_analyzer()
    rows = [evaluate_case(analyzer, api_key, args.model, c) for c in cases]

    for r in rows:
        print("=" * 88)
        print(f"{r['case_ref']}  (board_date={r['board_date']})")
        if r["error"]:
            print(f"  ERROR: {r['error']}")
            continue
        print(f"  regex : {r['regex_category']:<20} conf={r['regex_confidence']}")
        print(f"  gemini: {r['gemini_category']:<20} conf={r['gemini_confidence']}")
        print(f"  agree : {r['agree']}")
        print(f"  gemini rationale: {r['gemini_rationale']}")

    evaluated = [r for r in rows if not r["error"]]
    agreements = [r for r in evaluated if r["agree"]]
    disagreements = [r for r in evaluated if not r["agree"]]
    errors = [r for r in rows if r["error"]]

    print("=" * 88)
    print(
        f"\n{len(agreements)}/{len(evaluated)} agree"
        f" ({len(disagreements)} disagreement(s), {len(errors)} error(s))"
    )

    out_csv = f"{args.out}_results.csv"
    with open(out_csv, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    print(f"\nWrote {out_csv}")

    if disagreements:
        out_md = f"{args.out}_disagreements.md"
        with open(out_md, "w", encoding="utf-8") as fh:
            fh.write("# Regex vs. Gemini disagreements\n\n")
            for r in disagreements:
                fh.write(f"## {r['case_ref']}  ({r['board_date']})\n\n")
                fh.write(
                    f"- **regex**: {r['regex_category']} (conf={r['regex_confidence']})\n"
                )
                fh.write(
                    f"- **gemini**: {r['gemini_category']} (conf={r['gemini_confidence']})\n"
                )
                fh.write(f"- **gemini rationale**: {r['gemini_rationale']}\n")
                fh.write(f"- **order**: {r['order_link']}\n\n")
        print(f"Wrote {out_md} — start here")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

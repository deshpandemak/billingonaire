#!/usr/bin/env python3
"""
Extraction-copilot prototype: does an LLM improve on the regex extractor for
government-side advocate names?
============================================================================

order_analyzer.OrderDocumentAnalyzer._extract_govt_pleader_from_text is 250+
lines of cascading fallback regexes -- two of which interpolate the case
number directly into the pattern -- built up one production bug report at a
time. Board.create_record() has the same problem on the board-row side:
positional splitting followed by blind string surgery
(`respondent_lawyer.replace("in", "")`, which corrupts any name containing
"in": Jain, Sinha, Shinde).

This script runs the SAME production extractor against each order PDF's
text and separately asks an LLM (extraction_copilot.call_gemini_for_advocates)
to extract the same names with a JSON schema, reporting where they
agree/disagree so a human can judge whether the LLM's read is trustworthy
before it replaces (or supplements) either regex extractor.

Only order-PDF text is wired up here (the government-pleader extractor is a
plain function of text, easy to call standalone). Board.create_record()'s
board-row text (`court_details`) is never persisted to Firestore -- only the
regex-derived fields are -- so comparing it requires re-parsing a real board
PDF first; extraction_copilot.call_gemini_for_advocates is written generically
enough (same prompt, same schema) to reuse for that once the board-row text
is in hand, but that harness isn't built yet.

This does not change any production state -- read-only, PDFs are only
downloaded/read into memory for extraction.

Requires
--------
  * ``GEMINI_API_KEY`` in the environment -- a Google AI Studio key
    (https://aistudio.google.com/apikey).
  * No Firestore/GCP credentials needed in --dir mode (the only mode
    implemented so far).

Usage
-----
    # Folder of order PDFs (same convention as evaluate_orders.py /
    # review_copilot_prototype.py) -- multi-page board/cause-list PDFs are
    # skipped automatically.
    python tools/extraction_copilot_prototype.py --dir attached_assets --limit 20

Outputs ``<out>_results.csv`` (every file, both extractions) and, when any
disagreements exist, ``<out>_disagreements.md`` -- only the files where the
regex extractor and the LLM landed on a different set of government-side
names, so review time goes to the interesting cases first.
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

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

# spaCy/pydantic can be mutually incompatible in some envs; the analyzer only
# needs spaCy opportunistically, so stub it rather than hard-fail (same shim
# tools/evaluate_orders.py and tools/review_copilot_prototype.py use).
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

from extraction_copilot import (  # noqa: E402 - after the spaCy shim above
    ExtractionCopilotError,
    call_gemini_for_advocates,
)

# Same convention as review_copilot_prototype.py: a board/cause-list
# document lists many cases for one day and has no business going through
# a single-case extractor.
_BOARD_MARKERS = ("DAILY MAIN", "SUPPLEMENTARY", "C.R. No", "Bench Id", "Bench ID")


def _looks_like_board_listing(first_page_text: str) -> bool:
    upper = first_page_text.upper()
    return any(marker.upper() in upper for marker in _BOARD_MARKERS)


def build_analyzer():
    """Instantiate the real OrderDocumentAnalyzer with Firestore stubbed out
    (this script never talks to Firestore)."""
    with patch("firebase_admin.firestore.client", return_value=MagicMock()):
        from order_analyzer import OrderDocumentAnalyzer

        return OrderDocumentAnalyzer()


def load_local_pdfs(directory: str, limit: Optional[int]) -> List[Dict[str, Any]]:
    import pdfplumber

    root = Path(directory).expanduser().resolve()
    if not root.is_dir():
        raise SystemExit(f"Not a directory: {root}")

    pdfs = sorted(p for p in root.rglob("*.pdf") if p.is_file())
    pdfs += sorted(p for p in root.rglob("*.PDF") if p.is_file() and p not in pdfs)

    files: List[Dict[str, Any]] = []
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
        files.append({"name": pdf_path.name, "bytes": pdf_bytes})
        if limit and len(files) >= limit:
            break

    if skipped:
        print(f"Skipped {len(skipped)} board/cause-list PDF(s): {', '.join(skipped)}")
    return files


def _regex_case_key(analyzer, text: str, fallback: str) -> str:
    """Best-effort case_key for the regex extractor's own logging/pattern
    interpolation -- taken from whatever _extract_structured_cases_simplified
    finds, falling back to the filename when nothing parses."""
    try:
        document_structure = analyzer._parse_document_structure(text)
        order_date = analyzer._extract_order_date(text, document_structure)
        cases = analyzer._extract_structured_cases_simplified(
            document_structure, text, order_date
        )
        for case in cases:
            if case.case_type and case.case_number and case.case_year:
                return f"{case.case_type}/{case.case_number}/{case.case_year}"
    except Exception:
        pass
    return fallback


def evaluate_file(
    analyzer, api_key: str, model: str, file_info: Dict[str, Any]
) -> Dict[str, Any]:
    row: Dict[str, Any] = {
        "file": file_info["name"],
        "case_key": "",
        "regex_government_advocates": "",
        "llm_petitioner_advocates": "",
        "llm_government_advocates": "",
        "llm_roles": "",
        "agree": None,
        "error": "",
    }
    try:
        extraction_result = analyzer.ml_parser.enhance_pdf_extraction(
            file_info["name"], file_info["bytes"]
        )
        text = extraction_result.text
        if not text or not text.strip():
            row["error"] = "no text extracted"
            return row
    except Exception as exc:  # noqa: BLE001 - report, never abort the sweep
        row["error"] = f"text extraction failed: {type(exc).__name__}: {exc}"
        return row

    case_key = _regex_case_key(analyzer, text, fallback=Path(file_info["name"]).stem)
    row["case_key"] = case_key

    try:
        regex_names = analyzer._extract_govt_pleader_from_text(text, case_key)
    except Exception as exc:  # noqa: BLE001 - report, never abort the sweep
        row["error"] = f"regex extractor failed: {type(exc).__name__}: {exc}"
        return row
    row["regex_government_advocates"] = " | ".join(regex_names)

    try:
        llm_result = call_gemini_for_advocates(text, api_key, model)
    except ExtractionCopilotError as exc:
        row["error"] = f"gemini call failed: {exc}"
        return row

    llm_petitioners = llm_result.get("petitioner_advocates") or []
    llm_government = llm_result.get("government_advocates") or []
    llm_roles = llm_result.get("roles") or []
    row["llm_petitioner_advocates"] = " | ".join(llm_petitioners)
    row["llm_government_advocates"] = " | ".join(llm_government)
    row["llm_roles"] = " | ".join(llm_roles)

    # Order-insensitive, case-insensitive set comparison -- the regex and the
    # LLM have no reason to agree on ordering, and title-casing differs too.
    regex_set = {n.strip().lower() for n in regex_names if n.strip()}
    llm_set = {n.strip().lower() for n in llm_government if n.strip()}
    row["agree"] = regex_set == llm_set
    return row


def main() -> int:
    ap = argparse.ArgumentParser(
        description=(
            "Compare the regex government-pleader extractor against an LLM "
            "on real order PDFs."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    ap.add_argument(
        "--dir",
        dest="directory",
        required=True,
        help="folder of order PDFs to evaluate (no GCP credentials needed)",
    )
    ap.add_argument("--limit", type=int, default=20, help="max files to evaluate")
    ap.add_argument("--model", default="gemini-flash-latest", help="Gemini model name")
    ap.add_argument("--out", default="extraction_copilot", help="output file prefix")
    args = ap.parse_args()

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise SystemExit("Set GEMINI_API_KEY in the environment before running this.")

    print(f"Loading up to {args.limit} order PDF(s) from {args.directory} ...")
    files = load_local_pdfs(args.directory, args.limit)
    if not files:
        raise SystemExit(f"No usable order PDFs found under {args.directory}.")
    print(f"Found {len(files)} file(s). Evaluating ...\n")

    analyzer = build_analyzer()
    rows = [evaluate_file(analyzer, api_key, args.model, f) for f in files]

    for r in rows:
        print("=" * 88)
        print(f"{r['file']}  (case_key={r['case_key']})")
        if r["error"]:
            print(f"  ERROR: {r['error']}")
            continue
        print(f"  regex govt advocates: {r['regex_government_advocates']}")
        print(f"  llm govt advocates  : {r['llm_government_advocates']}")
        print(f"  llm petitioner side : {r['llm_petitioner_advocates']}")
        print(f"  agree               : {r['agree']}")

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
            fh.write("# Regex vs. Gemini government-advocate disagreements\n\n")
            for r in disagreements:
                fh.write(f"## {r['file']}  (case_key={r['case_key']})\n\n")
                fh.write(f"- **regex**: {r['regex_government_advocates']}\n")
                fh.write(f"- **gemini**: {r['llm_government_advocates']}\n")
                fh.write(f"- **gemini roles**: {r['llm_roles']}\n\n")
        print(f"Wrote {out_md} — start here")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

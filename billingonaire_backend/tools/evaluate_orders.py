#!/usr/bin/env python3
"""
Order classification & extraction evaluation harness.
=====================================================

Runs the real ``OrderDocumentAnalyzer`` over a folder of order PDFs and reports
how well it classifies them and how much it manages to extract.  No Firebase or
network access required — ``firestore.client()`` is stubbed out.

Why this and not "training": the classifier is a weighted-regex + hard-gate
rules engine, not a statistical model, so there are no weights to fit.  The way
it gets more accurate is: measure against a labelled corpus, look at what the
failures have in common, adjust patterns, lock the fix in with a test.  This
script is the measurement half of that loop.

Usage
-----
    # Report-only (no labels needed) — extraction health + predicted mix
    python tools/evaluate_orders.py /path/to/orders

    # With ground truth → accuracy + confusion matrix + failure dossier
    python tools/evaluate_orders.py /path/to/orders --labels labels.csv

    # Explain one file: every pattern that fired and the gate decision
    python tools/evaluate_orders.py /path/to/orders --explain some_order.pdf

Ground truth is auto-detected, first match wins:
  1. ``--labels FILE.csv``  with columns: file,expected  (expected = category)
  2. Parent folder name, when it is a category
     e.g. ``orders/ADJOURNED/xyz.pdf``
  3. Filename prefix before ``__``
     e.g. ``orders/DISPOSED_OFF__xyz.pdf``
Anything unlabelled is still analysed and reported, just not scored.

Outputs ``<out>_results.csv`` (every file, every extracted field) and, when
labels exist, ``<out>_failures.md`` — only the disagreements, each with the
matched patterns and the surrounding order text, so tuning is targeted rather
than guesswork.
"""

from __future__ import annotations

import argparse
import csv
import os
import re
import sys
import types
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from unittest.mock import MagicMock, patch

# Make the backend package importable when run from anywhere.
BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

# spaCy/pydantic can be mutually incompatible in some envs; the analyzer only
# needs spaCy opportunistically, so stub it rather than hard-fail (same shim the
# unit tests use).
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

CATEGORIES = ("ADJOURNED", "HEARD_AND_ADJOURNED", "DISPOSED_OFF")

# Accept common spellings of the categories in labels/folder names.
_CATEGORY_ALIASES = {
    "ADJOURNED": "ADJOURNED",
    "ADJOURN": "ADJOURNED",
    "ADJ": "ADJOURNED",
    "HEARD_AND_ADJOURNED": "HEARD_AND_ADJOURNED",
    "HEARD AND ADJOURNED": "HEARD_AND_ADJOURNED",
    "HEARD_AND_ADJRN": "HEARD_AND_ADJOURNED",
    "HEARD & ADJOURNED": "HEARD_AND_ADJOURNED",
    "HEARD&ADJOURNED": "HEARD_AND_ADJOURNED",
    "HEARD": "HEARD_AND_ADJOURNED",
    "H_AND_A": "HEARD_AND_ADJOURNED",
    "DISPOSED_OFF": "DISPOSED_OFF",
    "DISPOSED OFF": "DISPOSED_OFF",
    "DISPOSED": "DISPOSED_OFF",
    "DISPOSED_OF": "DISPOSED_OFF",
    "WP DISPOSED OF": "DISPOSED_OFF",
    "DISPOSAL": "DISPOSED_OFF",
}


def normalize_category(raw: Optional[str]) -> Optional[str]:
    """Map a human-written label onto a canonical category, or None."""
    if not raw:
        return None
    key = re.sub(r"[\s\-]+", "_", str(raw).strip().upper())
    key = re.sub(r"_+", "_", key).strip("_")
    if key in _CATEGORY_ALIASES:
        return _CATEGORY_ALIASES[key]
    # Try the un-underscored form too ("HEARD AND ADJOURNED")
    spaced = key.replace("_", " ")
    return _CATEGORY_ALIASES.get(spaced)


def build_analyzer():
    """Instantiate the real analyzer with Firestore stubbed out."""
    with patch("firebase_admin.firestore.client", return_value=MagicMock()):
        from order_analyzer import OrderDocumentAnalyzer

        return OrderDocumentAnalyzer()


def load_label_file(path: Path) -> Dict[str, str]:
    """Read a CSV of ``file,expected``.  Keys are matched on basename."""
    labels: Dict[str, str] = {}
    with open(path, newline="", encoding="utf-8-sig") as fh:
        sample = fh.read(4096)
        fh.seek(0)
        try:
            dialect = csv.Sniffer().sniff(sample)
        except csv.Error:
            dialect = csv.excel
        reader = csv.DictReader(fh, dialect=dialect)
        if not reader.fieldnames:
            return labels
        cols = {c.strip().lower(): c for c in reader.fieldnames}
        file_col = next(
            (cols[c] for c in ("file", "filename", "name", "pdf") if c in cols), None
        )
        cat_col = next(
            (
                cols[c]
                for c in ("expected", "category", "expected_category", "label", "truth")
                if c in cols
            ),
            None,
        )
        if not file_col or not cat_col:
            raise SystemExit(
                f"{path}: need a filename column (file/filename/name) and a "
                f"category column (expected/category/label). Found: {reader.fieldnames}"
            )
        for row in reader:
            fname = str(row.get(file_col) or "").strip()
            cat = normalize_category(row.get(cat_col))
            if fname and cat:
                labels[os.path.basename(fname)] = cat
    return labels


def infer_label(pdf: Path, root: Path, label_file: Dict[str, str]) -> Optional[str]:
    """Ground truth for one PDF: explicit CSV > folder name > filename prefix."""
    explicit = label_file.get(pdf.name)
    if explicit:
        return explicit
    # Any ancestor folder up to the scan root that names a category.
    for parent in pdf.parents:
        if parent == root.parent:
            break
        cat = normalize_category(parent.name)
        if cat:
            return cat
        if parent == root:
            break
    if "__" in pdf.stem:
        return normalize_category(pdf.stem.split("__", 1)[0])
    return None


def analyse_one(analyzer, pdf: Path) -> Dict[str, Any]:
    """Run the analyzer over one PDF and flatten the result for reporting."""
    row: Dict[str, Any] = {
        "file": pdf.name,
        "relpath": str(pdf),
        "predicted": None,
        "confidence": None,
        "order_date": None,
        "n_cases": 0,
        "case_refs": "",
        "government_pleaders": "",
        "petitioners": "",
        "respondents": "",
        "text_chars": 0,
        "error": "",
    }
    try:
        content = pdf.read_bytes()
        result = analyzer.analyze_order_document(pdf.name, content)
    except Exception as exc:  # noqa: BLE001 - report, never abort the sweep
        row["error"] = f"{type(exc).__name__}: {exc}"
        return row

    gps: List[str] = []
    refs: List[str] = []
    pets: List[str] = []
    resps: List[str] = []
    for case in result.cases or []:
        ref = "/".join(
            str(p)
            for p in (case.case_type, case.case_number, case.case_year)
            if p not in (None, "")
        )
        if ref:
            refs.append(ref)
        gps.extend([g for g in (case.government_pleader or []) if g])
        if case.petitioner:
            pets.append(case.petitioner)
        if case.respondent:
            resps.append(case.respondent)

    row.update(
        predicted=result.order_category,
        confidence=round(float(result.category_confidence or 0), 3),
        order_date=result.order_date or "",
        n_cases=len(result.cases or []),
        case_refs=" | ".join(refs),
        government_pleaders=" | ".join(dict.fromkeys(gps)),
        petitioners=" | ".join(dict.fromkeys(pets)),
        respondents=" | ".join(dict.fromkeys(resps)),
        text_chars=len(result.order_text or ""),
    )
    return row


def explain(analyzer, pdf: Path) -> None:
    """Print every signal the classifier used for a single order."""
    content = pdf.read_bytes()
    extraction = analyzer.ml_parser.enhance_pdf_extraction(pdf.name, content)
    text = extraction.text if extraction else ""
    if not text.strip():
        print(
            f"!! No text extracted from {pdf.name} — likely a scanned image (needs OCR)."
        )
        return

    print(f"\n=== {pdf.name} ===")
    print(f"text length: {len(text)} chars\n")

    gate = [p.pattern for p in analyzer._compiled_no_time if p.search(text)]
    print("NO_TIME gate (forces ADJOURNED):")
    print("  " + ("\n  ".join(gate) if gate else "— none —"))

    strong = [p.pattern for p in analyzer._compiled_strong_disposal if p.search(text)]
    print("\nSTRONG_DISPOSAL (forces DISPOSED_OFF unless gate fired):")
    print("  " + ("\n  ".join(strong) if strong else "— none —"))

    print("\nWeighted pattern hits by category:")
    for category, patterns in analyzer.order_patterns.items():
        hits: List[Tuple[str, int, float]] = []
        total = 0.0
        for pattern in patterns:
            found = re.findall(pattern, text, re.IGNORECASE)
            if found:
                weight = analyzer._pattern_weights.get(pattern, 1.0)
                total += len(found) * weight
                hits.append((pattern, len(found), weight))
        print(f"\n  {category}  (score={total:.2f})")
        for pattern, n, w in sorted(hits, key=lambda h: -h[1] * h[2]):
            print(f"     x{n}  w={w}  {pattern}")

    category, confidence = analyzer._classify_order(text)
    print(f"\n→ _classify_order      : {category}  ({confidence:.2f})")
    structure = analyzer._parse_document_structure(text)
    cat2, conf2 = analyzer._classify_order_enhanced(text, structure)
    print(f"→ _classify_order_enhanced: {cat2}  ({conf2:.2f})")
    print(f"→ order_date            : {analyzer._extract_order_date(text, structure)}")

    print("\n--- first 1200 chars ---")
    print(text[:1200])


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Evaluate order classification and extraction over a PDF corpus.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    ap.add_argument(
        "directory", help="Folder containing order PDFs (searched recursively)"
    )
    ap.add_argument("--labels", help="CSV of ground truth: file,expected")
    ap.add_argument("--out", default="order_eval", help="Output file prefix")
    ap.add_argument("--explain", help="Show all matched patterns for this one filename")
    ap.add_argument("--limit", type=int, help="Only process the first N PDFs")
    args = ap.parse_args()

    root = Path(args.directory).expanduser().resolve()
    if not root.is_dir():
        raise SystemExit(f"Not a directory: {root}")

    pdfs = sorted(p for p in root.rglob("*.pdf") if p.is_file())
    pdfs += sorted(p for p in root.rglob("*.PDF") if p.is_file() and p not in pdfs)
    if not pdfs:
        raise SystemExit(f"No PDFs found under {root}")

    analyzer = build_analyzer()

    if args.explain:
        target = next(
            (
                p
                for p in pdfs
                if p.name == args.explain or str(p).endswith(args.explain)
            ),
            None,
        )
        if not target:
            raise SystemExit(f"Not found under {root}: {args.explain}")
        explain(analyzer, target)
        return 0

    if args.limit:
        pdfs = pdfs[: args.limit]

    label_file = load_label_file(Path(args.labels)) if args.labels else {}

    rows: List[Dict[str, Any]] = []
    print(f"Analysing {len(pdfs)} order PDF(s) from {root} …\n")
    for i, pdf in enumerate(pdfs, 1):
        row = analyse_one(analyzer, pdf)
        row["expected"] = infer_label(pdf, root, label_file) or ""
        rows.append(row)
        mark = (
            "!"
            if row["error"]
            else (
                "✓"
                if not row["expected"] or row["expected"] == row["predicted"]
                else "✗"
            )
        )
        print(
            f"  [{i}/{len(pdfs)}] {mark} {pdf.name[:58]:<58} "
            f"{row['predicted'] or 'ERROR':<20} {row['error'][:40]}"
        )

    # ── Extraction health (works with or without labels) ───────────────────
    ok = [r for r in rows if not r["error"]]
    n = len(rows)
    print("\n" + "=" * 72)
    print("EXTRACTION HEALTH")
    print("=" * 72)
    failed = [r for r in rows if r["error"]]
    no_text = [r for r in ok if r["text_chars"] == 0]
    print(f"  PDFs processed              : {n}")
    print(f"  Analyzer errors             : {len(failed)}")
    print(f"  No text extracted (scanned?): {len(no_text)}")
    if ok:
        with_date = sum(1 for r in ok if r["order_date"])
        with_gp = sum(1 for r in ok if r["government_pleaders"])
        with_case = sum(1 for r in ok if r["case_refs"])
        multi = sum(1 for r in ok if r["n_cases"] > 1)
        pct = lambda k: f"{k}/{len(ok)} ({100.0 * k / len(ok):.1f}%)"  # noqa: E731
        print(f"  Order date extracted        : {pct(with_date)}")
        print(f"  Case number(s) extracted    : {pct(with_case)}")
        print(f"  Government pleader(s) found : {pct(with_gp)}")
        print(f"  Clubbed/related matters (>1): {pct(multi)}")
        print(
            f"  Avg matters per order       : {sum(r['n_cases'] for r in ok) / len(ok):.2f}"
        )

    print("\n  Predicted category mix:")
    for cat, cnt in Counter(r["predicted"] for r in ok).most_common():
        print(
            f"    {cat or 'None':<24} {cnt:>4}  ({100.0 * cnt / max(len(ok), 1):.1f}%)"
        )

    # ── Accuracy (labelled subset only) ────────────────────────────────────
    labelled = [r for r in ok if r["expected"]]
    if labelled:
        correct = sum(1 for r in labelled if r["expected"] == r["predicted"])
        print("\n" + "=" * 72)
        print(
            f"ACCURACY  —  {correct}/{len(labelled)} = {100.0 * correct / len(labelled):.1f}%"
        )
        print("=" * 72)

        matrix: Dict[str, Counter] = defaultdict(Counter)
        for r in labelled:
            matrix[r["expected"]][r["predicted"]] += 1
        seen = [
            c for c in CATEGORIES if c in matrix or any(c in m for m in matrix.values())
        ]
        print("\n  rows = expected, cols = predicted")
        print(f"    {'':<22}" + "".join(f"{c[:14]:>16}" for c in seen))
        for exp in seen:
            cells = "".join(f"{matrix[exp].get(p, 0):>16}" for p in seen)
            print(f"    {exp:<22}{cells}")

        print("\n  Per-category recall / precision:")
        for c in seen:
            tp = matrix[c].get(c, 0)
            actual = sum(matrix[c].values())
            predicted_n = sum(m.get(c, 0) for m in matrix.values())
            rec = f"{100.0 * tp / actual:.1f}%" if actual else "n/a"
            prec = f"{100.0 * tp / predicted_n:.1f}%" if predicted_n else "n/a"
            print(f"    {c:<24} recall {rec:>7}   precision {prec:>7}   (n={actual})")

        wrong = [r for r in labelled if r["expected"] != r["predicted"]]
        if wrong:
            fpath = Path(f"{args.out}_failures.md")
            with open(fpath, "w", encoding="utf-8") as fh:
                fh.write(
                    f"# Misclassified orders ({len(wrong)} of {len(labelled)})\n\n"
                )
                for r in wrong:
                    fh.write(f"## {r['file']}\n\n")
                    fh.write(f"- expected: **{r['expected']}**\n")
                    fh.write(
                        f"- predicted: **{r['predicted']}** (confidence {r['confidence']})\n"
                    )
                    fh.write(f"- path: `{r['relpath']}`\n\n")
                    fh.write(
                        f"Explain with:\n\n    python tools/evaluate_orders.py {root} --explain {r['file']}\n\n---\n\n"
                    )
            print(f"\n  Failure dossier → {fpath}")
    else:
        print(
            "\n  No ground-truth labels found — reporting extraction health only.\n"
            "  Add --labels FILE.csv (file,expected), or put PDFs in per-category\n"
            "  folders, to get an accuracy score and a failure dossier."
        )

    csv_path = Path(f"{args.out}_results.csv")
    fields = [
        "file",
        "expected",
        "predicted",
        "confidence",
        "order_date",
        "n_cases",
        "case_refs",
        "government_pleaders",
        "petitioners",
        "respondents",
        "text_chars",
        "error",
        "relpath",
    ]
    with open(csv_path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for r in rows:
            writer.writerow({k: r.get(k, "") for k in fields})
    print(f"  Full results  → {csv_path}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

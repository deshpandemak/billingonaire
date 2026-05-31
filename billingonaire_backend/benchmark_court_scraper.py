"""Benchmark Bombay High Court scraper providers on a sample list of case refs.

Usage example:
  /workspaces/billingonaire/.venv/bin/python benchmark_court_scraper.py \
    --input-file case_refs.txt \
        --provider http \
    --limit 50 \
    --board-date 2026-03-20
"""

import argparse
import json
import time
from collections import Counter
from pathlib import Path
from typing import Dict, List, Optional

from CourtScraper import BombayHighCourtScraper


def load_case_refs(input_file: str) -> List[str]:
    path = Path(input_file)
    if not path.exists():
        raise FileNotFoundError(f"Input file not found: {input_file}")

    refs: List[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        value = line.strip()
        if not value or value.startswith("#"):
            continue
        refs.append(value)
    return refs


def benchmark(
    case_refs: List[str],
    provider: str,
    board_date: Optional[str],
    bench: str,
) -> Dict:
    scraper = BombayHighCourtScraper()
    scraper.configure_scraper(provider=provider)

    source_counter: Counter = Counter()
    status_counter: Counter = Counter()
    timings_ms: List[float] = []
    found_count = 0
    results: List[Dict] = []

    for case_ref in case_refs:
        started = time.perf_counter()
        payload = scraper.get_case_orders(
            case_ref=case_ref, date=board_date, bench=bench
        )
        elapsed_ms = (time.perf_counter() - started) * 1000.0

        status = str(payload.get("status") or "unknown")
        source = str(payload.get("source") or "unknown")
        orders = payload.get("court_orders") or []

        status_counter[status] += 1
        source_counter[source] += 1
        timings_ms.append(elapsed_ms)

        if orders:
            found_count += 1

        results.append(
            {
                "case_ref": case_ref,
                "status": status,
                "source": source,
                "order_count": len(orders),
                "elapsed_ms": round(elapsed_ms, 2),
            }
        )

    total = len(case_refs)
    avg_ms = (sum(timings_ms) / total) if total else 0.0
    p95_ms = sorted(timings_ms)[int(total * 0.95) - 1] if total else 0.0

    return {
        "config": {
            "provider": provider,
            "board_date": board_date,
            "bench": bench,
        },
        "summary": {
            "total_cases": total,
            "found_cases": found_count,
            "found_rate": round((found_count / total) * 100.0, 2) if total else 0.0,
            "avg_latency_ms": round(avg_ms, 2),
            "p95_latency_ms": round(p95_ms, 2),
        },
        "status_distribution": dict(status_counter),
        "source_distribution": dict(source_counter),
        "results": results,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Benchmark Bombay High Court scraper providers"
    )
    parser.add_argument(
        "--input-file",
        required=True,
        help="Text file with one case ref per line, e.g. WP/3373/2025",
    )
    parser.add_argument(
        "--provider",
        default="http",
        choices=["http", "playwright"],
        help="Scraper provider strategy",
    )
    parser.add_argument(
        "--board-date", default=None, help="Optional board date filter in YYYY-MM-DD"
    )
    parser.add_argument(
        "--bench", default="mumbai", help="Bench code input, e.g. mumbai, aurangabad"
    )
    parser.add_argument(
        "--limit", type=int, default=50, help="Maximum number of case refs to benchmark"
    )
    parser.add_argument(
        "--output", default=None, help="Optional output JSON report path"
    )

    args = parser.parse_args()

    case_refs = load_case_refs(args.input_file)
    if args.limit and args.limit > 0:
        case_refs = case_refs[: args.limit]

    report = benchmark(
        case_refs=case_refs,
        provider=args.provider,
        board_date=args.board_date,
        bench=args.bench,
    )

    text = json.dumps(report, indent=2)
    print(text)

    if args.output:
        Path(args.output).write_text(text + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()

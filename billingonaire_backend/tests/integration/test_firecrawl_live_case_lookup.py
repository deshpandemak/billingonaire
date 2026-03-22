import json
import os
from pathlib import Path

import pytest

try:
    from dotenv import load_dotenv
except ImportError:

    def load_dotenv(*_args, **_kwargs):
        return False


from billingonaire_backend.CourtScraper import BombayHighCourtScraper


def _load_live_test_env() -> None:
    """Load env vars from common .env locations without overriding existing shell vars."""
    backend_root = Path(__file__).resolve().parents[2]
    repo_root = backend_root.parent

    load_dotenv(backend_root / ".env", override=False)
    load_dotenv(repo_root / ".env", override=False)


@pytest.fixture(scope="module")
def live_firecrawl_result():
    """Run a single live Firecrawl case-order lookup and reuse it across tests."""
    _load_live_test_env()

    if os.getenv("RUN_LIVE_FIRECRAWL_TESTS", "false").strip().lower() != "true":
        pytest.skip(
            "RUN_LIVE_FIRECRAWL_TESTS is not true (set it in shell or .env to enable live Firecrawl tests)"
        )

    if not os.getenv("FIRECRAWL_API_KEY"):
        pytest.skip("FIRECRAWL_API_KEY is not set in shell or .env")

    case_ref = (os.getenv("FIRECRAWL_TEST_CASE_REF") or "").strip()
    if not case_ref:
        pytest.skip(
            "FIRECRAWL_TEST_CASE_REF is not set. Provide a known listed Bombay HC case for live order-link lookup."
        )

    board_date = (os.getenv("FIRECRAWL_TEST_BOARD_DATE") or "").strip() or None

    scraper = BombayHighCourtScraper()
    # Always request all available order links; do not restrict by date.
    result = scraper.get_case_orders(case_ref=case_ref, date=None, bench="mumbai")

    print("\n=== FIRECRAWL LIVE API RESPONSE START ===")
    print(
        json.dumps(
            {
                "case_ref": case_ref,
                "requested_board_date": board_date,
                "query_date": None,
                "response": result,
            },
            indent=2,
            default=str,
        )
    )
    print("=== FIRECRAWL LIVE API RESPONSE END ===\n")

    return {
        "case_ref": case_ref,
        "requested_board_date": board_date,
        "result": result,
    }


@pytest.mark.integration
@pytest.mark.slow
def test_live_firecrawl_case_lookup(live_firecrawl_result):
    """Optional live integration test against Firecrawl for a real Bombay HC case lookup."""
    result = live_firecrawl_result["result"]

    assert isinstance(result, dict)

    source = str(result.get("source") or "")
    status = str(result.get("status") or "")
    if source != "firecrawl":
        firecrawl_debug = "unknown"
        try:
            from firecrawl import FirecrawlApp

            firecrawl_debug = (
                f"installed(has_extract={hasattr(FirecrawlApp, 'extract')}, "
                f"has_agent={hasattr(FirecrawlApp, 'agent')})"
            )
        except Exception as exc:
            firecrawl_debug = f"import_error({exc})"

        pytest.skip(
            "Live Firecrawl result unavailable for this environment/request "
            f"(source={source or 'unknown'}, status={status or 'unknown'}, sdk={firecrawl_debug})"
        )

    assert "case_details" in result
    assert "court_orders" in result
    assert isinstance(result["court_orders"], list)


@pytest.mark.integration
@pytest.mark.slow
def test_live_firecrawl_finds_orders_for_bombay_high_court_case(live_firecrawl_result):
    """Optional live test that validates listing order links (metadata only, no file download)."""
    case_ref = live_firecrawl_result["case_ref"]
    requested_board_date = live_firecrawl_result["requested_board_date"]
    result = live_firecrawl_result["result"]

    source = str(result.get("source") or "")
    status = str(result.get("status") or "")
    if source != "firecrawl":
        pytest.skip(
            "Live Firecrawl result unavailable for order-link assertion "
            f"(source={source or 'unknown'}, status={status or 'unknown'})"
        )

    orders = result.get("court_orders") or []
    assert isinstance(orders, list)

    if not orders:
        pytest.skip(
            "No order links listed for configured live input. "
            "Set FIRECRAWL_TEST_CASE_REF to a known listed matter (and optional FIRECRAWL_TEST_BOARD_DATE). "
            f"case_ref={case_ref}, requested_board_date={requested_board_date or 'none'}, status={status or 'unknown'}"
        )

    # Validate that extracted data is link metadata only (no binary content download).
    download_urls = [
        str(order.get("download_url") or "").strip()
        for order in orders
        if isinstance(order, dict)
    ]
    assert any(url.startswith("http") for url in download_urls), (
        "Orders were returned but no valid download_url values were found. "
        f"download_urls={download_urls[:5]}"
    )

    listing_dates = [
        str(order.get("listing_date") or "").strip()
        for order in orders
        if isinstance(order, dict)
    ]
    assert any(
        listing_dates
    ), "Orders were returned but listing_date is missing for all rows"

    forbidden_payload_keys = {
        "file_bytes",
        "file_content",
        "pdf_content",
        "binary",
    }
    for order in orders:
        if not isinstance(order, dict):
            continue
        assert forbidden_payload_keys.isdisjoint(set(order.keys())), (
            "Order entry contains downloaded-content fields; expected link metadata only. "
            f"keys={sorted(order.keys())}"
        )

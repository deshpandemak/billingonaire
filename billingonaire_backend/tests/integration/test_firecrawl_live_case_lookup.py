import os
from pathlib import Path

import pytest
from dotenv import load_dotenv

from billingonaire_backend.CourtScraper import BombayHighCourtScraper


def _load_live_test_env() -> None:
    """Load env vars from common .env locations without overriding existing shell vars."""
    backend_root = Path(__file__).resolve().parents[2]
    repo_root = backend_root.parent

    load_dotenv(backend_root / ".env", override=False)
    load_dotenv(repo_root / ".env", override=False)


@pytest.mark.integration
@pytest.mark.slow
def test_live_firecrawl_case_lookup():
    """Optional live integration test against Firecrawl for a real Bombay HC case lookup."""
    _load_live_test_env()

    if os.getenv("RUN_LIVE_FIRECRAWL_TESTS", "false").strip().lower() != "true":
        pytest.skip(
            "RUN_LIVE_FIRECRAWL_TESTS is not true (set it in shell or .env to enable live Firecrawl tests)"
        )

    if not os.getenv("FIRECRAWL_API_KEY"):
        pytest.skip("FIRECRAWL_API_KEY is not set in shell or .env")

    case_ref = os.getenv("FIRECRAWL_TEST_CASE_REF", "WP/3373/2025")
    board_date = os.getenv("FIRECRAWL_TEST_BOARD_DATE", "2025-04-09")

    scraper = BombayHighCourtScraper()
    result = scraper.get_case_orders(case_ref=case_ref, date=board_date, bench="mumbai")

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

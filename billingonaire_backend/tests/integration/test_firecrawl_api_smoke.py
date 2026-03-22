import os
from pathlib import Path

import pytest
import requests

try:
    from dotenv import load_dotenv
except ImportError:

    def load_dotenv(*_args, **_kwargs):
        return False


def _load_live_test_env() -> None:
    """Load env vars from common .env locations without overriding shell vars."""
    backend_root = Path(__file__).resolve().parents[2]
    repo_root = backend_root.parent

    load_dotenv(backend_root / ".env", override=False)
    load_dotenv(repo_root / ".env", override=False)


@pytest.mark.integration
@pytest.mark.slow
def test_firecrawl_api_smoke_once():
    """Optional one-call smoke test for Firecrawl API auth and response shape."""
    _load_live_test_env()

    if os.getenv("RUN_LIVE_FIRECRAWL_TESTS", "false").strip().lower() != "true":
        pytest.skip(
            "RUN_LIVE_FIRECRAWL_TESTS is not true (set it in shell or .env to enable live Firecrawl tests)"
        )

    api_key = os.getenv("FIRECRAWL_API_KEY")
    if not api_key:
        pytest.skip("FIRECRAWL_API_KEY is not set in shell or .env")

    smoke_url = os.getenv("FIRECRAWL_SMOKE_URL", "https://example.com")

    response = requests.post(
        "https://api.firecrawl.dev/v1/scrape",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={"url": smoke_url, "formats": ["markdown"]},
        timeout=60,
    )

    assert response.status_code == 200, (
        f"Firecrawl API smoke call failed: status={response.status_code}, "
        f"body={response.text[:500]}"
    )

    payload = response.json()
    assert isinstance(payload, dict)
    assert payload.get("success") is True

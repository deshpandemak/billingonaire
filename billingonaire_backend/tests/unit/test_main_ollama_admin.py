import json
import sys
import types
from types import SimpleNamespace

import pytest

# Test-only fallback to avoid spaCy import-time crashes in environments where
# spaCy and pydantic versions are temporarily incompatible.
if "spacy" not in sys.modules:
    spacy_stub = types.ModuleType("spacy")
    spacy_matcher_stub = types.ModuleType("spacy.matcher")

    class Matcher:  # pragma: no cover - test import shim only
        pass

    spacy_matcher_stub.Matcher = Matcher
    spacy_stub.matcher = spacy_matcher_stub
    sys.modules["spacy"] = spacy_stub
    sys.modules["spacy.matcher"] = spacy_matcher_stub

import main


@pytest.mark.asyncio
async def test_admin_ollama_test_case_returns_probe_payload(monkeypatch):
    monkeypatch.setattr(
        main,
        "get_court_scraper",
        lambda: SimpleNamespace(
            debug_case_orders=lambda case_ref, date=None, bench="mumbai": {
                "ok": True,
                "request": {
                    "case_ref": case_ref,
                    "date": date,
                    "bench": bench,
                },
                "final_result": {"status": "found", "source": "ollama_scraper"},
            }
        ),
    )

    response = await main.admin_ollama_test_case(
        main.ScraperProbeRequest(
            case_ref="WP/3373/2025", date="2025-04-09", bench="mumbai"
        ),
        current_user={"role": "admin"},
    )

    payload = json.loads(response.body)
    assert response.status_code == 200
    assert payload["request"]["case_ref"] == "WP/3373/2025"
    assert payload["final_result"]["source"] == "ollama_scraper"


@pytest.mark.asyncio
async def test_admin_ollama_test_case_invalid_case_ref_returns_200_with_ok_false(
    monkeypatch,
):
    """When debug_case_orders returns ok=False (invalid case ref), the endpoint
    must still return HTTP 200 with the structured error payload so the frontend
    can display request/response details rather than showing a generic error."""
    monkeypatch.setattr(
        main,
        "get_court_scraper",
        lambda: SimpleNamespace(
            debug_case_orders=lambda case_ref, date, bench: {
                "ok": False,
                "error": "Invalid case reference format",
                "request": {
                    "case_ref": case_ref,
                    "date": date,
                    "bench": bench,
                },
            }
        ),
    )

    response = await main.admin_ollama_test_case(
        main.ScraperProbeRequest(case_ref="INVALID", date=None, bench="mumbai"),
        current_user={"role": "admin"},
    )

    payload = json.loads(response.body)
    assert response.status_code == 200
    assert payload["ok"] is False
    assert "Invalid case reference format" in payload["error"]
    assert payload["request"]["case_ref"] == "INVALID"


@pytest.mark.asyncio
async def test_admin_ollama_test_case_unexpected_exception_returns_200_with_ok_false(
    monkeypatch,
):
    """When debug_case_orders raises an unexpected exception the endpoint must
    return HTTP 200 with a structured error payload instead of propagating 500."""

    def _raise(case_ref, date, bench):
        raise RuntimeError("simulated internal failure")

    monkeypatch.setattr(
        main,
        "get_court_scraper",
        lambda: SimpleNamespace(debug_case_orders=_raise),
    )

    response = await main.admin_ollama_test_case(
        main.ScraperProbeRequest(case_ref="WP/3373/2025", date=None, bench="mumbai"),
        current_user={"role": "admin"},
    )

    payload = json.loads(response.body)
    assert response.status_code == 200
    assert payload["ok"] is False
    assert "simulated internal failure" in payload["error"]
    assert payload["request"]["case_ref"] == "WP/3373/2025"


@pytest.mark.asyncio
async def test_analyze_order_document_from_link_downloads_and_serializes(monkeypatch):
    analysis_result = SimpleNamespace(
        order_category="ADJOURNED",
        category_confidence=0.91,
        order_date="2025-04-09",
        cases=[
            SimpleNamespace(
                case_type="WP",
                case_number=3373,
                case_year=2025,
                petitioner="ABC Ltd",
                respondent="State of Maharashtra",
                government_pleader=["A. Counsel"],
            )
        ],
    )

    fake_analyzer = SimpleNamespace(
        analyze_order_document=lambda filename, file_content: analysis_result,
        save_analysis_result=lambda filename, result: "analysis-123",
    )

    monkeypatch.setattr(
        main,
        "_download_pdf_from_url",
        lambda url: {
            "filename": "test-order.pdf",
            "file_content": b"%PDF-1.4 test",
            "metadata": {
                "source_url": url,
                "resolved_url": url,
                "content_type": "application/pdf",
                "content_length": 13,
                "status_code": 200,
            },
        },
    )
    monkeypatch.setattr(main, "get_order_analyzer", lambda: fake_analyzer)

    response = await main.analyze_order_document_from_link(
        main.OrderLinkAnalysisRequest(
            url="https://example.com/test-order.pdf", persist_result=True
        ),
        current_user={"role": "admin"},
    )

    payload = json.loads(response.body)
    assert response.status_code == 200
    assert payload["filename"] == "test-order.pdf"
    assert payload["analysis_id"] == "analysis-123"
    assert payload["source_url"] == "https://example.com/test-order.pdf"
    assert payload["persisted"] is True
    assert payload["download_metadata"]["content_type"] == "application/pdf"
    assert payload["cases"][0]["case_type"] == "WP"

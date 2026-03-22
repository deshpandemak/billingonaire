from unittest.mock import Mock

import pytest

from billingonaire_backend.CourtScraper import BombayHighCourtScraper


def test_scraper_initialization():
    scraper = BombayHighCourtScraper()
    assert scraper is not None


def test_parse_case_number():
    scraper = BombayHighCourtScraper()
    result = scraper.parse_case_number("WP/10460/2023")
    assert isinstance(result, dict)
    assert "case_type" in result
    assert "case_number" in result
    assert "year" in result


def test_parse_case_number_invalid():
    scraper = BombayHighCourtScraper()
    result = scraper.parse_case_number("INVALID")
    assert isinstance(result, dict)
    # Should be empty dict for invalid input
    assert result == {}


def test_scraper_runtime_config_roundtrip():
    scraper = BombayHighCourtScraper()
    updated = scraper.configure_scraper(
        provider="ollama_only",
        allow_firecrawl_fallback=False,
        ollama_base_url="http://localhost:11434",
        ollama_model="llama3.2",
        ollama_timeout_seconds=25,
    )

    assert updated["provider"] == "ollama_only"
    assert updated["allow_firecrawl_fallback"] is False
    assert updated["ollama"]["base_url"] == "http://localhost:11434"
    assert updated["ollama"]["model"] == "llama3.2"
    assert updated["ollama"]["timeout_seconds"] == 25


def test_scraper_runtime_config_rejects_invalid_provider():
    scraper = BombayHighCourtScraper()
    with pytest.raises(ValueError):
        scraper.configure_scraper(provider="invalid_provider")


def test_firecrawl_prompt_includes_listing_navigation_steps():
    scraper = BombayHighCourtScraper()
    prompt = scraper._build_firecrawl_prompt(
        "WP/3373/2025",
        case_parts={"case_type": "WP", "case_number": "3373", "year": "2025"},
    )

    # Starting URL must be present
    assert "case_no.php" in prompt
    # Form field values injected
    assert "WP" in prompt
    assert "3373" in prompt
    assert "2025" in prompt
    # Critical: agent must click "Listing Dates" tab
    assert "Listing Dates" in prompt
    # Critical: table column name so agent knows where to look
    assert "Order/Judgement" in prompt
    # Critical: agent must read href, not click the link
    assert "Order/Judg-1" in prompt
    # No-download restriction is prominent
    assert "MUST NOT" in prompt
    assert "NEVER" in prompt
    # No date filter
    assert "NO date filter" in prompt
    # All rows collected
    assert "ALL rows" in prompt or "ALL" in prompt


def test_get_case_details_error():
    scraper = BombayHighCourtScraper()
    # Should not raise, just return empty dict or error info
    result = scraper.get_case_details("INVALID")
    assert isinstance(result, dict)


def test_get_case_details_uses_firecrawl_result(monkeypatch):
    scraper = BombayHighCourtScraper()
    scraper.scraper_provider = "firecrawl_only"
    mocked = {
        "status": "found",
        "source": "firecrawl",
        "case_details": {
            "case_number": "WP/3373/2025",
            "petitioner_name": "Petitioner A",
            "respondent_name": "Respondent B",
            "case_status_url": "https://example.com/case-status",
        },
        "court_orders": [{"listing_date": "09/04/2025"}],
    }
    monkeypatch.setattr(
        scraper, "_fetch_with_firecrawl", lambda case_ref, date=None: mocked
    )

    result = scraper.get_case_details("WP/3373/2025")

    assert result["status"] == "found"
    assert result["source"] == "firecrawl"
    assert result["case_number"] == "WP/3373/2025"
    assert result["petitioner"] == "Petitioner A"
    assert result["respondent"] == "Respondent B"
    assert result["case_status_url"] == "https://example.com/case-status"
    assert isinstance(result["court_orders"], list)


def test_normalize_firecrawl_payload_returns_all_order_links_even_with_date():
    scraper = BombayHighCourtScraper()
    payload = {
        "case_details": {
            "petitioner_name": "Petitioner A",
            "respondent_name": "Respondent B",
            "case_number": "WP/3373/2025",
        },
        "court_orders": [
            {
                "listing_date": "09/04/2025",
                "download_url": "https://example.com/order-1.pdf",
            },
            {
                "listing_date": "08/04/2025",
                "download_url": "https://example.com/order-2.pdf",
            },
        ],
    }

    result = scraper._normalize_firecrawl_payload(
        payload,
        case_ref="WP/3373/2025",
        date="2025-04-09",
    )

    assert result["status"] == "found"
    assert result["source"] == "firecrawl"
    assert result["case_details"]["petitioner_name"] == "Petitioner A"
    assert len(result["court_orders"]) == 2
    assert (
        result["court_orders"][0]["download_url"] == "https://example.com/order-1.pdf"
    )
    assert (
        result["court_orders"][1]["download_url"] == "https://example.com/order-2.pdf"
    )


def test_get_case_orders_uses_firecrawl_result(monkeypatch):
    scraper = BombayHighCourtScraper()
    scraper.scraper_provider = "firecrawl_only"
    mocked = {
        "status": "found",
        "source": "firecrawl",
        "case_details": {"case_number": "WP/3373/2025"},
        "court_orders": [{"listing_date": "09/04/2025"}],
    }
    monkeypatch.setattr(
        scraper, "_fetch_with_firecrawl", lambda case_ref, date=None: mocked
    )

    result = scraper.get_case_orders("WP/3373/2025", "2025-04-09", "mumbai")
    assert result == mocked


def test_get_case_orders_fallback_shape_when_firecrawl_unavailable(monkeypatch):
    scraper = BombayHighCourtScraper()
    monkeypatch.setattr(
        scraper, "_fetch_with_firecrawl", lambda case_ref, date=None: None
    )

    result = scraper.get_case_orders("WP/3373/2025", "2025-04-09", "mumbai")

    assert isinstance(result, dict)
    assert result["status"] == "captcha_required"
    assert "case_details" in result
    assert "court_orders" in result
    assert isinstance(result["court_orders"], list)


def test_get_case_orders_prefers_ollama_when_configured(monkeypatch):
    scraper = BombayHighCourtScraper()
    scraper.scraper_provider = "ollama_first"

    ollama_result = {
        "status": "found",
        "source": "ollama_scraper",
        "case_details": {"case_number": "WP/3373/2025"},
        "court_orders": [
            {
                "listing_date": "09/04/2025",
                "download_url": "https://example.com/order-1.pdf",
            }
        ],
    }

    monkeypatch.setattr(
        scraper,
        "_fetch_with_ollama_scraper",
        lambda case_ref, date=None, bench="mumbai": ollama_result,
    )
    monkeypatch.setattr(
        scraper,
        "_fetch_with_firecrawl",
        lambda case_ref, date=None: pytest.fail("Firecrawl should not be called"),
    )

    result = scraper.get_case_orders("WP/3373/2025", "2025-04-09", "mumbai")
    assert result["source"] == "ollama_scraper"
    assert result["status"] == "found"


def test_get_case_orders_ollama_only_skips_firecrawl(monkeypatch):
    scraper = BombayHighCourtScraper()
    scraper.scraper_provider = "ollama_only"

    monkeypatch.setattr(
        scraper,
        "_fetch_with_ollama_scraper",
        lambda case_ref, date=None, bench="mumbai": None,
    )
    monkeypatch.setattr(
        scraper,
        "_fetch_with_firecrawl",
        lambda case_ref, date=None: pytest.fail(
            "Firecrawl must be skipped in ollama_only mode"
        ),
    )

    result = scraper.get_case_orders("WP/3373/2025", "2025-04-09", "mumbai")
    assert result["status"] in {"captcha_required", "error"}


def test_fetch_with_firecrawl_extract_sdk_compat(monkeypatch):
    scraper = BombayHighCourtScraper()
    scraper.firecrawl_api_key = "test-key"
    scraper.firecrawl_model = "spark-1-mini"

    class FakeExtractResponse:
        def model_dump(self):
            return {
                "data": {
                    "case_details": {
                        "petitioner_name": "Petitioner A",
                        "respondent_name": "Respondent B",
                        "case_number": "WP/3373/2025",
                    },
                    "court_orders": [
                        {
                            "listing_date": "09/04/2025",
                            "download_url": "https://example.com/order.pdf",
                        }
                    ],
                }
            }

    class FakeFirecrawlApp:
        def __init__(self, api_key):
            self.api_key = api_key

        def extract(self, **kwargs):
            assert kwargs.get("prompt")
            assert kwargs.get("schema")
            assert kwargs.get("agent", {}).get("model") == "spark-1-mini"
            return FakeExtractResponse()

    monkeypatch.setattr(
        "billingonaire_backend.CourtScraper.FirecrawlApp", FakeFirecrawlApp
    )

    result = scraper._fetch_with_firecrawl("WP/3373/2025", date="2025-04-09")

    assert isinstance(result, dict)
    assert result["source"] == "firecrawl"
    assert result["status"] == "found"
    assert result["case_details"]["case_number"] == "WP/3373/2025"
    assert len(result["court_orders"]) == 1


def test_fetch_with_firecrawl_agent_sdk_compat(monkeypatch):
    """Verify _fetch_with_firecrawl uses agent() when the SDK exposes that method."""
    scraper = BombayHighCourtScraper()
    scraper.firecrawl_api_key = "test-key"
    scraper.firecrawl_model = "spark-1-mini"

    agent_calls = []

    class FakeAgentFirecrawlApp:
        def __init__(self, api_key):
            self.api_key = api_key

        def agent(self, **kwargs):
            agent_calls.append(kwargs)
            return {
                "case_details": {
                    "petitioner_name": "Petitioner X",
                    "respondent_name": "Respondent Y",
                    "case_number": "WP/3373/2025",
                },
                "court_orders": [
                    {
                        "listing_date": "09/04/2025",
                        "download_url": "https://example.com/order-agent.pdf",
                    }
                ],
            }

    monkeypatch.setattr(
        "billingonaire_backend.CourtScraper.FirecrawlApp", FakeAgentFirecrawlApp
    )

    result = scraper._fetch_with_firecrawl("WP/3373/2025", date="2025-04-09")

    assert len(agent_calls) == 1
    call_kwargs = agent_calls[0]
    assert call_kwargs.get("prompt")
    assert call_kwargs.get("model") == "spark-1-mini"
    urls = call_kwargs.get("urls") or []
    assert any("case_no.php" in u for u in urls)
    assert any("bombayhighcourt.nic.in" in u for u in urls)
    assert any("hcservices.ecourts.gov.in/ecourtindiaHC" in u for u in urls)

    assert isinstance(result, dict)
    assert result["source"] == "firecrawl"
    assert result["status"] == "found"
    assert result["case_details"]["case_number"] == "WP/3373/2025"
    assert len(result["court_orders"]) == 1
    assert (
        result["court_orders"][0]["download_url"]
        == "https://example.com/order-agent.pdf"
    )


def test_fetch_with_firecrawl_returns_none_without_api_key():
    """Verify _fetch_with_firecrawl returns None when no API key is configured."""
    scraper = BombayHighCourtScraper()
    scraper.firecrawl_api_key = None

    result = scraper._fetch_with_firecrawl("WP/3373/2025", date="2025-04-09")

    assert result is None


def test_pull_ollama_model_success(monkeypatch):
    """Verify pull_ollama_model triggers model pull and returns status."""
    scraper = BombayHighCourtScraper()
    scraper.ollama_base_url = "http://localhost:11434"
    scraper.ollama_model = "llama3.2"

    # Mock successful POST request
    mock_response = Mock()
    mock_response.raise_for_status = Mock()
    mock_response.status_code = 200

    mock_post = Mock(return_value=mock_response)
    monkeypatch.setattr("billingonaire_backend.CourtScraper.requests.post", mock_post)

    result = scraper.pull_ollama_model(model_name="llama3.1:8b")

    # Verify POST called with correct URL and payload
    mock_post.assert_called_once()
    call_args = mock_post.call_args
    assert "http://localhost:11434/api/pull" in call_args[0]
    assert call_args[1]["json"]["model"] == "llama3.1:8b"

    # Verify response structure
    assert result["status"] == "pulling"
    assert result["model"] == "llama3.1:8b"
    assert result["ollama_base_url"] == "http://localhost:11434"
    assert "message" in result


def test_pull_ollama_model_uses_default_model(monkeypatch):
    """Verify pull_ollama_model defaults to configured model if not provided."""
    scraper = BombayHighCourtScraper()
    scraper.ollama_base_url = "http://localhost:11434"
    scraper.ollama_model = "llama3.2"

    mock_response = Mock()
    mock_response.raise_for_status = Mock()

    mock_post = Mock(return_value=mock_response)
    monkeypatch.setattr("billingonaire_backend.CourtScraper.requests.post", mock_post)

    result = scraper.pull_ollama_model()  # No model_name provided

    # Should use default llama3.2
    call_args = mock_post.call_args
    assert call_args[1]["json"]["model"] == "llama3.2"
    assert result["model"] == "llama3.2"


def test_pull_ollama_model_requires_base_url():
    """Verify pull_ollama_model raises error if base URL not configured."""
    scraper = BombayHighCourtScraper()
    scraper.ollama_base_url = ""

    with pytest.raises(ValueError, match="base URL"):
        scraper.pull_ollama_model(model_name="llama3.1:8b")


def test_pull_ollama_model_requires_model_name():
    """Verify pull_ollama_model raises error if model name not provided or configured."""
    scraper = BombayHighCourtScraper()
    scraper.ollama_base_url = "http://localhost:11434"
    scraper.ollama_model = ""  # Empty default

    with pytest.raises(ValueError, match="Model name"):
        scraper.pull_ollama_model()  # No model_name + empty default


def test_pull_ollama_model_handles_connection_error(monkeypatch):
    """Verify pull_ollama_model raises error on connection failure."""
    import requests

    scraper = BombayHighCourtScraper()
    scraper.ollama_base_url = "http://localhost:11434"
    scraper.ollama_model = "llama3.2"

    # Mock connection error
    mock_post = Mock(
        side_effect=requests.exceptions.ConnectionError("Network unreachable")
    )
    monkeypatch.setattr("billingonaire_backend.CourtScraper.requests.post", mock_post)

    with pytest.raises(ValueError, match="Cannot reach Ollama"):
        scraper.pull_ollama_model(model_name="llama3.1:8b")


def test_pull_ollama_model_handles_timeout(monkeypatch):
    """Verify pull_ollama_model raises error on timeout."""
    import requests

    scraper = BombayHighCourtScraper()
    scraper.ollama_base_url = "http://localhost:11434"
    scraper.ollama_model = "llama3.2"

    # Mock timeout
    mock_post = Mock(side_effect=requests.exceptions.Timeout("Request timed out"))
    monkeypatch.setattr("billingonaire_backend.CourtScraper.requests.post", mock_post)

    with pytest.raises(ValueError, match="Timeout"):
        scraper.pull_ollama_model(model_name="llama3.1:8b")


def test_debug_case_orders_returns_trace_and_ollama_payload(monkeypatch):
    scraper = BombayHighCourtScraper()
    scraper.ollama_base_url = "http://localhost:11434"
    scraper.ollama_model = "llama3.2"

    class FakeGetResponse:
        def __init__(self):
            self.status_code = 200
            self.url = (
                "https://hcservices.ecourts.gov.in/ecourtindiaHC/cases/case_detail.php"
            )
            self.text = """
                <html>
                  <body>
                    <p>Petitioner: ABC Ltd</p>
                    <p>Respondent: State of Maharashtra</p>
                    <a href=\"/orders/test-order.pdf\">Order/Judg-1</a>
                  </body>
                </html>
            """

    class FakePostResponse:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {
                "response": '{"case_details": {"case_number": "WP/3373/2025"}, "court_orders": [{"listing_date": "09/04/2025", "download_url": "https://example.com/test-order.pdf"}]}'
            }

    monkeypatch.setattr(scraper.session, "get", lambda url, timeout: FakeGetResponse())
    monkeypatch.setattr(
        "billingonaire_backend.CourtScraper.requests.post",
        lambda *args, **kwargs: FakePostResponse(),
    )
    monkeypatch.setattr(
        scraper,
        "get_case_orders",
        lambda case_ref, date=None, bench="mumbai": {
            "status": "found",
            "source": "ollama_scraper",
            "case_details": {"case_number": case_ref},
            "court_orders": [
                {
                    "listing_date": "09/04/2025",
                    "download_url": "https://example.com/test-order.pdf",
                }
            ],
        },
    )

    result = scraper.debug_case_orders("WP/3373/2025", "2025-04-09", "mumbai")

    assert result["ok"] is True
    assert result["request"]["case_ref"] == "WP/3373/2025"
    assert len(result["http_trace"]) >= 1
    assert result["http_trace"][0]["status_code"] == 200
    assert result["http_trace"][0]["extracted_order_count"] >= 1
    assert result["ollama_request"]["model"] == "llama3.2"
    assert result["ollama_response"]["normalized"]["status"] == "found"
    assert result["final_result"]["source"] == "ollama_scraper"

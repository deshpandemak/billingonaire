import sys
import types
from types import SimpleNamespace

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


class _FakeCaseStore:
    def __init__(self, details):
        self._details = details

    def get_case_details(self, case_ref):
        return self._details.get(case_ref)


def test_cached_case_details_payload_uses_case_store(monkeypatch):
    fake_store = _FakeCaseStore(
        {
            "WP/123/2025": {
                "petitioner": "ABC Ltd",
                "respondent": "State of Maharashtra",
                "latest_board_date": "2025-01-15",
                "latest_order_link": "https://example.com/order.pdf",
                "orders": [{"order_link": "https://example.com/order.pdf"}],
            }
        }
    )
    monkeypatch.setattr(
        main, "get_auto_order_manager", lambda: SimpleNamespace(case_store=fake_store)
    )

    payload = main._get_cached_case_details_payload("wp/123/2025")

    assert payload is not None
    assert payload["source"] == "case_store_cached"
    assert payload["case_ref"] == "WP/123/2025"
    assert payload["orders_count"] == 1


def test_cached_case_orders_payload_filters_by_date(monkeypatch):
    fake_store = _FakeCaseStore(
        {
            "WP/999/2025": {
                "petitioner": "ABC Ltd",
                "respondent": "State",
                "orders": [
                    {
                        "board_date": "2025-01-15",
                        "order_date": "2025-01-15",
                        "order_link": "https://example.com/order-1.pdf",
                        "order_filename": "order-1.pdf",
                    },
                    {
                        "board_date": "2025-01-16",
                        "order_date": "2025-01-16",
                        "order_link": "https://example.com/order-2.pdf",
                        "order_filename": "order-2.pdf",
                    },
                ],
            }
        }
    )
    monkeypatch.setattr(
        main, "get_auto_order_manager", lambda: SimpleNamespace(case_store=fake_store)
    )

    payload = main._get_cached_case_orders_payload("WP/999/2025", "2025-01-16")

    assert payload is not None
    assert payload["source"] == "case_store_cached"
    assert len(payload["court_orders"]) == 1
    assert payload["court_orders"][0]["download_url"].endswith("order-2.pdf")



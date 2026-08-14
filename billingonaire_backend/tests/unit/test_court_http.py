"""The shared court HTTP session.

The court's server requires pre-RFC5746 TLS renegotiation, which OpenSSL
3.x refuses by default. Fixing this in only one call site moved the failure
downstream rather than removing it -- the case-status lookup started
working while the order-PDF download kept failing with the same error, so
cases resolved their order links and then landed in "needs attention"
instead of "ready". These tests pin the contract that every court request
goes through the tolerant adapter and every other host does not.
"""

import threading

# Top-level import path, matching how CourtScraper/AutoOrderManager/main
# import it -- the same file imported under two module names would produce
# two distinct adapter classes and break the isinstance checks below.
from court_http import (
    COURT_HOST_PREFIXES,
    SSL_OP_LEGACY_SERVER_CONNECT,
    LegacyRenegotiationAdapter,
    court_get,
    get_session,
    mount_court_adapter,
)


def _ssl_context_for(session, url):
    adapter = session.get_adapter(url)
    return adapter.poolmanager.connection_pool_kw.get("ssl_context")


def test_every_known_court_host_gets_the_legacy_adapter():
    import requests

    session = mount_court_adapter(requests.Session())
    for prefix in COURT_HOST_PREFIXES:
        adapter = session.get_adapter(f"{prefix}/bhc/casestatus/casenumber")
        assert isinstance(adapter, LegacyRenegotiationAdapter), prefix


def test_court_adapter_enables_legacy_renegotiation():
    import requests

    session = mount_court_adapter(requests.Session())
    ctx = _ssl_context_for(session, "https://bombayhighcourt.gov.in/bhc/x")
    assert ctx is not None
    assert ctx.options & SSL_OP_LEGACY_SERVER_CONNECT


def test_order_pdf_download_path_uses_the_legacy_adapter():
    """The exact URL shape that was failing in production after the
    case-status lookup had already been fixed."""
    session = get_session()
    adapter = session.get_adapter(
        "https://bombayhighcourt.gov.in/bhc/casestatus/order-pdf/"
        "HCBM010466682024/2026-04-24?path=abc%3D%3D"
    )
    assert isinstance(adapter, LegacyRenegotiationAdapter)


def test_non_court_hosts_are_left_on_the_default_adapter():
    """Archived PDFs live on Google Cloud Storage -- those must keep strict
    default TLS rather than inheriting the court's legacy tolerance."""
    session = get_session()
    for url in (
        "https://storage.googleapis.com/bucket/court-orders/WP-1-2026/2026-01-01.pdf",
        "https://generativelanguage.googleapis.com/v1/models",
    ):
        assert not isinstance(session.get_adapter(url), LegacyRenegotiationAdapter)


def test_sessions_are_per_thread():
    """Order fetch/analysis run on thread pools and requests.Session is not
    documented as thread-safe (its cookie jar mutates as responses arrive),
    so each worker thread must get its own session."""
    sessions = {}

    def record(name):
        sessions[name] = get_session()

    threads = [threading.Thread(target=record, args=(i,)) for i in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(sessions) == 3
    assert len({id(s) for s in sessions.values()}) == 3


def test_same_thread_reuses_one_session():
    """Per-thread, not per-call -- connection pooling still applies."""
    assert get_session() is get_session()


def test_court_get_issues_the_request_through_the_shared_session(monkeypatch):
    captured = {}

    class _FakeResponse:
        status_code = 200

    def fake_get(self, url, **kwargs):
        captured["url"] = url
        captured["kwargs"] = kwargs
        captured["session"] = self
        return _FakeResponse()

    import requests

    monkeypatch.setattr(requests.Session, "get", fake_get)

    response = court_get("https://bombayhighcourt.gov.in/bhc/x.pdf", timeout=30)

    assert response.status_code == 200
    assert captured["url"] == "https://bombayhighcourt.gov.in/bhc/x.pdf"
    assert captured["kwargs"]["timeout"] == 30
    assert captured["session"] is get_session()

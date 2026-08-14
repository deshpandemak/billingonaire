"""Shared HTTP plumbing for talking to the Bombay High Court website.

The court's web server still requires the old, pre-RFC5746 TLS
renegotiation handshake that OpenSSL 3.x (which ships with Python 3.11 on
the deploy image) refuses by default. Any plain ``requests`` call to it
dies before it reaches application code with::

    [SSL: UNSAFE_LEGACY_RENEGOTIATION_DISABLED] unsafe legacy renegotiation
    disabled (_ssl.c:1016)

A real browser tolerates this silently, which is why the Playwright path
never hit it and only the HTTP paths broke.

This module exists because the fix has to apply to *every* court request,
not just one. The case-status lookup (CourtScraper) and the order-PDF
download (AutoOrderManager, plus several main.py endpoints) are separate
call sites that were each constructing their own bare ``requests``
session, so fixing only the first one moved the failure downstream rather
than removing it: cases started resolving their order links and then
failed to download the actual PDFs, landing in "needs attention" instead
of "ready".

Use :func:`court_get` for one-off downloads, or :func:`mount_court_adapter`
when a caller needs to own a full ``requests.Session`` (cookies, CSRF).
"""

import ssl
import threading
from typing import Any

import requests
from requests.adapters import HTTPAdapter

# OpenSSL's SSL_OP_LEGACY_SERVER_CONNECT. Not exposed as a named ssl.OP_*
# constant until Python 3.12 (this project runs 3.11), but
# SSLContext.options accepts the raw OpenSSL bit on any version.
SSL_OP_LEGACY_SERVER_CONNECT = 0x4

# Every host the court serves case data or order PDFs from. The adapter is
# mounted per-host rather than for all of https:// so that unrelated
# traffic through the same session -- notably Google Cloud Storage, which
# serves our archived PDFs -- keeps strict default TLS behaviour.
COURT_HOST_PREFIXES = (
    "https://bombayhighcourt.gov.in",
    "https://www.bombayhighcourt.gov.in",
    "https://bombayhighcourt.nic.in",
    "https://www.bombayhighcourt.nic.in",
    "https://hcbombay.gov.in",
    "https://www.hcbombay.gov.in",
)


class LegacyRenegotiationAdapter(HTTPAdapter):
    """A requests adapter that permits the court site's legacy TLS
    renegotiation -- the same tolerance a browser already has."""

    def init_poolmanager(self, *args, **kwargs):
        ctx = ssl.create_default_context()
        ctx.options |= SSL_OP_LEGACY_SERVER_CONNECT
        kwargs["ssl_context"] = ctx
        return super().init_poolmanager(*args, **kwargs)

    def proxy_manager_for(self, *args, **kwargs):
        ctx = ssl.create_default_context()
        ctx.options |= SSL_OP_LEGACY_SERVER_CONNECT
        kwargs["ssl_context"] = ctx
        return super().proxy_manager_for(*args, **kwargs)


def mount_court_adapter(session: requests.Session) -> requests.Session:
    """Mount the legacy-renegotiation adapter for every court host on
    *session*, leaving all other hosts on the default adapter. Returns the
    same session for chaining."""
    adapter = LegacyRenegotiationAdapter()
    for prefix in COURT_HOST_PREFIXES:
        session.mount(prefix, adapter)
    return session


_thread_local = threading.local()


def get_session() -> requests.Session:
    """A court-capable session, one per thread.

    Order fetch and analysis run on ThreadPoolExecutor pools, and
    ``requests.Session`` is not documented as thread-safe (its cookie jar
    is mutated as responses arrive). Per-thread sessions keep urllib3's
    connection pooling without sharing mutable state across workers.
    """
    session = getattr(_thread_local, "court_session", None)
    if session is None:
        session = mount_court_adapter(requests.Session())
        _thread_local.court_session = session
    return session


def court_get(url: str, **kwargs: Any) -> requests.Response:
    """``requests.get`` that can actually complete the court's TLS
    handshake. Safe for non-court URLs too (GCS archive links included) --
    those simply use the default adapter."""
    return get_session().get(url, **kwargs)

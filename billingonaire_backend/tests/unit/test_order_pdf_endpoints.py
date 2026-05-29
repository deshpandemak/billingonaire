"""End-to-end tests for GET /orders/pdf/{doc_id} and GET /admin/test-gcs."""

import sys
import types
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

# Stub spaCy before any main import so the import-time crash is avoided.
if "spacy" not in sys.modules:
    _spacy_stub = types.ModuleType("spacy")
    _spacy_matcher_stub = types.ModuleType("spacy.matcher")

    class _Matcher:  # pragma: no cover
        pass

    _spacy_matcher_stub.Matcher = _Matcher
    _spacy_stub.matcher = _spacy_matcher_stub
    sys.modules["spacy"] = _spacy_stub
    sys.modules["spacy.matcher"] = _spacy_matcher_stub

from fastapi.testclient import TestClient

import main

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

FAKE_PDF = b"%PDF-1.4 test-court-order-content"
FAKE_GCS_URL = "https://storage.googleapis.com/billingonaire-court-orders/court-orders/WP-123-2025/2025-01-15.pdf"
FAKE_COURT_URL = "https://bombayhighcourt.nic.in/generatenewauth.php?bhcpar=AAABBB"
FAKE_DOC_ID = "WP-123-2025-20250115"
FAKE_ADMIN = {"uid": "admin1", "email": "admin@test.com", "legal_category": "admin"}


def _make_snap(exists: bool, data: dict = None):
    """Return a Firestore snapshot-like MagicMock."""
    snap = MagicMock()
    snap.exists = exists
    snap.to_dict.return_value = data or {}
    return snap


def _make_db(daily_boards_snap=None, case_details_snap=None):
    """Return a mock firestore client with configurable collection responses."""
    db = MagicMock()

    def _collection(name):
        col = MagicMock()
        if name == "daily-boards":
            col.document.return_value.get.return_value = (
                daily_boards_snap or _make_snap(False)
            )
        elif name == "case-details":
            col.document.return_value.get.return_value = (
                case_details_snap or _make_snap(False)
            )
        else:
            col.document.return_value.get.return_value = _make_snap(False)
        return col

    db.collection.side_effect = _collection
    return db


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def client():
    """TestClient with Firebase and admin auth mocked."""
    from main import app, require_admin

    app.dependency_overrides[require_admin] = lambda: FAKE_ADMIN

    with (patch("main.ensure_firebase"),):
        yield TestClient(app, raise_server_exceptions=False)

    app.dependency_overrides.pop(require_admin, None)


# ---------------------------------------------------------------------------
# GET /orders/pdf/{doc_id}  — basic routing
# ---------------------------------------------------------------------------


def test_get_order_pdf_doc_not_found(client, monkeypatch):
    """Returns 404 when the daily-boards document doesn't exist."""
    db = _make_db(daily_boards_snap=_make_snap(False))
    monkeypatch.setattr(main.firestore, "client", lambda: db)

    resp = client.get(f"/orders/pdf/{FAKE_DOC_ID}")

    assert resp.status_code == 404
    assert "not found" in resp.json()["detail"].lower()


def test_get_order_pdf_no_order_link_anywhere(client, monkeypatch):
    """Returns 404 when neither daily-boards nor case-details holds an order_link."""
    board_snap = _make_snap(
        True,
        {"case_type": "WP", "case_no": "123", "case_year": "2025", "order_link": ""},
    )
    db = _make_db(
        daily_boards_snap=board_snap,
        case_details_snap=_make_snap(True, {"latest_order_link": ""}),
    )
    monkeypatch.setattr(main.firestore, "client", lambda: db)

    resp = client.get(f"/orders/pdf/{FAKE_DOC_ID}")

    assert resp.status_code == 404
    assert "no order link" in resp.json()["detail"].lower()


# ---------------------------------------------------------------------------
# GET /orders/pdf/{doc_id}  — fallback to case-details.latest_order_link
# ---------------------------------------------------------------------------


def test_get_order_pdf_falls_back_to_case_details(client, monkeypatch):
    """When daily-boards.order_link is empty, falls back to case-details.latest_order_link."""
    board_snap = _make_snap(
        True,
        {
            "case_type": "WP",
            "case_no": "123",
            "case_year": "2025",
            "order_link": "",  # empty in daily-boards
        },
    )
    # case-details has the link
    details_snap = _make_snap(True, {"latest_order_link": FAKE_COURT_URL})
    db = _make_db(daily_boards_snap=board_snap, case_details_snap=details_snap)
    monkeypatch.setattr(main.firestore, "client", lambda: db)

    fake_resp = MagicMock()
    fake_resp.content = FAKE_PDF
    fake_resp.raise_for_status.return_value = None
    monkeypatch.setattr(main.requests, "get", lambda *a, **kw: fake_resp)

    # Suppress background executor call
    monkeypatch.setattr(
        main,
        "get_auto_order_manager",
        lambda: SimpleNamespace(
            _upload_order_to_gcs=lambda *a, **kw: None,
            _gcs_bucket_name="",
            _process_single_case=lambda *a, **kw: None,
        ),
    )

    resp = client.get(f"/orders/pdf/{FAKE_DOC_ID}")

    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/pdf"
    assert resp.content == FAKE_PDF


def test_get_order_pdf_case_details_doc_id_format(client, monkeypatch):
    """Verifies case-details lookup uses 'TYPE-NO-YEAR' doc ID format."""
    board_snap = _make_snap(
        True,
        {"case_type": "SLP", "case_no": "9999", "case_year": "2023", "order_link": ""},
    )
    captured = {}

    def _collection(name):
        col = MagicMock()
        if name == "case-details":

            def _document(doc_id):
                captured["doc_id"] = doc_id
                inner = MagicMock()
                inner.get.return_value = _make_snap(False)
                return inner

            col.document.side_effect = _document
        else:
            col.document.return_value.get.return_value = board_snap
        return col

    db = MagicMock()
    db.collection.side_effect = _collection
    monkeypatch.setattr(main.firestore, "client", lambda: db)

    resp = client.get(f"/orders/pdf/{FAKE_DOC_ID}")

    # Should have looked up "SLP-9999-2023"
    assert captured.get("doc_id") == "SLP-9999-2023"
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /orders/pdf/{doc_id}  — GCS URL path
# ---------------------------------------------------------------------------


def test_get_order_pdf_gcs_url_streams_via_adc(client, monkeypatch):
    """GCS URLs are fetched via ADC and streamed as application/pdf."""
    board_snap = _make_snap(True, {"order_link": FAKE_GCS_URL})
    db = _make_db(daily_boards_snap=board_snap)
    monkeypatch.setattr(main.firestore, "client", lambda: db)

    mock_gcs_client = MagicMock()
    mock_gcs_client.bucket.return_value.blob.return_value.download_as_bytes.return_value = (
        FAKE_PDF
    )

    with patch("google.cloud.storage.Client", return_value=mock_gcs_client):
        resp = client.get(f"/orders/pdf/{FAKE_DOC_ID}")

    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/pdf"
    assert resp.content == FAKE_PDF


def test_get_order_pdf_gcs_url_parses_bucket_and_blob(client, monkeypatch):
    """GCS URL bucket and blob are parsed correctly from the URL."""
    gcs_url = (
        "https://storage.googleapis.com/my-bucket/court-orders/WP-1-2025/order.pdf"
    )
    board_snap = _make_snap(True, {"order_link": gcs_url})
    db = _make_db(daily_boards_snap=board_snap)
    monkeypatch.setattr(main.firestore, "client", lambda: db)

    captured = {}

    def _fake_bucket(name):
        captured["bucket"] = name
        b = MagicMock()

        def _blob(path):
            captured["blob"] = path
            bb = MagicMock()
            bb.download_as_bytes.return_value = FAKE_PDF
            return bb

        b.blob.side_effect = _blob
        return b

    mock_gcs = MagicMock()
    mock_gcs.bucket.side_effect = _fake_bucket

    with patch("google.cloud.storage.Client", return_value=mock_gcs):
        resp = client.get(f"/orders/pdf/{FAKE_DOC_ID}")

    assert resp.status_code == 200
    assert captured["bucket"] == "my-bucket"
    assert captured["blob"] == "court-orders/WP-1-2025/order.pdf"


def test_get_order_pdf_gcs_download_failure_triggers_refetch(client, monkeypatch):
    """When GCS download fails, re-fetch is queued and 503 with order_link_expired is returned."""
    board_snap = _make_snap(
        True,
        {"order_link": FAKE_GCS_URL, "case_type": "WP", "case_no": "123", "case_year": "2024"},
    )
    db = _make_db(daily_boards_snap=board_snap)
    monkeypatch.setattr(main.firestore, "client", lambda: db)

    mock_gcs_client = MagicMock()
    mock_gcs_client.bucket.return_value.blob.return_value.download_as_bytes.side_effect = Exception(
        "permission denied"
    )

    with patch("google.cloud.storage.Client", return_value=mock_gcs_client):
        resp = client.get(f"/orders/pdf/{FAKE_DOC_ID}")

    assert resp.status_code == 503
    assert resp.json()["error"] == "order_link_expired"


# ---------------------------------------------------------------------------
# GET /orders/pdf/{doc_id}  — live court URL path
# ---------------------------------------------------------------------------


def test_get_order_pdf_live_court_url_streams_pdf(client, monkeypatch):
    """Live court URL: PDF is streamed and GCS upgrade is queued."""
    board_snap = _make_snap(
        True,
        {
            "order_link": FAKE_COURT_URL,
            "case_type": "WP",
            "case_no": "123",
            "case_year": "2025",
        },
    )
    db = _make_db(daily_boards_snap=board_snap)
    monkeypatch.setattr(main.firestore, "client", lambda: db)

    fake_http = MagicMock()
    fake_http.content = FAKE_PDF
    fake_http.raise_for_status.return_value = None
    monkeypatch.setattr(main.requests, "get", lambda *a, **kw: fake_http)

    mgr = MagicMock()
    mgr._upload_order_to_gcs.return_value = None
    mgr._gcs_bucket_name = ""
    monkeypatch.setattr(main, "get_auto_order_manager", lambda: mgr)

    resp = client.get(f"/orders/pdf/{FAKE_DOC_ID}")

    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/pdf"
    assert resp.content == FAKE_PDF


def test_get_order_pdf_court_url_non_pdf_response_treated_as_expired(
    client, monkeypatch
):
    """When court URL returns non-PDF bytes, treat as expired and return 503."""
    board_snap = _make_snap(
        True,
        {
            "order_link": FAKE_COURT_URL,
            "case_type": "WP",
            "case_no": "123",
            "case_year": "2025",
        },
    )
    db = _make_db(daily_boards_snap=board_snap)
    monkeypatch.setattr(main.firestore, "client", lambda: db)

    fake_http = MagicMock()
    fake_http.content = b"<html>Session Expired</html>"  # not a PDF
    fake_http.raise_for_status.return_value = None
    monkeypatch.setattr(main.requests, "get", lambda *a, **kw: fake_http)

    mgr = MagicMock()
    monkeypatch.setattr(main, "get_auto_order_manager", lambda: mgr)

    resp = client.get(f"/orders/pdf/{FAKE_DOC_ID}")

    assert resp.status_code == 503
    body = resp.json()
    assert body["error"] == "order_link_expired"
    assert body["doc_id"] == FAKE_DOC_ID


# ---------------------------------------------------------------------------
# GET /orders/pdf/{doc_id}  — expired court URL path
# ---------------------------------------------------------------------------


def test_get_order_pdf_expired_court_url_returns_503(client, monkeypatch):
    """Expired court URL: returns 503 with error details."""
    board_snap = _make_snap(
        True,
        {
            "order_link": FAKE_COURT_URL,
            "case_type": "WP",
            "case_no": "123",
            "case_year": "2025",
        },
    )
    db = _make_db(daily_boards_snap=board_snap)
    monkeypatch.setattr(main.firestore, "client", lambda: db)

    import requests as _requests

    monkeypatch.setattr(
        main.requests,
        "get",
        lambda *a, **kw: (_ for _ in ()).throw(_requests.exceptions.Timeout()),
    )

    mgr = MagicMock()
    monkeypatch.setattr(main, "get_auto_order_manager", lambda: mgr)

    resp = client.get(f"/orders/pdf/{FAKE_DOC_ID}")

    assert resp.status_code == 503
    body = resp.json()
    assert body["error"] == "order_link_expired"
    assert "doc_id" in body


def test_get_order_pdf_expired_queues_reprocess(client, monkeypatch):
    """Expired court URL: _process_single_case is invoked via executor."""
    board_snap = _make_snap(
        True,
        {
            "order_link": FAKE_COURT_URL,
            "case_type": "WP",
            "case_no": "456",
            "case_year": "2025",
        },
    )
    db = _make_db(daily_boards_snap=board_snap)
    monkeypatch.setattr(main.firestore, "client", lambda: db)

    import requests as _requests

    monkeypatch.setattr(
        main.requests,
        "get",
        lambda *a, **kw: (_ for _ in ()).throw(_requests.exceptions.ConnectionError()),
    )

    submitted = []

    # Patch executor to capture submit calls
    fake_executor = MagicMock()
    fake_executor.submit.side_effect = (
        lambda fn, *a, **kw: submitted.append((fn, a)) or MagicMock()
    )

    mgr = MagicMock()
    monkeypatch.setattr(main, "get_auto_order_manager", lambda: mgr)

    # patch asyncio.get_event_loop().run_in_executor to capture calls
    fake_loop = MagicMock()
    monkeypatch.setattr(main.asyncio, "get_event_loop", lambda: fake_loop)

    resp = client.get(f"/orders/pdf/{FAKE_DOC_ID}")

    assert resp.status_code == 503
    # run_in_executor should have been called to queue the re-fetch
    assert fake_loop.run_in_executor.called


# ---------------------------------------------------------------------------
# GET /admin/test-gcs
# ---------------------------------------------------------------------------


def test_admin_test_gcs_skipped_when_bucket_not_configured(client, monkeypatch):
    """Returns skipped when ORDER_PDF_BUCKET env var is not set."""
    mgr = SimpleNamespace(_gcs_bucket_name="")
    monkeypatch.setattr(main, "get_auto_order_manager", lambda: mgr)

    resp = client.get("/admin/test-gcs")

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "skipped"


def test_admin_test_gcs_ok_when_bucket_accessible(client, monkeypatch):
    """Returns status:ok when GCS write/read/delete succeed."""
    mgr = SimpleNamespace(_gcs_bucket_name="test-bucket")
    monkeypatch.setattr(main, "get_auto_order_manager", lambda: mgr)

    mock_blob = MagicMock()
    mock_blob.download_as_bytes.return_value = b"ok"
    mock_bucket = MagicMock()
    mock_bucket.blob.return_value = mock_blob
    mock_gcs_client = MagicMock()
    mock_gcs_client.bucket.return_value = mock_bucket

    with patch("google.cloud.storage.Client", return_value=mock_gcs_client):
        resp = client.get("/admin/test-gcs")

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["bucket"] == "test-bucket"
    assert body["read_write"] is True


def test_admin_test_gcs_error_when_bucket_inaccessible(client, monkeypatch):
    """Returns status:error when GCS raises an exception."""
    mgr = SimpleNamespace(_gcs_bucket_name="test-bucket")
    monkeypatch.setattr(main, "get_auto_order_manager", lambda: mgr)

    mock_gcs_client = MagicMock()
    mock_gcs_client.bucket.return_value.blob.return_value.upload_from_string.side_effect = Exception(
        "403 forbidden"
    )

    with patch("google.cloud.storage.Client", return_value=mock_gcs_client):
        resp = client.get("/admin/test-gcs")

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "error"
    assert "403 forbidden" in body["detail"]

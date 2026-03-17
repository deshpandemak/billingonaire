"""Shared conftest.py for BDD specs — provides fixtures used across all step modules."""

import os
import sys
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest

# Ensure the backend package root is on the path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


# ---------------------------------------------------------------------------
# Fake users
# ---------------------------------------------------------------------------

FAKE_USER = {"uid": "test_uid", "email": "test@example.com", "role": "user"}
FAKE_ADMIN = {"uid": "admin_uid", "email": "admin@example.com", "role": "admin"}


# ---------------------------------------------------------------------------
# Firebase / Firestore mock (autouse)
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def mock_firebase_env(monkeypatch):
    """Set TESTING env var and mock Firebase for every BDD scenario."""
    monkeypatch.setenv("TESTING", "true")

    mock_client = MagicMock()
    mock_collection = MagicMock()
    mock_document = MagicMock()
    mock_doc_ref = MagicMock()

    mock_client.collection.return_value = mock_collection
    mock_collection.document.return_value = mock_document
    mock_collection.where.return_value = mock_collection
    mock_collection.limit.return_value = mock_collection
    mock_collection.order_by.return_value = mock_collection
    mock_collection.stream.return_value = []

    mock_document.get.return_value = mock_doc_ref
    mock_doc_ref.exists = True
    mock_doc_ref.to_dict.return_value = {}

    with patch("firebase_admin.firestore.client", return_value=mock_client):
        yield mock_client


@pytest.fixture
def mock_firestore_client(mock_firebase_env):
    """Expose the Firestore mock client to step definitions that need it."""
    return mock_firebase_env


# ---------------------------------------------------------------------------
# User manager mocks
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_user_manager():
    """Return a mocked UserManager used by the FastAPI app."""
    mgr = MagicMock()
    mgr.get_user_profile.return_value = {
        "uid": "test_uid",
        "email": "test@example.com",
        "role": "user",
        "is_active": True,
    }
    mgr.is_admin.return_value = False
    mgr.get_users.return_value = []
    return mgr


@pytest.fixture
def mock_admin_user_manager(mock_user_manager):
    """Return a mocked UserManager that acts as admin."""
    mock_user_manager.is_admin.return_value = True
    mock_user_manager.get_user_profile.return_value = {
        "uid": "admin_uid",
        "email": "admin@example.com",
        "role": "admin",
        "is_active": True,
    }
    return mock_user_manager


# ---------------------------------------------------------------------------
# FastAPI test clients
# ---------------------------------------------------------------------------


@pytest.fixture
def api_client(mock_user_manager):
    """TestClient for a regular (non-admin) authenticated user."""
    from fastapi.testclient import TestClient
    from main import (
        app,
        get_current_user,
        get_user_with_profile,
        require_active_user,
    )

    profile = mock_user_manager.get_user_profile(FAKE_USER["uid"])
    user_with_profile = {**FAKE_USER, "profile": profile}

    overrides = {
        get_current_user: lambda: FAKE_USER,
        require_active_user: lambda: user_with_profile,
        get_user_with_profile: lambda: user_with_profile,
    }
    app.dependency_overrides.update(overrides)

    with (
        patch("firebase_admin.auth.verify_id_token", return_value=FAKE_USER),
        patch("main.get_user_manager", return_value=mock_user_manager),
        patch("main.ensure_firebase"),
        patch("firebase_admin.auth.update_user"),
    ):
        yield TestClient(app, raise_server_exceptions=False)

    for key in overrides:
        app.dependency_overrides.pop(key, None)


@pytest.fixture
def admin_api_client(mock_admin_user_manager):
    """TestClient where the authenticated user has admin privileges."""
    from fastapi.testclient import TestClient
    from main import (
        app,
        get_current_user,
        get_user_with_profile,
        require_active_user,
        require_admin,
        require_admin_active,
    )

    profile = mock_admin_user_manager.get_user_profile(FAKE_ADMIN["uid"])
    admin_with_profile = {**FAKE_ADMIN, "profile": profile}

    overrides = {
        get_current_user: lambda: FAKE_ADMIN,
        require_active_user: lambda: admin_with_profile,
        get_user_with_profile: lambda: admin_with_profile,
        require_admin: lambda: FAKE_ADMIN,
        require_admin_active: lambda: admin_with_profile,
    }
    app.dependency_overrides.update(overrides)

    with (
        patch("firebase_admin.auth.verify_id_token", return_value=FAKE_ADMIN),
        patch("main.get_user_manager", return_value=mock_admin_user_manager),
        patch("main.ensure_firebase"),
        patch("firebase_admin.auth.create_user", return_value=MagicMock(uid="new_uid")),
        patch("firebase_admin.auth.update_user"),
        patch(
            "firebase_admin.auth.list_users",
            return_value=MagicMock(iterate_all=lambda: []),
        ),
    ):
        yield TestClient(app, raise_server_exceptions=False)

    for key in overrides:
        app.dependency_overrides.pop(key, None)


@pytest.fixture
def auth_headers():
    """Return Authorization headers (token is ignored since auth is mocked via dep overrides)."""
    return {"Authorization": "Bearer test_token"}


@pytest.fixture
def admin_auth_headers():
    """Return Authorization headers for admin."""
    return {"Authorization": "Bearer admin_test_token"}


# ---------------------------------------------------------------------------
# Sample data fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_case_data() -> Dict[str, Any]:
    return {
        "id": "test_case_123",
        "case_ref": "WP/3373/2024",
        "case_type": "WP",
        "case_no": "3373",
        "case_year": "2024",
        "board_date": "2024-10-01",
        "agp_name": "Pooja Joshi Deshpande",
        "lifecycle_status": "board_ingested",
        "order_status": "fetch_queued",
    }


@pytest.fixture
def sample_pdf_bytes() -> bytes:
    """Minimal valid PDF bytes for upload tests."""
    return (
        b"%PDF-1.4\n"
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
        b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n"
        b"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>\nendobj\n"
        b"4 0 obj\n<< /Length 44 >>\nstream\n"
        b"BT\n/F1 12 Tf\n100 700 Td\n(Test Board) Tj\nET\n"
        b"endstream\nendobj\n"
        b"5 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\nendobj\n"
        b"xref\n0 6\n"
        b"0000000000 65535 f \n"
        b"0000000009 00000 n \n"
        b"0000000058 00000 n \n"
        b"0000000115 00000 n \n"
        b"0000000262 00000 n \n"
        b"0000000357 00000 n \n"
        b"trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n439\n%%EOF"
    )

"""Integration tests for FastAPI endpoints"""

import json
from unittest.mock import MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient


@pytest.fixture
async def test_client():
    """Create test client for FastAPI app"""
    from main import app

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield client


@pytest.fixture
def mock_firebase_auth():
    """Mock Firebase authentication"""

    def mock_verify_token(token):
        return {"uid": "test_user_123", "email": "test@example.com"}

    with patch("firebase_admin.auth.verify_id_token", side_effect=mock_verify_token):
        yield


class TestHealthEndpoint:
    """Test health check endpoint"""

    @pytest.mark.asyncio
    async def test_health_check(self, test_client):
        """Test GET / health check"""
        response = await test_client.get("/")

        assert response.status_code == 200
        assert "message" in response.json()


class TestAutoOrderProcessingEndpoints:
    """Test auto order processing endpoints"""

    @pytest.mark.asyncio
    async def test_process_single_case_unauthorized(self, test_client):
        """Test processing without auth token"""
        response = await test_client.post(
            "/auto-orders/process-case",
            json={"case_id": "test_123", "case_ref": "WP/12345/2024"},
        )

        assert response.status_code in [401, 403]

    @pytest.mark.asyncio
    async def test_process_single_case_missing_params(
        self, test_client, mock_firebase_auth
    ):
        """Test processing with missing parameters"""
        response = await test_client.post(
            "/auto-orders/process-case",
            json={},
            headers={"Authorization": "Bearer test_token"},
        )

        assert response.status_code == 400
        assert "error" in response.json()

    @pytest.mark.asyncio
    async def test_start_bulk_processing_unauthorized(self, test_client):
        """Test bulk processing without auth"""
        response = await test_client.post(
            "/auto-orders/bulk-process", json={"case_ids": ["test"]}
        )

        assert response.status_code in [401, 403]


class TestOrderManagementEndpoints:
    """Test order management endpoints"""

    @pytest.mark.asyncio
    async def test_get_order_statuses_unauthorized(self, test_client):
        """Test getting order statuses without auth"""
        response = await test_client.get("/user-matters/my-matters")

        assert response.status_code in [401, 403]

    @pytest.mark.asyncio
    async def test_search_cases_unauthorized(self, test_client):
        """Test search endpoint without auth"""
        response = await test_client.get(
            "/auto-orders/search", params={"petitioner_search": "test"}
        )

        assert response.status_code in [401, 403]


class TestAnalyticsEndpoints:
    """Test analytics endpoints"""

    @pytest.mark.asyncio
    async def test_get_board_summary_unauthorized(self, test_client):
        """Test board summary without auth"""
        response = await test_client.get("/dashboard/weekly-status")

        assert response.status_code in [401, 403]

    @pytest.mark.asyncio
    async def test_get_analytics_unauthorized(self, test_client):
        """Test analytics endpoint without auth"""
        response = await test_client.get("/dashboard/agp-stats")

        assert response.status_code in [401, 403]

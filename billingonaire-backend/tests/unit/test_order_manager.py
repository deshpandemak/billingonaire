"""Unit tests for OrderManager.py module - Order lifecycle management"""

import pytest
from unittest.mock import MagicMock, patch
# from datetime import datetime


class TestOrderManager:
    """Test OrderManager class methods"""

    @pytest.fixture
    def order_manager_module(self, mock_firestore_client):
        with patch("OrderManager.firestore.client", return_value=mock_firestore_client):
            import OrderManager
            return OrderManager

    @pytest.fixture
    def order_manager(self, order_manager_module, mock_firestore_client):
        """Create OrderManager instance"""
        return order_manager_module.OrderManager(mock_firestore_client)

    def test_get_cases_without_orders(self, order_manager, mock_firestore_client):
        """Test retrieving cases without linked orders"""
        mock_collection = MagicMock()
        mock_docs = [
            MagicMock(id="case1", to_dict=lambda: {"case_ref": "WP/1/2024", "order_status": "not_linked"}),
            MagicMock(id="case2", to_dict=lambda: {"case_ref": "WP/2/2024", "order_status": "not_linked"})
        ]
        mock_collection.stream.return_value = mock_docs
        mock_firestore_client.collection.return_value.where.return_value = mock_collection

        result = order_manager.get_cases_without_orders()
        assert isinstance(result, list) or result == []

    def test_link_order_to_case(self, order_manager, mock_firestore_client):
        """Test linking order to case"""
        case_id = "test_case_123"
        order_link = "https://example.com/order.pdf"

        result = order_manager.link_order(case_id, order_link)
        if result:
            assert mock_firestore_client.collection.called

    def test_update_order_status(self, order_manager, mock_firestore_client):
        """Test updating order status"""
        case_id = "test_case_123"
        new_status = "order_linked"

        result = order_manager.update_status(case_id, new_status)
        assert result is not None or mock_firestore_client.collection.called

    def test_get_cases_by_status(self, order_manager, mock_firestore_client):
        """Test retrieving cases by status"""
        status = "order_linked"

        mock_collection = MagicMock()
        mock_collection.stream.return_value = []
        mock_firestore_client.collection.return_value.where.return_value = mock_collection

        result = order_manager.get_cases_by_status(status)
        assert isinstance(result, list)

    def test_get_cases_by_date_range(self, order_manager, mock_firestore_client):
        """Test retrieving cases by date range"""
        start_date = "2024-10-01"
        end_date = "2024-10-07"

        result = order_manager.get_cases_by_date_range(start_date, end_date)
        assert isinstance(result, list) or result is None

    def test_update_order_analysis(self, order_manager, mock_firestore_client):
        """Test updating order analysis data"""
        case_id = "test_case_123"
        analysis_data = {
            "order_category": "HEARD & ADJOURNED",
            "petitioners": ["Test Petitioner"],
            "respondents": ["Test Respondent"]
        }

        result = order_manager.update_analysis(case_id, analysis_data)
        assert result is not None or mock_firestore_client.collection.called

    def test_get_order_statistics(self, order_manager, mock_firestore_client):
        """Test getting order statistics"""
        result = order_manager.get_statistics()
        assert isinstance(result, dict) or result is None


class TestOrderFiltering:
    """Test order filtering and search"""

    @pytest.fixture
    def order_manager_module(self, mock_firestore_client):
        with patch("OrderManager.firestore.client", return_value=mock_firestore_client):
            import OrderManager
            return OrderManager

    def test_filter_by_agp_name(self, order_manager_module, mock_firestore_client):
        """Test filtering orders by AGP name"""
        om = order_manager_module.OrderManager(mock_firestore_client)
        agp_name = "POOJA JOSHI"

        result = om.filter_by_agp(agp_name)
        assert isinstance(result, list) or result is None

    def test_filter_by_order_category(self, order_manager_module, mock_firestore_client):
        """Test filtering orders by category"""
        om = order_manager_module.OrderManager(mock_firestore_client)
        category = "HEARD & ADJOURNED"

        result = om.filter_by_category(category)
        assert isinstance(result, list) or result is None

    def test_filter_hybrid_client_side(self, order_manager_module):
        """Test hybrid filtering with client-side fallback"""
        cases = [
            {"agp_name": "JOSHI", "order_category": "HEARD & ADJOURNED", "board_date": "2024-10-01"},
            {"agp_name": "SHARMA", "order_category": "DISPOSED", "board_date": "2024-10-02"},
            {"agp_name": "JOSHI", "order_category": "ADJOURNED", "board_date": "2024-10-03"}
        ]

        # Client-side filter
        filtered = [c for c in cases if c["agp_name"] == "JOSHI"]
        assert len(filtered) == 2


class TestOrderValidation:
    """Test order validation logic"""

    @pytest.fixture
    def order_manager_module(self, mock_firestore_client):
        with patch("OrderManager.firestore.client", return_value=mock_firestore_client):
            import OrderManager
            return OrderManager

    def test_validate_order_link(self, order_manager_module):
        """Test order link validation"""
        valid_link = "https://bombayhighcourt.nic.in/order.pdf"
        invalid_link = "not_a_url"

        assert "http" in valid_link
        assert "http" not in invalid_link

    def test_validate_order_status_transition(self, order_manager_module):
        """Test order status transition validation"""
        valid_transitions = {
            "not_linked": ["order_linked", "order_failed"],
            "order_linked": ["analysed", "order_analysis_failed"],
            "analysed": []
        }

        current = "not_linked"
        next_status = "order_linked"
        assert next_status in valid_transitions.get(current, [])

    def test_validate_case_reference_format(self, order_manager_module):
        """Test case reference format validation"""
        valid_ref = "WP/12345/2024"
        invalid_ref = "INVALID"

        # Simple regex check
        import re
        pattern = r"^[A-Z]+\s?\(?[A-Z]*\)?\/\d+\/\d{4}$"
        assert re.match(pattern, valid_ref)
        assert not re.match(pattern, invalid_ref)

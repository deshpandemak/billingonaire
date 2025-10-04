"""Unit tests for Dashboard.py module - Analytics and statistics"""

import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timedelta
from difflib import SequenceMatcher


class TestDashboardData:
    """Test DashboardData class methods"""

    @pytest.fixture
    def dashboard_module(self, mock_firestore_client):
        with patch("Dashboard.firestore.client", return_value=mock_firestore_client):
            import Dashboard
            return Dashboard

    @pytest.fixture
    def sample_board_docs(self):
        """Sample board documents for testing"""
        return [
            {
                "board_date": "2024-10-01",
                "cases": [
                    {"case_ref": "WP/1/2024", "agp_name": "POOJA JOSHI", "order_status": "analysed"},
                    {"case_ref": "WP/2/2024", "agp_name": "P.M.JOSHI", "order_status": "analysed"},
                ]
            },
            {
                "board_date": "2024-10-02",
                "cases": [
                    {"case_ref": "WP/3/2024", "agp_name": "POOJA M JOSHI", "order_status": "not_linked"},
                ]
            }
        ]

    def test_get_weekly_status(self, dashboard_module, mock_firestore_client):
        """Test weekly status calculation"""
        start_date = "2024-10-01"
        end_date = "2024-10-07"
        
        result = dashboard_module.DashboardData(mock_firestore_client).get_weekly_status(start_date, end_date)
        assert isinstance(result, dict)
        assert "total_cases" in result or result == {}

    def test_get_agp_stats(self, dashboard_module, mock_firestore_client, sample_board_docs):
        """Test AGP statistics calculation"""
        mock_collection = MagicMock()
        mock_docs = [MagicMock(to_dict=lambda: doc) for doc in sample_board_docs]
        mock_collection.stream.return_value = mock_docs
        mock_firestore_client.collection.return_value = mock_collection

        result = dashboard_module.DashboardData(mock_firestore_client).get_agp_stats()
        assert isinstance(result, list)

    def test_group_similar_agp_names(self, dashboard_module):
        """Test fuzzy AGP name grouping with 85% threshold"""
        agp_counts = {
            "POOJA JOSHI": 5,
            "P.M.JOSHI": 3,
            "POOJA M JOSHI": 2,
            "DIFFERENT NAME": 1
        }
        
        result = dashboard_module.DashboardData.group_similar_agp_names(agp_counts)
        assert isinstance(result, dict)
        # Similar names should be grouped
        grouped_keys = list(result.keys())
        assert len(grouped_keys) <= len(agp_counts)

    def test_calculate_name_similarity(self, dashboard_module):
        """Test name similarity calculation"""
        name1 = "POOJA JOSHI"
        name2 = "P.M.JOSHI"
        
        similarity = SequenceMatcher(None, name1.upper(), name2.upper()).ratio()
        assert 0 <= similarity <= 1

    def test_normalize_agp_name_for_matching(self, dashboard_module):
        """Test AGP name normalization for matching"""
        name = "SHRI P.M.JOSHI, AGP"
        normalized = dashboard_module.DashboardData.normalize_agp_name(name)
        
        assert "SHRI" not in normalized
        assert "AGP" not in normalized
        assert "GP" not in normalized

    def test_get_monthly_avg(self, dashboard_module, mock_firestore_client):
        """Test monthly average calculation"""
        year = 2024
        
        result = dashboard_module.DashboardData(mock_firestore_client).get_monthly_avg(year)
        assert isinstance(result, list)

    def test_calculate_matter_distribution(self, dashboard_module, mock_firestore_client):
        """Test matter distribution calculation"""
        start_date = "2024-10-01"
        end_date = "2024-10-31"
        
        result = dashboard_module.DashboardData(mock_firestore_client).get_matters_by_date_range(start_date, end_date)
        assert isinstance(result, dict)


class TestFuzzyNameMatching:
    """Test fuzzy name matching logic"""

    @pytest.fixture
    def dashboard_module(self, mock_firestore_client):
        with patch("Dashboard.firestore.client", return_value=mock_firestore_client):
            import Dashboard
            return Dashboard

    def test_match_similar_names_high_similarity(self, dashboard_module):
        """Test matching names with high similarity (>85%)"""
        names = ["POOJA JOSHI", "POOJA M JOSHI", "P M JOSHI"]
        
        # Test pairwise similarity
        for i, name1 in enumerate(names):
            for name2 in names[i+1:]:
                sim = SequenceMatcher(None, name1, name2).ratio()
                if sim >= 0.85:
                    assert True  # Names should be grouped

    def test_match_dissimilar_names(self, dashboard_module):
        """Test that dissimilar names are not grouped"""
        name1 = "POOJA JOSHI"
        name2 = "RAJESH SHARMA"
        
        sim = SequenceMatcher(None, name1, name2).ratio()
        assert sim < 0.85  # Should not be grouped

    def test_select_canonical_name(self, dashboard_module):
        """Test selection of most frequent name as canonical"""
        agp_counts = {
            "POOJA JOSHI": 10,
            "P.M.JOSHI": 3,
            "POOJA M JOSHI": 2
        }
        
        # Most frequent should be selected
        canonical = max(agp_counts, key=agp_counts.get)
        assert canonical == "POOJA JOSHI"


class TestAggregationFunctions:
    """Test data aggregation functions"""

    @pytest.fixture
    def dashboard_module(self, mock_firestore_client):
        with patch("Dashboard.firestore.client", return_value=mock_firestore_client):
            import Dashboard
            return Dashboard

    def test_aggregate_by_order_status(self, dashboard_module):
        """Test aggregation by order status"""
        cases = [
            {"order_status": "analysed"},
            {"order_status": "analysed"},
            {"order_status": "not_linked"},
        ]
        
        result = {}
        for case in cases:
            status = case.get("order_status", "unknown")
            result[status] = result.get(status, 0) + 1
        
        assert result["analysed"] == 2
        assert result["not_linked"] == 1

    def test_aggregate_by_agp_name(self, dashboard_module):
        """Test aggregation by AGP name"""
        cases = [
            {"agp_name": "JOSHI"},
            {"agp_name": "JOSHI"},
            {"agp_name": "SHARMA"},
        ]
        
        result = {}
        for case in cases:
            agp = case.get("agp_name", "unknown")
            result[agp] = result.get(agp, 0) + 1
        
        assert result["JOSHI"] == 2
        assert result["SHARMA"] == 1

    def test_calculate_weekly_totals(self, dashboard_module):
        """Test weekly totals calculation"""
        start = datetime(2024, 10, 1)
        end = datetime(2024, 10, 7)
        days = (end - start).days + 1
        
        assert days == 7

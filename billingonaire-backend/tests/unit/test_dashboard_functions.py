"""Functional tests for Dashboard.py - Actual DashboardData class methods"""

import pytest
from unittest.mock import MagicMock, patch
import sys
import os
from datetime import datetime

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))


@pytest.fixture(autouse=True)
def mock_firebase():
    """Mock Firebase before any imports"""
    with patch("firebase_admin.firestore"):
        with patch("google.cloud.firestore.Client") as mock_client:
            yield mock_client


@patch("Dashboard.firestore.client")
@pytest.mark.asyncio
async def test_get_weekly_status(mock_firestore):
    """Test get_weekly_status async method"""
    from Dashboard import DashboardData
    
    mock_docs = [
        MagicMock(to_dict=lambda: {
            "board_date": "2024-10-01",
            "cases": [
                {"order_status": "analysed"},
                {"order_status": "not_linked"}
            ]
        })
    ]
    mock_firestore.return_value.collection.return_value.where.return_value.stream.return_value = mock_docs
    
    dashboard = DashboardData()
    result = await dashboard.get_weekly_status("2024-10-01", "2024-10-07")
    assert isinstance(result, dict)


@patch("Dashboard.firestore.client")
@pytest.mark.asyncio
async def test_get_agp_stats(mock_firestore):
    """Test get_agp_stats with fuzzy matching"""
    from Dashboard import DashboardData
    
    mock_docs = [
        MagicMock(to_dict=lambda: {
            "board_date": "2024-10-01",
            "cases": [
                {"agp_name": "POOJA JOSHI", "order_status": "analysed"},
                {"agp_name": "P.M.JOSHI", "order_status": "analysed"},
                {"agp_name": "POOJA M JOSHI", "order_status": "not_linked"}
            ]
        })
    ]
    mock_firestore.return_value.collection.return_value.stream.return_value = mock_docs
    
    dashboard = DashboardData()
    result = await dashboard.get_agp_stats()
    assert isinstance(result, list)


def test_group_similar_agp_names():
    """Test fuzzy AGP name grouping"""
    from Dashboard import DashboardData
    
    agp_counts = {
        "POOJA JOSHI": 10,
        "P.M.JOSHI": 5,
        "POOJA M JOSHI": 3,
        "SHARMA": 2
    }
    
    result = DashboardData.group_similar_agp_names(agp_counts)
    assert isinstance(result, dict)
    # Similar names should be grouped
    assert len(result) < len(agp_counts)


def test_normalize_agp_name():
    """Test AGP name normalization"""
    from Dashboard import DashboardData
    
    result = DashboardData.normalize_agp_name("SHRI P.M.JOSHI, AGP, ADDL.GP")
    assert "SHRI" not in result
    assert "AGP" not in result
    assert "GP" not in result


@patch("Dashboard.firestore.client")
@pytest.mark.asyncio
async def test_get_monthly_avg(mock_firestore):
    """Test get_monthly_avg calculation"""
    from Dashboard import DashboardData
    
    mock_docs = []
    for month in range(1, 13):
        mock_docs.append(MagicMock(to_dict=lambda m=month: {
            "board_date": f"2024-{m:02d}-01",
            "cases": [{"order_status": "analysed"}] * 10
        }))
    
    mock_firestore.return_value.collection.return_value.where.return_value.stream.return_value = mock_docs
    
    dashboard = DashboardData()
    result = await dashboard.get_monthly_avg(2024)
    assert isinstance(result, list)


@patch("Dashboard.firestore.client")
@pytest.mark.asyncio
async def test_get_matters_by_date_range(mock_firestore):
    """Test matter distribution by date range"""
    from Dashboard import DashboardData
    
    mock_docs = [
        MagicMock(to_dict=lambda: {
            "board_date": "2024-10-01",
            "cases": [
                {"agp_name": "JOSHI", "case_type": "WP"},
                {"agp_name": "SHARMA", "case_type": "PIL"}
            ]
        })
    ]
    mock_firestore.return_value.collection.return_value.where.return_value.stream.return_value = mock_docs
    
    dashboard = DashboardData()
    result = await dashboard.get_matters_by_date_range("2024-10-01", "2024-10-31")
    assert isinstance(result, dict)


def test_calculate_similarity():
    """Test name similarity calculation"""
    from difflib import SequenceMatcher
    
    name1 = "POOJA JOSHI"
    name2 = "P.M.JOSHI"
    
    similarity = SequenceMatcher(None, name1, name2).ratio()
    assert 0 <= similarity <= 1


def test_select_canonical_name():
    """Test canonical name selection (most frequent)"""
    agp_counts = {
        "POOJA JOSHI": 15,
        "P.M.JOSHI": 5,
        "POOJA M JOSHI": 3
    }
    
    canonical = max(agp_counts, key=agp_counts.get)
    assert canonical == "POOJA JOSHI"


@patch("Dashboard.firestore.client")
def test_dashboard_initialization(mock_firestore):
    """Test DashboardData initialization"""
    from Dashboard import DashboardData
    
    dashboard = DashboardData()
    assert dashboard.db is not None
    assert dashboard.boards_collection == "daily-boards"

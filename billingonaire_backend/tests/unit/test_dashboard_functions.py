"""Functional tests for Dashboard.py - Actual DashboardData class methods"""

import os
import sys
from unittest.mock import MagicMock, patch

import pytest

# Unused: from datetime import datetime

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))


@pytest.fixture(autouse=True)
def mock_firebase():
    """Mock Firebase before any imports"""
    with patch("firebase_admin.firestore"):
        with patch("google.cloud.firestore.Client") as mock_client:
            yield mock_client


@pytest.mark.asyncio
@patch("Dashboard.firestore.client")
async def test_get_weekly_status(mock_firestore):
    """Test get_weekly_status async method (returns list not dict)"""
    from Dashboard import DashboardData

    mock_docs = [
        MagicMock(
            to_dict=lambda: {
                "board_date": "2024-10-01",
                "cases": [{"order_status": "analysed"}, {"order_status": "not_linked"}],
            }
        )
    ]
    mock_firestore.return_value.collection.return_value.where.return_value.stream.return_value = (
        mock_docs
    )

    dashboard = DashboardData()
    result = await dashboard.get_weekly_status("2024-10-01", "2024-10-07")
    assert isinstance(result, list)  # Returns list of weekly status data


@pytest.mark.asyncio
@patch("Dashboard.firestore.client")
async def test_get_agp_stats(mock_firestore):
    """Test get_agp_stats with fuzzy matching"""
    from Dashboard import DashboardData

    mock_docs = [
        MagicMock(
            to_dict=lambda: {
                "board_date": "2024-10-01",
                "cases": [
                    {"agp_name": "POOJA JOSHI", "order_status": "analysed"},
                    {"agp_name": "P.M.JOSHI", "order_status": "analysed"},
                    {"agp_name": "POOJA M JOSHI", "order_status": "not_linked"},
                ],
            }
        )
    ]
    mock_firestore.return_value.collection.return_value.stream.return_value = mock_docs

    dashboard = DashboardData()
    result = await dashboard.get_agp_stats()
    assert isinstance(result, list)


@pytest.mark.asyncio
@patch("Dashboard.firestore.client")
async def test_get_agp_stats_second_call_is_served_from_cache(mock_firestore):
    """The unfiltered ('all AGPs') call is the expensive one -- a full
    daily-boards scan plus O(N^2) fuzzy grouping. A second call with the
    same params within the TTL must not touch Firestore again."""
    from Dashboard import DashboardData

    mock_docs = [
        MagicMock(to_dict=lambda: {"respondent_lawyer": "POOJA JOSHI"}),
        MagicMock(to_dict=lambda: {"respondent_lawyer": "POOJA JOSHI"}),
    ]
    stream_mock = mock_firestore.return_value.collection.return_value.stream
    stream_mock.return_value = mock_docs

    dashboard = DashboardData()
    first = await dashboard.get_agp_stats()
    second = await dashboard.get_agp_stats()

    assert second == first
    stream_mock.assert_called_once()


@pytest.mark.asyncio
@patch("Dashboard.firestore.client")
async def test_get_agp_stats_different_agp_bypasses_cache(mock_firestore):
    """A different agp_name must be its own cache entry, not collide with
    (or be served by) the unfiltered admin view's cached result."""
    from Dashboard import DashboardData

    mock_docs = [MagicMock(to_dict=lambda: {"respondent_lawyer": "POOJA JOSHI"})]
    stream_mock = (
        mock_firestore.return_value.collection.return_value.where.return_value.stream
    )
    stream_mock.return_value = mock_docs

    dashboard = DashboardData()
    await dashboard.get_agp_stats(agp_name="POOJA JOSHI")
    await dashboard.get_agp_stats(agp_name="SHARMA")

    assert stream_mock.call_count == 2


@pytest.mark.asyncio
@patch("Dashboard.firestore.client")
async def test_get_agp_stats_cache_is_scoped_to_the_instance(mock_firestore):
    """Regression guard: the cache must be instance-level, not a module
    global -- two separate DashboardData() instances (e.g. two separate
    tests, or two request-scoped instances) must not share a cache entry."""
    from Dashboard import DashboardData

    mock_docs = [MagicMock(to_dict=lambda: {"respondent_lawyer": "POOJA JOSHI"})]
    stream_mock = mock_firestore.return_value.collection.return_value.stream
    stream_mock.return_value = mock_docs

    await DashboardData().get_agp_stats()
    await DashboardData().get_agp_stats()

    assert stream_mock.call_count == 2


@patch("Dashboard.firestore.client")
def test_group_similar_agp_names(mock_firestore):
    """Test fuzzy AGP name grouping"""
    from Dashboard import DashboardData

    agp_counts = {"POOJA JOSHI": 10, "P.M.JOSHI": 5, "POOJA M JOSHI": 3, "SHARMA": 2}

    dashboard = DashboardData()
    result = dashboard.group_similar_agp_names(agp_counts)
    assert isinstance(result, dict)
    # Similar names should be grouped
    assert len(result) < len(agp_counts)


@patch("Dashboard.firestore.client")
def test_normalize_agp_name(mock_firestore):
    """Test AGP name normalization"""
    from Dashboard import DashboardData

    dashboard = DashboardData()
    result = dashboard.normalize_agp_name("SHRI P.M.JOSHI, AGP, ADDL.GP")
    assert "SHRI" not in result
    assert "AGP" not in result
    assert "GP" not in result


@pytest.mark.asyncio
@patch("Dashboard.firestore.client")
async def test_get_monthly_avg(mock_firestore):
    """Test get_monthly_avg calculation"""
    from Dashboard import DashboardData

    mock_docs = []
    for month in range(1, 13):
        mock_docs.append(
            MagicMock(
                to_dict=lambda m=month: {
                    "board_date": f"2024-{m:02d}-01",
                    "cases": [{"order_status": "analysed"}] * 10,
                }
            )
        )

    mock_firestore.return_value.collection.return_value.where.return_value.stream.return_value = (
        mock_docs
    )

    dashboard = DashboardData()
    result = await dashboard.get_monthly_avg(2024)
    assert isinstance(result, list)


@pytest.mark.asyncio
@patch("Dashboard.firestore.client")
async def test_get_monthly_avg_second_call_is_served_from_cache(mock_firestore):
    """Same unbounded-scan-plus-fuzzy-grouping cost as get_agp_stats when
    no year/agp filter is given -- a repeat call within the TTL must not
    re-query Firestore."""
    from Dashboard import DashboardData

    mock_docs = [
        MagicMock(
            to_dict=lambda: {
                "respondent_lawyer": "POOJA JOSHI",
                "board_date": "2024-01-15",
            }
        )
    ]
    stream_mock = mock_firestore.return_value.collection.return_value.stream
    stream_mock.return_value = mock_docs

    dashboard = DashboardData()
    first = await dashboard.get_monthly_avg()
    second = await dashboard.get_monthly_avg()

    assert second == first
    stream_mock.assert_called_once()


@pytest.mark.asyncio
@patch("Dashboard.firestore.client")
async def test_get_monthly_avg_different_year_bypasses_cache(mock_firestore):
    """A different year must be its own cache entry."""
    from Dashboard import DashboardData

    mock_docs = [
        MagicMock(
            to_dict=lambda: {
                "respondent_lawyer": "POOJA JOSHI",
                "board_date": "2024-01-15",
            }
        )
    ]
    stream_mock = (
        mock_firestore.return_value.collection.return_value.where.return_value.where.return_value.stream
    )
    stream_mock.return_value = mock_docs

    dashboard = DashboardData()
    await dashboard.get_monthly_avg(year="2024")
    await dashboard.get_monthly_avg(year="2025")

    assert stream_mock.call_count == 2


@pytest.mark.asyncio
@patch("Dashboard.firestore.client")
async def test_get_matters_by_date_range(mock_firestore):
    """Test matter distribution by date range"""
    from Dashboard import DashboardData

    mock_docs = [
        MagicMock(
            to_dict=lambda: {
                "board_date": "2024-10-01",
                "cases": [
                    {"agp_name": "JOSHI", "case_type": "WP"},
                    {"agp_name": "SHARMA", "case_type": "PIL"},
                ],
            }
        )
    ]
    mock_firestore.return_value.collection.return_value.where.return_value.stream.return_value = (
        mock_docs
    )

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
    agp_counts = {"POOJA JOSHI": 15, "P.M.JOSHI": 5, "POOJA M JOSHI": 3}

    canonical = max(agp_counts, key=agp_counts.get)
    assert canonical == "POOJA JOSHI"


@patch("Dashboard.firestore.client")
def test_dashboard_initialization(mock_firestore):
    """Test DashboardData initialization"""
    from Dashboard import DashboardData

    dashboard = DashboardData()
    assert dashboard.db is not None

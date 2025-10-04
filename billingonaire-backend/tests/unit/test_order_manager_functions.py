# flake8: noqa: F401, F841
"""Functional tests for OrderManager.py"""

import pytest
from unittest.mock import MagicMock, patch
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))


@patch("OrderManager.firestore.client")
def test_get_cases_without_orders(mock_firestore):
    """Test retrieving cases without linked orders"""
    from OrderManager import OrderManager

    mock_docs = [
        MagicMock(id="case1", to_dict=lambda: {"case_ref": "WP/1/2024", "order_status": "not_linked"}),
        MagicMock(id="case2", to_dict=lambda: {"case_ref": "WP/2/2024", "order_status": "not_linked"})
    ]
    mock_collection = MagicMock()
    mock_collection.stream.return_value = mock_docs
    mock_firestore.return_value.collection.return_value.where.return_value = mock_collection

    om = OrderManager()
    result = om.get_cases_without_orders()
    assert isinstance(result, list)


@patch("OrderManager.firestore.client")
def test_link_order(mock_firestore):
    """Test linking order to case"""
    from OrderManager import OrderManager

    om = OrderManager()
    result = om.link_order("case_123", "https://example.com/order.pdf")
    assert mock_firestore.return_value.collection.called


@patch("OrderManager.firestore.client")
def test_update_order_status(mock_firestore):
    """Test updating order status"""
    from OrderManager import OrderManager

    om = OrderManager()
    om.update_order_status("case_123", "order_linked")
    assert mock_firestore.return_value.collection.called


@patch("OrderManager.firestore.client")
def test_get_cases_by_status(mock_firestore):
    """Test retrieving cases by status"""
    from OrderManager import OrderManager

    mock_collection = MagicMock()
    mock_collection.stream.return_value = []
    mock_firestore.return_value.collection.return_value.where.return_value = mock_collection

    om = OrderManager()
    result = om.get_cases_by_status("order_linked")
    assert isinstance(result, list)


@patch("OrderManager.firestore.client")
def test_get_cases_by_date_range(mock_firestore):
    """Test retrieving cases by date range"""
    from OrderManager import OrderManager

    mock_collection = MagicMock()
    mock_collection.stream.return_value = []
    mock_firestore.return_value.collection.return_value.where.return_value.where.return_value = mock_collection

    om = OrderManager()
    result = om.get_cases_by_date_range("2024-10-01", "2024-10-07")
    assert isinstance(result, list)


@patch("OrderManager.firestore.client")
def test_get_all_cases(mock_firestore):
    """Test get_all_cases"""
    from OrderManager import OrderManager

    mock_collection = MagicMock()
    mock_collection.stream.return_value = []
    mock_firestore.return_value.collection.return_value = mock_collection

    om = OrderManager()
    result = om.get_all_cases()
    assert isinstance(result, list)


@patch("OrderManager.firestore.client")
def test_update_case(mock_firestore):
    """Test update_case"""
    from OrderManager import OrderManager

    om = OrderManager()
    om.update_case("case_123", {"order_status": "analysed"})
    assert mock_firestore.return_value.collection.called

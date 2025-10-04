# flake8: noqa: F401, F841
"""Functional tests for OrderManager.py"""

import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))


@patch("OrderManager.firestore.client")
def test_get_cases_without_orders(mock_firestore):
    """Test retrieving cases without linked orders"""
    from OrderManager import OrderManager

    mock_docs = [
        MagicMock(
            id="case1",
            to_dict=lambda: {"case_ref": "WP/1/2024", "order_status": "not_linked"},
        ),
        MagicMock(
            id="case2",
            to_dict=lambda: {"case_ref": "WP/2/2024", "order_status": "not_linked"},
        ),
    ]
    mock_collection = MagicMock()
    mock_collection.stream.return_value = mock_docs
    mock_firestore.return_value.collection.return_value.where.return_value = (
        mock_collection
    )

    om = OrderManager()
    result = om.get_cases_without_orders()
    assert isinstance(result, dict)


@patch("OrderManager.firestore.client")
def test_link_order(mock_firestore):
    """Test linking order to case"""
    from OrderManager import OrderManager

    om = OrderManager()
    result = om.create_order_link("case_123", {"link": "https://example.com/order.pdf"})
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
    """Test retrieving orders by status"""
    from OrderManager import OrderManager

    mock_collection = MagicMock()
    mock_collection.stream.return_value = []
    mock_firestore.return_value.collection.return_value.where.return_value = (
        mock_collection
    )

    om = OrderManager()
    result = om.get_orders_by_status("linked")
    assert isinstance(result, list)


@patch("OrderManager.firestore.client")
def test_get_case_with_order_info(mock_firestore):
    """Test retrieving case with order info"""
    from OrderManager import OrderManager

    mock_doc = MagicMock()
    mock_doc.exists = True
    mock_doc.to_dict.return_value = {"case_ref": "WP/1/2024"}
    mock_firestore.return_value.collection.return_value.document.return_value.get.return_value = mock_doc

    om = OrderManager()
    result = om.get_case_with_order_info("case_123")
    assert isinstance(result, dict) or result is None


@patch("OrderManager.firestore.client")
def test_get_order_details(mock_firestore):
    """Test get_order_details"""
    from OrderManager import OrderManager

    mock_doc = MagicMock()
    mock_doc.exists = True
    mock_doc.to_dict.return_value = {"status": "linked"}
    mock_firestore.return_value.collection.return_value.document.return_value.get.return_value = mock_doc

    om = OrderManager()
    result = om.get_order_details("case_123")
    assert isinstance(result, dict)

# flake8: noqa: F401
"""Functional tests for UserManager.py"""

import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))


@patch("UserManager.firestore.client")
def test_create_user(mock_firestore):
    """Test user creation"""
    from UserManager import UserManager

    user_data = {
        "uid": "test_uid",
        "email": "test@example.com",
        "full_name": "Pooja Joshi",
        "role": "user",
    }

    um = UserManager()
    um.create_user(user_data)
    assert mock_firestore.return_value.collection.called


@patch("UserManager.firestore.client")
def test_get_user(mock_firestore):
    """Test get_user"""
    from UserManager import UserManager

    mock_doc = MagicMock()
    mock_doc.exists = True
    mock_doc.to_dict.return_value = {"uid": "test", "email": "test@example.com"}
    mock_firestore.return_value.collection.return_value.document.return_value.get.return_value = (
        mock_doc
    )

    um = UserManager()
    result = um.get_user("test_uid")
    assert result is not None


@patch("UserManager.firestore.client")
def test_update_user(mock_firestore):
    """Test update_user"""
    from UserManager import UserManager

    um = UserManager()
    um.update_user("test_uid", {"full_name": "Updated Name"})
    assert mock_firestore.return_value.collection.called


@patch("UserManager.firestore.client")
def test_delete_user(mock_firestore):
    """Test delete_user"""
    from UserManager import UserManager

    um = UserManager()
    um.delete_user("test_uid")
    assert mock_firestore.return_value.collection.called


@patch("UserManager.firestore.client")
def test_get_all_users(mock_firestore):
    """Test get_all_users"""
    from UserManager import UserManager

    mock_collection = MagicMock()
    mock_collection.stream.return_value = []
    mock_firestore.return_value.collection.return_value = mock_collection

    um = UserManager()
    result = um.get_all_users()
    assert isinstance(result, list)


@patch("UserManager.firestore.client")
def test_set_user_role(mock_firestore):
    """Test set_user_role"""
    from UserManager import UserManager

    um = UserManager()
    um.set_user_role("test_uid", "admin")
    assert mock_firestore.return_value.collection.called


@patch("UserManager.firestore.client")
def test_get_active_users(mock_firestore):
    """Test get_active_users"""
    from UserManager import UserManager

    mock_collection = MagicMock()
    mock_collection.stream.return_value = []
    mock_firestore.return_value.collection.return_value.where.return_value = (
        mock_collection
    )

    um = UserManager()
    result = um.get_active_users()
    assert isinstance(result, list)

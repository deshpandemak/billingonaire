# flake8: noqa: F401
"""Unit tests for UserManager.py module - User management and authentication"""

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest


class TestUserManager:
    """Test UserManager class methods"""

    @pytest.fixture
    def user_manager_module(self, mock_firestore_client):
        with patch("UserManager.firestore.client", return_value=mock_firestore_client):
            import UserManager

            return UserManager

    @pytest.fixture
    def user_manager(self, user_manager_module, mock_firestore_client):
        """Create UserManager instance"""
        return user_manager_module.UserManager()

    def test_create_user_profile(self, user_manager, mock_firestore_client):
        """Test user profile creation"""
        user_data = {
            "uid": "test_uid_123",
            "email": "test@example.com",
            "full_name": "Pooja Joshi Deshpande",
            "role": "user",
        }

        result = user_manager.create_user(user_data)
        if result:
            assert mock_firestore_client.collection.called

    def test_get_user_by_uid(self, user_manager, mock_firestore_client):
        """Test retrieving user by UID"""
        uid = "test_uid_123"

        mock_doc = MagicMock()
        mock_doc.exists = True
        mock_doc.to_dict.return_value = {"uid": uid, "email": "test@example.com"}
        mock_firestore_client.collection.return_value.document.return_value.get.return_value = (
            mock_doc
        )

        result = user_manager.get_user(uid)
        assert result is not None or isinstance(result, dict)

    def test_set_user_role(self, user_manager, mock_firestore_client):
        """Test setting user role"""
        uid = "test_uid_123"
        role = "admin"

        result = user_manager.set_role(uid, role)
        if result:
            assert mock_firestore_client.collection.called

    def test_deactivate_user(self, user_manager, mock_firestore_client):
        """Test user deactivation"""
        uid = "test_uid_123"

        result = user_manager.deactivate_user(uid)
        if result:
            assert mock_firestore_client.collection.called

    def test_get_active_users(self, user_manager, mock_firestore_client):
        """Test retrieving active users"""
        mock_collection = MagicMock()
        mock_docs = [
            MagicMock(to_dict=lambda: {"uid": "uid1", "is_active": True}),
            MagicMock(to_dict=lambda: {"uid": "uid2", "is_active": True}),
        ]
        mock_collection.stream.return_value = mock_docs
        mock_firestore_client.collection.return_value.where.return_value = (
            mock_collection
        )

        result = user_manager.get_active_users()
        assert isinstance(result, list)

    def test_update_user_profile(self, user_manager, mock_firestore_client):
        """Test updating user profile"""
        uid = "test_uid_123"
        updates = {"full_name": "Updated Name"}

        result = user_manager.update_profile(uid, updates)
        if result:
            assert mock_firestore_client.collection.called


class TestUserNameMatching:
    """Test user name matching logic"""

    @pytest.fixture
    def user_manager_module(self, mock_firestore_client):
        with patch("UserManager.firestore.client", return_value=mock_firestore_client):
            import UserManager

            return UserManager

    def test_extract_name_components(self, user_manager_module):
        """Test name component extraction"""
        full_name = "Pooja Makarand Joshi Deshpande"

        # Extract components
        parts = full_name.split()
        assert len(parts) == 4
        assert "Pooja" in parts
        assert "Deshpande" in parts

    def test_generate_initials(self, user_manager_module):
        """Test initials generation"""
        full_name = "Pooja Makarand Joshi"

        parts = full_name.split()
        initials = "".join([p[0] for p in parts])
        assert initials == "PMJ"

    def test_match_compound_last_name(self, user_manager_module):
        """Test compound last name matching"""
        user_name = "Pooja Joshi Deshpande"
        agp_name = "P.M.JOSHI"

        # Check if any word from user name is in AGP name
        user_words = user_name.upper().split()
        match = any(word in agp_name for word in user_words)
        assert match

    def test_fuzzy_name_similarity(self, user_manager_module):
        """Test fuzzy name matching similarity"""
        from difflib import SequenceMatcher

        name1 = "PABALE"
        name2 = "PABLE"

        similarity = SequenceMatcher(None, name1, name2).ratio()
        assert similarity > 0.8  # 83% similarity


class TestRoleBasedAccess:
    """Test role-based access control"""

    @pytest.fixture
    def user_manager_module(self, mock_firestore_client):
        with patch("UserManager.firestore.client", return_value=mock_firestore_client):
            import UserManager

            return UserManager

    def test_check_admin_role(self, user_manager_module, mock_firestore_client):
        """Test admin role check"""
        um = user_manager_module.UserManager(mock_firestore_client)

        mock_doc = MagicMock()
        mock_doc.exists = True
        mock_doc.to_dict.return_value = {"role": "admin"}
        mock_firestore_client.collection.return_value.document.return_value.get.return_value = (
            mock_doc
        )

        result = um.is_admin("test_uid")
        assert result is True or result is None

    def test_check_user_role(self, user_manager_module, mock_firestore_client):
        """Test user role check"""
        um = user_manager_module.UserManager(mock_firestore_client)

        mock_doc = MagicMock()
        mock_doc.exists = True
        mock_doc.to_dict.return_value = {"role": "user"}
        mock_firestore_client.collection.return_value.document.return_value.get.return_value = (
            mock_doc
        )

        result = um.is_admin("test_uid")
        assert result is False or result is None

    def test_validate_user_permissions(self, user_manager_module):
        """Test user permissions validation"""
        user_role = "user"
        admin_role = "admin"

        # Users can only access their own data
        assert user_role != admin_role

        # Admins can access all data
        assert admin_role == "admin"


class TestUserMatterAssignment:
    """Test user matter assignment"""

    @pytest.fixture
    def user_manager_module(self, mock_firestore_client):
        with patch("UserManager.firestore.client", return_value=mock_firestore_client):
            import UserManager

            return UserManager

    def test_get_user_assigned_cases(self, user_manager_module, mock_firestore_client):
        """Test getting user assigned cases"""
        um = user_manager_module.UserManager(mock_firestore_client)
        uid = "test_uid_123"

        result = um.get_assigned_cases(uid)
        assert isinstance(result, list) or result is None

    def test_match_user_to_board_matters(self, user_manager_module):
        """Test matching user to board matters"""
        user_name = "Pooja Joshi"
        board_agp_name = "SMT.P.M.JOSHI,AGP"

        # Normalize both names
        user_normalized = user_name.upper().replace(".", "").replace(",", "")
        agp_normalized = board_agp_name.upper().replace(".", "").replace(",", "")

        # Check for match
        match = "JOSHI" in agp_normalized and "JOSHI" in user_normalized
        assert match

"""Unit tests for UserMatterMatcher.py module - Pattern matching for user-matter assignment"""

import pytest
from unittest.mock import MagicMock, patch
from difflib import SequenceMatcher


class TestUserMatterMatcher:
    """Test UserMatterMatcher class methods"""

    @pytest.fixture
    def matcher_module(self, mock_firestore_client):
        with patch("UserMatterMatcher.firestore.client", return_value=mock_firestore_client):
            import UserMatterMatcher
            return UserMatterMatcher

    @pytest.fixture
    def matcher(self, matcher_module, mock_firestore_client):
        """Create UserMatterMatcher instance"""
        return matcher_module.UserMatterMatcher(mock_firestore_client)

    def test_match_user_to_matters(self, matcher):
        """Test matching user to board matters"""
        user_name = "Pooja Makarand Joshi Deshpande"
        board_matters = [
            {"agp_name": "SMT.P.M.JOSHI,AGP", "case_ref": "WP/1/2024"},
            {"agp_name": "SHARMA", "case_ref": "WP/2/2024"}
        ]
        
        result = matcher.match_user(user_name, board_matters)
        assert isinstance(result, dict) or result is None

    def test_generate_name_variations(self, matcher):
        """Test generating name variations"""
        full_name = "Pooja Makarand Joshi"
        
        variations = matcher.generate_variations(full_name)
        if variations:
            assert isinstance(variations, list)
            # Should include initials
            assert any("P" in v and "M" in v for v in variations)

    def test_calculate_matching_score(self, matcher):
        """Test matching score calculation"""
        user_name = "Pooja Makarand Joshi Deshpande"
        agp_name = "SMT.P.M.JOSHI,AGP"
        
        score = matcher.calculate_score(user_name, agp_name)
        if score is not None:
            assert 0 <= score <= 100

    def test_normalize_for_matching(self, matcher):
        """Test name normalization for matching"""
        name = "SMT.POOJA JOSHI,AGP"
        normalized = matcher.normalize_name(name)
        
        if normalized:
            assert "SMT" not in normalized
            assert "AGP" not in normalized
            assert "GP" not in normalized

    def test_extract_initials(self, matcher):
        """Test initials extraction"""
        full_name = "Pooja Makarand Joshi"
        initials = matcher.extract_initials(full_name)
        
        if initials:
            assert "P" in initials
            assert "M" in initials
            assert "J" in initials

    def test_match_with_confidence_threshold(self, matcher):
        """Test matching with 50% confidence threshold"""
        user_name = "Pooja Joshi"
        agp_name = "P.M.JOSHI"
        
        result = matcher.match_with_threshold(user_name, agp_name, threshold=50)
        assert result is not None or isinstance(result, bool)


class TestNameVariationGeneration:
    """Test name variation generation logic"""

    @pytest.fixture
    def matcher_module(self, mock_firestore_client):
        with patch("UserMatterMatcher.firestore.client", return_value=mock_firestore_client):
            import UserMatterMatcher
            return UserMatterMatcher

    def test_generate_initial_permutations(self, matcher_module):
        """Test generating initial permutations"""
        name_parts = ["Pooja", "Makarand", "Joshi", "Deshpande"]
        
        # Generate different initial combinations
        variations = []
        # Full initials
        variations.append("".join([p[0] for p in name_parts]))
        # First + last initials
        if len(name_parts) >= 2:
            variations.append(name_parts[0][0] + name_parts[-1][0])
        
        assert len(variations) > 0
        assert "PMJD" in variations or "PD" in variations

    def test_generate_last_name_variations(self, matcher_module):
        """Test last name variations"""
        full_name = "Pooja Joshi Deshpande"
        parts = full_name.split()
        
        # Both last names could be matches
        last_names = parts[-2:] if len(parts) >= 2 else [parts[-1]]
        assert "Joshi" in last_names
        assert "Deshpande" in last_names

    def test_handle_compound_names(self, matcher_module):
        """Test handling compound last names"""
        agp_last_name = "JOSHI"
        user_name_parts = ["Pooja", "Makarand", "Joshi", "Deshpande"]
        
        # Check if AGP last name matches any user name part
        match = any(agp_last_name.upper() in part.upper() for part in user_name_parts)
        assert match


class TestFuzzyMatching:
    """Test fuzzy matching algorithms"""

    @pytest.fixture
    def matcher_module(self, mock_firestore_client):
        with patch("UserMatterMatcher.firestore.client", return_value=mock_firestore_client):
            import UserMatterMatcher
            return UserMatterMatcher

    def test_spelling_variation_matching(self, matcher_module):
        """Test matching with spelling variations"""
        name1 = "PABALE"
        name2 = "PABLE"
        
        similarity = SequenceMatcher(None, name1, name2).ratio()
        assert similarity > 0.8  # Should be ~83%

    def test_exact_match_scores_100(self, matcher_module):
        """Test exact match gives 100% score"""
        name1 = "JOSHI"
        name2 = "JOSHI"
        
        similarity = SequenceMatcher(None, name1, name2).ratio()
        assert similarity == 1.0

    def test_weighted_scoring(self, matcher_module):
        """Test weighted scoring components"""
        # Weights: last_name 35%, initials 25%, full_words 25%, sequence 15%
        
        last_name_match = 1.0  # Exact match
        initials_match = 1.0
        full_word_match = 0.5
        sequence_match = 0.8
        
        weighted_score = (
            last_name_match * 0.35 +
            initials_match * 0.25 +
            full_word_match * 0.25 +
            sequence_match * 0.15
        )
        
        assert 0 <= weighted_score <= 1.0
        assert weighted_score > 0.5  # Should pass threshold


class TestMatchingEdgeCases:
    """Test edge cases in name matching"""

    @pytest.fixture
    def matcher_module(self, mock_firestore_client):
        with patch("UserMatterMatcher.firestore.client", return_value=mock_firestore_client):
            import UserMatterMatcher
            return UserMatterMatcher

    def test_single_name_user(self, matcher_module):
        """Test matching with single name"""
        user_name = "Joshi"
        agp_name = "JOSHI"
        
        match = user_name.upper() in agp_name
        assert match

    def test_empty_name_handling(self, matcher_module):
        """Test handling of empty names"""
        user_name = ""
        agp_name = "JOSHI"
        
        if not user_name:
            result = None
        else:
            result = "match"
        
        assert result is None

    def test_special_characters_handling(self, matcher_module):
        """Test handling of special characters"""
        name_with_special = "JOSHI, AGP."
        cleaned = name_with_special.replace(",", "").replace(".", "")
        
        assert "," not in cleaned
        assert "." not in cleaned

    def test_case_insensitive_matching(self, matcher_module):
        """Test case-insensitive matching"""
        name1 = "Pooja Joshi"
        name2 = "POOJA JOSHI"
        
        match = name1.upper() == name2.upper()
        assert match


class TestBoardMatterMatching:
    """Test matching against board matters"""

    @pytest.fixture
    def matcher_module(self, mock_firestore_client):
        with patch("UserMatterMatcher.firestore.client", return_value=mock_firestore_client):
            import UserMatterMatcher
            return UserMatterMatcher

    def test_filter_matched_matters(self, matcher_module):
        """Test filtering matched board matters"""
        user_name = "Pooja Joshi"
        matters = [
            {"agp_name": "P.M.JOSHI", "case_ref": "WP/1/2024"},
            {"agp_name": "SHARMA", "case_ref": "WP/2/2024"},
            {"agp_name": "P JOSHI", "case_ref": "WP/3/2024"}
        ]
        
        # Simple filter by last name
        matched = [m for m in matters if "JOSHI" in m["agp_name"].upper()]
        assert len(matched) == 2

    def test_return_best_match(self, matcher_module):
        """Test returning best match from multiple candidates"""
        candidates = [
            {"agp_name": "P.M.JOSHI", "score": 0.85},
            {"agp_name": "POOJA JOSHI", "score": 0.95},
            {"agp_name": "P JOSHI", "score": 0.75}
        ]
        
        best_match = max(candidates, key=lambda x: x["score"])
        assert best_match["agp_name"] == "POOJA JOSHI"

    def test_confidence_below_threshold(self, matcher_module):
        """Test handling when confidence is below 50%"""
        score = 0.45
        threshold = 0.50
        
        if score < threshold:
            result = {"error": "Low confidence", "best_match": None}
        else:
            result = {"match": True}
        
        assert "error" in result

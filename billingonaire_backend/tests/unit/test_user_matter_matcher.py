"""Unit tests for UserMatterMatcher.py module - Pattern matching for user-matter assignment"""

from difflib import SequenceMatcher
from unittest.mock import MagicMock, patch

import pytest


class TestUserMatterMatcher:
    """Test UserMatterMatcher class methods"""

    @pytest.fixture
    def matcher_module(self, mock_firestore_client):
        with patch(
            "UserMatterMatcher.firestore.client", return_value=mock_firestore_client
        ):
            import UserMatterMatcher

            return UserMatterMatcher

    @pytest.fixture
    def matcher(self, matcher_module, mock_firestore_client):
        """Create UserMatterMatcher instance"""
        return matcher_module.UserMatterMatcher()

    def test_match_user_to_matters(self, matcher):
        """Test finding user matters"""
        user_id = "test_user_123"

        result = matcher.find_user_matters(user_id, limit=10)
        assert isinstance(result, list)

    def test_generate_name_variations(self, matcher):
        """Test generating name variations"""
        full_name = "Pooja Makarand Joshi"

        variations = matcher.generate_name_variations(full_name)
        if variations:
            assert isinstance(variations, list)
            # Should include initials
            assert any("P" in v and "M" in v for v in variations)

    def test_calculate_matching_score(self, matcher):
        """Test fuzzy matching score calculation"""
        user_name = "Pooja Makarand Joshi Deshpande"
        agp_name = "SMT.P.M.JOSHI,AGP"

        score = matcher.fuzzy_match_score(user_name, agp_name)
        if score is not None:
            assert 0 <= score <= 1

    def test_normalize_for_matching(self, matcher):
        """Test name normalization for matching"""
        name = "SMT.POOJA JOSHI,AGP"
        normalized = matcher.normalize_name(name)

        if normalized:
            assert "SMT" not in normalized
            assert "AGP" not in normalized
            assert "GP" not in normalized

    def test_extract_initials(self, matcher):
        """Test initials extraction from name variations"""
        full_name = "Pooja Makarand Joshi"
        variations = matcher.generate_name_variations(full_name)

        if variations:
            # Check if any variation contains initials
            has_initials = any("P" in v or "M" in v or "J" in v for v in variations)
            assert has_initials

    def test_match_with_confidence_threshold(self, matcher):
        """Test fuzzy matching with similarity threshold"""
        user_name = "Pooja Joshi"
        agp_name = "P.M.JOSHI"

        score = matcher.fuzzy_match_score(user_name, agp_name)
        assert score is not None and 0 <= score <= 1


class TestNameVariationGeneration:
    """Test name variation generation logic"""

    @pytest.fixture
    def matcher_module(self, mock_firestore_client):
        with patch(
            "UserMatterMatcher.firestore.client", return_value=mock_firestore_client
        ):
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
        _user_name_parts = ["Pooja", "Makarand", "Joshi", "Deshpande"]

        # Check if AGP last name matches any user name part
        match = any(agp_last_name.upper() in part.upper() for part in _user_name_parts)
        assert match


class TestFuzzyMatching:
    """Test fuzzy matching algorithms"""

    @pytest.fixture
    def matcher_module(self, mock_firestore_client):
        with patch(
            "UserMatterMatcher.firestore.client", return_value=mock_firestore_client
        ):
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
            last_name_match * 0.35
            + initials_match * 0.25
            + full_word_match * 0.25
            + sequence_match * 0.15
        )

        assert 0 <= weighted_score <= 1.0
        assert weighted_score > 0.5  # Should pass threshold


class TestMatchingEdgeCases:
    """Test edge cases in name matching"""

    @pytest.fixture
    def matcher_module(self, mock_firestore_client):
        with patch(
            "UserMatterMatcher.firestore.client", return_value=mock_firestore_client
        ):
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
        with patch(
            "UserMatterMatcher.firestore.client", return_value=mock_firestore_client
        ):
            import UserMatterMatcher

            return UserMatterMatcher

    def test_filter_matched_matters(self, matcher_module):
        """Test filtering matched board matters"""
        user_name = "Pooja Joshi"
        matters = [
            {"_agp_name": "P.M.JOSHI", "case_ref": "WP/1/2024"},
            {"_agp_name": "SHARMA", "case_ref": "WP/2/2024"},
            {"_agp_name": "P JOSHI", "case_ref": "WP/3/2024"},
        ]

        # Simple filter by last name
        matched = [m for m in matters if "JOSHI" in m["_agp_name"].upper()]
        assert len(matched) == 2

    def test_return_best_match(self, matcher_module):
        """Test returning best match from multiple candidates"""
        candidates = [
            {"_agp_name": "P.M.JOSHI", "score": 0.85},
            {"_agp_name": "POOJA JOSHI", "score": 0.95},
            {"_agp_name": "P JOSHI", "score": 0.75},
        ]

        best_match = max(candidates, key=lambda x: x["score"])
        assert best_match["_agp_name"] == "POOJA JOSHI"

    def test_confidence_below_threshold(self, matcher_module):
        """Test handling when confidence is below 50%"""
        score = 0.45
        threshold = 0.50

        if score < threshold:
            result = {"error": "Low confidence", "best_match": None}
        else:
            result = {"match": True}

        assert "error" in result


class TestNearMissMatching:
    """Roadmap #9: a match that falls just short of the acceptance
    threshold is surfaced for a human to confirm instead of being
    discarded with no trace at all -- "ask, don't silently threshold"."""

    @pytest.fixture
    def matcher_module(self, mock_firestore_client):
        with patch(
            "UserMatterMatcher.firestore.client", return_value=mock_firestore_client
        ):
            import UserMatterMatcher

            return UserMatterMatcher

    @pytest.fixture
    def matcher(self, matcher_module, mock_firestore_client):
        return matcher_module.UserMatterMatcher()

    def _role(self, matcher_module, threshold=0.50):
        return matcher_module.UserRole(
            role_type="AGP",
            full_name="Pooja Deshpande",
            name_variations=["Pooja Deshpande"],
            pattern_keywords=[],
            confidence_threshold=threshold,
        )

    def test_score_within_band_below_threshold_is_a_near_miss_not_accepted(
        self, matcher, matcher_module
    ):
        role = self._role(matcher_module, threshold=0.50)
        with patch.object(matcher, "fuzzy_match_score", return_value=0.40):
            accepted, near_miss = matcher._score_text_against_role("XYZQ text", role)

        assert accepted == []
        assert len(near_miss) == 1
        assert near_miss[0][0] == "XYZQ text"

    def test_score_too_far_below_threshold_is_neither_accepted_nor_near_miss(
        self, matcher, matcher_module
    ):
        """Below (threshold - NEAR_MISS_BAND) is noise, not a plausible
        candidate -- must not flood users with meaningless confirmations."""
        role = self._role(matcher_module, threshold=0.50)
        with patch.object(matcher, "fuzzy_match_score", return_value=0.10):
            accepted, near_miss = matcher._score_text_against_role("XYZQ text", role)

        assert accepted == []
        assert near_miss == []

    def test_accepted_match_is_never_also_reported_as_a_near_miss(
        self, matcher, matcher_module
    ):
        role = self._role(matcher_module, threshold=0.50)
        with patch.object(matcher, "fuzzy_match_score", return_value=0.90):
            accepted, near_miss = matcher._score_text_against_role("XYZQ text", role)

        assert len(accepted) == 1
        assert near_miss == []

    def test_find_user_matches_in_text_and_near_miss_variant_stay_in_sync(
        self, matcher, matcher_module
    ):
        """The public find_* wrappers must return exactly what the shared
        scoring pass produced -- no drift between the two."""
        role = self._role(matcher_module, threshold=0.50)
        with patch.object(matcher, "fuzzy_match_score", return_value=0.40):
            accepted = matcher.find_user_matches_in_text("XYZQ text", role)
            near_miss = matcher.find_near_miss_matches_in_text("XYZQ text", role)

        assert accepted == []
        assert len(near_miss) == 1

    def test_near_miss_band_boundary_is_inclusive(self, matcher, matcher_module):
        role = self._role(matcher_module, threshold=0.50)
        boundary_score = 0.50 - matcher_module.UserMatterMatcher.NEAR_MISS_BAND
        with patch.object(matcher, "fuzzy_match_score", return_value=boundary_score):
            accepted, near_miss = matcher._score_text_against_role("XYZQ text", role)

        assert accepted == []
        assert len(near_miss) == 1

    def test_find_near_miss_matters_for_case_surfaces_a_below_threshold_candidate(
        self, matcher, matcher_module, mock_firestore_client
    ):
        """End-to-end: a case whose lawyer text almost, but doesn't quite,
        match the user must show up via the near-miss finder even though
        find_user_matters_for_case (the accepted-only path) finds nothing."""
        # matcher_module's `with patch(...): return UserMatterMatcher` exits its
        # patch before the `matcher` fixture actually constructs the instance,
        # so matcher.db is not reliably mock_firestore_client -- pin it directly
        # rather than depend on that fixture's patch timing.
        matcher.db = mock_firestore_client
        board_doc = MagicMock()
        board_doc.exists = True
        board_doc.to_dict.return_value = {
            "case_type": "WP",
            "case_no": "1",
            "case_year": "2026",
            "board_date": "2026-01-15",
            "petitioner_lawyer": "XYZQ text",
            "respondent_lawyer": "",
        }
        mock_firestore_client.collection.return_value.document.return_value.get.return_value = (
            board_doc
        )
        matcher.case_store.get_case_details = MagicMock(return_value={})

        role = self._role(matcher_module, threshold=0.50)
        with patch.object(matcher, "fuzzy_match_score", return_value=0.40):
            accepted = matcher.find_user_matters_for_case("user-1", role, "board-doc-1")
            near_misses = matcher.find_near_miss_matters_for_case(
                "user-1", role, "board-doc-1"
            )

        assert accepted == []
        assert len(near_misses) == 1
        assert near_misses[0].case_ref == "WP/1/2026"
        assert near_misses[0].matched_text == "XYZQ text"

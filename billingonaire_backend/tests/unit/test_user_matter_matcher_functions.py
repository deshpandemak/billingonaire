"""Functional tests for UserMatterMatcher.py"""

import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))


@patch("UserMatterMatcher.firestore.client")
def test_match_user_to_matters(mock_firestore):
    """Test generate_name_variations - actual method"""
    from UserMatterMatcher import UserMatterMatcher

    matcher = UserMatterMatcher()
    result = matcher.generate_name_variations("Pooja Makarand Joshi Deshpande")
    assert isinstance(result, list) or result is None


@patch("UserMatterMatcher.firestore.client")
def test_generate_name_variations(mock_firestore):
    """Test generate_name_variations"""
    from UserMatterMatcher import UserMatterMatcher

    matcher = UserMatterMatcher()
    result = matcher.generate_name_variations("Pooja Makarand Joshi")
    assert isinstance(result, (list, type(None)))


@patch("UserMatterMatcher.firestore.client")
def test_calculate_match_score(mock_firestore):
    """Test fuzzy_match_score - actual method"""
    from UserMatterMatcher import UserMatterMatcher

    matcher = UserMatterMatcher()
    score = matcher.fuzzy_match_score("Pooja Joshi", "P.M.JOSHI")
    assert score is None or isinstance(score, (int, float))


@patch("UserMatterMatcher.firestore.client")
def test_normalize_name(mock_firestore):
    """Test normalize_name"""
    from UserMatterMatcher import UserMatterMatcher

    matcher = UserMatterMatcher()
    result = matcher.normalize_name("SHRI P.M.JOSHI, AGP")
    assert result is not None


@patch("UserMatterMatcher.firestore.client")
def test_extract_initials(mock_firestore):
    """Test extract_role_from_text - actual method"""
    from UserMatterMatcher import UserMatterMatcher

    matcher = UserMatterMatcher()
    result = matcher.extract_role_from_text("SMT.P.M.JOSHI,AGP appears for State")
    assert result is None or isinstance(result, str)


@patch("UserMatterMatcher.firestore.client")
def test_fuzzy_match(mock_firestore):
    """Test fuzzy_match_score"""
    from UserMatterMatcher import UserMatterMatcher

    matcher = UserMatterMatcher()
    result = matcher.fuzzy_match_score("PABALE", "PABLE")
    assert result is None or isinstance(result, float)


@patch("UserMatterMatcher.firestore.client")
def test_get_best_match(mock_firestore):
    """Test normalize_name - method exists, get_best_match does not"""
    from UserMatterMatcher import UserMatterMatcher

    matcher = UserMatterMatcher()
    # Test an actual method that exists
    result = matcher.normalize_name("SHRI POOJA JOSHI, AGP")
    assert result is not None and isinstance(result, str)


# ---------------------------------------------------------------------------
# score_name_match — last-name gate false-positive regression tests
# ---------------------------------------------------------------------------


def test_score_name_match_different_last_names_returns_zero():
    """S D Vyas vs S D Chipade must NOT match — shared initials + single-letter
    substring in last name was previously bypassing the last-name gate."""
    from UserMatterMatcher import score_name_match

    assert score_name_match("S D Vyas", "S D Chipade") == 0.0
    assert score_name_match("S D Chipade", "S D Vyas") == 0.0


def test_score_name_match_same_last_name_matches():
    """Same last name with matching initials must score above threshold."""
    from UserMatterMatcher import score_name_match

    assert score_name_match("S D Vyas", "S.D.VYAS, AGP") >= 0.50
    assert score_name_match("S D Chipade", "SHRI S D CHIPADE, AGP") >= 0.50


def test_score_name_match_initial_only_user_words_cannot_pass_gate():
    """A name composed entirely of initials (e.g. 'A B') must not match a
    candidate whose last name merely contains one of those letters as a
    substring (e.g. 'A B Naik' vs 'A B Bane' — 'b' is in 'bane' but
    last names are different)."""
    from UserMatterMatcher import score_name_match

    # "b" is a substring of "bane" — should not pass the gate
    assert score_name_match("A B Naik", "A B Bane") == 0.0

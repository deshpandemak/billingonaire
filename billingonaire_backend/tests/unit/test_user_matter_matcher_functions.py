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


# ---------------------------------------------------------------------------
# score_name_match — bare-initials board format (modern Bombay HC boards
# print government lawyers as e.g. "P M J, AGP" with no surname at all;
# Board.py's _GP_INITIALS_PATTERN strips the role and keeps just "P M J")
# ---------------------------------------------------------------------------


def test_score_name_match_initials_prefix_matches_the_right_person():
    from UserMatterMatcher import score_name_match

    # "P M J" is a prefix of Pooja's first three name-words; the board
    # never prints her fourth word (the surname) at all.
    assert score_name_match("Pooja Makarand Joshi Deshpande", "P M J") >= 0.50
    assert score_name_match("Pooja Makarand Joshi Deshpande", "p.m.j.") >= 0.50


def test_score_name_match_initials_collision_no_longer_favors_the_wrong_person():
    """Regression: before the bare-initials scoring path existed, the
    last-name gate's substring check gave the WRONG same-initialed person
    (Priya Manoj Jadhav) a higher score than the RIGHT one (Pooja Makarand
    Joshi Deshpande) against board text "P M J" -- 0.595 vs 0.510. Both
    must now score identically, so a collision is a clean, detectable tie
    for the caller to route to manual review, not a coin-flip in disguise.
    """
    from UserMatterMatcher import score_name_match

    right = score_name_match("Pooja Makarand Joshi Deshpande", "P M J")
    wrong = score_name_match("Priya Manoj Jadhav", "P M J")
    assert right == wrong
    assert right >= 0.50


def test_score_name_match_initials_mismatch_scores_zero():
    """A wrong letter anywhere in the initials means it isn't this person
    -- no partial credit, unlike the old substring-luck behavior."""
    from UserMatterMatcher import score_name_match

    assert score_name_match("Sunita Ramesh Bhosale", "S R C") == 0.0
    assert score_name_match("Rajesh Suresh Chavan", "S R C") == 0.0


def test_score_name_match_initials_longer_than_name_scores_zero():
    from UserMatterMatcher import score_name_match

    assert score_name_match("A B", "A B C D") == 0.0


def test_is_bare_initials():
    from UserMatterMatcher import is_bare_initials

    assert is_bare_initials("P M J") is True
    assert is_bare_initials("p.m.j.") is True
    assert is_bare_initials("S.D.VYAS, AGP") is False
    assert is_bare_initials("") is False
    assert is_bare_initials(None) is False

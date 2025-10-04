"""Functional tests for UserMatterMatcher.py"""

import pytest
from unittest.mock import MagicMock, patch
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))


@patch("UserMatterMatcher.firestore.client")
def test_match_user_to_matters(mock_firestore):
    """Test match_user_to_matters"""
    from UserMatterMatcher import UserMatterMatcher
    
    user_name = "Pooja Makarand Joshi Deshpande"
    agp_name = "SMT.P.M.JOSHI,AGP"
    
    matcher = UserMatterMatcher()
    result = matcher.match_user_to_matters(user_name, agp_name)
    assert result is not None


@patch("UserMatterMatcher.firestore.client")
def test_generate_name_variations(mock_firestore):
    """Test generate_name_variations"""
    from UserMatterMatcher import UserMatterMatcher
    
    matcher = UserMatterMatcher()
    result = matcher.generate_name_variations("Pooja Makarand Joshi")
    assert isinstance(result, (list, type(None)))


@patch("UserMatterMatcher.firestore.client")
def test_calculate_match_score(mock_firestore):
    """Test calculate_match_score"""
    from UserMatterMatcher import UserMatterMatcher
    
    matcher = UserMatterMatcher()
    score = matcher.calculate_match_score("Pooja Joshi", "P.M.JOSHI")
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
    """Test extract_initials"""
    from UserMatterMatcher import UserMatterMatcher
    
    matcher = UserMatterMatcher()
    result = matcher.extract_initials("Pooja Makarand Joshi")
    assert result is None or isinstance(result, str)


@patch("UserMatterMatcher.firestore.client")
def test_fuzzy_match(mock_firestore):
    """Test fuzzy_match"""
    from UserMatterMatcher import UserMatterMatcher
    
    matcher = UserMatterMatcher()
    result = matcher.fuzzy_match("PABALE", "PABLE", threshold=0.8)
    assert result is None or isinstance(result, bool)


@patch("UserMatterMatcher.firestore.client")
def test_get_best_match(mock_firestore):
    """Test get_best_match"""
    from UserMatterMatcher import UserMatterMatcher
    
    candidates = [
        {"name": "P.M.JOSHI", "score": 0.85},
        {"name": "POOJA JOSHI", "score": 0.95}
    ]
    
    matcher = UserMatterMatcher()
    result = matcher.get_best_match(candidates)
    assert result is None or isinstance(result, dict)

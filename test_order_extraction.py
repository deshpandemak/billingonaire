"""
Test script to analyze order extraction accuracy for petitioners and government pleaders
"""
import sys
import os
import re
sys.path.append('/workspaces/billingonaire/billingonaire_backend')

# Mock Firebase to avoid initialization issues
import firebase_admin
from unittest.mock import MagicMock, patch

# Mock Firebase before importing OrderDocumentAnalyzer
firebase_admin.firestore = MagicMock()
firebase_admin.initialize_app = MagicMock()

from order_analyzer import OrderDocumentAnalyzer
import logging

# Set up logging
logging.basicConfig(level=logging.INFO)

def test_order_extraction():
    """Test the current order extraction with sample data"""

    # Sample court order text with petitioner and government pleader
    sample_order_text = """
    WRIT PETITION NO.11347 OF 2024

    Shri Rajesh Kumar Sharma ... Petitioner

    Versus

    The State Of Maharashtra Through Its Secretary ... Respondent

    Mr. P. P. Kakade, Addl. GP a/w Ms. M. J. Deshpande, AGP for Respondent State

    DATE: 15th July, 2024

    CORAM: HON'BLE SHRI JUSTICE A. B. CDE

    Heard the learned counsel for the petitioner and the learned AGP for the respondent State.

    Matter stands over to 22nd July, 2024.
    """

    analyzer = OrderDocumentAnalyzer()

    # Test the extraction methods directly
    print("=== TESTING PETITIONER EXTRACTION ===")

    # Test petitioner extraction
    petitioners = analyzer._extract_petitioners(sample_order_text)
    print(f"Extracted Petitioners: {petitioners}")

    # Test respondent extraction
    respondents = analyzer._extract_respondents(sample_order_text)
    print(f"Extracted Respondents: {respondents}")

    # Test AGP extraction
    agp_names = analyzer._extract_agp_names(sample_order_text, [])
    print(f"Extracted AGP Names: {agp_names}")

    print("\n=== TESTING MULTI-CASE DETAILS EXTRACTION ===")

    # Test multi-case extraction
    case_details = analyzer._extract_multi_case_details(sample_order_text)
    print(f"Case Details: {case_details}")

    print("\n=== TESTING GOVERNMENT PLEADER EXTRACTION ===")

    # Test government pleader extraction
    for case_key in case_details.keys():
        pleaders = analyzer._extract_govt_pleader_from_text(sample_order_text, case_key)
        print(f"Government Pleaders for {case_key}: {pleaders}")

if __name__ == "__main__":
    test_order_extraction()
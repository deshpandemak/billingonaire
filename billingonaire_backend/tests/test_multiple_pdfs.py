#!/usr/bin/env python3
"""
Test multiple PDFs to find cases where deduplication matters
"""

import logging
import os
import sys
from io import BytesIO

import pandas as pd

# Add the backend directory to Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "billingonaire_backend"))

# Configure logging
logging.basicConfig(level=logging.WARNING)  # Reduce noise


def test_pdf_file(pdf_path, pdf_name):
    """Test a single PDF file and return parsing results"""
    try:
        from unittest.mock import MagicMock

        from Board import Board

        # Create mock Board instance
        board = Board.__new__(Board)
        board.db = MagicMock()
        board.ml_parser = None

        # Read and parse the PDF
        with open(pdf_path, "rb") as file:
            file_stream = BytesIO(file.read())
            df = board.readFile(pdf_name, file_stream)

            if df is not None and not df.empty:
                # Test old vs new deduplication
                old_subset = [
                    "file_name",
                    "case_type",
                    "case_no",
                    "case_year",
                    "serial_number",
                ]
                df_old_logic = df.drop_duplicates(subset=old_subset)

                # Check serial number characteristics
                empty_serials = 0
                unique_serials = 0
                if "serial_number" in df.columns:
                    empty_serials = (
                        df["serial_number"].isna().sum()
                        + (df["serial_number"] == "").sum()
                    )
                    unique_serials = df["serial_number"].nunique()

                return {
                    "name": pdf_name,
                    "total_records": len(df),
                    "old_logic_records": len(df_old_logic),
                    "empty_serials": empty_serials,
                    "unique_serials": unique_serials,
                    "would_lose_records": len(df) - len(df_old_logic) > 0,
                }
            else:
                return {
                    "name": pdf_name,
                    "total_records": 0,
                    "old_logic_records": 0,
                    "empty_serials": 0,
                    "unique_serials": 0,
                    "would_lose_records": False,
                    "error": "No records extracted",
                }

    except Exception as e:
        return {
            "name": pdf_name,
            "error": str(e),
            "total_records": 0,
            "old_logic_records": 0,
            "empty_serials": 0,
            "unique_serials": 0,
            "would_lose_records": False,
        }


def main():
    """Test multiple PDF files to find the deduplication issue"""

    # List of PDFs to test
    test_pdfs = [
        "9r6f2-p2e8f.pdf",
        "BOARD DT 10.04.2024_1758477237678.pdf",
        "BOARD DT 05.04.2024_1758477237678.pdf",
        "BOARD DT 02.04.2024_1758477237678.pdf",
        "SUPPLY BOARD 21.03.2024_1758478866002.pdf",
        "hni7p-hp1dg.pdf",
    ]

    print("🔍 Testing multiple PDFs for deduplication behavior")
    print("=" * 80)

    results = []
    for pdf_name in test_pdfs:
        pdf_path = f"/workspaces/billingonaire/attached_assets/{pdf_name}"
        if os.path.exists(pdf_path):
            print(f"Testing: {pdf_name}")
            result = test_pdf_file(pdf_path, pdf_name)
            results.append(result)
        else:
            print(f"❌ File not found: {pdf_name}")

    print("\n📊 Results Summary:")
    print("-" * 80)
    print(
        f"{'PDF Name':<40} {'Records':<8} {'Old Logic':<10} {'Empty S#':<8} {'Lost?':<6}"
    )
    print("-" * 80)

    for result in results:
        if "error" not in result:
            lost_indicator = "⚠️ YES" if result["would_lose_records"] else "✅ NO"
            print(
                f"{result['name'][:39]:<40} {result['total_records']:<8} {result['old_logic_records']:<10} {result['empty_serials']:<8} {lost_indicator:<6}"
            )
        else:
            print(
                f"{result['name'][:39]:<40} {'ERROR':<8} {result.get('error', '')[:20]:<10}"
            )

    # Find problematic cases
    problem_cases = [r for r in results if r.get("would_lose_records", False)]
    if problem_cases:
        print(
            f"\n🎯 Found {len(problem_cases)} PDFs where old logic would lose records:"
        )
        for case in problem_cases:
            print(
                f"  - {case['name']}: {case['total_records']} → {case['old_logic_records']} records"
            )
    else:
        print(f"\n✅ All tested PDFs work correctly with both old and new logic")
        print("   The fix prevents potential future issues with different PDF formats")


if __name__ == "__main__":
    main()

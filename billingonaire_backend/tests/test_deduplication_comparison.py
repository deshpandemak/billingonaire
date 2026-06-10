#!/usr/bin/env python3
"""
Test script to demonstrate the before/after behavior of the PDF parsing fix
"""

import logging
import os
import sys
from io import BytesIO

import pandas as pd

# Add the backend directory to Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "billingonaire_backend"))

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)


def test_old_vs_new_deduplication():
    """Test the difference between old and new deduplication logic"""
    try:
        from unittest.mock import MagicMock

        from Board import Board

        # Create mock Board instance
        board = Board.__new__(Board)
        board.db = MagicMock()
        board.ml_parser = None

        # Read the PDF file
        pdf_path = "/workspaces/billingonaire/attached_assets/9r6f2-p2e8f.pd"
        with open(pdf_path, "rb") as file:
            file_stream = BytesIO(file.read())

            # Parse the PDF to get the raw matter_list before deduplication
            df = board.readFile("9r6f2-p2e8f.pd", file_stream)

            print("🔍 Analysis of deduplication behavior:")
            print("=" * 60)
            print(f"Current result: {len(df)} records")

            # Simulate old deduplication logic (always include serial_number)
            old_subset = [
                "file_name",
                "case_type",
                "case_no",
                "case_year",
                "serial_number",
            ]
            df_old_logic = df.drop_duplicates(subset=old_subset)

            print(f"Old logic would have: {len(df_old_logic)} records")

            # Show serial number distribution
            if "serial_number" in df.columns:
                print("\nSerial number analysis:")
                print(f"  Unique serial numbers: {df['serial_number'].nunique()}")
                print(f"  Total records: {len(df)}")
                print(
                    f"  Serial number values: {sorted(df['serial_number'].dropna().astype(str).tolist())}"
                )

                # Check if any serial numbers are duplicated
                duplicated_serials = df["serial_number"].duplicated()
                if duplicated_serials.any():
                    print(
                        f"  Duplicated serial numbers found: {duplicated_serials.sum()} cases"
                    )
                else:
                    print("  No duplicated serial numbers - all unique")

            # Show why the old logic would fail differently
            print("\nDeduplication test:")
            print(f"  New logic (dynamic subset): {len(df)} records preserved")
            print(f"  Old logic (fixed subset): {len(df_old_logic)} records preserved")

            if len(df) != len(df_old_logic):
                print(
                    f"  ❌ Old logic would lose {len(df) - len(df_old_logic)} records"
                )
            else:
                print("  ✅ Both methods give same result for this PDF")

            return df

    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback

        traceback.print_exc()
        return None


if __name__ == "__main__":
    test_old_vs_new_deduplication()

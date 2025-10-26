#!/usr/bin/env python3
"""
Test script to parse the specific PDF file mentioned in the issue
and verify the fix for single record extraction
"""

import logging
import os
import sys
from io import BytesIO

# Add the backend directory to Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "billingonaire_backend"))

# Configure logging to see detailed parsing info
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)


def test_pdf_parsing():
    """Test the PDF parsing with the specific file mentioned in the issue"""
    try:
        # Import Board class (this will import from the backend directory)
        from Board import Board

        # Path to the PDF file
        pdf_path = "/workspaces/billingonaire/attached_assets/9r6f2-p2e8f.pdf"

        if not os.path.exists(pdf_path):
            print(f"❌ PDF file not found: {pdf_path}")
            return

        print(f"📄 Testing PDF parsing for: {pdf_path}")
        print("=" * 60)

        # Read the PDF file
        with open(pdf_path, "rb") as file:
            file_content = file.read()
            print(f"📊 File size: {len(file_content)} bytes")

            # Create a BytesIO object for the Board.readFile method
            file_stream = BytesIO(file_content)

            # Create Board instance (will use mock Firestore for testing)
            try:
                board = Board()
                print("✅ Board instance created successfully")
            except Exception as e:
                print(
                    f"⚠️  Board initialization failed (expected in test environment): {e}"
                )
                # Create a minimal Board instance for testing
                from unittest.mock import MagicMock

                board = Board.__new__(Board)
                board.db = MagicMock()
                board.ml_parser = None
                print("✅ Mock Board instance created for testing")

            # Parse the PDF
            print("\n🔍 Starting PDF parsing...")
            try:
                df = board.readFile("9r6f2-p2e8f.pdf", file_stream)

                if df is not None and not df.empty:
                    record_count = len(df)
                    print(f"✅ PDF parsed successfully!")
                    print(f"📊 Records extracted: {record_count}")

                    # Show sample records
                    print("\n📋 Sample records:")
                    print("-" * 60)
                    for i, record in df.head(5).iterrows():
                        print(f"Record {i+1}:")
                        print(
                            f"  Case: {record.get('case_type', 'N/A')}/{record.get('case_no', 'N/A')}/{record.get('case_year', 'N/A')}"
                        )
                        print(f"  Serial: {record.get('serial_number', 'N/A')}")
                        print(
                            f"  Petitioner: {record.get('petitioner_lawyer', 'N/A')[:50]}..."
                        )
                        print(
                            f"  Respondent: {record.get('respondent_lawyer', 'N/A')[:50]}..."
                        )
                        print()

                    if record_count > 5:
                        print(f"... and {record_count - 5} more records")

                    # Show column info
                    print(f"\n📊 DataFrame info:")
                    print(f"  Columns: {list(df.columns)}")
                    print(f"  Shape: {df.shape}")

                    # Check for empty serial numbers
                    if "serial_number" in df.columns:
                        empty_serials = (
                            df["serial_number"].isna().sum()
                            + (df["serial_number"] == "").sum()
                        )
                        print(
                            f"  Empty serial numbers: {empty_serials} out of {record_count}"
                        )

                    return df

                else:
                    print("❌ No records extracted from PDF")
                    return None

            except Exception as e:
                print(f"❌ Error parsing PDF: {e}")
                import traceback

                traceback.print_exc()
                return None

    except ImportError as e:
        print(f"❌ Import error: {e}")
        print("Make sure you're running this from the correct directory")
        return None
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        import traceback

        traceback.print_exc()
        return None


if __name__ == "__main__":
    result = test_pdf_parsing()
    if result is not None:
        print(f"\n🎉 Test completed successfully - {len(result)} records extracted")
    else:
        print(f"\n💥 Test failed - check the errors above")

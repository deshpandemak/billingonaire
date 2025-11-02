#!/usr/bin/env python3
"""
Carefully test the deduplication logic with proper scenarios
"""

import pandas as pd


def test_scenario_1():
    """Scenario 1: Different cases, all with empty serial numbers"""
    print("🧪 SCENARIO 1: Different cases, all empty serials")
    print("This should preserve all records with new logic")

    data = [
        {
            "file_name": "test.pdf",
            "case_type": "WP",
            "case_no": "1001",
            "case_year": "2025",
            "serial_number": "",
            "lawyer": "A",
        },
        {
            "file_name": "test.pdf",
            "case_type": "WP",
            "case_no": "1002",
            "case_year": "2025",
            "serial_number": "",
            "lawyer": "B",
        },
        {
            "file_name": "test.pdf",
            "case_type": "WP",
            "case_no": "1003",
            "case_year": "2025",
            "serial_number": "",
            "lawyer": "C",
        },
        {
            "file_name": "test.pdf",
            "case_type": "CP",
            "case_no": "1004",
            "case_year": "2025",
            "serial_number": "",
            "lawyer": "D",
        },
    ]

    df = pd.DataFrame(data)
    run_deduplication_test(df, "Different cases with empty serials")


def test_scenario_2():
    """Scenario 2: SAME case appearing multiple times with empty serial numbers"""
    print("\n🧪 SCENARIO 2: Same case multiple times, empty serials")
    print("This is where the problem occurs - old logic keeps duplicates")

    data = [
        {
            "file_name": "test.pdf",
            "case_type": "WP",
            "case_no": "1001",
            "case_year": "2025",
            "serial_number": "",
            "lawyer": "First lawyer",
        },
        {
            "file_name": "test.pdf",
            "case_type": "WP",
            "case_no": "1001",
            "case_year": "2025",
            "serial_number": "",
            "lawyer": "Second lawyer",
        },  # DUPLICATE case
        {
            "file_name": "test.pdf",
            "case_type": "WP",
            "case_no": "1002",
            "case_year": "2025",
            "serial_number": "",
            "lawyer": "Different case",
        },
    ]

    df = pd.DataFrame(data)
    run_deduplication_test(df, "Same case appearing multiple times")


def test_scenario_3():
    """Scenario 3: Mix of empty and non-empty serial numbers"""
    print("\n🧪 SCENARIO 3: Mix of empty and populated serials")
    print("Should include serial_number in dedup since some are populated")

    data = [
        {
            "file_name": "test.pdf",
            "case_type": "WP",
            "case_no": "1001",
            "case_year": "2025",
            "serial_number": "1",
            "lawyer": "A",
        },
        {
            "file_name": "test.pdf",
            "case_type": "WP",
            "case_no": "1002",
            "case_year": "2025",
            "serial_number": "",
            "lawyer": "B",
        },
        {
            "file_name": "test.pdf",
            "case_type": "WP",
            "case_no": "1003",
            "case_year": "2025",
            "serial_number": "3",
            "lawyer": "C",
        },
    ]

    df = pd.DataFrame(data)
    run_deduplication_test(df, "Mix of populated and empty serials")


def run_deduplication_test(df, scenario_name):
    """Test both old and new deduplication logic"""
    print(f"\n📊 Testing: {scenario_name}")
    print(f"Original records: {len(df)}")

    # Show the data
    for i, row in df.iterrows():
        print(
            f"  {i+1}. {row['case_type']}/{row['case_no']}/{row['case_year']} serial:'{row['serial_number']}' lawyer:{row['lawyer']}"
        )

    # Old logic - always include serial_number
    old_subset = ["file_name", "case_type", "case_no", "case_year", "serial_number"]
    df_old = df.drop_duplicates(subset=old_subset)

    # New logic - conditional serial_number inclusion
    new_subset = ["file_name", "case_type", "case_no", "case_year"]
    if (
        "serial_number" in df.columns
        and not df["serial_number"].dropna().empty
        and any(str(x).strip() for x in df["serial_number"].dropna())
    ):
        new_subset.append("serial_number")
        include_serial = True
    else:
        include_serial = False

    df_new = df.drop_duplicates(subset=new_subset)

    print(f"  Old logic (always include serial): {len(df_old)} records")
    print(f"  New logic (conditional serial): {len(df_new)} records")
    print(f"  New logic includes serial_number: {include_serial}")

    if len(df_old) != len(df_new):
        diff = len(df_new) - len(df_old)
        if diff > 0:
            print(f"  ✅ New logic preserves {diff} more records")
        else:
            print(f"  ⚠️ New logic removes {-diff} more records")
    else:
        print("  ➖ Both give same result")


if __name__ == "__main__":
    test_scenario_1()
    test_scenario_2()
    test_scenario_3()

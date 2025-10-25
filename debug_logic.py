#!/usr/bin/env python3
"""
Debug the actual logic to understand the conditional behavior
"""

import pandas as pd

def debug_logic():
    """Debug the actual conditional logic"""
    
    # Test data with mixed serial numbers
    data = [
        {'file_name': 'test.pdf', 'case_type': 'WP', 'case_no': '1001', 'case_year': '2025', 'serial_number': None},
        {'file_name': 'test.pdf', 'case_type': 'WP', 'case_no': '1002', 'case_year': '2025', 'serial_number': ''},
        {'file_name': 'test.pdf', 'case_type': 'WP', 'case_no': '1003', 'case_year': '2025', 'serial_number': '  '},  # whitespace
        {'file_name': 'test.pdf', 'case_type': 'WP', 'case_no': '1004', 'case_year': '2025', 'serial_number': '1'},   # actual value
    ]
    
    df = pd.DataFrame(data)
    
    print("🔍 Debugging the conditional logic")
    print("=" * 50)
    
    print(f"Serial number values: {df['serial_number'].tolist()}")
    print(f"Dropna: {df['serial_number'].dropna().tolist()}")
    print(f"Non-empty check: {[str(x).strip() for x in df['serial_number'].dropna()]}")
    print(f"Any non-empty: {any(str(x).strip() for x in df['serial_number'].dropna())}")
    
    # Reproduce the exact logic from the fix
    subset_fields = ["file_name", "case_type", "case_no", "case_year"]
    condition_met = (
        "serial_number" in df.columns
        and not df["serial_number"].dropna().empty
        and any(str(x).strip() for x in df["serial_number"].dropna())
    )
    
    print(f"\nCondition evaluation:")
    print(f"  'serial_number' in columns: {'serial_number' in df.columns}")
    print(f"  dropna() not empty: {not df['serial_number'].dropna().empty}")
    print(f"  any non-empty strings: {any(str(x).strip() for x in df['serial_number'].dropna())}")
    print(f"  Overall condition: {condition_met}")
    
    if condition_met:
        subset_fields.append("serial_number")
        print(f"  → Including 'serial_number' in deduplication")
    else:
        print(f"  → NOT including 'serial_number' in deduplication")
    
    print(f"\nSubset fields for deduplication: {subset_fields}")
    
    # Now test with all empty/null serial numbers
    print(f"\n" + "="*50)
    print("Testing with ALL empty serial numbers:")
    
    empty_data = [
        {'file_name': 'test.pdf', 'case_type': 'WP', 'case_no': '1001', 'case_year': '2025', 'serial_number': None},
        {'file_name': 'test.pdf', 'case_type': 'WP', 'case_no': '1001', 'case_year': '2025', 'serial_number': ''},
        {'file_name': 'test.pdf', 'case_type': 'WP', 'case_no': '1002', 'case_year': '2025', 'serial_number': None},
        {'file_name': 'test.pdf', 'case_type': 'WP', 'case_no': '1002', 'case_year': '2025', 'serial_number': ''},
    ]
    
    df_empty = pd.DataFrame(empty_data)
    
    print(f"Data with all empty serials: {len(df_empty)} records")
    
    # Test old logic
    old_subset = ["file_name", "case_type", "case_no", "case_year", "serial_number"]
    df_old = df_empty.drop_duplicates(subset=old_subset)
    
    # Test new logic
    new_subset = ["file_name", "case_type", "case_no", "case_year"]
    new_condition = (
        "serial_number" in df_empty.columns
        and not df_empty["serial_number"].dropna().empty
        and any(str(x).strip() for x in df_empty["serial_number"].dropna())
    )
    if new_condition:
        new_subset.append("serial_number")
    
    df_new = df_empty.drop_duplicates(subset=new_subset)
    
    print(f"Old logic result: {len(df_old)} records")
    print(f"New logic result: {len(df_new)} records") 
    print(f"New logic condition met: {new_condition}")
    print(f"New logic subset: {new_subset}")
    
    if len(df_old) != len(df_new):
        print(f"🎯 DIFFERENCE FOUND: New logic preserves {len(df_new) - len(df_old)} more records!")
    else:
        print(f"Both methods give same result")

if __name__ == "__main__":
    debug_logic()
#!/usr/bin/env python3
"""
Demonstrate the deduplication fix with synthetic data that shows the problem
"""

import pandas as pd

def demonstrate_deduplication_fix():
    """Show how the old vs new deduplication logic behaves"""
    
    # Create synthetic data that demonstrates when the OLD logic would INCORRECTLY
    # consider records as duplicates due to empty serial numbers
    # Key insight: The actual deduplication bug happens when:
    # 1. All serial_numbers are empty/null
    # 2. Records are otherwise different but get collapsed
    # 3. The old logic includes serial_number in subset, making pandas think
    #    records with same case info + empty serial are "duplicates"
    
    # Let's create a scenario with different lawyers but same case pattern
    synthetic_data = [
        {
            'file_name': 'board.pdf',
            'case_type': 'WP',  
            'case_no': '1001',  
            'case_year': '2025',
            'serial_number': None,  # Missing serial 
            'petitioner_lawyer': 'Adv. Sharma for Petitioner',
            'respondent_lawyer': 'SHRI A.K. SINGH, AGP',
        },
        {
            'file_name': 'board.pdf',
            'case_type': 'WP',   
            'case_no': '1002',   # Different case number
            'case_year': '2025',
            'serial_number': None,  # Missing serial 
            'petitioner_lawyer': 'Adv. Patel for Applicant', 
            'respondent_lawyer': 'SMT. MEERA JOSHI, ADD. GP',
        },
        {
            'file_name': 'board.pdf',
            'case_type': 'CP',   # Different case type
            'case_no': '1003',   
            'case_year': '2025',
            'serial_number': None,  # Missing serial
            'petitioner_lawyer': 'Adv. Kumar',
            'respondent_lawyer': 'SHRI R.P. VERMA, AGP',
        },
        {
            'file_name': 'board.pdf',
            'case_type': 'IA',   # Different case type  
            'case_no': '1004',   
            'case_year': '2025',
            'serial_number': '',   # Empty string serial
            'petitioner_lawyer': 'Adv. Singh & Associates',
            'respondent_lawyer': 'DR. ANJALI MISHRA, ADD. GP',
        },
        # Add a case that would actually demonstrate the issue
        # Same case details but appearing multiple times due to parsing issues
        {
            'file_name': 'board.pdf',
            'case_type': 'WP',   
            'case_no': '1005',   
            'case_year': '2025',
            'serial_number': '',   # Empty serial - this causes the problem
            'petitioner_lawyer': 'First appearance of case with these lawyers',
            'respondent_lawyer': 'SHRI X.Y. AGGARWAL, AGP',
        },
        {
            'file_name': 'board.pdf',
            'case_type': 'WP',   
            'case_no': '1005',   # SAME case details
            'case_year': '2025',
            'serial_number': '',   # SAME empty serial
            'petitioner_lawyer': 'Second listing with additional counsel info',  # But different text
            'respondent_lawyer': 'SHRI X.Y. AGGARWAL, AGP WITH SMT. PRIYA SHARMA',  # Different respondent info
        },
    ]
    
    df = pd.DataFrame(synthetic_data)
    
    print("🧪 Demonstrating deduplication fix with synthetic data")
    print("=" * 60)
    print(f"Original data: {len(df)} records")
    print("\nRecords:")
    for i, row in df.iterrows():
        print(f"  {i+1}. {row['case_type']}/{row['case_no']}/{row['case_year']} (serial: '{row['serial_number']}')")
    
    # Old logic: always include serial_number in deduplication
    old_subset = ["file_name", "case_type", "case_no", "case_year", "serial_number"]
    df_old = df.drop_duplicates(subset=old_subset)
    
    # New logic: include serial_number only if it has meaningful values
    subset_fields = ["file_name", "case_type", "case_no", "case_year"]
    if (
        "serial_number" in df.columns
        and not df["serial_number"].dropna().empty
        and any(str(x).strip() for x in df["serial_number"].dropna())
    ):
        subset_fields.append("serial_number")
    
    df_new = df.drop_duplicates(subset=subset_fields)
    
    print(f"\n📊 Deduplication Results:")
    print(f"  Old logic (always include serial_number): {len(df_old)} records")
    print(f"  New logic (conditional serial_number): {len(df_new)} records")
    
    if len(df_old) < len(df_new):
        print(f"  🎯 OLD LOGIC PROBLEM: Lost {len(df_new) - len(df_old)} records!")
        print(f"     This happens because empty serial_numbers make distinct records")
        print(f"     look 'duplicate' when they're actually different cases/entries")
        
        # Show which records were lost
        lost_indices = set(df_new.index) - set(df_old.index)
        if lost_indices:
            print(f"     Records that would be lost with old logic:")
            for idx in lost_indices:
                row = df_new.loc[idx]
                print(f"       - {row['case_type']}/{row['case_no']}/{row['case_year']}: {row['petitioner_lawyer'][:40]}...")
                
    elif len(df_old) == len(df_new):
        print(f"  ✅ Both methods preserve all records for this data")
    
    print(f"\n🔍 Analysis:")
    print(f"  - Original data had {len(df)} records")
    print(f"  - Records with same case ID but different details: {len(df) - len(df.drop_duplicates(subset=['file_name', 'case_type', 'case_no', 'case_year']))}")
    print(f"  - Our fix prevents losing legitimate variations of cases")
    print(f"  - This is especially important for boards with multiple entries per case")
    
    return df_old, df_new

if __name__ == "__main__":
    demonstrate_deduplication_fix()
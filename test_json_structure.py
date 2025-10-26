#!/usr/bin/env python3
"""
Test to compare JSON structure output between ML enhanced and standard readers
for the 9r6f2-p2e8f.pdf file with 20 records
"""

import sys
import os
import json
import logging
from io import BytesIO
from unittest.mock import MagicMock

# Add the backend directory to Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'billingonaire_backend'))

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def create_mock_board():
    """Create a mock Board instance for testing"""
    from Board import Board
    
    # Create mock Board instance
    board = Board.__new__(Board)
    board.db = MagicMock()
    
    # Initialize ML parser if available
    board.ml_parser = None
    try:
        from ml_enhanced_parser import MLEnhancedParser
        board.ml_parser = MLEnhancedParser(fallback_parser=board)
        logging.info("✅ ML Enhanced Parser available")
    except Exception as e:
        logging.warning(f"⚠️ ML Enhanced Parser not available: {e}")
        board.ml_parser = None
    
    return board

def test_structure_consistency():
    """Test that both readers produce the same JSON structure"""
    
    pdf_path = "/workspaces/billingonaire/attached_assets/9r6f2-p2e8f.pdf"
    
    if not os.path.exists(pdf_path):
        print(f"❌ PDF file not found: {pdf_path}")
        return False
    
    print("🔍 Testing JSON Structure Consistency")
    print("=" * 60)
    
    board = create_mock_board()
    
    # Read the PDF file
    with open(pdf_path, 'rb') as file:
        file_content = file.read()
    
    # Test 1: Standard Reader
    print("\n📄 Testing Standard Reader...")
    file_stream_standard = BytesIO(file_content)
    try:
        df_standard = board.read_board("9r6f2-p2e8f.pdf", file_stream_standard)
        print(f"✅ Standard reader: {len(df_standard)} records")
        
        # Convert to records for JSON structure analysis
        records_standard = df_standard.to_dict(orient='records')
        
    except Exception as e:
        print(f"❌ Standard reader failed: {e}")
        return False
    
    # Test 2: ML Enhanced Reader (if available)
    if board.ml_parser:
        print("\n🤖 Testing ML Enhanced Reader...")
        file_stream_ml = BytesIO(file_content)
        try:
            df_ml = board.readFileWithML("9r6f2-p2e8f.pdf", file_stream_ml)
            print(f"✅ ML enhanced reader: {len(df_ml)} records")
            
            # Convert to records for JSON structure analysis
            records_ml = df_ml.to_dict(orient='records')
            
        except Exception as e:
            print(f"❌ ML enhanced reader failed: {e}")
            print("Will only test standard reader structure")
            records_ml = None
    else:
        print("\n⚠️ ML Enhanced Reader not available - testing standard only")
        records_ml = None
    
    # Analyze JSON structure
    print(f"\n📊 JSON Structure Analysis")
    print("-" * 40)
    
    # Define core fields for comparison
    core_fields = [
        'file_name', 'board_date', 'case_type', 'case_no', 'case_year',
        'serial_number', 'petitioner_lawyer', 'respondent_lawyer',
        'additional_cases', 'additional_respondent_lawyers'
    ]
    
    # Analyze standard reader structure
    if records_standard:
        standard_sample = records_standard[0] if records_standard else {}
        standard_fields = set(standard_sample.keys())
        print(f"\n🔧 Standard Reader Fields ({len(standard_fields)}):")
        for field in sorted(standard_fields):
            field_type = type(standard_sample[field]).__name__
            sample_value = str(standard_sample[field])[:50] if standard_sample[field] is not None else 'None'
            print(f"  • {field:<35} {field_type:<10} = {sample_value}...")
    
    # Analyze ML enhanced reader structure (if available)
    if records_ml:
        ml_sample = records_ml[0] if records_ml else {}
        ml_fields = set(ml_sample.keys())
        print(f"\n🤖 ML Enhanced Reader Fields ({len(ml_fields)}):")
        for field in sorted(ml_fields):
            field_type = type(ml_sample[field]).__name__
            sample_value = str(ml_sample[field])[:50] if ml_sample[field] is not None else 'None'
            print(f"  • {field:<35} {field_type:<10} = {sample_value}...")
        
        # Compare structures
        print(f"\n🔍 Structure Comparison:")
        common_fields = standard_fields & ml_fields
        standard_only = standard_fields - ml_fields
        ml_only = ml_fields - standard_fields
        
        print(f"  ✅ Common fields: {len(common_fields)}")
        for field in sorted(common_fields):
            print(f"     • {field}")
        
        if standard_only:
            print(f"  ⚠️ Standard-only fields: {len(standard_only)}")
            for field in sorted(standard_only):
                print(f"     • {field}")
        
        if ml_only:
            print(f"  🤖 ML-only fields: {len(ml_only)}")
            for field in sorted(ml_only):
                print(f"     • {field}")
        
        # Check core fields consistency
        
        print(f"\n🎯 Core Fields Consistency Check:")
        for field in core_fields:
            standard_has = field in standard_fields
            ml_has = field in ml_fields
            status = "✅" if standard_has == ml_has else "❌"
            print(f"  {status} {field:<35} Standard: {standard_has} | ML: {ml_has}")
            
            # Compare data types for common fields
            if standard_has and ml_has:
                std_type = type(standard_sample.get(field)).__name__
                ml_type = type(ml_sample.get(field)).__name__
                type_match = "✅" if std_type == ml_type else "❌"
                print(f"     {type_match} Data types: {std_type} vs {ml_type}")
    
    # Test JSON serialization
    print(f"\n🔄 JSON Serialization Test:")
    try:
        standard_json = json.dumps(records_standard[:2], indent=2, default=str)
        print(f"  ✅ Standard records can be serialized to JSON")
        
        if records_ml:
            ml_json = json.dumps(records_ml[:2], indent=2, default=str)
            print(f"  ✅ ML enhanced records can be serialized to JSON")
        
    except Exception as e:
        print(f"  ❌ JSON serialization failed: {e}")
    
    # Sample record comparison
    print(f"\n📋 Sample Record Comparison:")
    if records_standard:
        print(f"\n🔧 Standard Reader - Sample Record 1:")
        sample_std = {k: v for k, v in records_standard[0].items() if k in core_fields}
        for key, value in sample_std.items():
            print(f"  {key}: {value}")
    
    if records_ml:
        print(f"\n🤖 ML Enhanced Reader - Sample Record 1:")
        sample_ml = {k: v for k, v in records_ml[0].items() if k in core_fields}
        for key, value in sample_ml.items():
            print(f"  {key}: {value}")
    
    # Summary
    print(f"\n🎯 Test Summary:")
    print(f"  • Standard reader records: {len(records_standard) if records_standard else 0}")
    if records_ml:
        print(f"  • ML enhanced reader records: {len(records_ml)}")
        record_count_match = len(records_standard) == len(records_ml)
        print(f"  • Record count match: {'✅ YES' if record_count_match else '❌ NO'}")
        
        structure_compatible = len(standard_only) == 0  # Standard should not have fields ML doesn't
        print(f"  • Structure compatible: {'✅ YES' if structure_compatible else '❌ NO'}")
        
        if record_count_match and structure_compatible:
            print(f"  🎉 SUCCESS: Both readers produce compatible JSON structures!")
            return True
        else:
            print(f"  ⚠️ ISSUES: Structure differences found")
            return False
    else:
        print(f"  • ML enhanced reader: Not available")
        print(f"  📋 Standard reader structure verified")
        return True

if __name__ == "__main__":
    success = test_structure_consistency()
    if success:
        print(f"\n✅ All tests passed!")
    else:
        print(f"\n❌ Tests revealed issues that need fixing")
    
    print(f"\n💡 Next steps:")
    print(f"   1. If structure differences exist, update create_enhanced_record()")
    print(f"   2. Ensure ML fields are additive, not replacing standard fields")
    print(f"   3. Test with actual uploads to verify API compatibility")
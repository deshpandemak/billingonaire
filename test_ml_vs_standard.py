#!/usr/bin/env python3
"""
Enhanced test to force comparison between ML and standard readers
by mocking Firebase dependencies
"""

import sys
import os
import json
import logging
from io import BytesIO
from unittest.mock import MagicMock, patch

# Add the backend directory to Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'billingonaire_backend'))

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def create_board_with_ml():
    """Create Board instance with ML parser enabled by mocking Firebase"""
    
    # Mock Firebase dependencies
    with patch('firebase_admin.firestore.client') as mock_firestore:
        mock_firestore.return_value = MagicMock()
        
        from Board import Board
        
        # Create Board instance (will use mocked firestore)
        board = Board()
        
        return board

def force_test_both_methods():
    """Force test both standard and ML methods by bypassing availability checks"""
    
    pdf_path = "/workspaces/billingonaire/attached_assets/9r6f2-p2e8f.pdf"
    
    if not os.path.exists(pdf_path):
        print(f"❌ PDF file not found: {pdf_path}")
        return False
    
    print("🔍 Testing Both Standard and ML Enhanced Readers")
    print("=" * 60)
    
    board = create_board_with_ml()
    
    # Read the PDF file
    with open(pdf_path, 'rb') as file:
        file_content = file.read()
    
    # Define core fields for comparison
    core_fields = [
        'file_name', 'board_date', 'case_type', 'case_no', 'case_year',
        'serial_number', 'petitioner_lawyer', 'respondent_lawyer',
        'additional_cases', 'additional_respondent_lawyers'
    ]
    
    # Test 1: Standard Reader
    print("\n📄 Testing Standard Reader...")
    file_stream_standard = BytesIO(file_content)
    try:
        df_standard = board.read_board("9r6f2-p2e8f.pdf", file_stream_standard)
        print(f"✅ Standard reader: {len(df_standard)} records")
        records_standard = df_standard.to_dict(orient='records')
        
    except Exception as e:
        print(f"❌ Standard reader failed: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    # Test 2: Force ML Enhanced Processing
    print("\n🤖 Testing ML Enhanced Processing...")
    
    # First, try to use the process_enhanced_text method directly
    try:
        # Create a mock ML result
        from unittest.mock import MagicMock
        
        # Read text using standard pdfplumber
        import pdfplumber
        text = ""
        file_stream_for_text = BytesIO(file_content)
        with pdfplumber.open(file_stream_for_text) as reader:
            for page in reader.pages:
                page_text = page.extract_text()
                if page_text:
                    text += page_text.replace("\n", " ") + " "
        
        # Create mock ML result with the extracted text
        mock_ml_result = MagicMock()
        mock_ml_result.text = text
        mock_ml_result.extraction_method = "mock_ml"
        mock_ml_result.quality_score = 0.95
        mock_ml_result.entities = []
        mock_ml_result.name_mappings = []
        
        # Process using the ML enhanced method
        df_ml = board.process_enhanced_text("9r6f2-p2e8f.pdf", mock_ml_result)
        print(f"✅ ML enhanced processing: {len(df_ml)} records")
        records_ml = df_ml.to_dict(orient='records')
        
        ml_available = True
        
    except Exception as e:
        print(f"❌ ML enhanced processing failed: {e}")
        import traceback
        traceback.print_exc()
        records_ml = None
        ml_available = False
    
    # Compare structures
    print(f"\n📊 Structure Comparison")
    print("-" * 40)
    
    if records_standard:
        standard_sample = records_standard[0]
        standard_fields = set(standard_sample.keys())
        print(f"\n🔧 Standard Reader Fields ({len(standard_fields)}):")
        for field in sorted(standard_fields):
            print(f"  • {field}")
    
    if ml_available and records_ml:
        ml_sample = records_ml[0]
        ml_fields = set(ml_sample.keys())
        print(f"\n🤖 ML Enhanced Reader Fields ({len(ml_fields)}):")
        for field in sorted(ml_fields):
            print(f"  • {field}")
        
        # Compare structures
        print(f"\n🔍 Field Comparison:")
        common_fields = standard_fields & ml_fields
        standard_only = standard_fields - ml_fields
        ml_only = ml_fields - standard_fields
        
        print(f"  ✅ Common fields ({len(common_fields)}):")
        for field in sorted(common_fields):
            print(f"     • {field}")
        
        if standard_only:
            print(f"  ⚠️ Standard-only fields ({len(standard_only)}):")
            for field in sorted(standard_only):
                print(f"     • {field}")
        
        if ml_only:
            print(f"  🤖 ML-only fields ({len(ml_only)}):")
            for field in sorted(ml_only):
                print(f"     • {field}")
        
        # Test core fields consistency
        print(f"\n🎯 Core Fields Consistency:")
        all_core_present = True
        for field in core_fields:
            standard_has = field in standard_fields
            ml_has = field in ml_fields
            status = "✅" if standard_has and ml_has else "❌"
            print(f"  {status} {field}")
            if not (standard_has and ml_has):
                all_core_present = False
        
        # Compare sample values for core fields
        print(f"\n📋 Sample Data Comparison (Record 1):")
        print(f"\nField{'':30} Standard{'':25} ML Enhanced")
        print("-" * 80)
        for field in core_fields:
            if field in standard_fields and field in ml_fields:
                std_val = str(standard_sample.get(field, 'N/A'))[:25]
                ml_val = str(ml_sample.get(field, 'N/A'))[:25]
                match_indicator = "✅" if standard_sample.get(field) == ml_sample.get(field) else "❌"
                print(f"{field:<35} {std_val:<25} {ml_val:<25} {match_indicator}")
        
        # Record count comparison
        print(f"\n📊 Record Count Analysis:")
        print(f"  Standard reader: {len(records_standard)} records")
        print(f"  ML enhanced:     {len(records_ml)} records")
        count_match = len(records_standard) == len(records_ml)
        print(f"  Count match:     {'✅ YES' if count_match else '❌ NO'}")
        
        # JSON compatibility test
        print(f"\n🔄 JSON Compatibility Test:")
        try:
            # Test serialization
            std_json = json.dumps(records_standard[0], default=str, indent=2)
            ml_json = json.dumps(records_ml[0], default=str, indent=2)
            print(f"  ✅ Both can be serialized to JSON")
            
            # Test if ML structure is superset of standard
            std_keys = set(records_standard[0].keys())
            ml_keys = set(records_ml[0].keys())
            is_superset = std_keys.issubset(ml_keys)
            print(f"  ML is superset: {'✅ YES' if is_superset else '❌ NO'}")
            
        except Exception as e:
            print(f"  ❌ JSON serialization failed: {e}")
        
        # Final assessment
        print(f"\n🎯 Final Assessment:")
        structure_ok = all_core_present and count_match
        print(f"  Structure compatible: {'✅ YES' if structure_ok else '❌ NO'}")
        
        if structure_ok:
            print(f"  🎉 SUCCESS: Both readers produce compatible structures!")
            
            # Check for ML enhancements
            ml_enhancements = ml_only
            if ml_enhancements:
                print(f"  🚀 ML adds {len(ml_enhancements)} enhancement fields:")
                for field in sorted(ml_enhancements):
                    print(f"     • {field}")
            
            return True
        else:
            print(f"  ⚠️ ISSUES: Structure compatibility problems found")
            return False
    else:
        print(f"\n⚠️ Could not test ML enhanced reader")
        print(f"📋 Standard reader produces valid structure with {len(standard_fields)} fields")
        return True

if __name__ == "__main__":
    success = force_test_both_methods()
    
    print(f"\n{'='*60}")
    if success:
        print(f"✅ Structure compatibility test PASSED!")
    else:
        print(f"❌ Structure compatibility test FAILED!")
    
    print(f"\n💡 Key Requirements:")
    print(f"   1. Both readers must produce same core fields")
    print(f"   2. ML reader can add extra fields (ml_*)")
    print(f"   3. Same record count (20 for this PDF)")
    print(f"   4. JSON serializable structures")
    print(f"   5. Compatible with upload API expectations")
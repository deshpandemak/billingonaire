# Case Matching and Storage Documentation

## Overview
This document explains how order extraction data is matched and stored with the respective case details in the daily-boards collection, ensuring that multi-case orders correctly associate each case's parties with its database entry.

## Data Flow Architecture

### 1. Order Extraction Pipeline

```
PDF Order Document
    ↓
ML-Enhanced Parser (text extraction + entity recognition)
    ↓
Order Analyzer (case structure extraction)
    ↓
AutoOrderManager (multi-case linking + storage)
    ↓
Firestore (daily-boards collection)
```

### 2. Component Responsibilities

#### ML-Enhanced Parser (`ml_enhanced_parser.py`)
- **Purpose**: Enhanced text extraction and entity recognition
- **Input**: PDF bytes
- **Output**: `ExtractionResult` with cleaned text and legal entities
- **Key Methods**:
  - `enhance_pdf_extraction()`: Main entry point for PDF processing
  - `_extract_legal_entities()`: Extract AGP/GP/AG entities using regex + spaCy NER
  - `_preprocess_text()`: Clean and normalize extracted text

**Note**: The ML parser does NOT define case structure. It only provides enhanced text extraction that order_analyzer consumes.

#### Order Analyzer (`order_analyzer.py`)
- **Purpose**: Extract structured case information from order text
- **Input**: PDF bytes or extracted text
- **Output**: `OrderAnalysisResult` with simplified case structure
- **Key Methods**:
  - `analyze_order()`: Main analysis entry point
  - `_extract_structured_cases_simplified()`: Extract cases in new simplified format
  - `_extract_multi_case_details()`: Handle orders with multiple cases
  - `_extract_govt_pleader_from_text()`: Extract case-specific government pleader

**Simplified Case Structure**:
```python
@dataclass
class CaseInfo:
    case_type: str              # e.g., "WP"
    case_number: int            # e.g., 11347 (INTEGER)
    case_year: int              # e.g., 2024 (INTEGER)
    petitioner: str             # Case-specific petitioner name
    respondent: str             # Case-specific respondent name
    government_pleader: List[str]  # Case-specific GP/AGP names
```

#### AutoOrderManager (`AutoOrderManager.py`)
- **Purpose**: Automated order processing and multi-case linking
- **Input**: Downloaded PDF from court website
- **Output**: Stored order analysis + linked case records
- **Key Methods**:
  - `_analyze_order_with_date_validation()`: Analyze and store order with simplified structure
  - `_link_order_to_additional_cases()`: Link order to all cases found in document
  - `_create_case_specific_analysis()`: Store case-specific details in daily-boards
  - `_parse_case_reference()`: Parse case reference to (case_type, case_number, case_year)
  - `_find_case_id_by_reference()`: Find case ID in daily-boards by reference + date

## Case Matching Algorithm

### Matching Criteria
To link extracted order data with the correct case entry in daily-boards, the system matches on:

1. **Case Type** (exact match, case-insensitive): `WP`, `PIL`, `WA`, etc.
2. **Case Number** (exact match, integer): e.g., `11347`
3. **Case Year** (exact match, integer): e.g., `2024`
4. **Board Date** (exact match): The date the case appeared on the board

### Type Safety
⚠️ **Critical**: Case numbers and years MUST be stored and queried as integers:
```python
# ❌ WRONG - String comparison will fail
case_ref = db.collection('daily-boards').where('case_no', '==', '11347')

# ✅ CORRECT - Integer comparison
case_ref = db.collection('daily-boards').where('case_no', '==', 11347)
```

### Matching Flow

```python
def _find_case_id_by_reference(self, case_type: str, case_no: int, 
                                case_year: int, board_date: str) -> Optional[str]:
    """
    Find case ID in daily-boards collection by matching:
    - case_type (exact, case-insensitive)
    - case_no (exact, integer)
    - case_year (exact, integer)
    - board_date (exact, string YYYY-MM-DD)
    """
    cases = db.collection('daily-boards')\
        .where('case_type', '==', case_type.upper())\
        .where('case_no', '==', case_no)\           # INTEGER
        .where('case_year', '==', case_year)\       # INTEGER
        .where('board_date', '==', board_date)\
        .limit(1)\
        .get()
    
    return cases[0].id if cases else None
```

## Multi-Case Order Processing

### Scenario: Order with Multiple Cases
When a single order document mentions multiple cases (e.g., WP/11347/2024, WP/11348/2024, WP/11349/2024), each case gets its own extracted details.

### Example Order Text
```
WP/11347/2024 - Petitioner: ABC Ltd. - Respondent: State of Maharashtra - AGP: Mr. Sharma
WP/11348/2024 - Petitioner: XYZ Corp - Respondent: Collector, Mumbai - AGP: Mrs. Gupta
WP/11349/2024 - Petitioner: DEF Inc. - Respondent: BMC - AGP: Mr. Sharma
```

### Extraction Result
```json
{
  "order_date": "2025-01-15",
  "order_category": "ADJOURNED",
  "order_text": "...",
  "order_cases": [
    {
      "case_type": "WP",
      "case_number": 11347,
      "case_year": 2024,
      "petitioner": "ABC Ltd.",
      "respondent": "State of Maharashtra",
      "government_pleader": ["Mr. Sharma"]
    },
    {
      "case_type": "WP",
      "case_number": 11348,
      "case_year": 2024,
      "petitioner": "XYZ Corp",
      "respondent": "Collector, Mumbai",
      "government_pleader": ["Mrs. Gupta"]
    },
    {
      "case_type": "WP",
      "case_number": 11349,
      "case_year": 2024,
      "petitioner": "DEF Inc.",
      "respondent": "BMC",
      "government_pleader": ["Mr. Sharma"]
    }
  ]
}
```

### Storage Process

#### Step 1: Store Main Order Analysis
```python
# Store in order_analysis collection
order_doc = {
    "order_date": "2025-01-15",
    "order_category": "ADJOURNED",
    "order_text": "...",
    "order_cases": [...]  # All 3 cases
}
order_id = db.collection('order_analysis').add(order_doc)
```

#### Step 2: Link to Each Case in daily-boards
For each case in `order_cases`:

```python
for case in order_cases:
    # Parse case reference
    case_type = case['case_type']        # "WP"
    case_number = case['case_number']    # 11347 (int)
    case_year = case['case_year']        # 2024 (int)
    
    # Find matching case in daily-boards by reference + board_date
    case_id = _find_case_id_by_reference(
        case_type=case_type,
        case_no=case_number,
        case_year=case_year,
        board_date=order_date  # "2025-01-15"
    )
    
    if case_id:
        # Create case-specific analysis
        case_analysis = {
            "order_id": order_id,
            "order_date": "2025-01-15",
            "order_category": "ADJOURNED",
            "order_text": "...",
            "petitioner": case['petitioner'],         # Case-specific
            "respondent": case['respondent'],         # Case-specific
            "government_pleader": case['government_pleader']  # Case-specific
        }
        
        # Store in daily-boards/{case_id}/order_details
        db.collection('daily-boards').document(case_id)\
            .collection('order_details').add(case_analysis)
```

#### Step 3: Result in Firestore

**Collection: `order_analysis`**
```
order_analysis/{order_id}
{
  "order_date": "2025-01-15",
  "order_category": "ADJOURNED",
  "order_text": "...",
  "order_cases": [
    {"case_type": "WP", "case_number": 11347, ...},
    {"case_type": "WP", "case_number": 11348, ...},
    {"case_type": "WP", "case_number": 11349, ...}
  ]
}
```

**Collection: `daily-boards` (WP/11347/2024)**
```
daily-boards/{case_id_11347}
{
  "case_type": "WP",
  "case_no": 11347,
  "case_year": 2024,
  "board_date": "2025-01-15",
  ...
  
  order_details/{order_detail_id_1}
  {
    "order_id": "{order_id}",
    "order_date": "2025-01-15",
    "order_category": "ADJOURNED",
    "petitioner": "ABC Ltd.",              ← Case-specific
    "respondent": "State of Maharashtra",  ← Case-specific
    "government_pleader": ["Mr. Sharma"]   ← Case-specific
  }
}
```

**Collection: `daily-boards` (WP/11348/2024)**
```
daily-boards/{case_id_11348}
{
  "case_type": "WP",
  "case_no": 11348,
  "case_year": 2024,
  "board_date": "2025-01-15",
  ...
  
  order_details/{order_detail_id_2}
  {
    "order_id": "{order_id}",
    "order_date": "2025-01-15",
    "order_category": "ADJOURNED",
    "petitioner": "XYZ Corp",              ← Case-specific
    "respondent": "Collector, Mumbai",     ← Case-specific
    "government_pleader": ["Mrs. Gupta"]   ← Case-specific
  }
}
```

**Collection: `daily-boards` (WP/11349/2024)**
```
daily-boards/{case_id_11349}
{
  "case_type": "WP",
  "case_no": 11349,
  "case_year": 2024,
  "board_date": "2025-01-15",
  ...
  
  order_details/{order_detail_id_3}
  {
    "order_id": "{order_id}",
    "order_date": "2025-01-15",
    "order_category": "ADJOURNED",
    "petitioner": "DEF Inc.",              ← Case-specific
    "respondent": "BMC",                   ← Case-specific
    "government_pleader": ["Mr. Sharma"]   ← Case-specific
  }
}
```

## Key Implementation Details

### 1. Case Reference Parsing
```python
def _parse_case_reference(self, case_ref: str) -> Tuple[str, int, int]:
    """
    Parse case reference string into components
    
    Args:
        case_ref: e.g., "WP/11347/2024" or "PIL/123/2023"
    
    Returns:
        Tuple of (case_type, case_number, case_year)
        - case_type: str (e.g., "WP")
        - case_number: int (e.g., 11347)
        - case_year: int (e.g., 2024)
    """
    parts = case_ref.split('/')
    if len(parts) == 3:
        case_type = parts[0].strip().upper()
        case_no = parts[1].strip()
        case_year = parts[2].strip()
        
        # Convert to integers for proper Firestore queries
        return (case_type, int(case_no), int(case_year))
    
    return ("UNKNOWN", 0, 0)
```

### 2. Date Validation
- Order date must match board_date for case matching
- Prevents linking orders to cases on different dates
- Format: YYYY-MM-DD (ISO 8601)

### 3. Case-Specific Government Pleader Extraction
```python
def _extract_govt_pleader_from_text(self, text: str, case_ref: str) -> List[str]:
    """
    Extract government pleader names for a specific case from order text
    
    Strategy:
    1. Look for GP/AGP mentions near the case reference
    2. Extract names following titles (Mr., Mrs., Ms., Dr., Shri, Smt.)
    3. Return unique pleader names
    """
    pleaders = []
    
    # Find text segment containing this case reference
    case_pattern = re.escape(case_ref)
    matches = list(re.finditer(case_pattern, text, re.IGNORECASE))
    
    for match in matches:
        # Extract context around case reference (500 chars)
        start = max(0, match.start() - 250)
        end = min(len(text), match.end() + 250)
        context = text[start:end]
        
        # Extract GP/AGP names from context
        gp_pattern = r'(?:AGP|GP|A\.G\.P\.|G\.P\.)[:\s-]*([A-Z][a-zA-Z\s\.]+?)(?=\s*(?:for|AGP|GP|Respondent|Petitioner|\n|$))'
        gp_matches = re.findall(gp_pattern, context, re.IGNORECASE)
        
        for name in gp_matches:
            clean_name = name.strip()
            if clean_name and len(clean_name) > 3:
                pleaders.append(clean_name)
    
    return list(set(pleaders))  # Remove duplicates
```

## Testing and Validation

### Test Scenarios

#### Test 1: Single Case Order
```python
order_text = "WP/11347/2024 - Petitioner: ABC Ltd. - Respondent: State - AGP: Mr. Sharma"
# Expected: 1 case extracted with correct details
```

#### Test 2: Multi-Case Order
```python
order_text = """
WP/11347/2024 - Petitioner: ABC Ltd. - AGP: Mr. Sharma
WP/11348/2024 - Petitioner: XYZ Corp - AGP: Mrs. Gupta
"""
# Expected: 2 cases extracted, each with correct petitioner and AGP
```

#### Test 3: Case Matching by Date
```python
# Case exists in daily-boards with board_date="2025-01-15"
# Order has order_date="2025-01-15"
# Expected: Match found, details stored

# Order has order_date="2025-01-16"
# Expected: No match, details not stored
```

#### Test 4: Type Safety
```python
# daily-boards has case_no=11347 (integer)
# Query with case_no=11347 (integer)
# Expected: Match found

# Query with case_no="11347" (string)
# Expected: No match (type mismatch)
```

### Validation Checklist
- [ ] All case numbers are stored as integers
- [ ] All case years are stored as integers
- [ ] Board dates match order dates exactly
- [ ] Case-specific petitioners are correctly associated
- [ ] Case-specific respondents are correctly associated
- [ ] Case-specific government pleaders are correctly associated
- [ ] Multi-case orders create separate entries for each case
- [ ] Each case links to the same order_id in order_analysis

## Common Issues and Solutions

### Issue 1: Case Not Found
**Symptom**: `_find_case_id_by_reference()` returns None

**Possible Causes**:
1. Type mismatch (string vs integer for case_no/case_year)
2. Date mismatch (order_date ≠ board_date)
3. Case reference format incorrect
4. Case doesn't exist in daily-boards for that date

**Solution**:
```python
# Add logging to debug
logging.info(f"Looking for case: {case_type}/{case_no}/{case_year} on {board_date}")
logging.info(f"Types: case_no={type(case_no)}, case_year={type(case_year)}")

# Verify types
assert isinstance(case_no, int), f"case_no must be int, got {type(case_no)}"
assert isinstance(case_year, int), f"case_year must be int, got {type(case_year)}"
```

### Issue 2: Wrong Parties Associated
**Symptom**: Case A has parties from Case B

**Possible Causes**:
1. Multi-case detection failed
2. Government pleader extraction not case-specific
3. Petitioner/respondent extraction spanned multiple cases

**Solution**:
- Use `_extract_multi_case_details()` for orders with multiple case references
- Extract parties from text segment specific to each case reference
- Validate each case has unique petitioner/respondent

### Issue 3: Duplicate Storage
**Symptom**: Same order stored multiple times for one case

**Possible Causes**:
1. Multiple calls to `_create_case_specific_analysis()`
2. Duplicate case references in order text

**Solution**:
```python
# Check if order already linked before creating new entry
existing = db.collection('daily-boards').document(case_id)\
    .collection('order_details')\
    .where('order_id', '==', order_id)\
    .limit(1)\
    .get()

if not existing:
    # Create new entry
    _create_case_specific_analysis(...)
```

## Migration from Old Structure

### Old Structure (Deprecated)
```python
{
  "order_petitioners": ["ABC Ltd.", "XYZ Corp"],
  "order_respondents": ["State", "Collector"],
  "order_agp_names": ["Mr. Sharma", "Mrs. Gupta"],
  "order_case_numbers": ["WP/11347/2024", "WP/11348/2024"],
  # Problem: No clear association between petitioner and case
}
```

### New Structure (Current)
```python
{
  "order_cases": [
    {
      "case_type": "WP",
      "case_number": 11347,
      "case_year": 2024,
      "petitioner": "ABC Ltd.",        # Clear association
      "respondent": "State",
      "government_pleader": ["Mr. Sharma"]
    },
    {
      "case_type": "WP",
      "case_number": 11348,
      "case_year": 2024,
      "petitioner": "XYZ Corp",       # Clear association
      "respondent": "Collector",
      "government_pleader": ["Mrs. Gupta"]
    }
  ]
}
```

## Best Practices

1. **Always Use Integer Types**
   - Store case_number and case_year as integers
   - Parse case references to integers before querying

2. **Validate Date Matching**
   - Ensure order_date matches board_date before linking
   - Log mismatches for debugging

3. **Extract Case-Specific Details**
   - For multi-case orders, extract petitioner/respondent/GP for each case separately
   - Use text segmentation around each case reference

4. **Handle Missing Matches Gracefully**
   - Log when case not found in daily-boards
   - Don't fail entire order processing if one case can't be matched

5. **Test Multi-Case Scenarios**
   - Validate that each case gets its correct parties
   - Verify no cross-contamination between cases

## Summary

The case matching and storage system ensures that:

1. **ML-Enhanced Parser** provides clean text extraction with entity recognition
2. **Order Analyzer** extracts structured case information in simplified format
3. **AutoOrderManager** matches extracted cases to daily-boards entries by:
   - Case type (exact, case-insensitive)
   - Case number (exact, integer)
   - Case year (exact, integer)
   - Board date (exact, YYYY-MM-DD)
4. **Each case** gets its specific petitioner, respondent, and government pleader details
5. **Multi-case orders** are properly handled with separate entries for each case
6. **Type safety** is enforced with integer case numbers and years

This architecture ensures data integrity and accurate billing by maintaining clear associations between cases and their extracted order details.

# Order Extraction Cleanup - Implementation Summary

## Overview
Cleaned up the order extraction system to extract only essential information in a simplified JSON structure for each case in an order.

## Changes Made

### 1. Simplified Data Model (`order_analyzer.py`)

**Old `CaseInfo` structure:**
```python
@dataclass
class CaseInfo:
    case_number: Optional[str]
    petitioners: List[str]
    respondents: List[str]
    agp_names: List[str]
    advocates: List[str]
```

**New `CaseInfo` structure:**
```python
@dataclass
class CaseInfo:
    """Information about a single case within an order - simplified structure"""
    case_type: str
    case_number: int
    case_year: int
    petitioner: str
    respondent: str
    government_pleader: List[str]
```

**Old `OrderAnalysisResult` structure:**
- Had 11 fields including legacy compatibility fields
- Included document_structure, key_phrases, next_hearing_date, disposal_reason, tabular_data

**New `OrderAnalysisResult` structure:**
```python
@dataclass
class OrderAnalysisResult:
    """Result from order document analysis - simplified structure"""
    order_category: str  # ADJOURNED, HEARD_AND_ADJOURNED, DISPOSED_OFF
    category_confidence: float
    order_date: Optional[str]
    cases: List[CaseInfo]
    order_text: str
```

### 2. New Extraction Methods

Added three new methods to handle the simplified extraction:

#### `_extract_structured_cases_simplified()`
Main method that coordinates case extraction using the simplified format.

#### `_extract_multi_case_details()`
Extracts details for multiple cases from order text, handling:
- Case numbers (WP/11347/2024, etc.)
- Petitioner names with "And Ors." suffix
- Respondent names (including multi-line respondents)
- Government pleader assignment per case

#### `_extract_govt_pleader_from_text()`
Extracts government pleader names with proper case association:
- Pattern 1: Direct case association (e.g., "Adv. P. P. Kakade, Addl. GP a/w M J. Deshpande, AGP for the Respondent State in WP/11347/2024")
- Pattern 2: General State advocates as fallback
- Handles "a/w" (along with) pattern for multiple advocates

#### `_extract_parties_for_case()`
Extracts petitioner and respondent for a specific case with fallback patterns:
- Primary pattern: Expects title prefixes (Shri, Smt, Mr., Ms.)
- Fallback pattern: Handles names without title prefixes

#### `_extract_govt_pleader_for_case()`
Helper to extract government pleader by canonical case ID

### 3. Updated Main Analysis Method

**`analyze_order_document()` now:**
1. Extracts text using ML parser
2. Parses document structure
3. Extracts order date
4. Classifies order category (ADJOURNED/HEARD_AND_ADJOURNED/DISPOSED_OFF)
5. Calls `_extract_structured_cases_simplified()` for clean case extraction
6. Returns simplified `OrderAnalysisResult`

### 4. Updated API Response (`main.py`)

**Old response format:**
```json
{
  "cases": [{
    "case_number": "WP/11347/2024",
    "petitioners": [...],
    "respondents": [...],
    "agp_names": [...],
    "advocates": [...]
  }],
  "document_structure": {...},
  "tabular_data": [...],
  "petitioners": [...],
  "respondents": [...],
  "agp_names": [...],
  ...
}
```

**New response format:**
```json
{
  "analysis_id": "doc_id",
  "filename": "order.pdf",
  "order_category": "HEARD_AND_ADJOURNED",
  "category_confidence": 0.85,
  "order_date": "19th December 2024",
  "cases": [
    {
      "case_type": "WP",
      "case_number": 11347,
      "case_year": 2024,
      "petitioner": "Dareppa Vishwaanath Birajdar And Ors.",
      "respondent": "The State of Maharashtra Through The Sec. School Education dept And Ors.",
      "government_pleader": [
        "Adv. P. P. Kakade, Addl. GP",
        "M J. Deshpande, AGP"
      ]
    },
    {
      "case_type": "WP",
      "case_number": 11348,
      "case_year": 2024,
      "petitioner": "Sunil Gajanand Ambare And Ors.",
      "respondent": "The State of Maharashtra Through The Sec. School Education dept And Ors.",
      "government_pleader": [
        "Adv. P. M. J. Deshpande, AGP"
      ]
    }
  ],
  "summary": {
    "total_cases": 2
  }
}
```

### 5. Updated Database Storage (`save_analysis_result()`)

Firestore now stores:
```python
{
    "filename": "order.pdf",
    "order_category": "HEARD_AND_ADJOURNED",
    "category_confidence": 0.85,
    "order_date": "19th December 2024",
    "cases": [
        {
            "case_type": "WP",
            "case_number": 11347,
            "case_year": 2024,
            "petitioner": "...",
            "respondent": "...",
            "government_pleader": [...]
        }
    ],
    "analysis_timestamp": "2024-12-19T10:30:00",
    "text_length": 5000
}
```

## Order Categories

The system classifies orders into three categories:

1. **ADJOURNED** - Simple adjournment without hearing
2. **HEARD_AND_ADJOURNED** - Matter was heard (AGP/GP appeared) then adjourned
3. **DISPOSED_OFF** - Case disposed/completed

## Multi-Case Handling

The system properly handles orders with multiple case numbers:
- Each case can have different petitioners
- Each case can have different respondents
- Each case can have different government pleaders (AGP/GP)
- Government pleaders are extracted per case using case-specific patterns

## Pattern Examples

### Case Block Pattern
```
WRIT PETITION NO.11347 OF 2024

Dareppa Vishwaanath Birajdar And Ors. ....Petitioner
versus
The State of Maharashtra Through The Sec. ... ....Respondents
```

### Government Pleader Pattern
```
Adv. P. P. Kakade, Addl. GP a/w M J. Deshpande, AGP for the Respondent State in WP/11347/2024
```

## Testing

Created `test_order_extraction.py` to validate:
- ✅ Case number extraction (3/3 cases)
- ✅ Petitioner extraction (3/3 correct)
- ✅ Respondent extraction (3/3 correct)
- ✅ Government pleader extraction (3/3 correct with proper case association)
- ✅ Order date extraction
- ✅ Order category detection

## Files Modified

1. `/workspaces/billingonaire/billingonaire_backend/order_analyzer.py`
   - Updated data models (CaseInfo, OrderAnalysisResult)
   - Added simplified extraction methods
   - Updated analysis workflow
   - Updated database storage

2. `/workspaces/billingonaire/billingonaire_backend/main.py`
   - Updated API response format
   - Removed legacy fields

3. `/workspaces/billingonaire/billingonaire_backend/test_order_extraction.py` (NEW)
   - Validation tests for extraction logic

## Breaking Changes

⚠️ **API Response Structure Changed**

The `/analyze-order` endpoint now returns a different structure. If you have existing clients consuming this API, they will need to be updated to use:
- `cases[].case_type` instead of parsing from case_number
- `cases[].case_number` (int) instead of full string
- `cases[].case_year` (int) for the year
- `cases[].petitioner` (string) instead of `cases[].petitioners` (array)
- `cases[].respondent` (string) instead of `cases[].respondents` (array)
- `cases[].government_pleader` (array) instead of `cases[].agp_names` (array)

The response no longer includes:
- `document_structure`
- `tabular_data`
- `key_phrases`
- `next_hearing_date`
- `disposal_reason`
- Top-level `petitioners`, `respondents`, `agp_names`, `dates` arrays

## Next Steps

To integrate this with board data extraction:
1. When extracting orders from daily boards, call the simplified extraction
2. For each case in the order, match it to the board's case list by case_number
3. Add the petitioner, respondent, and government_pleader data to the matched case
4. Include order_date and order_category in the case record

"""
Test script to validate the new simplified order extraction
"""

import re

# Sample text that matches the user's requirement
sample_order_text = """
WRIT PETITION NO.11347 OF 2024

Dareppa Vishwaanath Birajdar And Ors. ....Petitioner
versus
The State of Maharashtra Through The Sec. School Education dept And Ors. ....Respondents

WRIT PETITION NO.11348 OF 2024

Sunil Gajanand Ambare And Ors. ....Petitioner
versus
The State of Maharashtra Through The Sec. School Education dept And Ors. ....Respondents

WRIT PETITION NO.11349 OF 2024

Shivraj Appasaheb Birajdar And Ors. ....Petitioner
versus
The State of Maharashtra Through The Sec. School Education dept And Ors. ....Respondents

WITH

Adv. P. P. Kakade, Addl. GP a/w M J. Deshpande, AGP for the Respondent State in WP/11347/2024
Adv. P. M. J. Deshpande, AGP for the Respondent State in WP/11348/2024
Adv. Neha Bhide, GP a/w S. B. Kalel, AGP for the Respondent State in WP/11349/2024

CORAM: Hon'ble Justice X.Y.Z.
DATE: 19th December 2024

ORDER:

Stand over to 15th January 2025.
"""


def test_case_extraction():
    """Test the case extraction patterns"""

    # Pattern to extract case blocks
    case_block_pattern = r"(?:WRIT PETITION|CRIMINAL WRIT PETITION|CIVIL APPLICATION)(?:\s+NO\.?)?\s*([0-9]+)\s+OF\s+([0-9]{4})(.*?)(?=(?:WRIT PETITION NO\.|WITH|(?:Mr\.|Ms\.|Adv\.)\s+[A-Z].*?for|$))"

    matches = re.findall(
        case_block_pattern, sample_order_text, re.DOTALL | re.IGNORECASE
    )

    print("=== Case Extraction Test ===\n")
    print(f"Found {len(matches)} cases\n")

    expected_cases = [
        {
            "case_type": "WP",
            "case_number": 11347,
            "case_year": 2024,
            "petitioner": "Dareppa Vishwaanath Birajdar And Ors.",
            "respondent": "The State of Maharashtra Through The Sec. School Education dept And Ors.",
            "government_pleader": [
                "Adv. P. P. Kakade, Addl. GP",
                "M J. Deshpande, AGP",
            ],
        },
        {
            "case_type": "WP",
            "case_number": 11348,
            "case_year": 2024,
            "petitioner": "Sunil Gajanand Ambare And Ors.",
            "respondent": "The State of Maharashtra Through The Sec. School Education dept And Ors.",
            "government_pleader": ["Adv. P. M. J. Deshpande, AGP"],
        },
        {
            "case_type": "WP",
            "case_number": 11349,
            "case_year": 2024,
            "petitioner": "Shivraj Appasaheb Birajdar And Ors.",
            "respondent": "The State of Maharashtra Through The Sec. School Education dept And Ors.",
            "government_pleader": ["Adv. Neha Bhide, GP", "S. B. Kalel, AGP"],
        },
    ]

    for idx, (case_num, year, block_text) in enumerate(matches):
        print(f"Case {idx + 1}: WP/{case_num}/{year}")

        # Extract petitioner
        petitioner_pattern = r"((?:Shri?\.?|Smt\.?|Mr\.?|Ms\.?)\s+[A-Za-z\s\.]+?)(?:\s+And\s+Ors\.?)?\s*\.{2,}\s*Petitioner"
        pet_match = re.search(petitioner_pattern, block_text, re.IGNORECASE)

        petitioner = ""
        if pet_match:
            petitioner = pet_match.group(1).strip()
            if re.search(
                r"And\s+Ors\.",
                block_text[pet_match.start() : pet_match.end()],
                re.IGNORECASE,
            ):
                petitioner += " And Ors."
        else:
            # Fallback: try without title prefixes
            petitioner_pattern2 = r"([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+(?:\s+And\s+Ors\.)?)\s*\.{2,}\s*Petitioner"
            pet_match2 = re.search(petitioner_pattern2, block_text, re.IGNORECASE)
            if pet_match2:
                petitioner = pet_match2.group(1).strip()

        if petitioner:
            print(f"  Petitioner: {petitioner}")
        else:
            print("  Petitioner: NOT FOUND")

        # Extract respondent
        respondent_pattern = r"versus\s+(.*?)(?:\s*\.{2,}\s*Respondent)"
        resp_match = re.search(
            respondent_pattern, block_text, re.DOTALL | re.IGNORECASE
        )

        if resp_match:
            respondent = resp_match.group(1).strip()
            respondent = re.sub(r"\s+", " ", respondent)
            print(f"  Respondent: {respondent}")
        else:
            print("  Respondent: NOT FOUND")

        # Extract government pleader for this case
        case_key = f"WP/{case_num}/{year}"
        pattern1 = rf"(?:Adv\.\s+|Ms\.\s+|Mr\.\s+)([^,]+),\s+((?:Addl\.\s+)?(?:AGP|GP))(?:\s+a/w\s+([^,]+),\s+((?:AGP|GP)))?\s+for\s+the\s+Respondent\s+State\s+in\s+{re.escape(case_key)}"
        match1 = re.search(pattern1, sample_order_text, re.IGNORECASE)

        pleaders = []
        if match1:
            name1 = match1.group(1).strip()
            role1 = match1.group(2).strip()
            pleaders.append(f"Adv. {name1}, {role1}")

            if match1.group(3):
                name2 = match1.group(3).strip()
                role2 = match1.group(4).strip() if match1.group(4) else "AGP"
                pleaders.append(f"{name2}, {role2}")

        print(f"  Government Pleader: {pleaders if pleaders else 'NOT FOUND'}")

        # Validate against expected
        expected = expected_cases[idx]
        print(f"\n  Validation:")
        print(
            f"    Petitioner match: {petitioner == expected['petitioner'] if 'petitioner' in locals() else 'SKIPPED'}"
        )
        print(
            f"    Respondent match: {respondent == expected['respondent'] if 'respondent' in locals() else 'SKIPPED'}"
        )
        print(f"    Expected GP: {expected['government_pleader']}")
        print(f"    Extracted GP: {pleaders}")
        print()


def test_order_category():
    """Test order category extraction"""
    print("\n=== Order Category Test ===\n")

    # Check for category indicators
    if re.search(r"\bstand\s+over\b", sample_order_text, re.IGNORECASE):
        print("✓ Found 'stand over' - indicates ADJOURNED")

    # Since there's advocate activity, this should be HEARD_AND_ADJOURNED
    if re.search(
        r"(?:Adv\.|Ms\.|Mr\.)\s+[A-Za-z\s\.]+(?:AGP|GP)",
        sample_order_text,
        re.IGNORECASE,
    ):
        print("✓ Found AGP/GP mentions - indicates hearing took place")
        print("✓ Expected Category: HEARD_AND_ADJOURNED")

    print()


def test_order_date():
    """Test order date extraction"""
    print("\n=== Order Date Test ===\n")

    date_pattern = r"DATE:\s*(\d{1,2}(?:st|nd|rd|th)?\s+(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{4})"
    match = re.search(date_pattern, sample_order_text, re.IGNORECASE)

    if match:
        print(f"✓ Order Date: {match.group(1)}")
    else:
        print("✗ Order Date: NOT FOUND")

    print()


if __name__ == "__main__":
    print("Testing Order Extraction Logic")
    print("=" * 60)
    test_case_extraction()
    test_order_category()
    test_order_date()
    print("\n" + "=" * 60)
    print("Test completed!")

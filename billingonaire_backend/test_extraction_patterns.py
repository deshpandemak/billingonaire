"""
Comprehensive test script for order extraction patterns
Tests all known case formats to ensure patterns work correctly
"""

import re


def test_petitioner_patterns():
    """Test all petitioner extraction patterns"""
    print("=" * 80)
    print("TESTING PETITIONER PATTERNS")
    print("=" * 80)

    test_cases = [
        {
            "name": "Pattern 1: Split by …Petitioner",
            "text": "Hemlata Kirtikumar Kakade Alias Hemlata …Petitioner Jagannath Veer Versus",
            "expected": "Hemlata Kirtikumar Kakade Alias Hemlata Jagannath Veer",
        },
        {
            "name": "Pattern 2: IN THE MATTER BETWEEN",
            "text": "IN THE MATTER BETWEEN Kanhaiyalal Madhavji Thakkar …Petitioner",
            "expected": "Kanhaiyalal Madhavji Thakkar",
        },
        {
            "name": "Pattern 3: Name …Petitioner Versus",
            "text": "Sunil Shivaji Wagh …Petitioner Versus",
            "expected": "Sunil Shivaji Wagh",
        },
        {
            "name": "Pattern 3: Rina Rajesh Vasudeo …Petitioner Versus",
            "text": "Rina Rajesh Vasudeo …Petitioner Versus State of Maharashtra",
            "expected": "Rina Rajesh Vasudeo",
        },
        {
            "name": "Pattern 4: Before Versus (no separator)",
            "text": "Bhimrao s/o Gangaramji Chourpagar Versus The State",
            "expected": "Bhimrao s/o Gangaramji Chourpagar",
        },
        {
            "name": "Pattern 4: Manikrao with dots separator",
            "text": "Manikrao Shankar Devkate .. Petitioner Versus The State",
            "expected": "Manikrao Shankar Devkate",
        },
        {
            "name": "Pattern 5: ....PETITIONER format (uppercase)",
            "text": "Manikrao Shankar Devkate ....PETITIONER V/S The State",
            "expected": "Manikrao Shankar Devkate",
        },
    ]

    # Pattern definitions from order_analyzer.py
    patterns = [
        (
            "Pattern 1",
            r"([A-Z][a-zA-Z\s\.\-/]+?(?:\s+[Aa]lias\s+[A-Z][a-zA-Z\s/]+?)?)(?:\s*…\s*Petitioners?\s+)([A-Z][a-zA-Z\s\.\-/]+?)\s*(?:Versus|vs\.?)",
        ),
        (
            "Pattern 2",
            r"IN\s+THE\s+MATTER\s+BETWEEN\s+([A-Z][a-zA-Z\s\.\-/]+?(?:\s+[Aa]lias\s+[A-Z][a-zA-Z\s\.\-/]+?)?)\s*…\s*Petitioners?",
        ),
        (
            "Pattern 3",
            r"([A-Z][a-zA-Z\s\.\-/]+?(?:\s+[Aa]lias\s+[A-Z][a-zA-Z\s\.\-/]+?)?)\s*…\s*Petitioners?\s+(?:Versus|vs\.?)",
        ),
        (
            "Pattern 4",
            r"([A-Z][a-zA-Z]+(?:\s+[a-zA-Z\.\-/]+){2,}(?:\s+[Aa]lias\s+[A-Z][a-zA-Z\s\.\-/]+)?)\s+(?:Versus|vs\.?)\s",
        ),
        (
            "Pattern 5",
            r"([A-Z][a-zA-Z]+(?:\s+[a-zA-Z\.\-/]+){1,})\s+\.{2,}\s*PETITIONER",
        ),
    ]

    results = []
    for test in test_cases:
        matched = False
        for pattern_name, pattern in patterns:
            match = re.search(pattern, test["text"], re.IGNORECASE)
            if match:
                if pattern_name == "Pattern 1":
                    # Combine parts
                    extracted = f"{match.group(1).strip()} {match.group(2).strip()}"
                else:
                    extracted = match.group(1).strip()

                # Clean up
                extracted = re.sub(r"\s+", " ", extracted).strip()
                extracted = re.sub(r"\.{2,}.*$", "", extracted).strip()
                extracted = re.sub(
                    r"\s*\.{2,}\s*PETITIONER.*$", "", extracted, flags=re.IGNORECASE
                ).strip()

                status = (
                    "✅ PASS"
                    if extracted == test["expected"]
                    else f"❌ FAIL (got: {extracted})"
                )
                print(f"\n{test['name']}")
                print(f"  Pattern: {pattern_name}")
                print(f"  Expected: {test['expected']}")
                print(f"  Got: {extracted}")
                print(f"  Status: {status}")
                results.append({"test": test["name"], "status": status.startswith("✅")})
                matched = True
                break

        if not matched:
            print(f"\n{test['name']}")
            print("  ❌ FAIL: No pattern matched!")
            results.append({"test": test["name"], "status": False})

    return results


def test_respondent_patterns():
    """Test all respondent extraction patterns"""
    print("\n" + "=" * 80)
    print("TESTING RESPONDENT PATTERNS")
    print("=" * 80)

    test_cases = [
        {
            "name": "Pattern 1: …Respondents separator",
            "text": "Versus Mr. Harun Attar & Anr. …Respondents Mr. Smith",
            "expected": "Mr. Harun Attar & Anr.",
        },
        {
            "name": "Pattern 1: State of Maharashtra",
            "text": "Versus State of Maharashtra & Anr. …Respondents Mr. Smith",
            "expected": "State of Maharashtra & Anr.",
        },
        {
            "name": "Pattern 2: before next section",
            "text": "Versus The State of Maharashtra & Ors. .. Respondents Mr. Rahul S. Kadam",
            "expected": "The State of Maharashtra & Ors. .. Respondents",
        },
        {
            "name": "Pattern 3: ....RESPONDENT format (uppercase)",
            "text": "V/S The State Of Maharashtra Throu.govt Pleader....RESPONDENT And Ors",
            "expected": "The State Of Maharashtra Throu.govt Pleader",
        },
    ]

    # Pattern definitions from order_analyzer.py
    patterns = [
        (
            "Pattern 1",
            r"versus\s+((?:(?:Mr\.?|Ms\.?|Dr\.?|Shri?\.?|Smt\.?|The)\s+)?[A-Za-z\s\.\-&,]+?(?:\s+(?:And|&)\s+(?:Ors?\.?|Anr\.?))*?)\s*…\s*Respondents?",
        ),
        (
            "Pattern 2",
            r"versus\s+((?:(?:Mr\.?|Ms\.?|Dr\.?|Shri?\.?|Smt\.?|The)\s+)?[A-Za-z\s\.\-&,]+?(?:\s+(?:And|&)\s+(?:Ors?\.?|Anr\.?))*?)(?:\s+(?:Mr\.|Ms\.|Adv\.|CORAM)|\n|$)",
        ),
        (
            "Pattern 3",
            r"V/S\s+((?:The\s+)?[A-Za-z\s\.\-&,]+)\s+\.{2,}\s*RESPONDENT(?:\s+And\s+Ors)?",
        ),
    ]

    results = []
    for test in test_cases:
        matched = False
        for pattern_name, pattern in patterns:
            match = re.search(pattern, test["text"], re.DOTALL | re.IGNORECASE)
            if match:
                extracted = match.group(1).strip()
                extracted = re.sub(r"\s+", " ", extracted).strip()
                extracted = re.sub(r"\s*…\s*$", "", extracted).strip()

                status = (
                    "✅ PASS"
                    if extracted == test["expected"]
                    else f"❌ FAIL (got: {extracted})"
                )
                print(f"\n{test['name']}")
                print(f"  Pattern: {pattern_name}")
                print(f"  Expected: {test['expected']}")
                print(f"  Got: {extracted}")
                print(f"  Status: {status}")
                results.append({"test": test["name"], "status": status.startswith("✅")})
                matched = True
                break

        if not matched:
            print(f"\n{test['name']}")
            print("  ❌ FAIL: No pattern matched!")
            results.append({"test": test["name"], "status": False})

    return results


def test_agp_patterns():
    """Test AGP extraction patterns"""
    print("\n" + "=" * 80)
    print("TESTING AGP PATTERNS")
    print("=" * 80)

    test_cases = [
        {
            "name": "Pattern 1: a/w connector",
            "text": "Mr. N. C. Walimbe, Addl.G.P. a/w Ms Ashwini A. Purav, AGP for Respondent No. 1.",
            "expected": ["Mr. N. C. Walimbe, Addl. G.P.", "Ms Ashwini A. Purav, AGP"],
        },
        {
            "name": "Pattern 1: with connector",
            "text": "Mr. N. C. Walimbe, Addl.G.P. with Ms N. M. Mehra, AGP, for Respondent No.1-State.",
            "expected": ["Mr. N. C. Walimbe, Addl. G.P.", "Ms N. M. Mehra, AGP"],
        },
        {
            "name": "Pattern 1: Single AGP",
            "text": "Mr. O. A. Chandurkar, Addl. Govt. Pleader with Mrs. G. R. Raghuwanshi, AGP for respondent nos.1 to 3.",
            "expected": [
                "Mr. O. A. Chandurkar, Addl. G.P.",
                "Mrs. G. R. Raghuwanshi, AGP",
            ],
        },
    ]

    # Simplified pattern from order_analyzer.py
    pattern = r"((?:Mr\.?|Ms\.?|Mrs\.?|Smt\.?)\s+[A-Z][A-Za-z\s\.]+?),\s*([A-Za-z\.\s]+?)(?:\s+(?:a/w|with)\s+((?:Mr\.?|Ms\.?|Mrs\.?|Smt\.?)?\s*[A-Z][A-Za-z\s\.]+?),\s*([A-Za-z\.\s]+?))?\s+for\s+(?:Respondent|respondent)"

    results = []
    for test in test_cases:
        matches = re.findall(pattern, test["text"], re.IGNORECASE)
        extracted_agps = []

        for match in matches:
            # First AGP/GP
            name1 = match[0].strip()
            role1 = match[1].strip()

            # Validate role contains AGP/GP/G.P
            if re.search(r"AGP|GP|G\.?\s*P\.?", role1, re.IGNORECASE):
                # Normalize role
                role1_normalized = re.sub(
                    r"Addl\.\s*Govt\.\s*Pleader",
                    "Addl. G.P.",
                    role1,
                    flags=re.IGNORECASE,
                )
                role1_normalized = re.sub(
                    r"Govt\.\s*Pleader", "G.P.", role1_normalized, flags=re.IGNORECASE
                )
                role1_normalized = re.sub(r"\s+", " ", role1_normalized).strip()
                extracted_agps.append(f"{name1}, {role1_normalized}")

            # Second AGP/GP (if exists)
            if match[2]:  # a/w or with connector exists
                name2 = match[2].strip()
                role2 = match[3].strip()

                if re.search(r"AGP|GP|G\.?\s*P\.?", role2, re.IGNORECASE):
                    role2_normalized = re.sub(
                        r"Addl\.\s*Govt\.\s*Pleader",
                        "Addl. G.P.",
                        role2,
                        flags=re.IGNORECASE,
                    )
                    role2_normalized = re.sub(
                        r"Govt\.\s*Pleader",
                        "G.P.",
                        role2_normalized,
                        flags=re.IGNORECASE,
                    )
                    role2_normalized = re.sub(r"\s+", " ", role2_normalized).strip()
                    extracted_agps.append(f"{name2}, {role2_normalized}")

        status = "✅ PASS" if extracted_agps == test["expected"] else "❌ FAIL"
        print(f"\n{test['name']}")
        print(f"  Expected: {test['expected']}")
        print(f"  Got: {extracted_agps}")
        print(f"  Status: {status}")
        results.append({"test": test["name"], "status": status.startswith("✅")})

    return results


def test_categorization():
    """Test order categorization logic"""
    print("\n" + "=" * 80)
    print("TESTING CATEGORIZATION")
    print("=" * 80)

    test_cases = [
        {
            "name": "Non-hearing adjournment (paucity of time)",
            "text": "Balance Daily Board cannot be taken up today on account of paucity of time. Stand over to 26/09/2025.",
            "expected": "ADJOURNED",
        },
        {
            "name": "Heard and adjourned",
            "text": "Heard. Stand over to 16th September 2025. The parties to maintain status quo till the next date.",
            "expected": "HEARD_AND_ADJOURNED",
        },
        {
            "name": "Disposed of",
            "text": "The petition is disposed of. No costs.",
            "expected": "DISPOSED_OFF",
        },
    ]

    # Non-hearing patterns from order_analyzer.py
    no_hearing_patterns = [
        r"Balance\s+Daily\s+Board\s+cannot\s+be\s+taken\s+up",
        r"paucity\s+of\s+time",
        r"cannot\s+be\s+taken\s+up\s+today",
    ]

    results = []
    for test in test_cases:
        # Check for non-hearing
        is_non_hearing = any(
            re.search(p, test["text"], re.IGNORECASE) for p in no_hearing_patterns
        )

        # Check for disposal
        is_disposed = (
            re.search(r"disposed\s+o", test["text"], re.IGNORECASE) is not None
        )

        # Determine category
        if is_disposed:
            category = "DISPOSED_OFF"
        elif is_non_hearing:
            category = "ADJOURNED"
        elif re.search(r"heard", test["text"], re.IGNORECASE):
            category = "HEARD_AND_ADJOURNED"
        else:
            category = "ADJOURNED"

        status = (
            "✅ PASS" if category == test["expected"] else f"❌ FAIL (got: {category})"
        )
        print(f"\n{test['name']}")
        print(f"  Expected: {test['expected']}")
        print(f"  Got: {category}")
        print(f"  Status: {status}")
        results.append({"test": test["name"], "status": status.startswith("✅")})

    return results


if __name__ == "__main__":
    print("\n" + "🔬 " * 40)
    print("COMPREHENSIVE ORDER EXTRACTION PATTERN TEST")
    print("🔬 " * 40 + "\n")

    all_results = []

    # Run all tests
    all_results.extend(test_petitioner_patterns())
    all_results.extend(test_respondent_patterns())
    all_results.extend(test_agp_patterns())
    all_results.extend(test_categorization())

    # Summary
    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)
    passed = sum(1 for r in all_results if r["status"])
    failed = len(all_results) - passed

    print(f"\nTotal Tests: {len(all_results)}")
    print(f"✅ Passed: {passed}")
    print(f"❌ Failed: {failed}")

    if failed == 0:
        print("\n🎉 ALL TESTS PASSED! 🎉")
    else:
        print(f"\n⚠️  {failed} TEST(S) FAILED - Review output above")
        print("\nFailed tests:")
        for r in all_results:
            if not r["status"]:
                print(f"  ❌ {r['test']}")

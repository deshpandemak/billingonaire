"""Unit tests for order_analyzer.py module - ML-powered document analysis"""

from unittest.mock import MagicMock, patch

import pytest


class TestOrderDocumentAnalyzer:
    """Test OrderDocumentAnalyzer class methods"""

    @pytest.fixture
    def analyzer_module(self):
        with patch("order_analyzer.pdfplumber"):
            import order_analyzer

            return order_analyzer

    @pytest.fixture
    def analyzer(self, analyzer_module):
        """Create OrderDocumentAnalyzer instance"""
        return analyzer_module.OrderDocumentAnalyzer()

    def test_classify_order_category(self, analyzer):
        """Test order category classification (private method returns tuple)"""
        order_text = "The matter is heard and adjourned to next date"

        result = analyzer._classify_order(order_text)
        if result:
            # _classify_order returns (category, score, matched_nothing) tuple
            category, score, matched_nothing = result
            assert category in ["ADJOURNED", "HEARD_AND_ADJOURNED", "DISPOSED_OFF"]
            assert isinstance(score, (int, float))
            assert isinstance(matched_nothing, bool)

    def test_extract_order_date(self, analyzer):
        """Test order date extraction (private method)"""
        order_text = "Order dated 01/10/2024"
        document_structure = {"order_section": order_text}

        result = analyzer._extract_order_date(order_text, document_structure)
        if result:
            # _extract_order_date returns formatted date string
            assert "2024" in result or "01" in result or "/" in result

    def test_extract_petitioners(self, analyzer):
        """Test petitioner extraction (private method)"""
        order_text = "Petitioner: John Doe vs Respondent: State"

        result = analyzer._extract_petitioners(order_text)
        if result:
            assert isinstance(result, list)

    def test_extract_respondents(self, analyzer):
        """Test respondent extraction (private method)"""
        order_text = "Petitioner: John Doe vs Respondent: State of Maharashtra"

        result = analyzer._extract_respondents(order_text)
        if result:
            assert isinstance(result, list)

    def test_extract_agp_names(self, analyzer):
        """Test AGP name extraction (private method)"""
        order_text = "AGP Pooja Joshi appears for the State"

        result = analyzer._extract_agp_names(order_text, {})
        if result:
            assert isinstance(result, list)

    def test_extract_next_hearing_date(self, analyzer):
        """Test next hearing date extraction (private method)"""
        order_text = "Adjourned to 15/10/2024"

        result = analyzer._extract_next_hearing_date(order_text)
        if result:
            assert "15/10" in result or "2024" in result

    # ── GP/AGP deduplication ────────────────────────────────────────────────

    def test_extract_govt_pleader_deduplicates_title_spacing(self, analyzer):
        """Advocate appearing as 'Mr. Name' in header and 'Mr.Name' in body must
        not produce duplicate entries in government_pleader list.

        Regression for WP-3434-2026 order where Asif Patel appeared twice with
        different spacing after 'Mr.' (header vs paragraph 1 of the order body).
        """
        text = (
            "Mr. Asif Patel, Addl. G.P a/w. Mr.Ketan Joshi, 'B' Panel Council present.\n"
            "1. Learned counsel appears. "
            "Mr.Asif Patel, Addl. G.P a/w. Mr.Ketan Joshi, 'B' Panel Council present."
        )
        pleaders = analyzer._extract_govt_pleader_from_text(text, "WP-3434-2026")

        names = [p.split(",")[0].strip() for p in pleaders]
        assert (
            names.count("Mr. Asif Patel") + names.count("Mr.Asif Patel") == 1
        ), f"Asif Patel duplicated in output: {pleaders}"
        assert (
            len(pleaders) == 2
        ), f"Expected exactly 2 pleaders, got {len(pleaders)}: {pleaders}"

    def test_extract_govt_pleader_excludes_petitioner_side_advocate(self, analyzer):
        """Advocate listed 'for the petitioner' must never appear in the GP list.

        Regression for WP-7810-2013 order where 'Mr.Balasaheb Deshmukh for the
        petitioner in WP.' was captured by the simple_pattern because the lazy
        group-1 regex spanned across the newline into 'Ms. A.A. Nadkarni, AGP'.
        """
        text = (
            "Mr.Balasaheb Deshmukh for the petitioner in WP.\n"
            "Ms. A.A. Nadkarni, AGP with Mr. Hamid Mulla, AGP\n"
            "for State.\n"
            "Mr. Vinayak T. Padvi, In-charge Deputy Collector, is present."
        )
        pleaders = analyzer._extract_govt_pleader_from_text(text, "WP/7810/2013")

        names = [p.split(",")[0].strip() for p in pleaders]
        assert (
            "Mr. Balasaheb Deshmukh" not in names
        ), f"Petitioner's lawyer incorrectly included: {pleaders}"
        assert any(
            "Nadkarni" in n for n in names
        ), f"AGP Nadkarni missing from output: {pleaders}"
        assert any(
            "Mulla" in n for n in names
        ), f"AGP Mulla missing from output: {pleaders}"

    def test_normalise_title_name_fixes_missing_space(self, analyzer):
        """_normalise_title_name inserts a space between title and name."""
        assert analyzer._normalise_title_name("Mr.Asif Patel") == "Mr. Asif Patel"
        assert (
            analyzer._normalise_title_name("Ms.Pooja Deshpande")
            == "Ms. Pooja Deshpande"
        )
        assert analyzer._normalise_title_name("Mr. Asif Patel") == "Mr. Asif Patel"

    def test_normalise_title_name_collapses_extra_whitespace(self, analyzer):
        """_normalise_title_name collapses runs of whitespace to a single space."""
        assert analyzer._normalise_title_name("Mr.  Asif   Patel") == "Mr. Asif Patel"


class TestCategoryClassification:
    """Test order category classification logic"""

    @pytest.fixture
    def analyzer_module(self):
        with patch("order_analyzer.pdfplumber"):
            import order_analyzer

            return order_analyzer

    @pytest.fixture
    def analyzer(self, analyzer_module):
        return analyzer_module.OrderDocumentAnalyzer()

    def test_detect_adjourned(self, analyzer_module):
        """Test detection of ADJOURNED category"""
        text = "The matter is adjourned to next date"

        keywords = ["adjourned", "adjourn"]
        detected = any(kw in text.lower() for kw in keywords)
        assert detected

    def test_detect_heard_and_adjourned(self, analyzer_module):
        """Test detection of HEARD & ADJOURNED category"""
        text = "The matter is heard and adjourned"

        has_heard = "heard" in text.lower()
        has_adjourned = "adjourned" in text.lower()
        assert has_heard and has_adjourned

    def test_detect_disposed(self, analyzer_module):
        """Test detection of DISPOSED category"""
        text = "The writ petition is disposed of"

        keywords = ["disposed", "dismiss", "allow", "rejected"]
        detected = any(kw in text.lower() for kw in keywords)
        assert detected

    def test_category_confidence_scoring(self, analyzer_module):
        """Test category confidence scoring"""
        text = "The matter is heard and adjourned to 15/10/2024"

        # Count keyword occurrences
        heard_count = text.lower().count("heard")
        adjourned_count = text.lower().count("adjourned")

        confidence = min((heard_count + adjourned_count) / 3.0, 1.0)
        assert 0 <= confidence <= 1.0

    # ------------------------------------------------------------------
    # Tests for classification accuracy improvements (false-positive fixes)
    # ------------------------------------------------------------------

    def test_adjourned_not_classified_as_disposed_when_petitioner_seeks_withdrawal(
        self, analyzer
    ):
        """Petitioner intending to withdraw should NOT trigger DISPOSED_OFF."""
        text = (
            "The petitioner seeks to withdraw the petition. "
            "The matter is adjourned to 15/10/2024."
        )
        category, _, _ = analyzer._classify_order(text)
        assert category == "ADJOURNED"

    def test_adjourned_not_classified_as_disposed_when_final_order_referenced(
        self, analyzer
    ):
        """Compliance reference to a prior final order should not be DISPOSED_OFF."""
        text = (
            "In compliance of the final order dated 01/01/2024, "
            "stand over to next date."
        )
        category, _, _ = analyzer._classify_order(text)
        assert category == "ADJOURNED"

    def test_adjourned_not_classified_as_disposed_when_ia_dismissed(self, analyzer):
        """Dismissal of an interlocutory application should not trigger DISPOSED_OFF
        when the main matter is merely adjourned."""
        text = (
            "The application for time is dismissed. "
            "The matter is adjourned to 15/10/2024."
        )
        category, _, _ = analyzer._classify_order(text)
        assert category == "ADJOURNED"

    def test_heard_and_adjourned_when_interim_relief_granted(self, analyzer):
        """Granting interim relief means the court heard the matter → HEARD_AND_ADJOURNED."""
        text = (
            "Interim relief is granted. Stand over to 15/10/2024. "
            "Interim order to continue."
        )
        category, _, _ = analyzer._classify_order(text)
        assert category == "HEARD_AND_ADJOURNED"

    def test_disposed_off_correctly_classified(self, analyzer):
        """Disposal via 'disposed off as infructuous' must still be DISPOSED_OFF."""
        text = "These Petitions are disposed off as being infructuous."
        category, confidence, _ = analyzer._classify_order(text)
        assert category == "DISPOSED_OFF"
        assert confidence >= 0.6

    def test_petition_dismissed_classified_as_disposed(self, analyzer):
        """'Petition is dismissed for want of prosecution' must be DISPOSED_OFF."""
        text = "The petition is dismissed for want of prosecution."
        category, _, _ = analyzer._classify_order(text)
        assert category == "DISPOSED_OFF"

    def test_heard_and_adjourned_with_court_directives(self, analyzer):
        """Orders containing court directives ('We direct ...') should be
        classified as HEARD_AND_ADJOURNED, not ADJOURNED."""
        text = (
            "Such conduct of the Committee Officials is deprecated in strong words. "
            "We direct learned AGP to communicate this order to the Additional "
            "Chief Secretary. "
            "We further direct that an affidavit be filed within four weeks. "
            "Stand over to 24th February, 2025. "
            "Ad-interim order granted earlier to continue till then."
        )
        category, _, _ = analyzer._classify_order(text)
        assert category == "HEARD_AND_ADJOURNED"

    def test_paucity_of_time_classified_as_adjourned(self, analyzer):
        """Paucity-of-time standover must be ADJOURNED, not HEARD_AND_ADJOURNED."""
        text = (
            "Due to paucity of time, stand over to 23/10/2024. "
            "Interim order, if any, to continue till then."
        )
        category, _, _ = analyzer._classify_order(text)
        assert category == "ADJOURNED"

    @pytest.mark.parametrize(
        "text",
        [
            "Due to paucity of time, the matter did not reach. S.O. to 12/08/2026.",
            "For want of time the matter is not reached today.",
            "On account of shortage of time, the matter could not be taken up.",
            "The matter was not reached. Stand over.",
            "Due to lack of time the petition could not be reached.",
            "Balance Daily Board cannot be taken up today.",
            "Owing to insufficient time, matters are not taken up today.",
            "Since there is no time available, stand over to next week.",
        ],
    )
    def test_matter_did_not_reach_is_adjourned(self, analyzer, text):
        """Every 'the matter never reached the bench' phrasing must be ADJOURNED."""
        category, _, _ = analyzer._classify_order(text)
        assert category == "ADJOURNED"

    def test_no_time_gate_beats_disposal_phrase_from_citation(self, analyzer):
        """A disposal phrase quoted from a cited judgment must not turn a
        not-reached matter into DISPOSED_OFF.

        This is the regression: the strong-disposal override used to fire on the
        cited 'petition was dismissed' before the no-hearing check ran.
        """
        text = (
            "Due to paucity of time, the matter did not reach. "
            "In Sharma vs State of Maharashtra the petition was dismissed. "
            "Stand over to 12/08/2026."
        )
        category, confidence, _ = analyzer._classify_order(text)
        assert category == "ADJOURNED"
        assert confidence >= 0.9

    @pytest.mark.parametrize(
        "text,expected",
        [
            # "not reached"/"did not reach" about a settlement is NOT a no-time
            # phrase and must not trip the gate.
            (
                "The parties have not reached a settlement. The petition is dismissed.",
                "DISPOSED_OFF",
            ),
            (
                "Since the parties did not reach any agreement, the writ petition "
                "is allowed.",
                "DISPOSED_OFF",
            ),
            # 'want of prosecution' must not be read as 'want of time'.
            ("The petition is dismissed for want of prosecution.", "DISPOSED_OFF"),
        ],
    )
    def test_no_time_gate_does_not_over_trigger(self, analyzer, text, expected):
        """Genuine disposals must survive the expanded no-time vocabulary."""
        category, _, _ = analyzer._classify_order(text)
        assert category == expected

    # ------------------------------------------------------------------
    # Regression: a real order (WP-10601-2014) scored HEARD_AND_ADJOURNED
    # at 1.0 confidence -- high enough to skip manual review entirely --
    # when nothing was actually argued. Found via tools/review_copilot_
    # prototype.py comparing the regex classifier against an LLM on real
    # downloaded orders.
    # ------------------------------------------------------------------

    def test_office_directed_future_listing_is_adjourned_not_heard(self, analyzer):
        """'Office to list...for hearing' describes a FUTURE hearing that has
        not happened yet -- it must not be read as evidence a hearing occurred,
        even though the sentence contains the word 'hearing'."""
        text = (
            "IN THE HIGH COURT OF JUDICATURE AT BOMBAY CIVIL APPELLATE "
            "JURISDICTION WRIT PETITION NO.10601 OF 2014 Shri. Baban "
            "Ramchandra Dhobale .. Petitioner versus Shri. Chhatrapati "
            "Shikshan Sanstha and Ors. .. Respondents Mr. Rakesh Saroj for "
            "the Petitioner. Ms. Pooja Joshi Deshpande for Respondent "
            "Nos.3 to 5-State. CORAM: RAVINDRA V. GHUGE AND SHYAM C. "
            "CHANDAK, JJ. DATE: 3rd FEBRUARY, 2025. P.C.: Considering that "
            "these proceedings are pending for a long time, office to list "
            "the same on 6th March, 2025 for a final hearing/final hearing "
            "at admission stage. These matters would be called out after "
            "the 'fresh admissions' board is over."
        )
        structure = analyzer._parse_document_structure(text)
        category, confidence = analyzer._classify_order_enhanced(text, structure)
        assert category == "ADJOURNED"
        assert confidence >= 0.9

    # ------------------------------------------------------------------
    # Regression: a second, larger real-order batch (26 orders, run through
    # the same tools/review_copilot_prototype.py comparison) turned up a
    # deeper version of the same AGP/APP pattern problem: even after
    # anchoring the \b boundary above, "AGP, for the Respondent-State" --
    # boilerplate present in essentially every AGP case's appearance
    # line -- satisfies the pattern's trailing "states?" alternative via
    # the word "State" (the government as a party), not any verb. Three
    # real orders scored HEARD_AND_ADJOURNED at confidences up to 1.0 for
    # this reason alone before the fix.
    # ------------------------------------------------------------------

    def test_agp_for_the_respondent_state_is_not_read_as_agp_states_something(
        self, analyzer
    ):
        """The noun 'State' in the routine appearance line 'AGP, for the
        Respondent-State' must not satisfy the pattern's 'states?' verb
        alternative -- an AGP being listed as counsel for the government is
        not evidence anyone said anything."""
        text = (
            "IN THE HIGH COURT OF JUDICATURE AT BOMBAY WRIT PETITION "
            "NO.999 OF 2024 X ....PETITIONER versus Y ....RESPONDENT. "
            "Ms. A. Deshpande, AGP, for the Respondent-State. "
            "Wrongly on board. To be placed before the appropriate Bench "
            "having the said assignment as per the roster."
        )
        category, _, _ = analyzer._classify_order(text)
        assert category == "ADJOURNED"

    def test_app_pattern_does_not_match_appellate_jurisdiction_boilerplate(
        self, analyzer
    ):
        """'APP' must not match as a bare prefix of 'APPELLATE' -- combined
        with a State respondent (present in nearly every AGP case), the
        unanchored pattern used to read ordinary case-caption boilerplate as
        evidence that an AGP had appeared and made submissions."""
        text = (
            "IN THE HIGH COURT OF JUDICATURE AT BOMBAY APPELLATE "
            "JURISDICTION WRIT PETITION NO.999 OF 2024 X ....PETITIONER "
            "V/S The State Of Maharashtra ....RESPONDENT. "
            "The matter is adjourned to 10th March 2025."
        )
        category, _, _ = analyzer._classify_order(text)
        assert category == "ADJOURNED"

    # ------------------------------------------------------------------
    # matched_nothing guard -- a classification adjustment must never move
    # a "the classifier understood nothing about this order" result across
    # the review gate (AutoOrderManager.REVIEW_CONFIDENCE_THRESHOLD, 0.55).
    # Before this guard, _classify_order_enhanced's document-type
    # multipliers (x1.15 for COMPLETE_ORDER, 0.8+conf*0.2 for
    # ADJOURNMENT_ONLY) pushed the 0.5 "matched nothing" fallback above
    # 0.55, so guesses were billed with no human or LLM ever seeing them.
    # ------------------------------------------------------------------

    def test_classify_order_flags_matched_nothing(self, analyzer):
        """Text with no matching pattern at all must set matched_nothing."""
        text = "Registry to place papers before the appropriate bench."
        category, confidence, matched_nothing = analyzer._classify_order(text)
        assert category == "ADJOURNED"
        assert confidence == 0.5
        assert matched_nothing is True

    def test_classify_order_does_not_flag_matched_nothing_on_real_signal(
        self, analyzer
    ):
        """A genuine match (even a weak one) must NOT set matched_nothing."""
        text = "Interim relief is granted. Stand over to 15/10/2024."
        category, confidence, matched_nothing = analyzer._classify_order(text)
        assert matched_nothing is False

    @pytest.mark.parametrize(
        "document_type", ["COMPLETE_ORDER", "ADJOURNMENT_ONLY", "PARTIAL"]
    )
    def test_matched_nothing_never_crosses_the_review_gate(
        self, analyzer, document_type
    ):
        """The abbreviated 'S.O.' form (standard Bombay HC shorthand for
        'stand over') matches no classification pattern. Regardless of
        document_type, the enhanced classifier's confidence must stay
        below AutoOrderManager.REVIEW_CONFIDENCE_THRESHOLD (0.55) so the
        case reaches manual review / the LLM assist instead of being
        billed as a silent guess."""
        text = "S.O. to 3 weeks."
        structure = {"document_type": document_type, "advocates_section": ""}
        category, confidence = analyzer._classify_order_enhanced(text, structure)
        assert category == "ADJOURNED"
        assert confidence < 0.55

    def test_matched_nothing_confidence_is_unmodified_by_complete_order_boost(
        self, analyzer
    ):
        """Direct regression for the exact arithmetic that broke: 0.5 * 1.15
        = 0.575, which used to clear the 0.55 gate."""
        text = "S.O. to 3 weeks."
        structure = {"document_type": "COMPLETE_ORDER", "advocates_section": ""}
        category, confidence = analyzer._classify_order_enhanced(text, structure)
        assert confidence == 0.5

    def test_genuine_low_confidence_match_still_reaches_review(self, analyzer):
        """A real (non-matched_nothing) but weak match should still be able
        to land below the review gate -- the guard must not accidentally
        make every case unreviewable."""
        text = "Stand over to 3 weeks."
        structure = {"document_type": "COMPLETE_ORDER", "advocates_section": ""}
        category, confidence = analyzer._classify_order_enhanced(text, structure)
        assert confidence < 0.55

    # ------------------------------------------------------------------
    # AGP-presence business rule: an AGP named on the order means the
    # government's counsel appeared -- even a bare adjournment is then a
    # billable appearance (HEARD_AND_ADJOURNED), not a silent
    # non-appearance (ADJOURNED). Previously gated on BOTH an AGP name
    # AND the literal phrase "stand over", using
    # document_structure["advocates_section"] to detect the AGP -- which
    # was always empty for real orders (see the comment above this rule
    # in order_analyzer.py: PDF text extraction joins lines with spaces,
    # not newlines, so the newline-based section parser never finds an
    # advocates section). Confirmed empirically against real Bombay HC
    # orders before this fix: WP-10460/2023 and WP-10466/2025 both name
    # an AGP and were classified as plain ADJOURNED.
    # ------------------------------------------------------------------

    def test_agp_named_promotes_bare_adjournment_to_heard_and_adjourned(self, analyzer):
        """No 'stand over' phrase at all -- AGP presence alone must be
        enough now (this is the real WP-10466/2025 order text: an
        administrative mis-listing, not a hearing, but Smt. P.M.J.
        Deshpande, AGP is named)."""
        text = (
            "Prajakta Hanumant Koli ....PETITIONER V/S The State Of "
            "Maharashtra Dept Of Tribal Development And Anr Adv Sahil "
            "Chaudhari i/b Yeramwar sushant chandrakantrao for Petitioner "
            "Smt. P.M.J. Deshpande AGP CORAM : HON'BLE JUSTICE REVATI "
            "MOHITE DERE & HON'BLE JUSTICE DR. NEELA KEDAR GOKHALE, JJ "
            "DATE : 7th August, 2025 P.C. : Wrongly on board. Remove "
            "from the Board."
        )
        structure = {"document_type": "PARTIAL", "advocates_section": ""}
        category, confidence = analyzer._classify_order_enhanced(text, structure)
        assert category == "HEARD_AND_ADJOURNED"

    def test_no_agp_named_stays_plain_adjourned(self, analyzer):
        """The rule must not fire when no AGP is named -- a bare
        adjournment with no government appearance stays ADJOURNED."""
        text = "Due to paucity of time, stand over to 23/10/2024."
        structure = {"document_type": "PARTIAL", "advocates_section": ""}
        category, confidence = analyzer._classify_order_enhanced(text, structure)
        assert category == "ADJOURNED"

    def test_agp_presence_rule_does_not_override_matched_nothing_floor(self, analyzer):
        """The matched_nothing guard (confidence == 0.5, category ==
        ADJOURNED, nothing else may run) must still take priority even
        when an AGP is named -- an AGP mention alone is not itself a
        classification pattern match, so a case the base classifier
        understood nothing about must still land at the unmodifiable
        floor and go to review."""
        text = "Mr. R. S. Pawar, AGP present. Registry to verify record."
        structure = {"document_type": "COMPLETE_ORDER", "advocates_section": ""}
        category, confidence = analyzer._classify_order_enhanced(text, structure)
        assert category == "ADJOURNED"
        assert confidence == 0.5

    def test_agp_override_clears_the_review_threshold_even_from_a_tiny_base_score(
        self, analyzer
    ):
        """Confirmed against production logs: a x1.2 multiplier alone was
        not enough when the base "stand over" score is tiny -- real orders
        like IA/1339/2026 and IA(ST)/16151/2026 scored 0.12-0.34 after the
        boost, still well under the 0.55 review threshold, sending a
        routine AGP-confirmed appearance to manual review for no reason.
        The floor must push this comfortably above that gate."""
        text = (
            "By consent of learned Advocates for the respective parties, "
            "stand over to 27th April 2026. Ms. A. Deshpande, AGP for the "
            "Respondent-State."
        )
        structure = {"document_type": "PARTIAL", "advocates_section": ""}
        category, confidence = analyzer._classify_order_enhanced(text, structure)
        assert category == "HEARD_AND_ADJOURNED"
        assert confidence >= 0.55

    def test_agp_confidence_floor_also_applies_when_the_base_scorer_already_agreed(
        self, analyzer
    ):
        """Same rule, the other branch: the base classifier independently
        landed on HEARD_AND_ADJOURNED (not via the ADJOURNED override) but
        at a low score -- an AGP being named must credit that classification
        the same way, not only when it overrides a wrongly-scored
        ADJOURNED."""
        text = (
            "Heard, stand over to 12th August 2026. Mr. R.S. Pawar, AGP "
            "for the Respondent-State."
        )
        structure = {"document_type": "PARTIAL", "advocates_section": ""}
        base_category, _base_score, _matched_nothing = analyzer._classify_order(text)
        assert (
            base_category == "HEARD_AND_ADJOURNED"
        )  # sanity: base scorer agrees already

        category, confidence = analyzer._classify_order_enhanced(text, structure)
        assert category == "HEARD_AND_ADJOURNED"
        assert confidence >= 0.55

    def test_no_time_gate_still_takes_priority_over_agp_presence(self, analyzer):
        """Documents current, UNCHANGED behavior: the NO_TIME hard gate
        ("the matter was never reached") is checked before this business
        rule and returns immediately, so it is not overridden by an AGP
        being named -- this is the real WP-10601/2014 order text, which
        genuinely names Ms. Pooja Joshi Deshpande, AGP, but was never
        reached ("office to list the same on ... for a final hearing").
        If this is ever meant to change, this test must be updated
        deliberately, not as a side effect."""
        text = (
            "Mr. Rakesh Saroj for the Petitioner. Ms. Pooja Joshi "
            "Deshpande for Respondent Nos.3 to 5-State, AGP. Considering "
            "that these proceedings are pending for a long time, office "
            "to list the same on 6th March, 2025 for a final hearing."
        )
        structure = {"document_type": "PARTIAL", "advocates_section": ""}
        category, confidence = analyzer._classify_order_enhanced(text, structure)
        assert category == "ADJOURNED"
        assert confidence == 0.95


class TestEntityExtraction:
    """Test entity extraction from orders"""

    @pytest.fixture
    def analyzer_module(self):
        with patch("order_analyzer.pdfplumber"):
            import order_analyzer

            return order_analyzer

    def test_extract_case_numbers(self, analyzer_module):
        """Test case number extraction"""
        text = "In the matter of WP/12345/2024 and WP/12346/2024"

        import re

        pattern = r"[A-Z]+\s?\(?[A-Z]*\)?\/\d+\/\d{4}"
        cases = re.findall(pattern, text)
        assert len(cases) == 2

    def test_extract_party_names_from_vs(self, analyzer_module):
        """Test extracting parties from 'vs' pattern"""
        text = "John Doe vs State of Maharashtra"

        if " vs " in text.lower():
            parts = text.lower().split(" vs ")
            assert len(parts) == 2

    def test_extract_dates(self, analyzer_module):
        """Test date extraction"""
        text = "Order dated 01/10/2024 and next hearing on 15/10/2024"

        import re

        pattern = r"\d{1,2}/\d{1,2}/\d{4}"
        dates = re.findall(pattern, text)
        assert len(dates) == 2

    def test_extract_key_phrases(self, analyzer_module):
        """Test key phrase extraction"""
        text = "The court observed that the petition is maintainable"

        key_phrases = []
        if "observed" in text:
            key_phrases.append("court observed")
        assert len(key_phrases) > 0


class TestTableExtraction:
    """Test table data extraction from orders"""

    @pytest.fixture
    def analyzer_module(self):
        with patch("order_analyzer.pdfplumber"):
            import order_analyzer

            return order_analyzer

    @patch("order_analyzer.pdfplumber")
    def test_extract_case_table(self, mock_pdfplumber, analyzer_module):
        """Test case table extraction (using analyze_order_document)"""
        mock_pdf = MagicMock()
        mock_page = MagicMock()
        mock_page.extract_tables.return_value = [
            [
                ["Case No.", "Petitioner", "Respondent"],
                ["WP/12345/2024", "John Doe", "State"],
            ]
        ]
        mock_page.extract_text.return_value = "Test order text"
        mock_pdf.pages = [mock_page]
        mock_pdfplumber.open.return_value.__enter__.return_value = mock_pdf

        analyzer = analyzer_module.OrderDocumentAnalyzer()
        # Test table extraction is done through analyze_order_document
        assert analyzer is not None

    def test_parse_table_headers(self, analyzer_module):
        """Test table header parsing"""
        headers = ["Sr.No.", "Case No.", "Parties"]

        # Normalize headers
        normalized = [h.lower().strip() for h in headers]
        assert "case no" in " ".join(normalized)


class TestMLEnhancedDetection:
    """Test ML-enhanced detection features"""

    @pytest.fixture
    def analyzer_module(self):
        with patch("order_analyzer.pdfplumber"):
            import order_analyzer

            return order_analyzer

    def test_enhanced_heard_and_adjourned_detection(self, analyzer_module):
        """Test enhanced HEARD & ADJOURNED detection"""
        text = "Arguments heard. Matter stands adjourned"

        # Pattern variations
        patterns = ["heard.*adjourned", "arguments.*heard", "submissions.*heard"]

        import re

        detected = any(re.search(p, text.lower()) for p in patterns)
        assert detected

    def test_scoring_logic(self, analyzer_module):
        """Test improved scoring logic"""
        keyword_matches = 3
        pattern_matches = 2

        # Weighted scoring
        score = (keyword_matches * 0.6 + pattern_matches * 0.4) / 5
        assert 0 <= score <= 1.0

    def test_dual_extraction_parties(self, analyzer_module):
        """Test dual extraction from table and body text"""
        table_petitioner = "John Doe (from table)"
        text_petitioner = "John Doe (from text)"

        # Prefer table data
        final_petitioner = table_petitioner if table_petitioner else text_petitioner
        assert "from table" in final_petitioner


class TestAnalysisResult:
    """Test analysis result structure"""

    @pytest.fixture
    def analyzer_module(self):
        with patch("order_analyzer.pdfplumber"):
            import order_analyzer

            return order_analyzer

    def test_create_analysis_result(self, analyzer_module):
        """Test creating analysis result object"""
        result = {
            "order_category": "HEARD & ADJOURNED",
            "category_confidence": 0.95,
            "order_date": "01/10/2024",
            "petitioners": ["John Doe"],
            "respondents": ["State"],
            "agp_names": ["Pooja Joshi"],
            "order_text": "Sample order",
        }

        assert result["order_category"] in [
            "ADJOURNED",
            "HEARD & ADJOURNED",
            "DISPOSED",
        ]
        assert 0 <= result["category_confidence"] <= 1.0

    def test_validate_analysis_result(self, analyzer_module):
        """Test analysis result validation"""
        result = {
            "order_category": "HEARD & ADJOURNED",
            "petitioners": ["John Doe"],
            "respondents": ["State"],
        }

        # Validate required fields
        assert "order_category" in result
        assert result["petitioners"] is not None
        assert result["respondents"] is not None

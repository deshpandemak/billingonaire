from bill_qa import FEE_SCHEDULE, qa_check_bill


def _entry(case_ref, date, result, fee, confidence=0.9):
    return {
        "case_detail": case_ref,
        "date": date,
        "results": result,
        "fees_rs": fee,
        "order_category_confidence": confidence,
    }


class TestFeeMismatch:
    def test_flags_a_fee_that_does_not_match_its_result_category(self):
        entries = [_entry("WP/1/2026", "2026-01-15", "ADJOURNED", 1875)]
        report = qa_check_bill(entries)

        assert report["ok"] is False
        assert len(report["fee_mismatches"]) == 1
        mismatch = report["fee_mismatches"][0]
        assert mismatch["fee"] == 1875
        assert mismatch["expected_fee"] == 1250

    def test_correct_fee_for_each_known_result_is_not_flagged(self):
        entries = [
            _entry("WP/1/2026", "2026-01-15", "WP DISPOSED OF", 2500),
            _entry("WP/2/2026", "2026-01-15", "HEARD & ADJN.", 1875),
            _entry("WP/3/2026", "2026-01-15", "ADJOURNED", 1250),
            _entry("WP/4/2026", "2026-01-15", "*ADJOURNED*", 1250),
        ]
        report = qa_check_bill(entries)
        assert report["fee_mismatches"] == []
        assert report["ok"] is True

    def test_unrecognized_result_string_is_not_flagged_as_a_mismatch(self):
        """An unknown/custom result value has no expected fee to compare
        against -- silently skip rather than false-flag every unusual row."""
        entries = [_entry("WP/1/2026", "2026-01-15", "SOME OTHER OUTCOME", 999)]
        report = qa_check_bill(entries)
        assert report["fee_mismatches"] == []


class TestDuplicates:
    def test_same_case_and_date_twice_in_one_bill_is_flagged(self):
        entries = [
            _entry("WP/1/2026", "2026-01-15", "ADJOURNED", 1250),
            _entry("WP/1/2026", "2026-01-15", "ADJOURNED", 1250),
        ]
        report = qa_check_bill(entries)

        assert report["ok"] is False
        assert len(report["duplicates_within_bill"]) == 1

    def test_same_case_different_dates_is_not_a_duplicate(self):
        """The same case appears on the board twice a month apart -- two
        genuinely separate hearings, not a duplicate."""
        entries = [
            _entry("WP/1/2026", "2026-01-15", "ADJOURNED", 1250),
            _entry("WP/1/2026", "2026-02-15", "ADJOURNED", 1250),
        ]
        report = qa_check_bill(entries)
        assert report["duplicates_within_bill"] == []

    def test_case_already_in_a_previously_saved_bill_is_flagged(self):
        entries = [_entry("WP/1/2026", "2026-01-15", "ADJOURNED", 1250)]
        already_billed = {("WP/1/2026", "2026-01-15")}

        report = qa_check_bill(entries, previously_billed_keys=already_billed)

        assert report["ok"] is False
        assert len(report["duplicates_across_bills"]) == 1

    def test_no_cross_bill_check_when_previously_billed_keys_not_provided(self):
        entries = [_entry("WP/1/2026", "2026-01-15", "ADJOURNED", 1250)]
        report = qa_check_bill(entries)
        assert report["duplicates_across_bills"] == []


class TestFlaggedEntries:
    def test_assumed_entry_with_no_order_is_flagged_informationally(self):
        entries = [
            _entry("WP/1/2026", "2026-01-15", "*ADJOURNED*", 1250, confidence=None)
        ]
        report = qa_check_bill(entries)

        assert len(report["flagged_entries"]) == 1
        assert report["flagged_entries"][0]["assumed"] is True
        # Informational only -- must not block saving on its own.
        assert report["ok"] is True

    def test_low_confidence_entry_is_flagged(self):
        entries = [_entry("WP/1/2026", "2026-01-15", "ADJOURNED", 1250, confidence=0.3)]
        report = qa_check_bill(entries, review_confidence_threshold=0.55)
        assert len(report["flagged_entries"]) == 1

    def test_high_confidence_entry_is_not_flagged(self):
        entries = [
            _entry("WP/1/2026", "2026-01-15", "ADJOURNED", 1250, confidence=0.95)
        ]
        report = qa_check_bill(entries, review_confidence_threshold=0.55)
        assert report["flagged_entries"] == []


class TestOkFlag:
    def test_ok_is_false_only_for_blocking_issue_types(self):
        """Fee mismatches and duplicates are the "something is probably
        actually wrong" signals; low-confidence/assumed entries are
        informational (the bill already surfaces those at generation time
        per an earlier fix) and must not flip ok to False on their own."""
        entries = [
            _entry("WP/1/2026", "2026-01-15", "*ADJOURNED*", 1250, confidence=None)
        ]
        report = qa_check_bill(entries)
        assert report["ok"] is True

    def test_empty_bill_is_ok(self):
        report = qa_check_bill([])
        assert report["ok"] is True
        assert report["summary_lines"] == ["No issues found."]


class TestFeeScheduleStaysInSyncWithCalculateCaseFee:
    """Regression guard: bill_qa.FEE_SCHEDULE is a deliberate duplicate of
    main.calculate_case_fee's result->fee mapping (kept import-light rather
    than importing main.py's full dependency chain). If someone changes
    the fee schedule in one place and not the other, this must fail."""

    def test_every_result_calculate_case_fee_can_produce_matches_the_schedule(
        self, monkeypatch
    ):
        import sys
        import types
        from unittest.mock import patch

        if "spacy" not in sys.modules:
            spacy_stub = types.ModuleType("spacy")
            matcher_stub = types.ModuleType("spacy.matcher")

            class Matcher:  # pragma: no cover
                pass

            matcher_stub.Matcher = Matcher
            spacy_stub.matcher = matcher_stub
            sys.modules["spacy"] = spacy_stub
            sys.modules["spacy.matcher"] = matcher_stub

        with patch("firebase_admin.firestore.client"):
            import main as main_module

        def _case(order_category, order_status="analysed"):
            return {
                "case_type": "WP",
                "case_no": "1",
                "case_year": "2026",
            }

        mock_manager = types.SimpleNamespace(
            case_store=types.SimpleNamespace(
                get_case_details=lambda ref: {
                    "orders": [
                        {
                            "order_status": "analysed",
                            "order_category": order_category,
                            "order_link": "https://example.com/o.pdf",
                            "board_date": "2026-01-15",
                        }
                    ]
                }
            )
        )

        for order_category in (
            "DISPOSED_OFF",
            "HEARD_AND_ADJOURNED",
            "ADJOURNED",
        ):
            monkeypatch.setattr(
                main_module, "get_auto_order_manager", lambda: mock_manager
            )
            fee_info = main_module.calculate_case_fee(
                _case(order_category), board_date="2026-01-15"
            )
            assert fee_info["result"] in FEE_SCHEDULE, (
                f"calculate_case_fee produced result={fee_info['result']!r} for "
                f"order_category={order_category!r}, but bill_qa.FEE_SCHEDULE "
                f"has no entry for it -- the two schedules have drifted apart."
            )
            assert FEE_SCHEDULE[fee_info["result"]] == fee_info["fee"], (
                f"bill_qa.FEE_SCHEDULE says {fee_info['result']!r} -> "
                f"{FEE_SCHEDULE[fee_info['result']]}, but calculate_case_fee "
                f"actually returns {fee_info['fee']} -- the two schedules "
                f"have drifted apart."
            )

    def test_no_order_on_file_result_matches_the_schedule(self, monkeypatch):
        import sys
        import types
        from unittest.mock import patch

        if "spacy" not in sys.modules:
            spacy_stub = types.ModuleType("spacy")
            matcher_stub = types.ModuleType("spacy.matcher")

            class Matcher:  # pragma: no cover
                pass

            matcher_stub.Matcher = Matcher
            spacy_stub.matcher = matcher_stub
            sys.modules["spacy"] = spacy_stub
            sys.modules["spacy.matcher"] = matcher_stub

        with patch("firebase_admin.firestore.client"):
            import main as main_module

        mock_manager = types.SimpleNamespace(
            case_store=types.SimpleNamespace(get_case_details=lambda ref: {})
        )
        monkeypatch.setattr(main_module, "get_auto_order_manager", lambda: mock_manager)

        fee_info = main_module.calculate_case_fee(
            {"case_type": "WP", "case_no": "1", "case_year": "2026"},
            board_date="2026-01-15",
        )
        assert fee_info["result"] in FEE_SCHEDULE
        assert FEE_SCHEDULE[fee_info["result"]] == fee_info["fee"]

from unittest.mock import patch

import pytest

import compliance_extractor
from review_copilot import ReviewCopilotError


class TestExtractDirectives:
    def test_explicit_deadline_date_is_used_as_is(self):
        with patch(
            "compliance_extractor.call_gemini_json",
            return_value={
                "directives": [
                    {
                        "directive_type": "FILE_REPLY_AFFIDAVIT",
                        "deadline_date": "2026-08-13",
                        "deadline_relative_amount": 0,
                        "deadline_relative_unit": "NONE",
                        "description": "Respondents shall file their reply affidavits "
                        "on or before 13th August 2026.",
                    }
                ]
            },
        ):
            result = compliance_extractor.extract_directives(
                "order text", "fake-key", order_date="2026-07-08"
            )

        assert result == [
            {
                "directive_type": "FILE_REPLY_AFFIDAVIT",
                "description": "Respondents shall file their reply affidavits "
                "on or before 13th August 2026.",
                "deadline_date": "2026-08-13",
            }
        ]

    def test_relative_deadline_resolves_against_order_date(self):
        with patch(
            "compliance_extractor.call_gemini_json",
            return_value={
                "directives": [
                    {
                        "directive_type": "PRODUCE_DOCUMENTS",
                        "deadline_date": "",
                        "deadline_relative_amount": 3,
                        "deadline_relative_unit": "WEEKS",
                        "description": "file an affidavit of service within three "
                        "weeks from today.",
                    }
                ]
            },
        ):
            result = compliance_extractor.extract_directives(
                "order text", "fake-key", order_date="2026-07-08"
            )

        # 2026-07-08 + 21 days = 2026-07-29
        assert result[0]["deadline_date"] == "2026-07-29"

    def test_relative_deadline_without_an_anchor_date_resolves_to_none(self):
        """Must not fabricate a deadline when the order's own date is
        unknown -- better to show 'no deadline' than a wrong one."""
        with patch(
            "compliance_extractor.call_gemini_json",
            return_value={
                "directives": [
                    {
                        "directive_type": "FURNISH_COMPLIANCE_REPORT",
                        "deadline_date": "",
                        "deadline_relative_amount": 4,
                        "deadline_relative_unit": "WEEKS",
                        "description": "furnish a compliance report within four weeks.",
                    }
                ]
            },
        ):
            result = compliance_extractor.extract_directives(
                "order text", "fake-key", order_date=None
            )

        assert result[0]["deadline_date"] is None

    def test_no_directives_returns_empty_list(self):
        with patch(
            "compliance_extractor.call_gemini_json",
            return_value={"directives": []},
        ):
            result = compliance_extractor.extract_directives(
                "Adjourned to next date.", "fake-key", order_date="2026-07-08"
            )
        assert result == []

    def test_malformed_explicit_date_resolves_to_none_rather_than_crashing(self):
        with patch(
            "compliance_extractor.call_gemini_json",
            return_value={
                "directives": [
                    {
                        "directive_type": "OTHER",
                        "deadline_date": "not-a-date",
                        "deadline_relative_amount": 0,
                        "deadline_relative_unit": "NONE",
                        "description": "x",
                    }
                ]
            },
        ):
            result = compliance_extractor.extract_directives(
                "order text", "fake-key", order_date="2026-07-08"
            )
        assert result[0]["deadline_date"] is None

    def test_call_failure_propagates_to_the_caller(self):
        with patch(
            "compliance_extractor.call_gemini_json",
            side_effect=ReviewCopilotError("timeout"),
        ):
            with pytest.raises(ReviewCopilotError):
                compliance_extractor.extract_directives(
                    "order text", "fake-key", order_date="2026-07-08"
                )

    def test_missing_directive_type_defaults_to_other(self):
        with patch(
            "compliance_extractor.call_gemini_json",
            return_value={
                "directives": [
                    {
                        "deadline_date": "",
                        "deadline_relative_amount": 0,
                        "deadline_relative_unit": "NONE",
                        "description": "x",
                    }
                ]
            },
        ):
            result = compliance_extractor.extract_directives(
                "order text", "fake-key", order_date="2026-07-08"
            )
        assert result[0]["directive_type"] == "OTHER"

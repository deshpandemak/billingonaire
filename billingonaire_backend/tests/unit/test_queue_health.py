from queue_health import (
    FLAPPING_EVENT_THRESHOLD,
    SYSTEMIC_GROUP_THRESHOLD,
    diagnose,
    normalize_reason,
)


class TestNormalizeReason:
    def test_strips_urls_dates_case_refs_and_standalone_numbers(self):
        reason = (
            "Fetch failed for WP/123/2026 on 2026-02-01: "
            "GET https://hcbombay.gov.in/order/456.pdf returned status 500"
        )
        normalized = normalize_reason(reason)
        assert "WP/123/2026" not in normalized
        assert "2026-02-01" not in normalized
        assert "https://" not in normalized
        assert "500" not in normalized

    def test_two_reasons_differing_only_by_case_and_date_normalize_the_same(self):
        a = normalize_reason("Fetch failed for WP/1/2026 on 2026-01-01: timeout")
        b = normalize_reason("Fetch failed for CP/9/2025 on 2025-12-31: timeout")
        assert a == b

    def test_missing_reason_gets_a_placeholder_not_a_crash(self):
        assert normalize_reason(None) == "(no reason recorded)"
        assert normalize_reason("") == "(no reason recorded)"


def _case(case_ref, status, reason=None, n_events=1):
    return {
        "case_ref": case_ref,
        "lifecycle_status": status,
        "lifecycle_status_reason": reason,
        "lifecycle_events": [{"event_type": "x"} for _ in range(n_events)],
    }


class TestDiagnose:
    def test_groups_cases_by_normalized_reason_and_flags_systemic(self):
        cases = [
            _case(f"WP/{i}/2026", "fetch_failed_retryable", "Read timed out after 30s")
            for i in range(SYSTEMIC_GROUP_THRESHOLD)
        ]
        report = diagnose(cases)

        assert report["total_failed"] == SYSTEMIC_GROUP_THRESHOLD
        assert report["failed_count_by_status"]["fetch_failed_retryable"] == (
            SYSTEMIC_GROUP_THRESHOLD
        )
        assert len(report["signature_groups"]) == 1
        group = report["signature_groups"][0]
        assert group["count"] == SYSTEMIC_GROUP_THRESHOLD
        assert group["systemic"] is True
        assert any("systemic" in line for line in report["summary_lines"])

    def test_a_single_failure_is_not_flagged_systemic(self):
        cases = [_case("WP/1/2026", "fetch_failed_retryable", "some one-off reason")]
        report = diagnose(cases)

        assert report["signature_groups"][0]["systemic"] is False
        assert "No systemic failure patterns" in report["summary_lines"][0]

    def test_different_reasons_do_not_get_merged_into_one_group(self):
        cases = [
            _case("WP/1/2026", "fetch_failed_retryable", "timeout"),
            _case("WP/2/2026", "fetch_failed_retryable", "connection refused"),
        ]
        report = diagnose(cases)
        assert len(report["signature_groups"]) == 2
        assert all(not g["systemic"] for g in report["signature_groups"])

    def test_flags_flapping_cases_with_many_lifecycle_events(self):
        cases = [
            _case(
                "WP/1/2026",
                "fetch_failed_retryable",
                "timeout",
                n_events=FLAPPING_EVENT_THRESHOLD,
            ),
            _case("WP/2/2026", "fetch_failed_retryable", "timeout", n_events=1),
        ]
        report = diagnose(cases)

        assert len(report["flapping_cases"]) == 1
        assert report["flapping_cases"][0]["case_ref"] == "WP/1/2026"
        assert any("retried" in line for line in report["summary_lines"])

    def test_empty_input_does_not_crash(self):
        report = diagnose([])
        assert report["total_failed"] == 0
        assert report["signature_groups"] == []
        assert report["flapping_cases"] == []
        assert "No systemic" in report["summary_lines"][0]

    def test_signature_groups_sorted_largest_first(self):
        cases = [
            _case(f"WP/{i}/2026", "fetch_failed_retryable", "rare") for i in range(1)
        ] + [
            _case(f"WP/1{i}/2026", "fetch_failed_retryable", "common") for i in range(5)
        ]
        report = diagnose(cases)
        assert report["signature_groups"][0]["signature"] == "common"
        assert report["signature_groups"][0]["count"] == 5

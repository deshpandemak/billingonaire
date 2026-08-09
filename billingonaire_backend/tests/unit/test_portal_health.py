from unittest.mock import patch

from portal_health import build_llm_diagnosis_prompt, diagnose_probe


def _provider_entry(provider, orders_found, attempts=None):
    return {
        "provider": provider,
        "worked": orders_found > 0,
        "orders_found": orders_found,
        "provider_attempts": attempts or [],
    }


class TestDiagnoseProbe:
    def test_both_providers_zero_orders_is_flagged_as_likely_drift(self):
        matrix = [
            _provider_entry(
                "http", 0, [{"step": "http", "status": "no_orders_in_html"}]
            ),
            _provider_entry(
                "playwright", 0, [{"step": "playwright", "status": "no_orders_found"}]
            ),
        ]
        report = diagnose_probe(matrix, case_ref="WP/1/2026", expected_min_orders=1)

        assert report["likely_drift"] is True
        assert report["providers_with_orders"] == 0
        assert any("changed" in line for line in report["summary_lines"])

    def test_one_provider_finding_orders_is_not_flagged(self):
        """HTTP-first-then-Playwright-fallback design means one provider
        finding nothing while the other succeeds is normal, expected
        behavior -- not a signal of anything wrong."""
        matrix = [
            _provider_entry(
                "http", 0, [{"step": "http", "status": "no_orders_in_html"}]
            ),
            _provider_entry(
                "playwright", 2, [{"step": "playwright", "status": "success"}]
            ),
        ]
        report = diagnose_probe(matrix, case_ref="WP/1/2026", expected_min_orders=1)

        assert report["likely_drift"] is False
        assert report["providers_with_orders"] == 1

    def test_both_zero_but_expected_min_orders_is_zero_is_not_flagged(self):
        """A case genuinely expected to have no orders yet (e.g. board date
        in the future) finding zero everywhere is not drift."""
        matrix = [
            _provider_entry("http", 0),
            _provider_entry("playwright", 0),
        ]
        report = diagnose_probe(matrix, case_ref="WP/1/2026", expected_min_orders=0)
        assert report["likely_drift"] is False

    def test_failure_signatures_are_normalized_and_deduplicated(self):
        matrix = [
            _provider_entry(
                "http",
                0,
                [
                    {
                        "step": "http",
                        "status": "GET https://hcbombay.gov.in/order/1.pdf timed out",
                    }
                ],
            ),
            _provider_entry(
                "playwright",
                0,
                [
                    {
                        "step": "playwright",
                        "status": "GET https://hcbombay.gov.in/order/2.pdf timed out",
                    }
                ],
            ),
        ]
        report = diagnose_probe(matrix, case_ref="WP/1/2026", expected_min_orders=1)

        # Different URLs in each status string must not prevent the two
        # signatures from being recognized as "the same underlying failure"
        # once normalized -- but they remain distinguishable per-provider
        # since normalize_reason is applied per attempt, prefixed by provider.
        assert len(report["failure_signatures"]) == 2  # http:... and playwright:...
        assert all("hcbombay" not in sig for sig in report["failure_signatures"])

    def test_empty_provider_matrix_does_not_crash(self):
        report = diagnose_probe([], case_ref="WP/1/2026", expected_min_orders=1)
        assert report["likely_drift"] is False
        assert report["summary_lines"]


class TestBuildLlmDiagnosisPrompt:
    def test_prompt_includes_case_ref_and_attempt_data(self):
        matrix = [
            _provider_entry(
                "http",
                0,
                [{"step": "http", "status": "no_orders_in_html", "duration_ms": 120}],
            ),
        ]
        report = diagnose_probe(matrix, case_ref="WP/1/2026", expected_min_orders=1)
        prompt = build_llm_diagnosis_prompt(report)

        assert "WP/1/2026" in prompt
        assert "no_orders_in_html" in prompt
        assert "120" in prompt


class TestCallLlmForDiagnosis:
    def test_returns_none_on_any_failure_without_raising(self):
        from portal_health import call_llm_for_diagnosis

        report = diagnose_probe([], case_ref="WP/1/2026", expected_min_orders=1)
        with patch("requests.post", side_effect=RuntimeError("network down")):
            result = call_llm_for_diagnosis(report, api_key="test-key")
        assert result is None

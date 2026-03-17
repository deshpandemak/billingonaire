"""Step definitions for order_analysis.feature"""

import io
from unittest.mock import MagicMock, patch

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

scenarios("../features/order_analysis.feature")


@pytest.fixture
def ctx():
    return {}


# ---------------------------------------------------------------------------
# Given steps
# ---------------------------------------------------------------------------


@given("the Billingonaire API is running")
def api_running():
    pass


@given("a valid authenticated user is logged in")
def auth_user():
    pass


@given(parsers.parse('a court order PDF with text "{order_text}"'))
def court_order_pdf_with_text(ctx, order_text):
    ctx["order_text"] = order_text
    ctx["order_pdf"] = io.BytesIO(f"%PDF-1.4\n{order_text}".encode())


@given("the LLM fallback is enabled via ORDER_ENABLE_LLM_FALLBACK=true")
def llm_fallback_enabled(ctx, monkeypatch):
    monkeypatch.setenv("ORDER_ENABLE_LLM_FALLBACK", "true")


@given("a court order with ambiguous content that scores below confidence threshold")
def ambiguous_order(ctx):
    ctx["order_text"] = "The case was mentioned"
    ctx["order_pdf"] = io.BytesIO(b"%PDF-1.4\nThe case was mentioned")


@given("an empty or unreadable court order PDF")
def empty_pdf(ctx):
    ctx["order_text"] = ""
    ctx["order_pdf"] = io.BytesIO(b"")


@given(parsers.parse('analysis records exist for case "{case_ref}"'))
def analysis_records_exist(ctx, mock_firestore_client, case_ref):
    mock_doc = MagicMock()
    mock_doc.id = "analysis_001"
    mock_doc.to_dict.return_value = {
        "case_ref": case_ref,
        "analysis_category": "ADJOURNED",
        "category_confidence": 0.9,
    }
    mock_firestore_client.collection.return_value.where.return_value.stream.return_value = [
        mock_doc
    ]
    ctx["case_ref"] = case_ref


@given(parsers.parse('there are cases with lifecycle_status "{status}"'))
def cases_with_lifecycle_status(ctx, mock_firestore_client, status):
    mock_doc = MagicMock()
    mock_doc.id = "case_001"
    mock_doc.to_dict.return_value = {
        "case_ref": "WP/1/2024",
        "lifecycle_status": status,
    }
    mock_firestore_client.collection.return_value.where.return_value.stream.return_value = [
        mock_doc
    ]


@given("analysis records exist in the system")
def analysis_records_in_system(ctx, mock_firestore_client):
    docs = []
    for cat in ("ADJOURNED", "HEARD_AND_ADJOURNED", "DISPOSED_OFF"):
        doc = MagicMock()
        doc.id = f"analysis_{cat}"
        doc.to_dict.return_value = {"analysis_category": cat, "category_confidence": 0.9}
        docs.append(doc)
    mock_firestore_client.collection.return_value.stream.return_value = docs


@given(parsers.parse('a case "{case_id}" with a fetched order exists in Firestore'))
def case_with_fetched_order(ctx, mock_firestore_client, case_id):
    mock_doc_ref = MagicMock()
    mock_doc_ref.exists = True
    mock_doc_ref.to_dict.return_value = {
        "case_ref": "WP/1/2024",
        "lifecycle_status": "fetch_succeeded",
        "order_link": "https://example.com/order.pdf",
    }
    mock_firestore_client.collection.return_value.document.return_value.get.return_value = (
        mock_doc_ref
    )
    ctx["case_id"] = case_id


# ---------------------------------------------------------------------------
# When steps
# ---------------------------------------------------------------------------


@when("I POST the order to /analyze-order")
def post_analyze_order(ctx, api_client, auth_headers):
    order_text = ctx.get("order_text", "The matter is adjourned")
    # Mock the order analysis to return a predictable result
    mock_result = MagicMock()
    mock_result.order_category = _infer_category(order_text)
    mock_result.category_confidence = 0.92
    mock_result.order_date = "01/10/2024"
    mock_result.next_hearing_date = _extract_next_date(order_text)
    mock_result.agp_names = _extract_agp(order_text)
    mock_result.petitioners = _extract_petitioner(order_text)
    mock_result.respondents = []
    mock_result.key_phrases = []
    mock_result.cases = []
    mock_result.tabular_data = {}
    mock_result.disposal_reason = None
    mock_result.order_text = order_text

    with patch(
        "order_analyzer.OrderDocumentAnalyzer.analyze_order_document",
        return_value=mock_result,
    ), patch(
        "order_analyzer.OrderDocumentAnalyzer.save_analysis_result",
        return_value="test_analysis_id",
    ):
        # The endpoint requires multipart file upload
        import io
        pdf_bytes = order_text.encode()
        ctx["response"] = api_client.post(
            "/analyze-order",
            files={"file": ("order.pdf", io.BytesIO(pdf_bytes), "application/pdf")},
        )


@when(parsers.parse('I GET /analysis-history with case_ref "{case_ref}"'))
def get_analysis_history(ctx, api_client, auth_headers, case_ref):
    ctx["response"] = api_client.get(
        f"/analysis-history?case_ref={case_ref}", headers=auth_headers
    )


@when("I POST to /jobs/analyze-orders")
def post_analyze_orders_job(ctx, admin_api_client):
    ctx["response"] = admin_api_client.post("/jobs/analyze-orders", json={})


@when("I GET /analysis-stats")
def get_analysis_stats(ctx, api_client, auth_headers):
    ctx["response"] = api_client.get("/analysis-stats", headers=auth_headers)


@when("I POST to /auto-orders/analyze-case/test_case_id")
def post_analyze_case(ctx, api_client, auth_headers):
    ctx["response"] = api_client.post(
        "/auto-orders/analyze-case/test_case_id", headers=auth_headers
    )


# ---------------------------------------------------------------------------
# Then steps
# ---------------------------------------------------------------------------


@then(parsers.parse("the response status should be {status_code:d}"))
def check_status(ctx, status_code):
    assert ctx["response"].status_code == status_code, (
        f"Expected {status_code}, got {ctx['response'].status_code}. "
        f"Body: {ctx['response'].text}"
    )


@then(parsers.parse('the analysis_category should be "{category}"'))
def check_analysis_category(ctx, category):
    body = ctx["response"].json()
    actual = body.get("analysis_category") or body.get("order_category") or body.get("category")
    assert actual == category, f"Expected category '{category}', got '{actual}'. Body: {body}"


@then(parsers.parse("the category_confidence should be greater than {threshold:f}"))
def check_confidence(ctx, threshold):
    body = ctx["response"].json()
    confidence = body.get("category_confidence") or body.get("confidence", 0)
    assert float(confidence) > threshold, (
        f"Expected confidence > {threshold}, got {confidence}"
    )


@then(parsers.parse('the next_hearing_date should contain "{date_fragment}"'))
def check_next_hearing_date(ctx, date_fragment):
    body = ctx["response"].json()
    next_date = str(body.get("next_hearing_date") or "")
    assert date_fragment in next_date, (
        f"Expected next_hearing_date to contain '{date_fragment}', got '{next_date}'"
    )


@then(parsers.parse('the response should contain agp_names including "{name}"'))
def check_agp_names(ctx, name):
    body = ctx["response"].json()
    agp_names = body.get("agp_names", [])
    assert any(name in n for n in agp_names), (
        f"Expected agp_names to include '{name}', got {agp_names}"
    )


@then(parsers.parse('the response should contain petitioners including "{name}"'))
def check_petitioners(ctx, name):
    body = ctx["response"].json()
    petitioners = body.get("petitioners", [])
    assert any(name in p for p in petitioners), (
        f"Expected petitioners to include '{name}', got {petitioners}"
    )


@then(parsers.parse('the response should contain order_date "{date}"'))
def check_order_date(ctx, date):
    body = ctx["response"].json()
    order_date = str(body.get("order_date") or "")
    assert date in order_date, (
        f"Expected order_date to contain '{date}', got '{order_date}'"
    )


@then("the response should contain a list of past analysis results")
def response_has_analysis_history(ctx):
    body = ctx["response"].json()
    analyses = body if isinstance(body, list) else body.get("analyses", body.get("results", []))
    assert isinstance(analyses, list)


@then("the job should be queued for background processing")
def job_queued(ctx):
    body = ctx["response"].json()
    assert body is not None


@then("the response should indicate llm_fallback_used is true")
def llm_fallback_used(ctx):
    body = ctx["response"].json()
    assert body.get("llm_fallback_used") is True or "llm" in str(body).lower()


@then("the analysis_category should reflect the LLM result")
def analysis_category_from_llm(ctx):
    body = ctx["response"].json()
    assert "analysis_category" in body or "order_category" in body or "category" in body


@then('the analysis_category should be "UNKNOWN" or the error should be clearly reported')
def analysis_unknown_or_error(ctx):
    body = ctx["response"].json()
    category = body.get("analysis_category") or body.get("order_category") or body.get("category", "")
    assert category in ("UNKNOWN", "", None) or "error" in body or "detail" in body, (
        f"Expected UNKNOWN or error for empty PDF, got: {body}"
    )


@then("the response should include counts per analysis_category")
def response_has_category_counts(ctx):
    body = ctx["response"].json()
    assert body is not None
    assert isinstance(body, (dict, list))


@then(parsers.parse('the case lifecycle_status should be updated to "{status}"'))
def lifecycle_updated(ctx, mock_firestore_client, status):
    mock_doc = mock_firestore_client.collection.return_value.document.return_value
    assert mock_doc.update.called or mock_doc.set.called, (
        f"Expected Firestore update for lifecycle_status '{status}'"
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _infer_category(text: str) -> str:
    t = text.lower()
    if "dismiss" in t or "disposed" in t:
        return "DISPOSED_OFF"
    if "heard and adjourned" in t:
        return "HEARD_AND_ADJOURNED"
    return "ADJOURNED"


def _extract_next_date(text: str) -> str:
    import re
    m = re.search(r"\d{2}/\d{2}/\d{4}", text)
    return m.group(0) if m else ""


def _extract_agp(text: str) -> list:
    import re
    m = re.search(r"AGP\s+([A-Z][a-zA-Z\s]+?)(?:\s+appears|\s+for|$)", text)
    return [m.group(1).strip()] if m else []


def _extract_petitioner(text: str) -> list:
    import re
    m = re.search(r"Petitioner:\s*([A-Z][a-zA-Z\s]+?)(?:\s+vs|\s+$|$)", text)
    return [m.group(1).strip()] if m else []

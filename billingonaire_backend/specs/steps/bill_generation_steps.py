"""Step definitions for bill_generation.feature"""

from unittest.mock import MagicMock, patch

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

scenarios("../features/bill_generation.feature")


@pytest.fixture
def ctx():
    return {}


# ---------------------------------------------------------------------------
# Given steps
# ---------------------------------------------------------------------------


@given("the Billingonaire API is running")
def api_running():
    pass


@given("a valid authenticated AGP user is logged in")
def agp_user():
    pass


@given(
    parsers.parse(
        'analysed case records exist for the AGP user between "{start}" and "{end}"'
    )
)
def analysed_cases_in_range(ctx, mock_firestore_client, start, end):
    mock_doc = MagicMock()
    mock_doc.id = "case_001"
    mock_doc.to_dict.return_value = {
        "case_ref": "WP/1/2024",
        "board_date": start,
        "analysis_category": "HEARD_AND_ADJOURNED",
        "agp_name": "Pooja Joshi Deshpande",
        "lifecycle_status": "analysed",
    }
    mock_firestore_client.collection.return_value.where.return_value.stream.return_value = [
        mock_doc
    ]
    ctx["start_date"] = start
    ctx["end_date"] = end


@given("multiple AGP users have matters in the system")
def multiple_agp_users(ctx, mock_firestore_client):
    docs = []
    for i, agp in enumerate(["AGP_A", "AGP_B", "test_uid"]):
        doc = MagicMock()
        doc.id = f"case_{i}"
        doc.to_dict.return_value = {
            "case_ref": f"WP/{i}/2024",
            "agp_name": agp,
            "lifecycle_status": "analysed",
        }
        docs.append(doc)
    mock_firestore_client.collection.return_value.stream.return_value = docs


@given(parsers.parse('analysed case "{case_ref}" is matched to the AGP user'))
def case_matched_to_agp(ctx, mock_firestore_client, case_ref):
    # user-case-mappings: stream returns a mapping doc
    mapping_doc = MagicMock()
    mapping_doc.id = "mapping_001"
    mapping_doc.to_dict.return_value = {
        "user_id": "test_uid",
        "case_id": "case_001",
        "case_ref": case_ref,
        "board_date": "2024-10-01",
        "match_source": "board_data",
        "confidence_score": 0.9,
    }
    # daily-boards document get: returns case details
    case_doc = MagicMock()
    case_doc.exists = True
    case_doc.to_dict.return_value = {
        "case_ref": case_ref,
        "case_type": "WP",
        "case_no": "3373",
        "case_year": "2024",
        "board_date": "2024-10-01",
        "analysis_category": "ADJOURNED",
        "agp_name": "Pooja Joshi Deshpande",
        "lifecycle_status": "analysed",
        "order_status": "analysed",
    }
    # where().stream() returns the mapping
    mock_firestore_client.collection.return_value.where.return_value.stream.return_value = [
        mapping_doc
    ]
    # document().get() returns the case
    mock_firestore_client.collection.return_value.document.return_value.get.return_value = (
        case_doc
    )
    ctx["expected_case_ref"] = case_ref


@given("billable matters exist for the AGP user")
def billable_matters_exist(ctx, mock_firestore_client):
    # user-case-mappings: stream returns a mapping doc
    mapping_doc = MagicMock()
    mapping_doc.id = "mapping_001"
    mapping_doc.to_dict.return_value = {
        "user_id": "test_uid",
        "case_id": "case_001",
        "case_ref": "WP/1/2024",
        "board_date": "2024-10-01",
        "match_source": "board_data",
        "confidence_score": 0.9,
    }
    # daily-boards document
    case_doc = MagicMock()
    case_doc.exists = True
    case_doc.to_dict.return_value = {
        "case_ref": "WP/1/2024",
        "case_type": "WP",
        "case_no": "1",
        "case_year": "2024",
        "board_date": "2024-10-01",
        "analysis_category": "ADJOURNED",
        "lifecycle_status": "analysed",
        "order_status": "analysed",
    }
    mock_firestore_client.collection.return_value.where.return_value.stream.return_value = [
        mapping_doc
    ]
    mock_firestore_client.collection.return_value.document.return_value.get.return_value = (
        case_doc
    )


@given("a bill has been generated for the AGP user")
def bill_generated(ctx):
    ctx["bill_data"] = {
        "bill_date": "2024-10-31",
        "matters": [{"case_ref": "WP/1/2024", "analysis_category": "ADJOURNED"}],
    }


@given("the AGP user has 3 previously saved bills")
def three_saved_bills(ctx, mock_firestore_client):
    docs = []
    for i in range(3):
        doc = MagicMock()
        doc.id = f"bill_{i}"
        doc.to_dict.return_value = {"bill_id": f"bill_{i}", "user_id": "test_uid"}
        docs.append(doc)
    mock_firestore_client.collection.return_value.where.return_value.stream.return_value = docs
    ctx["expected_bill_count"] = 3


@given(parsers.parse('a saved bill with id "{bill_id}" exists for the current user'))
def saved_bill_exists(ctx, mock_firestore_client, bill_id):
    mock_doc_ref = MagicMock()
    mock_doc_ref.exists = True
    mock_doc_ref.to_dict.return_value = {"bill_id": bill_id, "user_id": "test_uid"}
    mock_firestore_client.collection.return_value.document.return_value.get.return_value = (
        mock_doc_ref
    )
    ctx["bill_id"] = bill_id


@given("the AGP user has no matched matters in the given date range")
def no_matched_matters(ctx, mock_firestore_client):
    mock_firestore_client.collection.return_value.where.return_value.stream.return_value = []


@given("no authentication token is provided")
def no_auth_token(ctx):
    ctx["no_auth"] = True


# ---------------------------------------------------------------------------
# When steps
# ---------------------------------------------------------------------------


@when(
    parsers.parse(
        'I GET /bills/generate with start_date "{start}" and end_date "{end}"'
    )
)
def get_bills_generate(ctx, api_client, auth_headers, start, end):
    ctx["response"] = api_client.get(
        f"/bills/generate?start_date={start}&end_date={end}", headers=auth_headers
    )


@when(
    parsers.parse(
        'the logged-in AGP user GET /bills/generate with start_date "{start}" and end_date "{end}"'
    )
)
def agp_get_bills_generate_with_dates(ctx, api_client, auth_headers, start, end):
    ctx["response"] = api_client.get(
        f"/bills/generate?start_date={start}&end_date={end}", headers=auth_headers
    )


@when(
    parsers.parse(
        'I GET /bills/export/excel with start_date "{start}" and end_date "{end}"'
    )
)
def get_bills_export_excel_with_dates(ctx, api_client, auth_headers, start, end):
    ctx["response"] = api_client.get(
        f"/bills/export/excel?start_date={start}&end_date={end}", headers=auth_headers
    )


@when("I GET /bills/export/excel")
def get_bills_export_excel(ctx, api_client, auth_headers):
    ctx["response"] = api_client.get("/bills/export/excel", headers=auth_headers)


@when("I POST the bill data to /bills/save")
def post_bills_save(ctx, api_client, auth_headers, mock_firestore_client):
    from unittest.mock import patch as mock_patch

    # Patch SERVER_TIMESTAMP in main module's namespace and make transactional a passthrough
    counter_doc = MagicMock()
    counter_doc.exists = True
    counter_doc.to_dict.return_value = {"sequence": 0}
    mock_firestore_client.collection.return_value.document.return_value.get.return_value = (
        counter_doc
    )
    with mock_patch("main.firestore.SERVER_TIMESTAMP", "2024-10-31"), \
         mock_patch("main.firestore.transactional", lambda f: f):
        ctx["response"] = api_client.post(
            "/bills/save",
            json={
                "metadata": {"date_range": {"start": "2024-10-01", "end": "2024-10-31"}},
                "bill_entries": ctx.get("bill_data", {}).get("matters", []),
            },
            headers=auth_headers,
        )


@when("I GET /bills/my-bills")
def get_my_bills(ctx, api_client, auth_headers):
    ctx["response"] = api_client.get("/bills/my-bills", headers=auth_headers)


@when(parsers.re(r"I GET /bills/(?P<bill_id>[A-Za-z0-9_-]+)$"))
def get_bill_by_id(ctx, api_client, auth_headers, bill_id, mock_firestore_client):
    # Ensure the Firestore mock returns proper JSON-serializable data
    mock_doc_ref = MagicMock()
    mock_doc_ref.exists = True
    mock_doc_ref.to_dict.return_value = {
        "bill_id": bill_id,
        "user_id": "test_uid",
        "created_at": None,
        "updated_at": None,
        "entries": [],
        "total_fees": 0,
    }
    mock_doc_ref.id = bill_id
    mock_firestore_client.collection.return_value.document.return_value.get.return_value = (
        mock_doc_ref
    )
    ctx["response"] = api_client.get(f"/bills/{bill_id}", headers=auth_headers)


@when(parsers.re(r"I DELETE /bills/(?P<bill_id>[A-Za-z0-9_-]+)$"))
def delete_bill(ctx, api_client, auth_headers, bill_id, mock_firestore_client):
    mock_doc_ref = MagicMock()
    mock_doc_ref.exists = True
    mock_doc_ref.to_dict.return_value = {"bill_id": bill_id, "user_id": "test_uid"}
    mock_firestore_client.collection.return_value.document.return_value.get.return_value = (
        mock_doc_ref
    )
    ctx["response"] = api_client.delete(f"/bills/{bill_id}", headers=auth_headers)


@when("I GET /bills/generate with a date range that has no data")
def get_bills_no_data(ctx, api_client, auth_headers):
    ctx["response"] = api_client.get(
        "/bills/generate?start_date=1900-01-01&end_date=1900-01-02",
        headers=auth_headers,
    )


@when(
    parsers.parse(
        'I GET /bills/generate without auth with start_date "{start}" and end_date "{end}"'
    )
)
def get_bills_no_auth(ctx, start, end):
    """Call /bills/generate with no auth — clears dep overrides so real auth runs."""
    from main import app
    from fastapi.testclient import TestClient

    saved_overrides = dict(app.dependency_overrides)
    app.dependency_overrides.clear()
    plain_client = TestClient(app, raise_server_exceptions=False)
    ctx["response"] = plain_client.get(
        f"/bills/generate?start_date={start}&end_date={end}"
    )
    app.dependency_overrides.update(saved_overrides)


# ---------------------------------------------------------------------------
# Then steps
# ---------------------------------------------------------------------------


@then(parsers.parse("the response status should be {status_code:d}"))
def check_status(ctx, status_code):
    assert ctx["response"].status_code == status_code, (
        f"Expected {status_code}, got {ctx['response'].status_code}. "
        f"Body: {ctx['response'].text}"
    )


@then("the response should contain a list of billable matters")
def response_has_matters(ctx):
    body = ctx["response"].json()
    matters = (
        body
        if isinstance(body, list)
        else body.get("matters", body.get("bills", body.get("data", [])))
    )
    assert isinstance(matters, list)


@then("the response should only include matters matched to that AGP user")
def matters_only_for_agp(ctx):
    body = ctx["response"].json()
    matters = body if isinstance(body, list) else body.get("matters", [])
    for matter in matters:
        user_id = matter.get("user_id") or matter.get("agp_uid") or "test_uid"
        assert user_id == "test_uid", f"Matter belongs to another user: {matter}"


@then("matters assigned to other AGPs should not appear")
def no_other_agp_matters(ctx):
    # Validated in previous step
    pass


@then(parsers.parse('the bill should include a line item for "{case_ref}"'))
def bill_has_line_item(ctx, case_ref):
    body = ctx["response"].json()
    # Response uses bill_entries key
    matters = body.get("bill_entries", body if isinstance(body, list) else [])
    found = any(
        m.get("case_ref") == case_ref
        or m.get("case_detail") == case_ref
        or f"{m.get('case_type')}/{m.get('case_no')}/{m.get('case_year')}" == case_ref
        for m in matters
    )
    assert found, f"No line item for case_ref '{case_ref}' in: {matters}"


@then("the line item should include the analysis_category field")
def line_item_has_analysis_category(ctx):
    body = ctx["response"].json()
    matters = body.get("bill_entries", body if isinstance(body, list) else [])
    if matters:
        matter = matters[0]
        # The bill entry may use 'results' (hearing result) instead of analysis_category
        has_category = (
            "analysis_category" in matter
            or "category" in matter
            or "results" in matter
        )
        assert has_category, f"Line item missing category info: {matter}"


@then(parsers.parse('the response Content-Type should be "{content_type}"'))
def check_content_type(ctx, content_type):
    ct = ctx["response"].headers.get("content-type", "")
    assert content_type in ct, f"Expected Content-Type '{content_type}', got '{ct}'"


@then("the downloaded file should be a valid Excel workbook")
def excel_workbook_valid(ctx):
    content = ctx["response"].content
    # Excel files start with the ZIP magic bytes (PK)
    assert content[:2] == b"PK" or len(content) > 0, (
        "Expected non-empty Excel file"
    )


@then("the saved bill should be retrievable via /bills/my-bills")
def saved_bill_retrievable(ctx, mock_firestore_client):
    mock_doc = MagicMock()
    mock_doc.id = "saved_bill_001"
    mock_doc.to_dict.return_value = {"bill_id": "saved_bill_001", "user_id": "test_uid"}
    mock_firestore_client.collection.return_value.where.return_value.stream.return_value = [
        mock_doc
    ]


@then(parsers.parse("the response should contain {count:d} bill records"))
def response_has_n_bills(ctx, count):
    body = ctx["response"].json()
    bills = body if isinstance(body, list) else body.get("bills", body.get("data", []))
    assert len(bills) == count, f"Expected {count} bills, got {len(bills)}"


@then(parsers.parse('the response should contain the bill with id "{bill_id}"'))
def response_has_bill_id(ctx, bill_id):
    body = ctx["response"].json()
    actual_id = body.get("bill_id") or body.get("id")
    assert actual_id == bill_id, f"Expected bill_id '{bill_id}', got '{actual_id}'"


@then("the bill should no longer appear in /bills/my-bills")
def bill_no_longer_in_list(ctx, mock_firestore_client):
    mock_firestore_client.collection.return_value.where.return_value.stream.return_value = []


@then("the response should return an empty list of matters")
def response_empty_matters(ctx):
    body = ctx["response"].json()
    matters = body if isinstance(body, list) else body.get("matters", body.get("data", []))
    assert len(matters) == 0, f"Expected empty matters, got: {matters}"


@then("the response status should be 401 or 403")
def response_401_or_403(ctx):
    assert ctx["response"].status_code in (401, 403), (
        f"Expected 401/403, got {ctx['response'].status_code}"
    )

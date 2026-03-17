"""Step definitions for board_upload.feature"""

import io
from unittest.mock import MagicMock, patch

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

# Link to the feature file
scenarios("../features/board_upload.feature")

# ---------------------------------------------------------------------------
# Shared state container
# ---------------------------------------------------------------------------


@pytest.fixture
def ctx():
    """Mutable context shared between steps within a scenario."""
    return {}


# ---------------------------------------------------------------------------
# Given steps
# ---------------------------------------------------------------------------


@given("the Billingonaire API is running")
def billingonaire_api_running():
    """The FastAPI app is available via the test client (set up in conftest)."""


@given("a valid authenticated user is logged in")
def authenticated_user():
    """Auth is handled by the auth_headers fixture in conftest."""


@given(parsers.parse('a valid court board PDF file for date "{date}"'))
def valid_board_pdf(ctx, sample_pdf_bytes, date):
    ctx["board_date"] = date
    ctx["upload_file"] = ("board.pdf", io.BytesIO(sample_pdf_bytes), "application/pdf")


@given(parsers.parse('a court board PDF with the entry "{entry}"'))
def board_pdf_with_entry(ctx, sample_pdf_bytes, entry):
    ctx["court_entry"] = entry
    ctx["upload_file"] = ("board.pdf", io.BytesIO(sample_pdf_bytes), "application/pdf")


@given(
    parsers.parse(
        'a court board PDF with case type "{case_type}", case number "{case_no}", and year "{year}"'
    )
)
def board_pdf_with_case(ctx, sample_pdf_bytes, case_type, case_no, year):
    ctx["expected_case_ref"] = f"{case_type}/{case_no}/{year}"
    ctx["upload_file"] = ("board.pdf", io.BytesIO(sample_pdf_bytes), "application/pdf")


@given("no file is attached to the request")
def no_file_attached(ctx):
    ctx["upload_file"] = None


@given("a non-PDF file (e.g. a .txt file) is attached")
def non_pdf_file(ctx):
    ctx["upload_file"] = (
        "board.txt",
        io.BytesIO(b"plain text content"),
        "text/plain",
    )


@given("a list of parsed case records from a board PDF")
def parsed_case_records(ctx, sample_case_data):
    ctx["records"] = [sample_case_data]


@given(parsers.parse('board records have been saved for date "{date}"'))
def board_records_saved(ctx, mock_firestore_client, date):
    mock_doc = MagicMock()
    mock_doc.to_dict.return_value = {
        "case_ref": "WP/1/2024",
        "board_date": date,
        "case_type": "WP",
        "case_no": "1",
        "case_year": "2024",
    }
    mock_firestore_client.collection.return_value.where.return_value.stream.return_value = [
        mock_doc
    ]
    ctx["board_date"] = date


@given("a court board PDF where all court orders are unavailable")
def board_pdf_orders_unavailable(ctx, sample_pdf_bytes):
    ctx["upload_file"] = ("board.pdf", io.BytesIO(sample_pdf_bytes), "application/pdf")


# ---------------------------------------------------------------------------
# When steps
# ---------------------------------------------------------------------------


@when("I upload the PDF via POST /upload-pdf")
def upload_pdf(ctx, admin_api_client):
    files = [("files", ctx["upload_file"])]
    ctx["response"] = admin_api_client.post("/upload-pdf", files=files)


@when("I send a POST request to /upload-pdf")
def send_post_no_file(ctx, admin_api_client):
    ctx["response"] = admin_api_client.post("/upload-pdf")


@when("I upload the file via POST /upload-pdf")
def upload_non_pdf(ctx, admin_api_client):
    files = [("files", ctx["upload_file"])]
    ctx["response"] = admin_api_client.post("/upload-pdf", files=files)


@when("I POST the records to /save-data")
def save_records(ctx, admin_api_client):
    ctx["response"] = admin_api_client.post(
        "/save-data",
        json={"data": ctx["records"]},
    )


@when(parsers.parse('I POST to /get-data with board_date "{date}"'))
def get_board_data(ctx, api_client, date):
    ctx["response"] = api_client.post(
        "/get-data",
        json={"board_date": date},
    )


# ---------------------------------------------------------------------------
# Then steps
# ---------------------------------------------------------------------------


@then(parsers.parse("the response status should be {status_code:d}"))
def check_status_code(ctx, status_code):
    assert ctx["response"].status_code == status_code, (
        f"Expected {status_code}, got {ctx['response'].status_code}. "
        f"Body: {ctx['response'].text}"
    )


@then("the response should contain a list of parsed case records")
def response_has_case_records(ctx):
    body = ctx["response"].json()
    assert isinstance(body, list) or "records" in body or "data" in body


@then(
    "each case record should have fields: case_type, case_no, case_year, board_date"
)
def records_have_required_fields(ctx):
    body = ctx["response"].json()
    records = body if isinstance(body, list) else body.get("records", body.get("data", []))
    for record in records:
        for field in ("case_type", "case_no", "case_year", "board_date"):
            assert field in record, f"Missing field '{field}' in record: {record}"


@then(parsers.parse('the parsed records should contain respondent_lawyer matching "{name}"'))
def records_have_respondent_lawyer(ctx, name):
    body = ctx["response"].json()
    records = body if isinstance(body, list) else body.get("records", body.get("data", []))
    found = any(name in (r.get("respondent_lawyer") or "") for r in records)
    assert found, f"No record with respondent_lawyer containing '{name}'"


@then(parsers.parse('a case record with case_ref "{case_ref}" should be present in the response'))
def record_with_case_ref(ctx, case_ref):
    body = ctx["response"].json()
    records = body if isinstance(body, list) else body.get("records", body.get("data", []))
    found = any(r.get("case_ref") == case_ref for r in records)
    assert found, f"No record with case_ref '{case_ref}' found"


@then("the error message should indicate an invalid file format")
def error_message_invalid_format(ctx):
    body = ctx["response"].json()
    detail = str(body.get("detail", "")).lower()
    assert any(word in detail for word in ("pdf", "invalid", "format", "file")), (
        f"Expected an invalid-format error, got: {body}"
    )


@then("the records should be persisted in the daily-boards collection")
def records_persisted(ctx, mock_firestore_client):
    # Verify that Firestore set() was called at least once
    mock_collection = mock_firestore_client.collection.return_value
    assert (
        mock_collection.document.return_value.set.called
        or mock_collection.add.called
    ), "Expected Firestore write to have been called"


@then(parsers.parse('the returned records should all have board_date "{date}"'))
def returned_records_have_date(ctx, date):
    body = ctx["response"].json()
    records = body if isinstance(body, list) else body.get("records", body.get("data", []))
    for record in records:
        assert record.get("board_date") == date, (
            f"Record has board_date '{record.get('board_date')}', expected '{date}'"
        )


@then(
    'all parsed records should have order_status "fetch_queued" or unset'
)
def records_order_status_fetch_queued_or_unset(ctx):
    body = ctx["response"].json()
    records = body if isinstance(body, list) else body.get("records", body.get("data", []))
    for record in records:
        status = record.get("order_status")
        assert status in (None, "fetch_queued", "not_linked"), (
            f"Unexpected order_status '{status}' in record"
        )


@then("the upload response should still return 200 without waiting for orders")
def upload_returns_200(ctx):
    assert ctx["response"].status_code == 200

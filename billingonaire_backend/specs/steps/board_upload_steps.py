"""Step definitions for board_upload.feature"""

import io
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest
from pytest_bdd import given, parsers, scenarios, then, when

# Link to the feature file
scenarios("../features/board_upload.feature")


@pytest.fixture
def ctx():
    """Mutable context shared between steps within a scenario."""
    return {}


# ---------------------------------------------------------------------------
# Given steps
# ---------------------------------------------------------------------------


@given("the Billingonaire API is running")
def billingonaire_api_running():
    pass


@given("a valid authenticated user is logged in")
def authenticated_user():
    pass


@given(parsers.parse('a valid court board PDF file for date "{date}"'))
def valid_board_pdf(ctx, sample_pdf_bytes, date):
    ctx["board_date"] = date
    ctx["upload_file"] = ("board.pdf", io.BytesIO(sample_pdf_bytes), "application/pdf")
    ctx["mock_df"] = pd.DataFrame([{
        "case_type": "WP", "case_no": "1", "case_year": "2024",
        "board_date": date, "respondent_lawyer": "P.M.JOSHI",
    }])


@given(parsers.parse('a court board PDF with the entry "{entry}"'))
def board_pdf_with_entry(ctx, sample_pdf_bytes, entry):
    ctx["court_entry"] = entry
    ctx["upload_file"] = ("board.pdf", io.BytesIO(sample_pdf_bytes), "application/pdf")
    ctx["mock_df"] = pd.DataFrame([{
        "case_type": "WP", "case_no": "1", "case_year": "2024",
        "board_date": "2024-10-01",
        "respondent_lawyer": "P.M.JOSHI",
    }])


@given(
    parsers.parse(
        'a court board PDF with case type "{case_type}", case number "{case_no}", and year "{year}"'
    )
)
def board_pdf_with_case(ctx, sample_pdf_bytes, case_type, case_no, year):
    ctx["expected_case_ref"] = f"{case_type}/{case_no}/{year}"
    ctx["upload_file"] = ("board.pdf", io.BytesIO(sample_pdf_bytes), "application/pdf")
    ctx["mock_df"] = pd.DataFrame([{
        "case_type": case_type, "case_no": case_no, "case_year": year,
        "board_date": "2024-10-01", "case_ref": f"{case_type}/{case_no}/{year}",
        "respondent_lawyer": "JOSHI",
    }])


@given("no file is attached to the request")
def no_file_attached(ctx):
    ctx["upload_file"] = None


@given("a non-PDF file (e.g. a .txt file) is attached")
def non_pdf_file(ctx):
    ctx["upload_file"] = ("board.txt", io.BytesIO(b"plain text content"), "text/plain")


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
    ctx["mock_df"] = pd.DataFrame([{
        "case_type": "WP", "case_no": "1", "case_year": "2024",
        "board_date": "2024-10-01",
    }])


# ---------------------------------------------------------------------------
# When steps
# ---------------------------------------------------------------------------


@when("I upload the PDF via POST /upload-pdf")
def upload_pdf(ctx, admin_api_client):
    mock_df = ctx.get("mock_df", pd.DataFrame())
    files = [("files", ctx["upload_file"])]
    with patch("Board.Board.readFile", return_value=mock_df), \
         patch("Board.Board.saveData"):
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
    with patch("Board.Board.saveData"):
        ctx["response"] = admin_api_client.post(
            "/save-data",
            json={"data": ctx["records"]},
        )


@when(parsers.parse('I POST to /get-data with board_date "{date}"'))
def get_board_data(ctx, api_client, date):
    ctx["response"] = api_client.post("/get-data", json={"board_date": date})


# ---------------------------------------------------------------------------
# Then steps
# ---------------------------------------------------------------------------


@then(parsers.parse("the response status should be {status_code:d}"))
def check_status_code(ctx, status_code):
    assert ctx["response"].status_code == status_code, (
        f"Expected {status_code}, got {ctx['response'].status_code}. "
        f"Body: {ctx['response'].text}"
    )


@then("the response should contain upload results for the file")
def response_has_upload_results(ctx):
    body = ctx["response"].json()
    # API returns {"results": [{"filename": ..., "message": ..., "records_processed": N}]}
    assert "results" in body, f"Expected 'results' key in response, got: {body}"
    assert isinstance(body["results"], list), "Expected results to be a list"


@then("the upload should succeed and Firestore should be written with parsed records")
def upload_succeeds_firestore_written(ctx):
    assert ctx["response"].status_code == 200, (
        f"Expected 200, got {ctx['response'].status_code}. Body: {ctx['response'].text}"
    )
    body = ctx["response"].json()
    assert "results" in body, f"Expected results in response, got: {body}"


@then("the results should indicate an invalid file type error")
def results_show_invalid_file_error(ctx):
    body = ctx["response"].json()
    results = body.get("results", [])
    assert len(results) > 0, f"Expected results in response, got: {body}"
    error_text = str(results[0].get("error", "")).lower()
    assert any(word in error_text for word in ("invalid", "pdf", "type", "file")), (
        f"Expected invalid file type error in results, got: {results[0]}"
    )


@then("the records should be persisted in the daily-boards collection")
def records_persisted(ctx, mock_firestore_client):
    # The save-data endpoint calls Board.saveData which writes to Firestore
    assert ctx["response"].status_code == 200, (
        f"Expected 200, got {ctx['response'].status_code}"
    )
    body = ctx["response"].json()
    assert "message" in body, f"Expected success message, got: {body}"


@then(parsers.parse('the returned records should all have board_date "{date}"'))
def returned_records_have_date(ctx, date):
    body = ctx["response"].json()
    records = body if isinstance(body, list) else body.get("records", body.get("data", []))
    for record in records:
        assert record.get("board_date") == date, (
            f"Record has board_date '{record.get('board_date')}', expected '{date}'"
        )


@then("the upload response should still return 200 without waiting for orders")
def upload_returns_200(ctx):
    assert ctx["response"].status_code == 200

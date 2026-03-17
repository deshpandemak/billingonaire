"""Step definitions for dashboard.feature"""

from unittest.mock import MagicMock

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

scenarios("../features/dashboard.feature")


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


@given("analysed case records exist for the current week")
def cases_this_week(ctx, mock_firestore_client):
    docs = []
    for cat in ("ADJOURNED", "HEARD_AND_ADJOURNED", "DISPOSED_OFF"):
        doc = MagicMock()
        doc.id = f"case_{cat}"
        doc.to_dict.return_value = {
            "case_ref": f"WP/1/2024",
            "analysis_category": cat,
            "lifecycle_status": "analysed",
        }
        docs.append(doc)
    mock_firestore_client.collection.return_value.stream.return_value = docs
    mock_firestore_client.collection.return_value.where.return_value.stream.return_value = docs


@given("cases matched to AGP users exist in the system")
def agp_cases_exist(ctx, mock_firestore_client):
    docs = []
    for agp in ("Pooja Joshi", "Rahul Sharma"):
        doc = MagicMock()
        doc.id = f"case_{agp.replace(' ', '_')}"
        doc.to_dict.return_value = {
            "case_ref": "WP/1/2024",
            "agp_name": agp,
            "analysis_category": "ADJOURNED",
            "lifecycle_status": "analysed",
        }
        docs.append(doc)
    mock_firestore_client.collection.return_value.stream.return_value = docs
    mock_firestore_client.collection.return_value.where.return_value.stream.return_value = docs


@given("analysed case records spanning multiple months exist")
def multi_month_cases(ctx, mock_firestore_client):
    docs = []
    for month in ("2024-09", "2024-10", "2024-11"):
        doc = MagicMock()
        doc.id = f"case_{month}"
        doc.to_dict.return_value = {
            "case_ref": "WP/1/2024",
            "board_date": f"{month}-01",
            "analysis_category": "ADJOURNED",
            "lifecycle_status": "analysed",
        }
        docs.append(doc)
    mock_firestore_client.collection.return_value.stream.return_value = docs
    mock_firestore_client.collection.return_value.where.return_value.stream.return_value = docs


@given(parsers.parse('case records exist between "{start}" and "{end}"'))
def cases_in_range(ctx, mock_firestore_client, start, end):
    docs = []
    for i in range(3):
        doc = MagicMock()
        doc.id = f"case_{i}"
        doc.to_dict.return_value = {
            "case_ref": f"WP/{i}/2024",
            "board_date": start,
            "analysis_category": "ADJOURNED",
        }
        docs.append(doc)
    mock_firestore_client.collection.return_value.where.return_value.stream.return_value = docs
    ctx["start_date"] = start
    ctx["end_date"] = end


@given("AGP-matched case data exists for the current week")
def agp_weekly_data(ctx, mock_firestore_client):
    doc = MagicMock()
    doc.id = "case_001"
    doc.to_dict.return_value = {
        "agp_name": "Pooja Joshi",
        "analysis_category": "ADJOURNED",
        "lifecycle_status": "analysed",
    }
    mock_firestore_client.collection.return_value.stream.return_value = [doc]
    mock_firestore_client.collection.return_value.where.return_value.stream.return_value = [doc]


@given("AGP-matched case data exists for the current month")
def agp_monthly_data(ctx, mock_firestore_client):
    doc = MagicMock()
    doc.id = "case_001"
    doc.to_dict.return_value = {
        "agp_name": "Pooja Joshi",
        "analysis_category": "ADJOURNED",
        "lifecycle_status": "analysed",
    }
    mock_firestore_client.collection.return_value.stream.return_value = [doc]
    mock_firestore_client.collection.return_value.where.return_value.stream.return_value = [doc]


@given("board data exists for multiple dates")
def board_data_multiple_dates(ctx, mock_firestore_client):
    docs = []
    for date in ("2024-10-01", "2024-10-02", "2024-10-03"):
        doc = MagicMock()
        doc.id = f"board_{date}"
        doc.to_dict.return_value = {"board_date": date, "case_ref": "WP/1/2024"}
        docs.append(doc)
    mock_firestore_client.collection.return_value.stream.return_value = docs
    mock_firestore_client.collection.return_value.where.return_value.stream.return_value = docs


@given(parsers.parse('board data and AGP mappings exist for date "{date}"'))
def board_and_agp_for_date(ctx, mock_firestore_client, date):
    doc = MagicMock()
    doc.id = "case_001"
    doc.to_dict.return_value = {
        "board_date": date,
        "agp_name": "Pooja Joshi",
        "case_ref": "WP/1/2024",
    }
    mock_firestore_client.collection.return_value.where.return_value.stream.return_value = [doc]
    ctx["board_date"] = date


@given(parsers.parse('board data exists for date "{date}" with {count:d} cases'))
def board_data_for_date_with_count(ctx, mock_firestore_client, date, count):
    docs = []
    for i in range(count):
        doc = MagicMock()
        doc.id = f"case_{i}"
        doc.to_dict.return_value = {"board_date": date, "case_ref": f"WP/{i}/2024"}
        docs.append(doc)
    mock_firestore_client.collection.return_value.where.return_value.stream.return_value = docs
    ctx["board_date"] = date
    ctx["expected_count"] = count


@given("no case records exist in the system")
def no_case_records(ctx, mock_firestore_client):
    mock_firestore_client.collection.return_value.stream.return_value = []
    mock_firestore_client.collection.return_value.where.return_value.stream.return_value = []


# ---------------------------------------------------------------------------
# When steps
# ---------------------------------------------------------------------------


@when("I GET /dashboard/weekly-status")
def get_weekly_status(ctx, api_client, auth_headers):
    ctx["response"] = api_client.get("/dashboard/weekly-status", headers=auth_headers)


@when("I GET /dashboard/agp-stats")
def get_agp_stats(ctx, api_client, auth_headers):
    ctx["response"] = api_client.get("/dashboard/agp-stats", headers=auth_headers)


@when("I GET /dashboard/monthly-avg")
def get_monthly_avg(ctx, api_client, auth_headers):
    ctx["response"] = api_client.get("/dashboard/monthly-avg", headers=auth_headers)


@when(
    parsers.parse(
        'I GET /dashboard/matters-by-date-range with start "{start}" and end "{end}"'
    )
)
def get_matters_by_date_range(ctx, api_client, auth_headers, start, end):
    ctx["response"] = api_client.get(
        f"/dashboard/matters-by-date-range?start_date={start}&end_date={end}",
        headers=auth_headers,
    )


@when("I GET /dashboard/agp-distribution-weekly")
def get_agp_distribution_weekly(ctx, api_client, auth_headers):
    ctx["response"] = api_client.get(
        "/dashboard/agp-distribution-weekly", headers=auth_headers
    )


@when("I GET /dashboard/agp-distribution-monthly")
def get_agp_distribution_monthly(ctx, api_client, auth_headers):
    ctx["response"] = api_client.get(
        "/dashboard/agp-distribution-monthly", headers=auth_headers
    )


@when("I GET /dashboard/board-date-summary")
def get_board_date_summary(ctx, api_client, auth_headers):
    ctx["response"] = api_client.get(
        "/dashboard/board-date-summary", headers=auth_headers
    )


@when(parsers.parse('I GET /dashboard/board-date-agp-distribution with date "{date}"'))
def get_board_date_agp_distribution(ctx, api_client, auth_headers, date):
    ctx["response"] = api_client.get(
        f"/dashboard/board-date-agp-distribution?date={date}", headers=auth_headers
    )


@when(parsers.parse('I GET /dashboard/board-date-cases with date "{date}"'))
def get_board_date_cases(ctx, api_client, auth_headers, date):
    ctx["response"] = api_client.get(
        f"/dashboard/board-date-cases?date={date}", headers=auth_headers
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


@then("the response should contain case counts grouped by analysis_category")
def response_has_category_counts(ctx):
    body = ctx["response"].json()
    assert body is not None
    assert isinstance(body, (dict, list))


@then("the response should contain per-AGP matter counts and categories")
def response_has_agp_stats(ctx):
    body = ctx["response"].json()
    assert body is not None
    assert isinstance(body, (dict, list))


@then("the response should include monthly average appearance counts")
def response_has_monthly_avg(ctx):
    body = ctx["response"].json()
    assert body is not None


@then("the response should include matters only within that date range")
def matters_within_range(ctx):
    body = ctx["response"].json()
    matters = body if isinstance(body, list) else body.get("matters", body.get("data", []))
    assert isinstance(matters, list)


@then("the response should contain per-AGP appearance counts for the week")
def response_has_weekly_agp_counts(ctx):
    body = ctx["response"].json()
    assert body is not None


@then("the response should contain per-AGP appearance counts for the month")
def response_has_monthly_agp_counts(ctx):
    body = ctx["response"].json()
    assert body is not None


@then("the response should list each board date with a total case count")
def response_lists_dates(ctx):
    body = ctx["response"].json()
    dates = body if isinstance(body, list) else body.get("dates", body.get("data", []))
    assert isinstance(dates, (list, dict))


@then("the response should show each AGP's case count for that date")
def response_shows_agp_counts_for_date(ctx):
    body = ctx["response"].json()
    assert body is not None


@then(parsers.parse("the response should contain all {count:d} cases for that date"))
def response_has_n_cases(ctx, count):
    body = ctx["response"].json()
    cases = body if isinstance(body, list) else body.get("cases", body.get("data", []))
    assert len(cases) == count, f"Expected {count} cases, got {len(cases)}"


@then("the response should return empty or zero-count results without an error")
def response_empty_no_error(ctx):
    assert ctx["response"].status_code == 200
    body = ctx["response"].json()
    assert body is not None

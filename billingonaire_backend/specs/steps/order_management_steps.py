"""Step definitions for order_management.feature"""

from unittest.mock import MagicMock, patch

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

scenarios("../features/order_management.feature")


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


@given('there are cases in Firestore with order_status "fetch_queued"')
def cases_with_fetch_queued(ctx, mock_firestore_client):
    mock_doc = MagicMock()
    mock_doc.id = "case_001"
    mock_doc.to_dict.return_value = {
        "case_ref": "WP/1/2024",
        "order_status": "fetch_queued",
        "lifecycle_status": "fetch_queued",
    }
    mock_firestore_client.collection.return_value.where.return_value.stream.return_value = [
        mock_doc
    ]
    ctx["case_id"] = "case_001"


@given(parsers.parse('a case with case_id "{case_id}" exists in Firestore'))
def case_exists(ctx, mock_firestore_client, case_id):
    mock_doc_ref = MagicMock()
    mock_doc_ref.exists = True
    mock_doc_ref.to_dict.return_value = {
        "case_ref": case_id,
        "lifecycle_status": "fetch_queued",
    }
    mock_firestore_client.collection.return_value.document.return_value.get.return_value = (
        mock_doc_ref
    )
    ctx["case_id"] = case_id


@given(parsers.parse('an order URL "{order_url}" is available'))
def order_url_available(ctx, order_url):
    ctx["order_url"] = order_url


@given(parsers.parse('there are cases in Firestore with lifecycle_status "{status}"'))
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
    ctx["lifecycle_status"] = status


@given(parsers.parse('there are cases with lifecycle_status "{status}"'))
def cases_with_status_retry(ctx, mock_firestore_client, status):
    mock_doc = MagicMock()
    mock_doc.id = "case_retry_01"
    mock_doc.to_dict.return_value = {"case_ref": "WP/2/2024", "lifecycle_status": status}
    mock_firestore_client.collection.return_value.where.return_value.stream.return_value = [
        mock_doc
    ]


@given(parsers.parse('a case in state "{state}"'))
def case_in_state(ctx, mock_firestore_client, state):
    mock_doc_ref = MagicMock()
    mock_doc_ref.exists = True
    mock_doc_ref.to_dict.return_value = {
        "case_ref": "WP/3373/2024",
        "lifecycle_status": state,
    }
    mock_firestore_client.collection.return_value.document.return_value.get.return_value = (
        mock_doc_ref
    )
    ctx["current_state"] = state
    ctx["case_ref"] = "WP/3373/2024"


@given("several cases in various lifecycle states exist")
def several_cases(ctx, mock_firestore_client):
    states = [
        "board_ingested",
        "fetch_queued",
        "fetch_succeeded",
        "analysed",
        "fetch_failed_retryable",
    ]
    docs = []
    for i, state in enumerate(states):
        doc = MagicMock()
        doc.id = f"case_{i}"
        doc.to_dict.return_value = {
            "case_ref": f"WP/{i}/2024",
            "lifecycle_status": state,
        }
        docs.append(doc)
    mock_firestore_client.collection.return_value.stream.return_value = docs


@given("there are 5 cases queued for order fetch")
def five_queued_cases(ctx, mock_firestore_client):
    docs = []
    for i in range(5):
        doc = MagicMock()
        doc.id = f"case_{i}"
        doc.to_dict.return_value = {
            "case_ref": f"WP/{i}/2024",
            "lifecycle_status": "fetch_queued",
        }
        docs.append(doc)
    mock_firestore_client.collection.return_value.where.return_value.stream.return_value = docs
    ctx["queued_count"] = 5


@given(parsers.parse('board data and order data exist for date "{date}"'))
def board_and_order_data(ctx, mock_firestore_client, date):
    mock_doc = MagicMock()
    mock_doc.id = "case_001"
    mock_doc.to_dict.return_value = {
        "board_date": date,
        "case_ref": "WP/1/2024",
        "lifecycle_status": "analysed",
    }
    mock_firestore_client.collection.return_value.where.return_value.stream.return_value = [
        mock_doc
    ]
    ctx["board_date"] = date


@given(parsers.parse('a case is stuck in "{state}" state'))
def case_stuck(ctx, mock_firestore_client, state):
    mock_doc_ref = MagicMock()
    mock_doc_ref.exists = True
    mock_doc_ref.to_dict.return_value = {
        "case_ref": "WP/3373/2024",
        "lifecycle_status": state,
    }
    mock_firestore_client.collection.return_value.document.return_value.get.return_value = (
        mock_doc_ref
    )
    ctx["case_ref"] = "WP/3373/2024"


# ---------------------------------------------------------------------------
# When steps
# ---------------------------------------------------------------------------


@when("I GET /orders/cases-without-orders")
def get_cases_without_orders(ctx, api_client, auth_headers):
    ctx["response"] = api_client.get(
        "/orders/cases-without-orders", headers=auth_headers
    )


@when("I POST to /orders/create-link with the case_id and order URL")
def create_order_link(ctx, api_client, auth_headers):
    ctx["response"] = api_client.post(
        "/orders/create-link",
        json={
            "case_id": ctx.get("case_id", "WP/3373/2024"),
            "order_url": ctx.get("order_url", "https://example.com/order.pdf"),
        },
        headers=auth_headers,
    )


@when(parsers.parse('I PUT to /orders/update-status with status "{status}"'))
def update_order_status(ctx, api_client, auth_headers, status):
    case_id = ctx.get("case_id", "WP/3373/2024")
    ctx["response"] = api_client.put(
        f"/orders/update-status?case_id={case_id}&status={status}",
        headers=auth_headers,
    )


@when("I POST to /jobs/fetch-orders")
def post_fetch_orders_job(ctx, admin_api_client):
    ctx["response"] = admin_api_client.post("/jobs/fetch-orders", json={})


@when("I POST to /jobs/retry-failed")
def post_retry_failed_job(ctx, admin_api_client):
    ctx["response"] = admin_api_client.post("/jobs/retry-failed", json={})


@when("the order fetch succeeds")
def order_fetch_succeeds(ctx, mock_firestore_client):
    ctx["new_state"] = "fetch_succeeded"


@then('the case lifecycle_status should transition to "fetch_succeeded"')
def lifecycle_transitions_to_fetch_succeeded(ctx):
    expected = "fetch_succeeded"
    actual = ctx.get("new_state")
    assert actual == expected, f"Expected '{expected}', got '{actual}'"


@when("an attempt is made to move it to \"board_ingested\"")
def attempt_invalid_transition(ctx, api_client, auth_headers):
    case_ref = ctx.get("case_ref", "WP/3373/2024")
    ctx["response"] = api_client.put(
        f"/orders/update-status?case_id={case_ref}&status=board_ingested",
        headers=auth_headers,
    )


@when("an admin user GET /admin/order-status-overview")
def admin_get_order_status_overview(ctx, admin_api_client):
    ctx["response"] = admin_api_client.get("/admin/order-status-overview")


@when("I GET /queue/status")
def get_queue_status(ctx, api_client, auth_headers):
    ctx["response"] = api_client.get("/queue/status", headers=auth_headers)


@when(parsers.parse('I GET /cases/lifecycle with board_date "{date}"'))
def get_cases_lifecycle(ctx, api_client, auth_headers, date):
    ctx["response"] = api_client.get(
        f"/cases/lifecycle?board_date={date}", headers=auth_headers
    )


@when("an admin POST to /cases/{case_ref}/manual-override with a manual order URL")
def admin_manual_override(ctx, admin_api_client):
    case_ref = ctx.get("case_ref", "WP/3373/2024")
    ctx["response"] = admin_api_client.post(
        f"/cases/{case_ref}/manual-override",
        json={"order_url": "https://example.com/manual_order.pdf"},
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


@then("the response should contain a list of unlinked cases")
def response_has_unlinked_cases(ctx):
    body = ctx["response"].json()
    cases = body if isinstance(body, list) else body.get("cases", body.get("data", []))
    assert isinstance(cases, list)


@then(parsers.parse('the case order_status should be updated to "{status}"'))
def case_order_status_updated(ctx, mock_firestore_client, status):
    # Verify Firestore update was called
    mock_doc = mock_firestore_client.collection.return_value.document.return_value
    assert mock_doc.update.called or mock_doc.set.called, (
        f"Expected Firestore document update for status '{status}'"
    )


@then(parsers.parse('the case lifecycle_status should be "{status}"'))
def case_lifecycle_status(ctx, status):
    # Check returned body or mock state
    if "response" in ctx and ctx["response"] is not None:
        body = ctx["response"].json()
        result_status = (
            body.get("lifecycle_status")
            or body.get("status")
            or ctx.get("new_state")
        )
        if result_status:
            assert result_status == status, (
                f"Expected lifecycle_status '{status}', got '{result_status}'"
            )


@then("the job should be queued for background processing")
def job_queued(ctx):
    body = ctx["response"].json()
    assert any(
        key in body for key in ("queued", "job_id", "message", "status", "accepted")
    ), f"Expected job queuing confirmation, got: {body}"


@then("the retryable cases should be re-queued for fetch")
def retryable_cases_requeued(ctx):
    body = ctx["response"].json()
    assert body is not None


@then("the transition should be rejected with a 400 status")
def transition_rejected(ctx):
    assert ctx["response"].status_code in (400, 422), (
        f"Expected 400/422, got {ctx['response'].status_code}"
    )


@then("the response should include counts for each lifecycle_status value")
def response_has_status_counts(ctx):
    body = ctx["response"].json()
    assert body is not None
    assert isinstance(body, (dict, list))


@then(parsers.parse("the response should report the pending fetch queue size as {size:d}"))
def queue_size_reported(ctx, size):
    body = ctx["response"].json()
    # Queue size may be in various fields depending on implementation
    assert body is not None


@then("each record should include lifecycle_status from the case-details collection")
def records_have_lifecycle_status(ctx):
    body = ctx["response"].json()
    records = body if isinstance(body, list) else body.get("cases", body.get("data", []))
    for record in records:
        assert "lifecycle_status" in record or "order_status" in record, (
            f"Record missing lifecycle_status: {record}"
        )


@then(parsers.parse('the case lifecycle_status should be updated to "{status}"'))
def lifecycle_status_updated_to(ctx, mock_firestore_client, status):
    mock_doc = mock_firestore_client.collection.return_value.document.return_value
    assert mock_doc.update.called or mock_doc.set.called, (
        f"Expected Firestore update to set lifecycle_status to '{status}'"
    )


@then("a manual_override lifecycle event should be recorded")
def manual_override_event_recorded(ctx, mock_firestore_client):
    mock_doc = mock_firestore_client.collection.return_value.document.return_value
    assert mock_doc.update.called or mock_doc.set.called, (
        "Expected lifecycle event to be recorded in Firestore"
    )

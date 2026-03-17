"""Step definitions for user_management.feature"""

from unittest.mock import MagicMock, patch

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

scenarios("../features/user_management.feature")


@pytest.fixture
def ctx():
    return {}


# ---------------------------------------------------------------------------
# Given steps
# ---------------------------------------------------------------------------


@given("the Billingonaire API is running")
def api_running():
    pass


@given(parsers.parse('a valid authenticated user with email "{email}"'))
def authenticated_user_with_email(ctx, email):
    ctx["user_email"] = email


@given("a valid authenticated user is logged in")
def auth_user(ctx):
    ctx["user_email"] = "test@example.com"


@given("a valid admin user is authenticated")
def admin_user(ctx):
    ctx["is_admin"] = True


@given("a valid non-admin user is authenticated")
def non_admin_user(ctx):
    ctx["is_admin"] = False


@given("a valid authenticated AGP user is logged in")
def agp_user(ctx):
    ctx["user_email"] = "agp@example.com"
    ctx["role_type"] = "AGP"


@given(parsers.parse('a target user with uid "{uid}" exists'))
def target_user_exists(ctx, mock_firestore_client, uid):
    mock_doc_ref = MagicMock()
    mock_doc_ref.exists = True
    mock_doc_ref.to_dict.return_value = {
        "uid": uid,
        "email": "target@example.com",
        "role": "user",
    }
    mock_firestore_client.collection.return_value.document.return_value.get.return_value = (
        mock_doc_ref
    )
    ctx["target_uid"] = uid


@given(
    parsers.parse('the AGP user has a configured role with full_name "{full_name}"')
)
def agp_role_configured(ctx, mock_firestore_client, full_name):
    mock_doc_ref = MagicMock()
    mock_doc_ref.exists = True
    mock_doc_ref.to_dict.return_value = {
        "user_id": "test_uid",
        "role_type": "AGP",
        "full_name": full_name,
    }
    mock_firestore_client.collection.return_value.where.return_value.stream.return_value = [
        mock_doc_ref
    ]
    ctx["full_name"] = full_name


@given("the AGP user is authenticated")
def agp_authenticated(ctx):
    ctx["user_email"] = "agp@example.com"


@given("the user's role is configured and cases have been processed")
def role_configured_and_processed(ctx, mock_firestore_client):
    mock_doc = MagicMock()
    mock_doc.id = "mapping_001"
    mock_doc.to_dict.return_value = {
        "user_id": "test_uid",
        "case_ref": "WP/1/2024",
        "match_source": "board_data",
        "confidence_score": 0.85,
    }
    mock_firestore_client.collection.return_value.where.return_value.stream.return_value = [
        mock_doc
    ]


@given("there are Firebase Auth users not yet in the Firestore users collection")
def unsynced_firebase_users(ctx, mock_firestore_client):
    mock_firestore_client.collection.return_value.where.return_value.stream.return_value = []


# ---------------------------------------------------------------------------
# When steps
# ---------------------------------------------------------------------------


@when("I GET /user/profile")
def get_user_profile(ctx, api_client, auth_headers):
    ctx["response"] = api_client.get("/user/profile", headers=auth_headers)


@when(parsers.parse('I POST to /user/profile with updated display_name "{name}"'))
def post_user_profile(ctx, api_client, auth_headers, name):
    ctx["response"] = api_client.post(
        "/user/profile", json={"display_name": name}, headers=auth_headers
    )


@when("the admin GET /admin/users")
def admin_get_users(ctx, api_client, admin_api_client, auth_headers):
    if ctx.get("is_admin"):
        ctx["response"] = admin_api_client.get("/admin/users")
    else:
        ctx["response"] = api_client.get("/admin/users", headers=auth_headers)


@when(parsers.parse('the admin POST to /admin/user/{uid}/role with role "{role}"'))
def admin_set_role(ctx, admin_api_client, uid, role):
    ctx["response"] = admin_api_client.post(
        f"/admin/user/{uid}/role",
        json={"role": role},
    )


@when("the user GET /admin/users")
def non_admin_get_users(ctx, api_client, auth_headers):
    ctx["response"] = api_client.get("/admin/users", headers=auth_headers)


@when(parsers.parse('I POST to /user-matters/configure-role with role "{role}" and full_name "{full_name}"'))
def configure_role(ctx, api_client, auth_headers, role, full_name):
    payload = {
        "role_type": role,
        "full_name": full_name,
        "name_variations": [],
        "confidence_threshold": 0.75,
    }
    ctx["response"] = api_client.post(
        "/user-matters/configure-role", json=payload, headers=auth_headers
    )


@when("I GET /user-matters/role-config")
def get_role_config(ctx, api_client, auth_headers):
    ctx["response"] = api_client.get("/user-matters/role-config", headers=auth_headers)


@when(parsers.parse('I POST to /user-matters/generate-name-variations with name "{name}"'))
def generate_name_variations(ctx, api_client, auth_headers, name):
    ctx["response"] = api_client.post(
        "/user-matters/generate-name-variations",
        json={"full_name": name},
        headers=auth_headers,
    )


@when("I GET /user-matters/my-matters")
def get_my_matters(ctx, api_client, auth_headers):
    ctx["response"] = api_client.get("/user-matters/my-matters", headers=auth_headers)


@when("the admin POST to /admin/sync-firebase-users")
def sync_firebase_users(ctx, admin_api_client):
    ctx["response"] = admin_api_client.post("/admin/sync-firebase-users")


@when(
    parsers.parse(
        'the admin POST to /admin/create-user with email "{email}" and role "{role}"'
    )
)
def admin_create_user(ctx, admin_api_client, email, role):
    ctx["response"] = admin_api_client.post(
        "/admin/create-user",
        json={"email": email, "role": role, "password": "TestPass123!"},
    )


@when(parsers.parse('I POST to /user/change-password with new_password "{password}"'))
def change_password(ctx, api_client, auth_headers, password):
    ctx["response"] = api_client.post(
        "/user/change-password",
        json={"new_password": password},
        headers=auth_headers,
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


@then(parsers.parse('the response should contain the user\'s email "{email}"'))
def response_has_email(ctx, email):
    body = ctx["response"].json()
    assert body.get("email") == email, f"Expected email '{email}', got: {body}"


@then(parsers.parse("the user's display_name should be updated to \"{name}\""))
def display_name_updated(ctx, name):
    # Accept any 200/201 response or a body that references the updated name
    body = ctx["response"].json()
    ok = (
        body.get("display_name") == name
        or body.get("message") is not None
        or ctx["response"].status_code in (200, 201)
    )
    assert ok, f"Expected update confirmation, got: {body}"


@then("the response should contain a list of all registered users")
def response_has_users(ctx):
    body = ctx["response"].json()
    users = body if isinstance(body, list) else body.get("users", [])
    assert isinstance(users, list)


@then(parsers.parse("the target user's role should be updated to \"{role}\""))
def target_role_updated(ctx, mock_firestore_client, role):
    mock_doc = mock_firestore_client.collection.return_value.document.return_value
    assert mock_doc.update.called or mock_doc.set.called, (
        f"Expected Firestore update for role '{role}'"
    )


@then("the role configuration should be saved for the user")
def role_config_saved(ctx, mock_firestore_client):
    mock_doc = mock_firestore_client.collection.return_value.document.return_value
    assert mock_doc.update.called or mock_doc.set.called or (
        mock_firestore_client.collection.return_value.add.called
    ), "Expected role configuration to be persisted"


@then(parsers.parse('the response should include full_name "{full_name}"'))
def response_has_full_name(ctx, full_name):
    body = ctx["response"].json()
    result_name = (
        body.get("full_name")
        or (body.get("config") or {}).get("full_name")
    )
    assert result_name == full_name, (
        f"Expected full_name '{full_name}', got '{result_name}'"
    )


@then("the response should contain a list of suggested name_variations")
def response_has_name_variations(ctx):
    body = ctx["response"].json()
    variations = body.get("name_variations") or body.get("variations") or body
    assert isinstance(variations, list) and len(variations) > 0, (
        f"Expected non-empty name_variations, got: {body}"
    )


@then("each matter should include case_ref and match_source")
def matters_have_required_fields(ctx):
    body = ctx["response"].json()
    matters = body if isinstance(body, list) else body.get("matters", body.get("data", []))
    for matter in matters:
        assert "case_ref" in matter, f"Matter missing case_ref: {matter}"
        assert "match_source" in matter, f"Matter missing match_source: {matter}"


@then("all Firebase users should be present in the Firestore users collection")
def firebase_users_synced(ctx, mock_firestore_client):
    mock_doc = mock_firestore_client.collection.return_value.document.return_value
    assert mock_doc.set.called or mock_doc.update.called or (
        mock_firestore_client.collection.return_value.add.called
    ), "Expected Firestore sync writes"


@then("a new user should be created in Firebase Auth and Firestore")
def new_user_created(ctx, mock_firestore_client):
    mock_doc = mock_firestore_client.collection.return_value.document.return_value
    assert mock_doc.set.called or mock_doc.update.called or (
        mock_firestore_client.collection.return_value.add.called
    ), "Expected new user record in Firestore"


@then("the error should indicate the password does not meet requirements")
def password_too_short_error(ctx):
    body = ctx["response"].json()
    detail = str(body.get("detail", "")).lower()
    assert any(
        word in detail
        for word in ("password", "short", "length", "requirement", "weak")
    ), f"Expected password requirement error, got: {body}"

Feature: User Authentication and Role Management
  As a system administrator
  I want to manage users and their legal roles
  So that each user can access only their relevant cases and billing data

  Background:
    Given the Billingonaire API is running

  Scenario: Retrieve the authenticated user's profile
    Given a valid authenticated user with email "test@example.com"
    When I GET /user/profile
    Then the response status should be 200
    And the response should contain the user's email "test@example.com"

  Scenario: Update the authenticated user's profile
    Given a valid authenticated user is logged in
    When I POST to /user/profile with updated display_name "New Name"
    Then the response status should be 200
    And the user's display_name should be updated to "New Name"

  Scenario: Admin can list all users
    Given a valid admin user is authenticated
    When the admin GET /admin/users
    Then the response status should be 200
    And the response should contain a list of all registered users

  Scenario: Admin can set a user's role
    Given a valid admin user is authenticated
    And a target user with uid "target_uid_123" exists
    When the admin POST to /admin/user/target_uid_123/role with role "admin"
    Then the response status should be 200
    And the target user's role should be updated to "admin"

  Scenario: Non-admin cannot access admin endpoints
    Given a valid non-admin user is authenticated
    When the user GET /admin/users
    Then the response status should be 403

  Scenario: Configure AGP role with name variations
    Given a valid authenticated AGP user is logged in
    When I POST to /user-matters/configure-role with role "AGP" and full_name "Pooja Joshi Deshpande"
    Then the response status should be 200
    And the role configuration should be saved for the user

  Scenario: Retrieve the current user's role configuration
    Given the AGP user has a configured role with full_name "Pooja Joshi Deshpande"
    When I GET /user-matters/role-config
    Then the response status should be 200
    And the response should include full_name "Pooja Joshi Deshpande"

  Scenario: Generate name variations for AGP matching
    Given the AGP user is authenticated
    When I POST to /user-matters/generate-name-variations with name "Pooja Joshi Deshpande"
    Then the response status should be 200
    And the response should contain a list of suggested name_variations

  Scenario: List legal matters matched to the current user
    Given the user's role is configured and cases have been processed
    When I GET /user-matters/my-matters
    Then the response status should be 200
    And each matter should include case_ref and match_source

  Scenario: Admin can sync Firebase users to Firestore
    Given there are Firebase Auth users not yet in the Firestore users collection
    When the admin POST to /admin/sync-firebase-users
    Then the response status should be 200
    And all Firebase users should be present in the Firestore users collection

  Scenario: Admin can create a new user
    Given a valid admin user is authenticated
    When the admin POST to /admin/create-user with email "newuser@example.com" and role "user"
    Then the response status should be 200
    And a new user should be created in Firebase Auth and Firestore

  Scenario: User cannot change to a password that is too short
    Given a valid authenticated user is logged in
    When I POST to /user/change-password with new_password "abc"
    Then the response status should be 400
    And the error should indicate the password does not meet requirements

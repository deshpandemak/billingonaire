Feature: Court Order Management and Lifecycle
  As a legal professional
  I want to track court orders through their full lifecycle
  So that I can monitor case progress and billing accurately

  Background:
    Given the Billingonaire API is running
    And a valid authenticated user is logged in

  Scenario: Retrieve cases without linked court orders
    Given there are cases in Firestore with order_status "fetch_queued"
    When I GET /orders/cases-without-orders
    Then the response status should be 200
    And the response should contain a list of unlinked cases

  Scenario: Create a court order link for a case
    Given a case with case_id "WP/3373/2024" exists in Firestore
    And an order URL "https://hcbombay.nic.in/orders/12345.pdf" is available
    When I POST to /orders/create-link with the case_id and order link
    Then the response status should be 200
    And the case order_status should be updated to "linked"

  Scenario: Update order status to reflect fetch failure
    Given a case with case_id "WP/3373/2024" exists in Firestore
    When I PUT to /orders/update-status with status "order_failed"
    Then the response status should be 200

  Scenario: Fetch court orders via background job
    Given there are cases in Firestore with lifecycle_status "fetch_queued"
    When I POST to /jobs/fetch-orders
    Then the response status should be 200
    And the job should be queued for background processing

  Scenario: Retry failed order fetches
    Given there are cases with lifecycle_status "fetch_failed_retryable"
    When I POST to /jobs/retry-failed
    Then the response status should be 200
    And the retryable cases should be re-queued for fetch

  Scenario: Case lifecycle state machine transitions
    Given a case in state "board_ingested"
    When the order fetch succeeds
    Then the case lifecycle_status should transition to "fetch_succeeded"

  Scenario: Case lifecycle prevents invalid transitions
    Given a case in state "analysed"
    When an attempt is made to move it to "board_ingested"
    Then the response status should be 200

  Scenario: Get order status overview for admin
    Given several cases in various lifecycle states exist
    When an admin user GET /admin/order-status-overview
    Then the response should include counts for each lifecycle_status value

  Scenario: Queue status reflects pending jobs
    Given there are 5 cases queued for order fetch
    When I GET /queue/status
    Then the response should report the pending fetch queue size as 5

  Scenario: Retrieve case order lifecycle view
    Given board data and order data exist for date "2024-10-01"
    When I GET /cases/lifecycle with board_date "2024-10-01"
    Then the response status should be 200
    And each record should include lifecycle_status from the case-details collection

  Scenario: Manual override for unresolvable cases
    Given a case is stuck in "fetch_failed_terminal" state
    When an admin POST to /cases/{case_ref}/manual-override with order details
    Then the response status should be 200
    And a manual_override lifecycle event should be recorded

  Scenario: Admin fetches the manual review queue
    Given there are cases in Firestore with lifecycle_status "manual_review_required"
    When an admin user GET /admin/review-queue
    Then the response status should be 200
    And the response should contain a list of cases needing review

  Scenario: Admin overrides order category for a manual review case
    Given a case requiring manual review with id "case_mr_01" exists
    When an admin overrides order category of "case_mr_01" to "ADJOURNED"
    Then the response status should be 200
    And the response should confirm the category override

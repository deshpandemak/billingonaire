Feature: AGP Bill Generation
  As an Additional Government Pleader (AGP)
  I want to generate billing reports for my court appearances
  So that I can submit accurate fee claims for my work

  Background:
    Given the Billingonaire API is running
    And a valid authenticated AGP user is logged in

  Scenario: Generate a bill for a date range
    Given analysed case records exist for the AGP user between "2024-10-01" and "2024-10-31"
    When I GET /bills/generate with start_date "2024-10-01" and end_date "2024-10-31"
    Then the response status should be 200
    And the response should contain a list of billable matters

  Scenario: Bill includes only matters matched to the requesting AGP
    Given multiple AGP users have matters in the system
    When the logged-in AGP user GET /bills/generate with start_date "2024-10-01" and end_date "2024-10-31"
    Then the response should only include matters matched to that AGP user
    And matters assigned to other AGPs should not appear

  Scenario: Bill line items include case reference and classification
    Given analysed case "WP/3373/2024" is matched to the AGP user
    When I GET /bills/generate with start_date "2024-10-01" and end_date "2024-10-31"
    Then the bill should include a line item for "WP/3373/2024"
    And the line item should include the analysis_category field

  Scenario: Export bill as Excel file
    Given billable matters exist for the AGP user
    When I GET /bills/export/excel with start_date "2024-10-01" and end_date "2024-10-31"
    Then the response status should be 200
    And the response Content-Type should be "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    And the downloaded file should be a valid Excel workbook

  Scenario: Save a generated bill for record keeping
    Given a bill has been generated for the AGP user
    When I POST the bill data to /bills/save
    Then the response status should be 200
    And the saved bill should be retrievable via /bills/my-bills

  Scenario: List saved bills for the current user
    Given the AGP user has 3 previously saved bills
    When I GET /bills/my-bills
    Then the response status should be 200
    And the response should contain 3 bill records

  Scenario: Retrieve a specific saved bill by ID
    Given a saved bill with id "bill_123" exists for the current user
    When I GET /bills/bill_123
    Then the response status should be 200
    And the response should contain the bill with id "bill_123"

  Scenario: Delete a saved bill
    Given a saved bill with id "bill_123" exists for the current user
    When I DELETE /bills/bill_123
    Then the response status should be 200
    And the bill should no longer appear in /bills/my-bills

  Scenario: Bill generation returns empty list when no matters are found
    Given the AGP user has no matched matters in the given date range
    When I GET /bills/generate with a date range that has no data
    Then the response status should be 200
    And the response should return an empty list of matters

  Scenario: Bill generation requires authentication
    Given no authentication token is provided
    When I GET /bills/generate without auth with start_date "2024-10-01" and end_date "2024-10-31"
    Then the response status should be 401 or 403

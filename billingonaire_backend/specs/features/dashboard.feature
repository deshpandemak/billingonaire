Feature: Analytics Dashboard
  As a legal professional or administrator
  I want to view aggregated analytics about court cases and AGP activity
  So that I can understand workload patterns and billing trends

  Background:
    Given the Billingonaire API is running
    And a valid authenticated user is logged in

  Scenario: Retrieve weekly case status summary
    Given analysed case records exist for the current week
    When I GET /dashboard/weekly-status
    Then the response status should be 200
    And the response should contain case counts grouped by analysis_category

  Scenario: Retrieve AGP performance statistics
    Given cases matched to AGP users exist in the system
    When I GET /dashboard/agp-stats
    Then the response status should be 200
    And the response should contain per-AGP matter counts and categories

  Scenario: Retrieve monthly average appearances
    Given analysed case records spanning multiple months exist
    When I GET /dashboard/monthly-avg
    Then the response status should be 200
    And the response should include monthly average appearance counts

  Scenario: Retrieve matters by date range
    Given case records exist between "2024-10-01" and "2024-10-31"
    When I GET /dashboard/matters-by-date-range with start "2024-10-01" and end "2024-10-31"
    Then the response status should be 200
    And the response should include matters only within that date range

  Scenario: Retrieve AGP distribution data for weekly chart
    Given AGP-matched case data exists for the current week
    When I GET /dashboard/agp-distribution-weekly
    Then the response status should be 200
    And the response should contain per-AGP appearance counts for the week

  Scenario: Retrieve AGP distribution data for monthly chart
    Given AGP-matched case data exists for the current month
    When I GET /dashboard/agp-distribution-monthly
    Then the response status should be 200
    And the response should contain per-AGP appearance counts for the month

  Scenario: Retrieve board date summary
    Given board data exists for multiple dates
    When I GET /dashboard/board-date-summary
    Then the response status should be 200
    And the response should list each board date with a total case count

  Scenario: Retrieve per-AGP case breakdown for a specific board date
    Given board data and AGP mappings exist for date "2024-10-01"
    When I GET /dashboard/board-date-agp-distribution with date "2024-10-01"
    Then the response status should be 200
    And the response should show each AGP's case count for that date

  Scenario: Retrieve all cases for a specific board date
    Given board data exists for date "2024-10-01" with 10 cases
    When I GET /dashboard/board-date-cases with date "2024-10-01"
    Then the response status should be 200
    And the response should contain all 10 cases for that date

  Scenario: Dashboard endpoints return empty data gracefully
    Given no case records exist in the system
    When I GET /dashboard/weekly-status
    Then the response status should be 200
    And the response should return empty or zero-count results without an error

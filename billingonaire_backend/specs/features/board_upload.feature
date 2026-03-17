Feature: PDF Board Upload and Parsing
  As a legal professional
  I want to upload daily court board PDFs
  So that case listings are automatically extracted and stored

  Background:
    Given the Billingonaire API is running
    And a valid authenticated user is logged in

  Scenario: Successfully upload and parse a valid court board PDF
    Given a valid court board PDF file for date "2024-10-01"
    When I upload the PDF via POST /upload-pdf
    Then the response status should be 200
    And the response should contain a list of parsed case records
    And each case record should have fields: case_type, case_no, case_year, board_date

  Scenario: Upload PDF extracts lawyer names from court details
    Given a court board PDF with the entry "SHRI P.M.JOSHI, AGP WITH"
    When I upload the PDF via POST /upload-pdf
    Then the parsed records should contain respondent_lawyer matching "P.M.JOSHI"

  Scenario: Upload PDF extracts case reference correctly
    Given a court board PDF with case type "WP", case number "3373", and year "2024"
    When I upload the PDF via POST /upload-pdf
    Then a case record with case_ref "WP/3373/2024" should be present in the response

  Scenario: Reject upload when no file is provided
    Given no file is attached to the request
    When I send a POST request to /upload-pdf
    Then the response status should be 422

  Scenario: Reject upload when file is not a PDF
    Given a non-PDF file (e.g. a .txt file) is attached
    When I upload the file via POST /upload-pdf
    Then the response status should be 400
    And the error message should indicate an invalid file format

  Scenario: Save parsed board data to Firestore
    Given a list of parsed case records from a board PDF
    When I POST the records to /save-data
    Then the response status should be 200
    And the records should be persisted in the daily-boards collection

  Scenario: Retrieve board data by date
    Given board records have been saved for date "2024-10-01"
    When I POST to /get-data with board_date "2024-10-01"
    Then the response status should be 200
    And the returned records should all have board_date "2024-10-01"

  Scenario: Board ingestion does not block on order availability
    Given a court board PDF where all court orders are unavailable
    When I upload the PDF via POST /upload-pdf
    Then all parsed records should have order_status "fetch_queued" or unset
    And the upload response should still return 200 without waiting for orders

Feature: ML-Powered Court Order Analysis
  As a legal professional
  I want court orders to be automatically classified
  So that I can quickly understand case outcomes and generate accurate bills

  Background:
    Given the Billingonaire API is running
    And a valid authenticated user is logged in

  Scenario: Classify an adjourned court order
    Given a court order PDF with text "The matter is adjourned to the next date of hearing"
    When I POST the order to /analyze-order
    Then the response status should be 200
    And the analysis_category should be "ADJOURNED"
    And the category_confidence should be greater than 0.6

  Scenario: Classify a heard and adjourned court order
    Given a court order PDF with text "The matter is heard and adjourned to 15/10/2024"
    When I POST the order to /analyze-order
    Then the response status should be 200
    And the analysis_category should be "HEARD_AND_ADJOURNED"
    And the next_hearing_date should contain "15/10/2024"

  Scenario: Classify a disposed court order
    Given a court order PDF with text "The petition is dismissed for want of prosecution"
    When I POST the order to /analyze-order
    Then the response status should be 200
    And the analysis_category should be "DISPOSED_OFF"

  Scenario: Extract AGP name from court order
    Given a court order PDF with text "AGP Pooja Joshi Deshpande appears for the State"
    When I POST the order to /analyze-order
    Then the response should contain agp_names including "Pooja Joshi Deshpande"

  Scenario: Extract petitioner names from court order
    Given a court order PDF with text "Petitioner: John Doe"
    When I POST the order to /analyze-order
    Then the response should contain petitioners including "John Doe"

  Scenario: Extract order date from court order
    Given a court order PDF with text "Order dated 01/10/2024"
    When I POST the order to /analyze-order
    Then the response should contain order_date "01/10/2024"

  Scenario: Return analysis history for a case
    Given analysis records exist for case "WP/3373/2024"
    When I GET /analysis-history with case_ref "WP/3373/2024"
    Then the response status should be 200
    And the response should contain a list of past analysis results

  Scenario: Trigger background order analysis job
    Given there are cases with lifecycle_status "fetch_succeeded"
    When I POST to /jobs/analyze-orders
    Then the response status should be 200
    And the job should be queued for background processing

  Scenario: Low-confidence analysis triggers LLM fallback when enabled
    Given the LLM fallback is enabled via ORDER_ENABLE_LLM_FALLBACK=true
    And a court order with ambiguous content that scores below confidence threshold
    When I POST the order to /analyze-order
    Then the response should indicate llm_fallback_used is true
    And the analysis_category should reflect the LLM result

  Scenario: Analysis gracefully handles corrupt or empty PDF
    Given an empty or unreadable court order PDF
    When I POST the order to /analyze-order
    Then the response status should be 200
    And the analysis_category should be "UNKNOWN" or the error should be clearly reported

  Scenario: Retrieve analysis stats
    Given analysis records exist in the system
    When I GET /analysis-stats
    Then the response status should be 200
    And the response should include counts per analysis_category

  Scenario: Analyze a single case by case_id
    Given a case "test_case_id" with a fetched order exists in Firestore
    When I POST to /auto-orders/analyze-case/test_case_id
    Then the response status should be 200
    And the case lifecycle_status should be updated to "analysed"

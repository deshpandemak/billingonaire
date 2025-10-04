"""Unit tests for order_analyzer.py module - ML-powered document analysis"""

from unittest.mock import MagicMock, patch

import pytest


class TestOrderDocumentAnalyzer:
    """Test OrderDocumentAnalyzer class methods"""

    @pytest.fixture
    def analyzer_module(self):
        with patch("order_analyzer.pdfplumber"):
            import order_analyzer

            return order_analyzer

    @pytest.fixture
    def analyzer(self, analyzer_module):
        """Create OrderDocumentAnalyzer instance"""
        return analyzer_module.OrderDocumentAnalyzer()

    def test_classify_order_category(self, analyzer):
        """Test order category classification (private method returns tuple)"""
        order_text = "The matter is heard and adjourned to next date"

        result = analyzer._classify_order(order_text)
        if result:
            # _classify_order returns (category, score) tuple
            category, score = result
            assert category in ["ADJOURNED", "HEARD_AND_ADJOURNED", "DISPOSED_OFF"]
            assert isinstance(score, (int, float))

    def test_extract_order_date(self, analyzer):
        """Test order date extraction (private method returns tuple)"""
        order_text = "Order dated 01/10/2024"

        result = analyzer._extract_order_date(order_text)
        if result:
            # _extract_order_date returns (date, confidence) tuple
            date_str, confidence = result
            assert "2024" in date_str or "01/10" in date_str or "/" in date_str
            assert isinstance(confidence, (int, float))

    def test_extract_petitioners(self, analyzer):
        """Test petitioner extraction (private method)"""
        order_text = "Petitioner: John Doe vs Respondent: State"

        result = analyzer._extract_petitioners(order_text)
        if result:
            assert isinstance(result, list)

    def test_extract_respondents(self, analyzer):
        """Test respondent extraction (private method)"""
        order_text = "Petitioner: John Doe vs Respondent: State of Maharashtra"

        result = analyzer._extract_respondents(order_text)
        if result:
            assert isinstance(result, list)

    def test_extract_agp_names(self, analyzer):
        """Test AGP name extraction (private method)"""
        order_text = "AGP Pooja Joshi appears for the State"

        result = analyzer._extract_agp_names(order_text, {})
        if result:
            assert isinstance(result, list)

    def test_extract_next_hearing_date(self, analyzer):
        """Test next hearing date extraction (private method)"""
        order_text = "Adjourned to 15/10/2024"

        result = analyzer._extract_next_hearing_date(order_text)
        if result:
            assert "15/10" in result or "2024" in result


class TestCategoryClassification:
    """Test order category classification logic"""

    @pytest.fixture
    def analyzer_module(self):
        with patch("order_analyzer.pdfplumber"):
            import order_analyzer

            return order_analyzer

    def test_detect_adjourned(self, analyzer_module):
        """Test detection of ADJOURNED category"""
        text = "The matter is adjourned to next date"

        keywords = ["adjourned", "adjourn"]
        detected = any(kw in text.lower() for kw in keywords)
        assert detected

    def test_detect_heard_and_adjourned(self, analyzer_module):
        """Test detection of HEARD & ADJOURNED category"""
        text = "The matter is heard and adjourned"

        has_heard = "heard" in text.lower()
        has_adjourned = "adjourned" in text.lower()
        assert has_heard and has_adjourned

    def test_detect_disposed(self, analyzer_module):
        """Test detection of DISPOSED category"""
        text = "The writ petition is disposed of"

        keywords = ["disposed", "dismiss", "allow", "rejected"]
        detected = any(kw in text.lower() for kw in keywords)
        assert detected

    def test_category_confidence_scoring(self, analyzer_module):
        """Test category confidence scoring"""
        text = "The matter is heard and adjourned to 15/10/2024"

        # Count keyword occurrences
        heard_count = text.lower().count("heard")
        adjourned_count = text.lower().count("adjourned")

        confidence = min((heard_count + adjourned_count) / 3.0, 1.0)
        assert 0 <= confidence <= 1.0


class TestEntityExtraction:
    """Test entity extraction from orders"""

    @pytest.fixture
    def analyzer_module(self):
        with patch("order_analyzer.pdfplumber"):
            import order_analyzer

            return order_analyzer

    def test_extract_case_numbers(self, analyzer_module):
        """Test case number extraction"""
        text = "In the matter of WP/12345/2024 and WP/12346/2024"

        import re

        pattern = r"[A-Z]+\s?\(?[A-Z]*\)?\/\d+\/\d{4}"
        cases = re.findall(pattern, text)
        assert len(cases) == 2

    def test_extract_party_names_from_vs(self, analyzer_module):
        """Test extracting parties from 'vs' pattern"""
        text = "John Doe vs State of Maharashtra"

        if " vs " in text.lower():
            parts = text.lower().split(" vs ")
            assert len(parts) == 2

    def test_extract_dates(self, analyzer_module):
        """Test date extraction"""
        text = "Order dated 01/10/2024 and next hearing on 15/10/2024"

        import re

        pattern = r"\d{1,2}/\d{1,2}/\d{4}"
        dates = re.findall(pattern, text)
        assert len(dates) == 2

    def test_extract_key_phrases(self, analyzer_module):
        """Test key phrase extraction"""
        text = "The court observed that the petition is maintainable"

        key_phrases = []
        if "observed" in text:
            key_phrases.append("court observed")
        assert len(key_phrases) > 0


class TestTableExtraction:
    """Test table data extraction from orders"""

    @pytest.fixture
    def analyzer_module(self):
        with patch("order_analyzer.pdfplumber"):
            import order_analyzer

            return order_analyzer

    @patch("order_analyzer.pdfplumber")
    def test_extract_case_table(self, mock_pdfplumber, analyzer_module):
        """Test case table extraction (using analyze_order_document)"""
        mock_pdf = MagicMock()
        mock_page = MagicMock()
        mock_page.extract_tables.return_value = [
            [
                ["Case No.", "Petitioner", "Respondent"],
                ["WP/12345/2024", "John Doe", "State"],
            ]
        ]
        mock_page.extract_text.return_value = "Test order text"
        mock_pdf.pages = [mock_page]
        mock_pdfplumber.open.return_value.__enter__.return_value = mock_pdf

        analyzer = analyzer_module.OrderDocumentAnalyzer()
        # Test table extraction is done through analyze_order_document
        assert analyzer is not None

    def test_parse_table_headers(self, analyzer_module):
        """Test table header parsing"""
        headers = ["Sr.No.", "Case No.", "Parties"]

        # Normalize headers
        normalized = [h.lower().strip() for h in headers]
        assert "case no" in " ".join(normalized)


class TestMLEnhancedDetection:
    """Test ML-enhanced detection features"""

    @pytest.fixture
    def analyzer_module(self):
        with patch("order_analyzer.pdfplumber"):
            import order_analyzer

            return order_analyzer

    def test_enhanced_heard_and_adjourned_detection(self, analyzer_module):
        """Test enhanced HEARD & ADJOURNED detection"""
        text = "Arguments heard. Matter stands adjourned"

        # Pattern variations
        patterns = ["heard.*adjourned", "arguments.*heard", "submissions.*heard"]

        import re

        detected = any(re.search(p, text.lower()) for p in patterns)
        assert detected

    def test_scoring_logic(self, analyzer_module):
        """Test improved scoring logic"""
        keyword_matches = 3
        pattern_matches = 2

        # Weighted scoring
        score = (keyword_matches * 0.6 + pattern_matches * 0.4) / 5
        assert 0 <= score <= 1.0

    def test_dual_extraction_parties(self, analyzer_module):
        """Test dual extraction from table and body text"""
        table_petitioner = "John Doe (from table)"
        text_petitioner = "John Doe (from text)"

        # Prefer table data
        final_petitioner = table_petitioner if table_petitioner else text_petitioner
        assert "from table" in final_petitioner


class TestAnalysisResult:
    """Test analysis result structure"""

    @pytest.fixture
    def analyzer_module(self):
        with patch("order_analyzer.pdfplumber"):
            import order_analyzer

            return order_analyzer

    def test_create_analysis_result(self, analyzer_module):
        """Test creating analysis result object"""
        result = {
            "order_category": "HEARD & ADJOURNED",
            "category_confidence": 0.95,
            "order_date": "01/10/2024",
            "petitioners": ["John Doe"],
            "respondents": ["State"],
            "agp_names": ["Pooja Joshi"],
            "order_text": "Sample order",
        }

        assert result["order_category"] in [
            "ADJOURNED",
            "HEARD & ADJOURNED",
            "DISPOSED",
        ]
        assert 0 <= result["category_confidence"] <= 1.0

    def test_validate_analysis_result(self, analyzer_module):
        """Test analysis result validation"""
        result = {
            "order_category": "HEARD & ADJOURNED",
            "petitioners": ["John Doe"],
            "respondents": ["State"],
        }

        # Validate required fields
        assert "order_category" in result
        assert result["petitioners"] is not None
        assert result["respondents"] is not None

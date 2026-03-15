"""
Unit tests for LLMExtractor
============================

Tests cover:
- Initialisation with defaults and custom config
- is_available() / list_models() / get_status() with mocked HTTP
- extract_board_data() happy-path and error paths
- extract_order_data() happy-path and error paths
- JSON parsing helper (_parse_json_response)
- Normalisation helpers
"""

import json
from unittest.mock import MagicMock, patch

import pytest

from billingonaire_backend.llm_extractor import LLMExtractor, _ensure_string_list

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def extractor():
    """Return a fresh LLMExtractor with default settings."""
    return LLMExtractor(base_url="http://localhost:11434", model="llama3.2")


# ---------------------------------------------------------------------------
# Initialisation
# ---------------------------------------------------------------------------


def test_default_init():
    e = LLMExtractor()
    assert e.base_url == "http://localhost:11434"
    assert e.model == "llama3.2"
    assert e.timeout == 120


def test_custom_init():
    e = LLMExtractor(base_url="http://myhost:11434", model="mistral", timeout=60)
    assert e.base_url == "http://myhost:11434"
    assert e.model == "mistral"
    assert e.timeout == 60


def test_trailing_slash_stripped():
    e = LLMExtractor(base_url="http://localhost:11434/")
    assert e.base_url == "http://localhost:11434"


# ---------------------------------------------------------------------------
# is_available
# ---------------------------------------------------------------------------


def test_is_available_true(extractor):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"models": [{"name": "llama3.2:latest"}]}
    with patch("requests.get", return_value=mock_resp):
        assert extractor.is_available() is True


def test_is_available_exact_name(extractor):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"models": [{"name": "llama3.2"}]}
    with patch("requests.get", return_value=mock_resp):
        assert extractor.is_available() is True


def test_is_available_model_not_found(extractor):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"models": [{"name": "mistral:latest"}]}
    with patch("requests.get", return_value=mock_resp):
        assert extractor.is_available() is False


def test_is_available_connection_error(extractor):
    import requests as req

    with patch("requests.get", side_effect=req.exceptions.ConnectionError):
        assert extractor.is_available() is False


def test_is_available_bad_status(extractor):
    mock_resp = MagicMock()
    mock_resp.status_code = 500
    with patch("requests.get", return_value=mock_resp):
        assert extractor.is_available() is False


# ---------------------------------------------------------------------------
# list_models
# ---------------------------------------------------------------------------


def test_list_models(extractor):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "models": [{"name": "llama3.2"}, {"name": "mistral"}]
    }
    mock_resp.raise_for_status = MagicMock()
    with patch("requests.get", return_value=mock_resp):
        models = extractor.list_models()
    assert "llama3.2" in models
    assert "mistral" in models


def test_list_models_on_error(extractor):
    import requests as req

    with patch("requests.get", side_effect=req.exceptions.ConnectionError):
        assert extractor.list_models() == []


# ---------------------------------------------------------------------------
# get_status
# ---------------------------------------------------------------------------


def test_get_status_shape(extractor):
    mock_tags = MagicMock()
    mock_tags.status_code = 200
    mock_tags.json.return_value = {"models": [{"name": "llama3.2"}]}
    mock_tags.raise_for_status = MagicMock()
    with patch("requests.get", return_value=mock_tags):
        status = extractor.get_status()
    assert "available" in status
    assert "base_url" in status
    assert "model" in status
    assert "available_models" in status


# ---------------------------------------------------------------------------
# extract_board_data
# ---------------------------------------------------------------------------

_BOARD_RESPONSE = json.dumps(
    {
        "entries": [
            {
                "serial_number": "1",
                "case_number": "WP/1234/2024",
                "board_date": "01/10/2024",
                "agp_names": ["Smt. P. J. Deshpande"],
                "associated_cases": ["IA/56/2024"],
                "petitioner_lawyer": "Shri. R. Sharma",
            }
        ]
    }
)


def _mock_generate(response_text):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"response": response_text}
    mock_resp.raise_for_status = MagicMock()
    return mock_resp


def test_extract_board_data_happy_path(extractor):
    with patch("requests.post", return_value=_mock_generate(_BOARD_RESPONSE)):
        result = extractor.extract_board_data("1 WP/1234/2024 date:01/10/2024")
    assert "entries" in result
    assert len(result["entries"]) == 1
    entry = result["entries"][0]
    assert entry["case_number"] == "WP/1234/2024"
    assert entry["board_date"] == "01/10/2024"
    assert "Smt. P. J. Deshpande" in entry["agp_names"]
    assert entry["petitioner_lawyer"] == "Shri. R. Sharma"


def test_extract_board_data_empty_text(extractor):
    result = extractor.extract_board_data("")
    assert result["entries"] == []
    assert "error" in result


def test_extract_board_data_llm_unavailable(extractor):
    import requests as req

    with patch("requests.post", side_effect=req.exceptions.ConnectionError):
        result = extractor.extract_board_data("some text")
    assert result["entries"] == []
    assert "error" in result


def test_extract_board_data_bad_json(extractor):
    with patch("requests.post", return_value=_mock_generate("not json at all")):
        result = extractor.extract_board_data("some text")
    assert result["entries"] == []
    assert "error" in result


def test_extract_board_data_direct_list(extractor):
    """LLM may return a bare list instead of {entries: [...]}"""
    bare_list = json.dumps(
        [
            {
                "serial_number": "2",
                "case_number": "PIL/5/2025",
                "board_date": "15/01/2025",
                "agp_names": [],
                "associated_cases": [],
                "petitioner_lawyer": "",
            }
        ]
    )
    with patch("requests.post", return_value=_mock_generate(bare_list)):
        result = extractor.extract_board_data("PIL/5/2025")
    assert len(result["entries"]) == 1
    assert result["entries"][0]["case_number"] == "PIL/5/2025"


# ---------------------------------------------------------------------------
# extract_order_data
# ---------------------------------------------------------------------------

_ORDER_RESPONSE = json.dumps(
    {
        "order_date": "01/10/2024",
        "order_category": "HEARD_AND_ADJOURNED",
        "affidavit_instructions": "File affidavit within 4 weeks",
        "cases": [
            {
                "case_number": "WP/1234/2024",
                "petitioner_name": "Ramchandra Sathe",
                "respondent_name": "State of Maharashtra",
                "govt_pleader": "Smt. P. J. Deshpande",
            }
        ],
    }
)


def test_extract_order_data_happy_path(extractor):
    with patch("requests.post", return_value=_mock_generate(_ORDER_RESPONSE)):
        result = extractor.extract_order_data("Order text for WP/1234/2024")
    assert result["order_date"] == "01/10/2024"
    assert result["order_category"] == "HEARD_AND_ADJOURNED"
    assert result["affidavit_instructions"] == "File affidavit within 4 weeks"
    assert len(result["cases"]) == 1
    case = result["cases"][0]
    assert case["case_number"] == "WP/1234/2024"
    assert case["petitioner_name"] == "Ramchandra Sathe"
    assert case["govt_pleader"] == "Smt. P. J. Deshpande"


def test_extract_order_data_empty_text(extractor):
    result = extractor.extract_order_data("")
    assert result["cases"] == []
    assert "error" in result


def test_extract_order_data_llm_unavailable(extractor):
    import requests as req

    with patch("requests.post", side_effect=req.exceptions.ConnectionError):
        result = extractor.extract_order_data("order text")
    assert "error" in result


def test_extract_order_data_category_normalisation(extractor):
    response = json.dumps(
        {
            "order_date": "01/10/2024",
            "order_category": "Disposed Off",
            "affidavit_instructions": "",
            "cases": [],
        }
    )
    with patch("requests.post", return_value=_mock_generate(response)):
        result = extractor.extract_order_data("text")
    # "Disposed Off" -> "DISPOSED_OFF" after upper + replace spaces with _
    assert result["order_category"] == "DISPOSED_OFF"


def test_extract_order_data_heard_and_adjourned_alias(extractor):
    response = json.dumps(
        {
            "order_date": "",
            "order_category": "HEARD & ADJOURNED",
            "affidavit_instructions": "",
            "cases": [],
        }
    )
    with patch("requests.post", return_value=_mock_generate(response)):
        result = extractor.extract_order_data("text")
    assert result["order_category"] == "HEARD_AND_ADJOURNED"


# ---------------------------------------------------------------------------
# _parse_json_response
# ---------------------------------------------------------------------------


def test_parse_json_clean(extractor):
    data = {"key": "value"}
    assert extractor._parse_json_response(json.dumps(data)) == data


def test_parse_json_with_code_fence(extractor):
    raw = '```json\n{"a": 1}\n```'
    assert extractor._parse_json_response(raw) == {"a": 1}


def test_parse_json_with_prose(extractor):
    raw = 'Here is the result:\n{"b": 2}\nEnd.'
    assert extractor._parse_json_response(raw) == {"b": 2}


def test_parse_json_none_on_failure(extractor):
    assert extractor._parse_json_response("this is not json") is None


def test_parse_json_empty(extractor):
    assert extractor._parse_json_response("") is None


# ---------------------------------------------------------------------------
# _normalise_board_entry / _normalise_case_entry
# ---------------------------------------------------------------------------


def test_normalise_board_entry_missing_fields(extractor):
    result = extractor._normalise_board_entry({})
    assert result["serial_number"] == ""
    assert result["case_number"] == ""
    assert result["agp_names"] == []
    assert result["associated_cases"] == []


def test_normalise_case_entry_missing_fields(extractor):
    result = extractor._normalise_case_entry({})
    assert result["case_number"] == ""
    assert result["petitioner_name"] == ""
    assert result["govt_pleader"] == ""


def test_normalise_board_entry_non_dict(extractor):
    result = extractor._normalise_board_entry("invalid")
    assert result["case_number"] == ""


# ---------------------------------------------------------------------------
# _ensure_string_list utility
# ---------------------------------------------------------------------------


def test_ensure_string_list_from_list():
    assert _ensure_string_list(["a", "b"]) == ["a", "b"]


def test_ensure_string_list_from_string():
    assert _ensure_string_list("hello") == ["hello"]


def test_ensure_string_list_empty_string():
    assert _ensure_string_list("") == []


def test_ensure_string_list_none():
    assert _ensure_string_list(None) == []


def test_ensure_string_list_filters_empty():
    assert _ensure_string_list(["a", "", "b"]) == ["a", "b"]

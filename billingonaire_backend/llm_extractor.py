"""
LLM-Based PDF Data Extractor for Legal Documents
=================================================

This module provides local open-source LLM (via Ollama) capabilities for
extracting structured data from unstructured court board and order PDFs.

Supported extraction targets:
- Court boards: serial number, board date, case number, AGP/GP names,
  associated cases, petitioner lawyers
- Court orders: case number, petitioner, respondent, government pleader,
  order date, order category, affidavit/reply instructions, clubbed cases

The extractor integrates with Ollama (https://ollama.com) which can run
popular open-source models such as Llama 3, Mistral, Gemma and others
entirely on local hardware without sending data to external services.

Configuration via environment variables:
  LLM_BASE_URL  – Ollama base URL (default: http://localhost:11434)
  LLM_MODEL     – Model name to use  (default: llama3.2)
  LLM_TIMEOUT   – Request timeout in seconds (default: 120)

Author: Billingonaire Legal Billing System
"""

import json
import logging
import os
import re
from typing import Any, Dict, List, Optional

import requests

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Default configuration
# ---------------------------------------------------------------------------
_DEFAULT_BASE_URL = "http://localhost:11434"
_DEFAULT_MODEL = "llama3.2"
_DEFAULT_TIMEOUT = 120  # seconds

# Maximum number of characters to send per LLM call.
# Most 7B–13B models comfortably handle ~4 000–8 000 tokens; keeping the
# input at 8 000 UTF-8 characters leaves headroom for the prompt template
# itself and the model's response within a typical 4 096-token context window.
_MAX_CONTEXT_CHARS = 8000


# ---------------------------------------------------------------------------
# Prompt templates
# ---------------------------------------------------------------------------

_BOARD_SYSTEM_PROMPT = (
    "You are an expert legal document analyst specialising in Indian High Court "
    "board documents. Extract structured information exactly as it appears in the "
    "document. Return ONLY a valid JSON object and nothing else."
)

_BOARD_USER_PROMPT = """Extract the following fields from the court board text below.
Return a JSON object where each key maps to a list of objects (one per board entry).

Required JSON structure:
{{
  "entries": [
    {{
      "serial_number": "string – serial/item number on the board",
      "case_number": "string – full case reference, e.g. WP/1234/2024",
      "board_date": "string – date of the board in DD/MM/YYYY format",
      "agp_names": ["list of AGP / GP / government pleader names"],
      "associated_cases": ["list of other case numbers linked to this entry"],
      "petitioner_lawyer": "string – lawyer representing the petitioner, or empty string"
    }}
  ]
}}

Board document text:
\"\"\"
{text}
\"\"\"
"""

_ORDER_SYSTEM_PROMPT = (
    "You are an expert legal document analyst specialising in Indian High Court "
    "order documents. Extract structured information exactly as it appears in the "
    "document. Return ONLY a valid JSON object and nothing else."
)

_ORDER_USER_PROMPT = """Extract the following fields from the court order text below.
When multiple cases are clubbed together in one order, include each as a separate
object in the 'cases' array.

Required JSON structure:
{{
  "order_date": "string – date of the order in DD/MM/YYYY format",
  "order_category": "string – one of: ADJOURNED | HEARD_AND_ADJOURNED | DISPOSED_OFF",
  "affidavit_instructions": "string – any specific instructions about filing an affidavit or reply, or empty string",
  "cases": [
    {{
      "case_number": "string – full case reference, e.g. WP/1234/2024",
      "petitioner_name": "string – name of the petitioner",
      "respondent_name": "string – name of the respondent",
      "govt_pleader": "string – government pleader / AGP who appeared for the state"
    }}
  ]
}}

Order document text:
\"\"\"
{text}
\"\"\"
"""


class LLMExtractor:
    """
    Local LLM-based extractor for court board and order documents.

    Uses Ollama's REST API to run open-source models (Llama 3, Mistral,
    Gemma, etc.) locally and extract structured data from raw PDF text.
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        timeout: Optional[int] = None,
    ):
        """
        Initialise the LLM Extractor.

        Args:
            base_url: Ollama base URL.  Falls back to ``LLM_BASE_URL`` env
                      variable and then ``http://localhost:11434``.
            model:    Ollama model name.  Falls back to ``LLM_MODEL`` env
                      variable and then ``llama3.2``.
            timeout:  HTTP request timeout in seconds.  Falls back to
                      ``LLM_TIMEOUT`` env variable and then 120 s.
        """
        self.base_url = (
            base_url or os.environ.get("LLM_BASE_URL", _DEFAULT_BASE_URL)
        ).rstrip("/")
        self.model = model or os.environ.get("LLM_MODEL", _DEFAULT_MODEL)
        self.timeout = int(
            timeout or os.environ.get("LLM_TIMEOUT", str(_DEFAULT_TIMEOUT))
        )

        self._generate_url = f"{self.base_url}/api/generate"
        self._tags_url = f"{self.base_url}/api/tags"

        logger.info(
            "LLMExtractor initialised – base_url=%s model=%s timeout=%ss",
            self.base_url,
            self.model,
            self.timeout,
        )

    # ------------------------------------------------------------------
    # Public helpers
    # ------------------------------------------------------------------

    def is_available(self) -> bool:
        """Return True if Ollama is reachable and the configured model is available."""
        try:
            resp = requests.get(self._tags_url, timeout=5)
            if resp.status_code != 200:
                return False
            models = [m.get("name", "") for m in resp.json().get("models", [])]
            # Model names in Ollama may include a tag, e.g. "llama3.2:latest"
            return any(
                m == self.model or m.startswith(self.model + ":") for m in models
            )
        except Exception:
            return False

    def list_models(self) -> List[str]:
        """Return list of model names currently available in Ollama."""
        try:
            resp = requests.get(self._tags_url, timeout=5)
            resp.raise_for_status()
            return [m.get("name", "") for m in resp.json().get("models", [])]
        except Exception as exc:
            logger.warning("Could not list Ollama models: %s", exc)
            return []

    def get_status(self) -> Dict[str, Any]:
        """Return a status dictionary describing the LLM configuration."""
        available = self.is_available()
        return {
            "available": available,
            "base_url": self.base_url,
            "model": self.model,
            "timeout": self.timeout,
            "available_models": self.list_models() if available else [],
        }

    # ------------------------------------------------------------------
    # Extraction methods
    # ------------------------------------------------------------------

    def extract_board_data(self, text: str) -> Dict[str, Any]:
        """
        Extract structured board data from raw PDF text using the local LLM.

        Args:
            text: Raw text extracted from a court board PDF.

        Returns:
            Dictionary with an ``entries`` list.  Each entry has keys:
            ``serial_number``, ``case_number``, ``board_date``,
            ``agp_names``, ``associated_cases``, ``petitioner_lawyer``.
            On failure returns ``{"entries": [], "error": "<message>"}``.
        """
        if not text or not text.strip():
            return {"entries": [], "error": "Empty text provided"}

        prompt = _BOARD_USER_PROMPT.format(text=text[:_MAX_CONTEXT_CHARS])
        raw = self._call_llm(_BOARD_SYSTEM_PROMPT, prompt)
        if raw is None:
            return {"entries": [], "error": "LLM call failed"}

        parsed = self._parse_json_response(raw)
        if parsed is None:
            return {"entries": [], "error": "Could not parse LLM response as JSON"}

        # Normalise to expected structure
        if "entries" not in parsed:
            # LLM may have returned the list directly
            if isinstance(parsed, list):
                parsed = {"entries": parsed}
            else:
                parsed = {"entries": [parsed]}

        parsed["entries"] = [
            self._normalise_board_entry(e) for e in parsed.get("entries", [])
        ]
        return parsed

    def extract_order_data(self, text: str) -> Dict[str, Any]:
        """
        Extract structured order data from raw PDF text using the local LLM.

        Args:
            text: Raw text extracted from a court order PDF.

        Returns:
            Dictionary with keys: ``order_date``, ``order_category``,
            ``affidavit_instructions``, ``cases`` (list).  Each case has:
            ``case_number``, ``petitioner_name``, ``respondent_name``,
            ``govt_pleader``.
            On failure returns the same structure with empty / default values
            and an ``error`` key.
        """
        empty: Dict[str, Any] = {
            "order_date": "",
            "order_category": "",
            "affidavit_instructions": "",
            "cases": [],
        }

        if not text or not text.strip():
            return {**empty, "error": "Empty text provided"}

        prompt = _ORDER_USER_PROMPT.format(text=text[:_MAX_CONTEXT_CHARS])
        raw = self._call_llm(_ORDER_SYSTEM_PROMPT, prompt)
        if raw is None:
            return {**empty, "error": "LLM call failed"}

        parsed = self._parse_json_response(raw)
        if parsed is None:
            return {**empty, "error": "Could not parse LLM response as JSON"}

        # Fill missing top-level keys with defaults
        result: Dict[str, Any] = {
            "order_date": parsed.get("order_date", ""),
            "order_category": self._normalise_order_category(
                parsed.get("order_category", "")
            ),
            "affidavit_instructions": parsed.get("affidavit_instructions", ""),
            "cases": [self._normalise_case_entry(c) for c in parsed.get("cases", [])],
        }
        return result

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _call_llm(self, system: str, user: str) -> Optional[str]:
        """
        Send a generation request to Ollama and return the response text.

        Returns None on any error.
        """
        payload = {
            "model": self.model,
            "system": system,
            "prompt": user,
            "stream": False,
            "options": {
                "temperature": 0.0,  # deterministic for extraction tasks
                "num_predict": 2048,
            },
        }
        try:
            resp = requests.post(self._generate_url, json=payload, timeout=self.timeout)
            resp.raise_for_status()
            return resp.json().get("response", "")
        except requests.exceptions.ConnectionError:
            logger.warning(
                "Ollama not reachable at %s – LLM extraction skipped",
                self.base_url,
            )
            return None
        except Exception as exc:
            logger.warning("LLM call failed: %s", exc)
            return None

    def _parse_json_response(self, text: str) -> Optional[Any]:
        """
        Parse JSON from LLM response, tolerating common formatting issues
        (leading/trailing prose, markdown code fences).
        """
        if not text:
            return None

        # Strip markdown code fences that some models add
        text = re.sub(r"```(?:json)?\s*", "", text)
        text = re.sub(r"```\s*$", "", text, flags=re.MULTILINE)

        # Try the whole string first
        try:
            return json.loads(text.strip())
        except json.JSONDecodeError:
            pass

        # Fall back: find the first { ... } or [ ... ] block
        for pattern in (r"\{[\s\S]*\}", r"\[[\s\S]*\]"):
            match = re.search(pattern, text)
            if match:
                try:
                    return json.loads(match.group())
                except json.JSONDecodeError:
                    continue

        logger.debug("Could not extract JSON from LLM response: %s", text[:200])
        return None

    @staticmethod
    def _normalise_board_entry(entry: Any) -> Dict[str, Any]:
        """Ensure a board entry dict has all expected keys with sane defaults."""
        if not isinstance(entry, dict):
            entry = {}
        return {
            "serial_number": str(entry.get("serial_number", "")),
            "case_number": str(entry.get("case_number", "")),
            "board_date": str(entry.get("board_date", "")),
            "agp_names": _ensure_string_list(entry.get("agp_names")),
            "associated_cases": _ensure_string_list(entry.get("associated_cases")),
            "petitioner_lawyer": str(entry.get("petitioner_lawyer", "")),
        }

    @staticmethod
    def _normalise_case_entry(entry: Any) -> Dict[str, Any]:
        """Ensure an order case entry dict has all expected keys."""
        if not isinstance(entry, dict):
            entry = {}
        return {
            "case_number": str(entry.get("case_number", "")),
            "petitioner_name": str(entry.get("petitioner_name", "")),
            "respondent_name": str(entry.get("respondent_name", "")),
            "govt_pleader": str(entry.get("govt_pleader", "")),
        }

    @staticmethod
    def _normalise_order_category(raw: str) -> str:
        """Map LLM output to one of the canonical category strings."""
        upper = raw.upper().replace(" ", "_").replace("&", "AND")
        candidates = {
            "ADJOURNED": "ADJOURNED",
            "HEARD_AND_ADJOURNED": "HEARD_AND_ADJOURNED",
            "HEARD_&_ADJOURNED": "HEARD_AND_ADJOURNED",
            "DISPOSED_OFF": "DISPOSED_OFF",
            "DISPOSED": "DISPOSED_OFF",
        }
        return candidates.get(upper, raw)


# ---------------------------------------------------------------------------
# Module-level singleton (lazy, instantiated on first use)
# ---------------------------------------------------------------------------
_extractor_instance: Optional[LLMExtractor] = None


def get_llm_extractor() -> LLMExtractor:
    """Return the module-level singleton LLMExtractor instance."""
    global _extractor_instance
    if _extractor_instance is None:
        _extractor_instance = LLMExtractor()
    return _extractor_instance


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------


def _ensure_string_list(value: Any) -> List[str]:
    """Convert a value to a list of non-empty strings."""
    if isinstance(value, list):
        return [str(v) for v in value if v]
    if isinstance(value, str) and value:
        return [value]
    return []

"""Shared logic for the advocate/party extraction copilot: an LLM read of
the messy advocate-listing text found in board rows and order PDFs, used
by tools/extraction_copilot_prototype.py's offline shadow-mode comparison
against the regex extractors -- Board.create_record() (board rows) and
order_analyzer.OrderDocumentAnalyzer._extract_govt_pleader_from_text
(order PDFs).

Both regex extractors do the same job -- "given this messy column of
text, which names are petitioner-side and which are government-side" --
with hand-written positional splitting and blind string surgery
(Board.create_record does `respondent_lawyer.replace("in", "")`, which
corrupts any name containing "in": Jain, Sinha, Shinde). That is exactly
the shape of problem an LLM with a JSON schema handles well.

NOT wired into any production write path yet. Per the same "shadow-mode
first" sequencing tools/review_copilot_prototype.py established before
_maybe_llm_assist (AutoOrderManager.py) was ever wired into production
classification: run this offline against real board/order text, compare
against the regex extractors, and only promote it to primary where it
measurably wins -- see tools/extraction_copilot_prototype.py.

Kept deliberately small and dependency-light (stdlib + requests only, no
Firestore/scraper dependency chain), matching review_copilot.py.
"""

from __future__ import annotations

import json
from typing import Any, Dict

import requests

DEFAULT_MODEL = "gemini-flash-latest"

PROMPT_TEMPLATE = """You are extracting advocate names from a snippet of text taken from a
Bombay High Court daily board row or order sheet. The snippet lists the advocates
appearing for each side, using titles like Mr./Ms./Shri/Smt and government-side role
markers such as AGP, Addl. GP, GP, or B'Pnl.

Extract:
- petitioner_advocates: full names of advocates for the petitioner/applicant side.
  Do not include titles (Mr./Ms./Shri/Smt) or role markers -- just the name.
- government_advocates: full names of advocates appearing for the government /
  respondent-State side (anyone carrying an AGP / GP / Addl. GP / B'Pnl marker).
- roles: one entry per government_advocates name (same order), giving the role
  marker exactly as printed in the text (e.g. "AGP", "Addl. GP", "B'Pnl").

Only extract names that actually appear in the text -- never invent one. If a side
has no advocates listed in this snippet, return an empty list for it.

Text:
\"\"\"{text}\"\"\"

Respond with ONLY a JSON object, no other text, matching this shape:
{{"petitioner_advocates": ["<name>", ...],
  "government_advocates": ["<name>", ...],
  "roles": ["<role for the government_advocates entry at the same index>", ...]}}
"""


class ExtractionCopilotError(RuntimeError):
    """Raised for any failure calling the LLM -- callers surface str(e)."""


def call_gemini_for_advocates(
    text: str, api_key: str, model: str = DEFAULT_MODEL
) -> Dict[str, Any]:
    payload = {
        "contents": [{"parts": [{"text": PROMPT_TEMPLATE.format(text=text)}]}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseSchema": {
                "type": "OBJECT",
                "properties": {
                    "petitioner_advocates": {
                        "type": "ARRAY",
                        "items": {"type": "STRING"},
                    },
                    "government_advocates": {
                        "type": "ARRAY",
                        "items": {"type": "STRING"},
                    },
                    "roles": {"type": "ARRAY", "items": {"type": "STRING"}},
                },
                "required": [
                    "petitioner_advocates",
                    "government_advocates",
                    "roles",
                ],
            },
        },
    }
    try:
        resp = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
            params={"key": api_key},
            json=payload,
            timeout=30,
        )
        resp.raise_for_status()
        raw = resp.json()["candidates"][0]["content"]["parts"][0]["text"]
        return json.loads(raw)
    except Exception as exc:  # noqa: BLE001 - normalize every failure mode for callers
        raise ExtractionCopilotError(str(exc)) from exc

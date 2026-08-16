"""Shared logic for the order-classification review copilot: an LLM read of
an order, with a rationale, offered alongside (never in place of) the
regex classifier's own result -- used by the manual review queue UI and by
tools/review_copilot_prototype.py's offline comparison harness.

Also extracts petitioner/government-side advocate names in the SAME call
(merged from what was a separate, shadow-mode-only extraction_copilot.py
prompt) -- wired into the live pipeline (AutoOrderManager._maybe_llm_assist)
so that whenever an order is already being sent to Gemini for a low-
confidence classification, the response carries the same breadth of
entity data the regex extractor produces, at no extra API call. Still
never overrides the regex extractor's result outright; see
_maybe_llm_assist's fallback-only-when-regex-found-nothing logic.

Kept deliberately small and dependency-light (stdlib + requests only) so it
can be imported from both main.py at request time and from a standalone
CLI tool without pulling in the rest of the backend.
"""

from __future__ import annotations

import json
from typing import Any, Dict

import requests

CATEGORIES = ("ADJOURNED", "HEARD_AND_ADJOURNED", "DISPOSED_OFF")

DEFAULT_MODEL = "gemini-flash-latest"

PROMPT_TEMPLATE = """You are reading a single entry from a Bombay High Court daily
cause-list order sheet, for AGP (Assistant Government Pleader) billing purposes.
Do two things:

1. Classify it into exactly one of these three categories:

- DISPOSED_OFF: the matter was finally decided/disposed of on this date.
- HEARD_AND_ADJOURNED: the matter was called before the court and then
  adjourned to a future date. This does NOT require substantive arguments,
  interim relief, or a hearing on merits -- a routine "stand over" / "by
  consent" / "at the request of" adjournment still counts, because the
  matter was reached and the government's counsel's appearance is
  billable regardless of how much was argued. In particular: if any AGP
  or Government Pleader is named in the text as present, appearing,
  submitting, requesting, or consenting, the matter was necessarily
  called that day -- classify it as HEARD_AND_ADJOURNED, never ADJOURNED,
  even if no arguments were made and nothing beyond a routine adjournment
  was ordered.
- ADJOURNED: the matter was NOT reached/called at all on this date -- e.g.
  adjourned for want/paucity of court time, or a generic date-shift with
  no advocate or AGP named as present for this specific matter.

2. Extract the advocates named in the text:
- petitioner_advocates: full names of advocates for the petitioner/applicant
  side. Do not include titles (Mr./Ms./Shri/Smt) or role markers -- just
  the name.
- government_advocates: full names of advocates appearing for the
  government / respondent-State side (anyone carrying an AGP / GP /
  Addl. GP / B'Pnl marker).
- roles: one entry per government_advocates name (same order), giving the
  role marker exactly as printed in the text (e.g. "AGP", "Addl. GP",
  "B'Pnl").
Only extract names that actually appear in the text -- never invent one.
If a side has no advocates listed, return an empty list for it.

Order text:
\"\"\"{text}\"\"\"

Respond with ONLY a JSON object, no other text, matching this shape:
{{"category": "DISPOSED_OFF" | "HEARD_AND_ADJOURNED" | "ADJOURNED",
  "confidence": <float 0 to 1>,
  "rationale": "<one sentence, must quote the specific phrase(s) from the text that justify the category>",
  "petitioner_advocates": ["<name>", ...],
  "government_advocates": ["<name>", ...],
  "roles": ["<role for the government_advocates entry at the same index>", ...]}}
"""


class ReviewCopilotError(RuntimeError):
    """Raised for any failure calling the LLM -- callers surface str(e)."""


def call_gemini(text: str, api_key: str, model: str = DEFAULT_MODEL) -> Dict[str, Any]:
    payload = {
        "contents": [{"parts": [{"text": PROMPT_TEMPLATE.format(text=text)}]}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseSchema": {
                "type": "OBJECT",
                "properties": {
                    "category": {"type": "STRING", "enum": list(CATEGORIES)},
                    "confidence": {"type": "NUMBER"},
                    "rationale": {"type": "STRING"},
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
                    "category",
                    "confidence",
                    "rationale",
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
        raise ReviewCopilotError(str(exc)) from exc

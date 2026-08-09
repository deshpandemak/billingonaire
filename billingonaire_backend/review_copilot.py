"""Shared logic for the order-classification review copilot: an LLM read of
an order, with a rationale, offered alongside (never in place of) the
regex classifier's own result -- used by the manual review queue UI and by
tools/review_copilot_prototype.py's offline comparison harness.

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

PROMPT_TEMPLATE = """You are classifying a single entry from a Bombay High Court daily
cause-list order sheet. Classify it into exactly one of these three categories:

- DISPOSED_OFF: the matter was finally decided/disposed of on this date.
- HEARD_AND_ADJOURNED: the matter was heard/argued (notice issued, interim
  relief granted or considered, submissions made) and then adjourned to a
  future date -- some substantive progress happened.
- ADJOURNED: the matter was adjourned with no substantive hearing -- it was
  not reached, or postponed for want of time, with no argument or interim
  order.

Order text:
\"\"\"{text}\"\"\"

Respond with ONLY a JSON object, no other text, matching this shape:
{{"category": "DISPOSED_OFF" | "HEARD_AND_ADJOURNED" | "ADJOURNED",
  "confidence": <float 0 to 1>,
  "rationale": "<one sentence, must quote the specific phrase(s) from the text that justify the category>"}}
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
                },
                "required": ["category", "confidence", "rationale"],
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

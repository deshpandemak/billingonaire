"""Ad-hoc extraction of court directives that require GOVERNMENT-side action --
"file a reply affidavit by <date>", "furnish a compliance report", etc.

This is deliberately separate from review_copilot.py: that module runs
automatically, in the live pipeline, only for low-confidence classifications.
This one runs on demand, over already-classified HEARD_AND_ADJOURNED and
DISPOSED_OFF orders (an AGP or admin explicitly requests a compliance scan --
see /compliance/scan in main.py), regardless of classification confidence,
because a directive can appear in an order the classifier was completely
certain about. Never touches ADJOURNED orders -- if the matter wasn't
reached, there is nothing to direct anyone to do.

Results are cached onto the order entry (case_data_store.
set_order_compliance_directives) so re-scanning the same order is free.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from review_copilot import call_gemini_json

DEFAULT_MODEL = "gemini-flash-latest"

# Fixed taxonomy -- keeps the resulting report groupable/filterable by type
# instead of free-text directives that would each read slightly differently
# for the same underlying obligation.
DIRECTIVE_TYPES = (
    "FILE_REPLY_AFFIDAVIT",
    "FILE_REJOINDER",
    "FURNISH_COMPLIANCE_REPORT",
    "PRODUCE_DOCUMENTS",
    "APPEAR_IN_PERSON",
    "PAY_COSTS_OR_COMPENSATION",
    "OTHER",
)

_UNIT_TO_DAYS = {"DAYS": 1, "WEEKS": 7, "MONTHS": 30}

PROMPT_TEMPLATE = """You are reading a single order from a Bombay High Court writ
petition, for Assistant Government Pleader (AGP) compliance tracking.

Find every directive in this order that requires ACTION FROM THE GOVERNMENT /
STATE / RESPONDENT side (the side the AGP represents) -- NOT directives aimed
at the petitioner or private respondents, and NOT directives aimed at the
Registry/Court itself.

For each such directive, classify it into exactly one of:
- FILE_REPLY_AFFIDAVIT: file a reply/counter affidavit.
- FILE_REJOINDER: file a rejoinder or additional affidavit responding to the
  petitioner's rejoinder.
- FURNISH_COMPLIANCE_REPORT: submit a status/compliance/action-taken report.
- PRODUCE_DOCUMENTS: produce specific documents/records to the court.
- APPEAR_IN_PERSON: a named government officer must appear in person.
- PAY_COSTS_OR_COMPENSATION: pay costs, compensation, or a specified amount,
  or a restraint on disbursing/withholding an amount pending further orders.
- OTHER: any other directive squarely aimed at the government side that does
  not fit the above.

For each directive also extract the deadline, if any is stated:
- deadline_date: an explicit calendar date mentioned for THIS directive,
  formatted YYYY-MM-DD. Empty string if no explicit date is given.
- deadline_relative_amount / deadline_relative_unit: if the deadline is
  phrased relative to the order (e.g. "within three weeks", "within four
  weeks from today"), the amount (integer) and unit (DAYS, WEEKS, or
  MONTHS). Use 0 / "NONE" if not applicable or if deadline_date was given
  instead.

If the order contains NO directive requiring government-side action, return
an empty directives list -- do not invent one.

Order text:
\"\"\"{text}\"\"\"

Respond with ONLY a JSON object matching this shape:
{{"directives": [
  {{"directive_type": "FILE_REPLY_AFFIDAVIT" | "FILE_REJOINDER" | "FURNISH_COMPLIANCE_REPORT" | "PRODUCE_DOCUMENTS" | "APPEAR_IN_PERSON" | "PAY_COSTS_OR_COMPENSATION" | "OTHER",
    "deadline_date": "<YYYY-MM-DD or empty string>",
    "deadline_relative_amount": <integer, 0 if none>,
    "deadline_relative_unit": "DAYS" | "WEEKS" | "MONTHS" | "NONE",
    "description": "<one sentence, must quote the specific phrase(s) from the text>"}}, ...]}}
"""

_RESPONSE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "directives": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "directive_type": {
                        "type": "STRING",
                        "enum": list(DIRECTIVE_TYPES),
                    },
                    "deadline_date": {"type": "STRING"},
                    "deadline_relative_amount": {"type": "INTEGER"},
                    "deadline_relative_unit": {
                        "type": "STRING",
                        "enum": ["DAYS", "WEEKS", "MONTHS", "NONE"],
                    },
                    "description": {"type": "STRING"},
                },
                "required": [
                    "directive_type",
                    "deadline_date",
                    "deadline_relative_amount",
                    "deadline_relative_unit",
                    "description",
                ],
            },
        },
    },
    "required": ["directives"],
}


def _resolve_deadline(
    deadline_date: str,
    relative_amount: int,
    relative_unit: str,
    anchor_date: Optional[str],
) -> Optional[str]:
    """Prefer an explicit date; otherwise resolve a relative deadline against
    the order's own date. Returns None when neither is available -- e.g. the
    anchor date is missing/unparseable, which must not silently fabricate a
    deadline."""
    deadline_date = (deadline_date or "").strip()
    if deadline_date:
        try:
            return datetime.strptime(deadline_date, "%Y-%m-%d").strftime("%Y-%m-%d")
        except ValueError:
            return None

    days_per_unit = _UNIT_TO_DAYS.get((relative_unit or "").upper())
    if not days_per_unit or not relative_amount or not anchor_date:
        return None
    try:
        anchor = datetime.strptime(anchor_date, "%Y-%m-%d")
    except ValueError:
        return None
    return (anchor + timedelta(days=days_per_unit * relative_amount)).strftime(
        "%Y-%m-%d"
    )


def extract_directives(
    text: str,
    api_key: str,
    order_date: Optional[str] = None,
    model: str = DEFAULT_MODEL,
) -> List[Dict[str, Any]]:
    """Returns a list of {directive_type, description, deadline_date}
    (deadline_date resolved to an absolute YYYY-MM-DD or None). Raises
    ReviewCopilotError on any call failure -- callers decide how to handle
    it (main.py's endpoint skips the order and continues the scan)."""
    response = call_gemini_json(
        PROMPT_TEMPLATE.format(text=text), _RESPONSE_SCHEMA, api_key, model
    )
    directives = response.get("directives") or []
    resolved = []
    for d in directives:
        resolved.append(
            {
                "directive_type": d.get("directive_type") or "OTHER",
                "description": d.get("description") or "",
                "deadline_date": _resolve_deadline(
                    d.get("deadline_date") or "",
                    int(d.get("deadline_relative_amount") or 0),
                    d.get("deadline_relative_unit") or "NONE",
                    order_date,
                ),
            }
        )
    return resolved

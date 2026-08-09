"""Conversational front door over the existing REST API (roadmap #8).

An AGP with a question -- "how many of my cases need attention", "what
would my October bill look like" -- otherwise navigates Table, filters,
then Bills to find an answer that already exists behind an API call. This
is a natural-language front door to that same data, not a new data path.

Deliberately sequenced last and scoped narrowly, per the roadmap's own
note ("a multiplier on a pipeline that's already trustworthy, not a fix
for one that isn't") and this session's repeated lesson that the biggest
risk with LLM features is silently wrong output with no track record:

  * READ-ONLY. The tool set below can only look things up -- it cannot
    save a bill, override a category, retry a fetch, or touch anything.
    "Generate my bill" gets a preview (what /bills/generate itself
    returns) with an explicit note that saving/exporting still happens
    in the Bill Generation screen, never as a side effect of a chat
    message.
  * Every tool is scoped to the asking user's own uid by the caller (see
    main.py's /assistant/ask) -- this module never sees or chooses a
    user_id itself, so there is no way for a crafted question to make it
    answer about (or act on behalf of) anyone else.
  * Small, fixed tool set. No open-ended code execution, no arbitrary
    Firestore queries -- only the specific lookups declared here.

Kept import-light and Firestore-free, same as review_copilot.py /
portal_health.py: the actual tool implementations (which need Firestore
and the current user's uid) live in main.py and are injected here as a
plain callable, so this module is fully unit-testable without mocking
Firestore at all.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

import requests

DEFAULT_MODEL = "gemini-flash-latest"

SYSTEM_INSTRUCTION = (
    "You are a helpful assistant embedded in Billingonaire, a billing tool for "
    "Assistant Government Pleaders (AGPs) at the Bombay High Court. Answer the "
    "user's question using the tools available -- call a tool whenever the "
    "question needs current data rather than guessing. You cannot save bills, "
    "override case categories, or trigger any fetch/analysis job -- you can "
    "only look things up. If asked to 'generate' or 'submit' a bill, use "
    "get_bill_preview and make clear this is a preview only, and that saving "
    "or exporting still happens on the Bill Generation screen. Keep answers "
    "brief and concrete -- lead with the number or fact being asked for."
)

TOOL_DECLARATIONS: List[Dict[str, Any]] = [
    {
        "name": "get_queue_status",
        "description": (
            "Counts of the current user's cases needing attention, awaiting "
            "manual review, or still being fetched/analysed. Use for "
            "questions like 'how many cases need my attention' or 'is "
            "anything stuck'."
        ),
        "parameters": {"type": "OBJECT", "properties": {}},
    },
    {
        "name": "get_bill_preview",
        "description": (
            "Preview -- does NOT save or submit anything -- of what a bill "
            "for the given date range would contain: total entries, total "
            "fees, and the outcome breakdown. Use for questions like 'what "
            "would my bill for October look like' or 'how many billable "
            "matters do I have this month'."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "start_date": {
                    "type": "STRING",
                    "description": "YYYY-MM-DD, inclusive",
                },
                "end_date": {
                    "type": "STRING",
                    "description": "YYYY-MM-DD, inclusive",
                },
            },
            "required": ["start_date", "end_date"],
        },
    },
    {
        "name": "get_my_saved_bills",
        "description": (
            "Bills the current user has already saved/submitted, most "
            "recent first. Use for questions like 'what bills have I "
            "submitted' or 'when did I last bill'."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "limit": {
                    "type": "NUMBER",
                    "description": "max bills to return, default 5",
                }
            },
        },
    },
    {
        "name": "get_pending_matter_confirmations",
        "description": (
            "Matters awaiting the current user's 'is this you?' "
            "confirmation from ambiguous name matching. Use for questions "
            "like 'do I have any matters to confirm'."
        ),
        "parameters": {"type": "OBJECT", "properties": {}},
    },
]

_ALLOWED_TOOL_NAMES = {decl["name"] for decl in TOOL_DECLARATIONS}


class AssistantError(RuntimeError):
    pass


def _call_gemini(
    contents: List[Dict[str, Any]], api_key: str, model: str
) -> Dict[str, Any]:
    try:
        resp = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
            params={"key": api_key},
            json={
                "contents": contents,
                "tools": [{"functionDeclarations": TOOL_DECLARATIONS}],
                "systemInstruction": {"parts": [{"text": SYSTEM_INSTRUCTION}]},
            },
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:  # noqa: BLE001
        raise AssistantError(str(exc)) from exc


def _extract_text(response: Dict[str, Any]) -> Optional[str]:
    parts = response.get("candidates", [{}])[0].get("content", {}).get("parts", [])
    texts = [p["text"] for p in parts if "text" in p]
    return "\n".join(texts) if texts else None


def _extract_function_call(response: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    parts = response.get("candidates", [{}])[0].get("content", {}).get("parts", [])
    for part in parts:
        if "functionCall" in part:
            return part
    return None


async def ask(
    question: str,
    history: List[Dict[str, str]],
    tool_executor: Callable[[str, Dict[str, Any]], Any],
    api_key: str,
    model: str = DEFAULT_MODEL,
) -> Dict[str, Any]:
    """``history``: prior turns as [{"role": "user"|"assistant", "text": "..."}],
    oldest first -- kept short by the caller (this does no trimming itself).
    ``tool_executor``: an async callable, awaited as
    ``await tool_executor(name, args)`` for any tool in TOOL_DECLARATIONS
    the model chooses to call; must already be scoped to the asking user.
    Only one tool call round-trip is supported (matches the small,
    single-purpose tool set above -- no chained multi-tool use).

    Returns {"answer": str, "tool_used": Optional[str]}.
    """
    contents: List[Dict[str, Any]] = []
    for turn in history:
        role = "model" if turn.get("role") == "assistant" else "user"
        contents.append({"role": role, "parts": [{"text": turn.get("text", "")}]})
    contents.append({"role": "user", "parts": [{"text": question}]})

    first = _call_gemini(contents, api_key, model)
    function_call_part = _extract_function_call(first)

    if function_call_part is None:
        answer = _extract_text(first)
        if not answer:
            raise AssistantError("Model returned neither a function call nor text.")
        return {"answer": answer, "tool_used": None}

    tool_name = function_call_part["functionCall"]["name"]
    tool_args = function_call_part["functionCall"].get("args") or {}
    if tool_name not in _ALLOWED_TOOL_NAMES:
        # Should be unreachable (the model can only request tools we
        # declared) -- but never execute anything outside the fixed set.
        raise AssistantError(f"Model requested an unknown tool: {tool_name}")

    tool_result = await tool_executor(tool_name, tool_args)

    contents.append({"role": "model", "parts": [function_call_part]})
    contents.append(
        {
            "role": "user",
            "parts": [
                {
                    "functionResponse": {
                        "name": tool_name,
                        "response": tool_result,
                    }
                }
            ],
        }
    )

    second = _call_gemini(contents, api_key, model)
    answer = _extract_text(second)
    if not answer:
        raise AssistantError("Model returned no text after the tool call.")
    return {"answer": answer, "tool_used": tool_name}

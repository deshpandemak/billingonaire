from unittest.mock import AsyncMock, Mock, patch

import pytest

import assistant


def _text_response(text):
    return {"candidates": [{"content": {"parts": [{"text": text}]}}]}


def _function_call_response(name, args):
    return {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {
                            "functionCall": {"name": name, "args": args},
                            "thoughtSignature": "sig-abc",
                        }
                    ]
                }
            }
        ]
    }


def _mock_post(*responses):
    """Returns a Mock whose .json() yields each response in sequence across
    successive calls, matching one call per requests.post() invocation."""
    mock = Mock()
    mock_responses = []
    for r in responses:
        resp = Mock()
        resp.json.return_value = r
        resp.raise_for_status = Mock()
        mock_responses.append(resp)
    mock.side_effect = mock_responses
    return mock


class TestAskWithoutATool:
    @pytest.mark.asyncio
    async def test_returns_direct_text_answer_when_no_tool_call_is_made(self):
        with patch(
            "requests.post",
            _mock_post(_text_response("Billingonaire is a billing tool.")),
        ):
            result = await assistant.ask(
                "What is this app?", history=[], tool_executor=AsyncMock(), api_key="k"
            )
        assert result["tool_used"] is None
        assert "billing tool" in result["answer"]

    @pytest.mark.asyncio
    async def test_raises_when_model_returns_neither_text_nor_a_function_call(self):
        empty = {"candidates": [{"content": {"parts": []}}]}
        with patch("requests.post", _mock_post(empty)):
            with pytest.raises(assistant.AssistantError):
                await assistant.ask(
                    "hi", history=[], tool_executor=AsyncMock(), api_key="k"
                )


class TestAskWithATool:
    @pytest.mark.asyncio
    async def test_calls_the_requested_tool_and_returns_the_follow_up_answer(self):
        executor = AsyncMock(return_value={"needs_attention_count": 3})
        with patch(
            "requests.post",
            _mock_post(
                _function_call_response("get_queue_status", {}),
                _text_response("You have 3 cases that need attention."),
            ),
        ):
            result = await assistant.ask(
                "How many cases need attention?",
                history=[],
                tool_executor=executor,
                api_key="k",
            )

        executor.assert_called_once_with("get_queue_status", {})
        assert result["tool_used"] == "get_queue_status"
        assert "3 cases" in result["answer"]

    @pytest.mark.asyncio
    async def test_passes_the_models_chosen_args_through_to_the_tool_executor(self):
        executor = AsyncMock(return_value={"total_entries": 5, "total_fees": 6250})
        with patch(
            "requests.post",
            _mock_post(
                _function_call_response(
                    "get_bill_preview",
                    {"start_date": "2026-10-01", "end_date": "2026-10-31"},
                ),
                _text_response("Preview: 5 entries, Rs 6250."),
            ),
        ):
            await assistant.ask(
                "Generate my October bill",
                history=[],
                tool_executor=executor,
                api_key="k",
            )

        executor.assert_called_once_with(
            "get_bill_preview", {"start_date": "2026-10-01", "end_date": "2026-10-31"}
        )

    @pytest.mark.asyncio
    async def test_the_thought_signature_is_preserved_verbatim_in_the_follow_up_call(
        self,
    ):
        """Gemini's function-calling API rejects a follow-up call whose
        history is missing the model's thoughtSignature on the function-call
        turn -- this must be forwarded exactly, not reconstructed."""
        post_mock = _mock_post(
            _function_call_response("get_queue_status", {}),
            _text_response("3 cases."),
        )
        with patch("requests.post", post_mock):
            await assistant.ask(
                "How many cases need attention?",
                history=[],
                tool_executor=AsyncMock(return_value={}),
                api_key="k",
            )

        second_call_kwargs = post_mock.call_args_list[1].kwargs
        model_turn = second_call_kwargs["json"]["contents"][1]
        assert model_turn["role"] == "model"
        assert model_turn["parts"][0]["thoughtSignature"] == "sig-abc"

    @pytest.mark.asyncio
    async def test_rejects_a_tool_name_outside_the_declared_set(self):
        """Should be unreachable in practice (the model can only request
        tools we declared), but this is the hard boundary against ever
        executing anything else -- must not silently call the executor."""
        executor = AsyncMock()
        with patch(
            "requests.post",
            _mock_post(_function_call_response("delete_everything", {})),
        ):
            with pytest.raises(assistant.AssistantError):
                await assistant.ask(
                    "do something bad",
                    history=[],
                    tool_executor=executor,
                    api_key="k",
                )
        executor.assert_not_called()

    @pytest.mark.asyncio
    async def test_raises_when_no_text_follows_the_tool_call(self):
        empty_followup = {"candidates": [{"content": {"parts": []}}]}
        with patch(
            "requests.post",
            _mock_post(_function_call_response("get_queue_status", {}), empty_followup),
        ):
            with pytest.raises(assistant.AssistantError):
                await assistant.ask(
                    "How many cases need attention?",
                    history=[],
                    tool_executor=AsyncMock(return_value={}),
                    api_key="k",
                )


class TestHistoryFormatting:
    @pytest.mark.asyncio
    async def test_assistant_role_is_mapped_to_model_for_the_gemini_api(self):
        post_mock = _mock_post(_text_response("ok"))
        with patch("requests.post", post_mock):
            await assistant.ask(
                "follow-up question",
                history=[
                    {"role": "user", "text": "first question"},
                    {"role": "assistant", "text": "first answer"},
                ],
                tool_executor=AsyncMock(),
                api_key="k",
            )

        sent_contents = post_mock.call_args_list[0].kwargs["json"]["contents"]
        assert sent_contents[0]["role"] == "user"
        assert sent_contents[1]["role"] == "model"
        assert sent_contents[2]["parts"][0]["text"] == "follow-up question"


class TestToolDeclarations:
    def test_every_declared_tool_has_a_name_and_description(self):
        for decl in assistant.TOOL_DECLARATIONS:
            assert decl["name"]
            assert decl["description"]

    def test_tool_names_are_unique(self):
        names = [d["name"] for d in assistant.TOOL_DECLARATIONS]
        assert len(names) == len(set(names))

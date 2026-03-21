"""Tests for inference functions (using mocks — no live API)."""

from dataclasses import dataclass
from typing import Optional
from unittest.mock import AsyncMock, patch

import pytest

from theact.llm.config import AgentLLMConfig, LLMConfig
from theact.llm.inference import (
    _extract_think_tags,
    complete,
    complete_structured,
)
from theact.llm.parsing import YAMLParseError
from theact.llm.streaming import LLMResult, StructuredResult


class TestExtractThinkTags:
    def test_no_tags(self):
        content, thinking = _extract_think_tags("Hello world")
        assert content == "Hello world"
        assert thinking == ""

    def test_single_tag(self):
        content, thinking = _extract_think_tags("Before<think>reasoning</think>After")
        assert content == "BeforeAfter"
        assert thinking == "reasoning"

    def test_multiple_tags(self):
        content, thinking = _extract_think_tags(
            "<think>first</think>Middle<think>second</think>End"
        )
        assert content == "MiddleEnd"
        assert "first" in thinking
        assert "second" in thinking

    def test_multiline_think(self):
        content, thinking = _extract_think_tags(
            "<think>line1\nline2\nline3</think>Result"
        )
        assert content == "Result"
        assert "line1" in thinking
        assert "line3" in thinking

    def test_only_think_tags(self):
        content, thinking = _extract_think_tags("<think>only thinking</think>")
        assert content == ""
        assert thinking == "only thinking"


# --- Mock helpers ---


@dataclass
class FakeMessage:
    content: Optional[str] = None
    model_extra: Optional[dict] = None


@dataclass
class FakeChoice:
    message: FakeMessage
    finish_reason: str = "stop"


@dataclass
class FakeUsage:
    prompt_tokens: int = 10
    completion_tokens: int = 20


@dataclass
class FakeResponse:
    choices: list[FakeChoice]
    usage: Optional[FakeUsage] = None


def make_response(content: str, thinking: str = "", finish_reason: str = "stop"):
    """Create a fake non-streaming API response."""
    model_extra = None
    if thinking:
        model_extra = {"reasoning_content": thinking}

    return FakeResponse(
        choices=[
            FakeChoice(
                message=FakeMessage(content=content, model_extra=model_extra),
                finish_reason=finish_reason,
            )
        ],
        usage=FakeUsage(prompt_tokens=10, completion_tokens=20),
    )


class TestComplete:
    @pytest.mark.asyncio
    async def test_basic_completion(self):
        config = LLMConfig(api_key="test")
        response = make_response("Hello world")

        with patch("theact.llm.inference._call_api", new_callable=AsyncMock) as mock:
            mock.return_value = response
            result = await complete([{"role": "user", "content": "test"}], config)

        assert isinstance(result, LLMResult)
        assert result.content == "Hello world"
        assert result.finish_reason == "stop"
        assert result.prompt_tokens == 10
        assert result.completion_tokens == 20

    @pytest.mark.asyncio
    async def test_thinking_via_model_extra(self):
        config = LLMConfig(api_key="test")
        response = make_response("The answer is 4", thinking="2+2=4")

        with patch("theact.llm.inference._call_api", new_callable=AsyncMock) as mock:
            mock.return_value = response
            result = await complete([{"role": "user", "content": "test"}], config)

        assert result.content == "The answer is 4"
        assert "2+2=4" in result.thinking

    @pytest.mark.asyncio
    async def test_thinking_via_think_tags(self):
        config = LLMConfig(api_key="test")
        response = make_response("<think>reasoning</think>The answer")

        with patch("theact.llm.inference._call_api", new_callable=AsyncMock) as mock:
            mock.return_value = response
            result = await complete([{"role": "user", "content": "test"}], config)

        assert result.content == "The answer"
        assert "reasoning" in result.thinking

    @pytest.mark.asyncio
    async def test_agent_config_passed(self):
        config = LLMConfig(api_key="test")
        agent_config = AgentLLMConfig(temperature=0.5, max_tokens=200)
        response = make_response("ok")

        with patch("theact.llm.inference._call_api", new_callable=AsyncMock) as mock:
            mock.return_value = response
            await complete([{"role": "user", "content": "test"}], config, agent_config)
            mock.assert_called_once_with(
                [{"role": "user", "content": "test"}], config, agent_config
            )


class TestCompleteStructured:
    @pytest.mark.asyncio
    async def test_successful_yaml(self):
        config = LLMConfig(api_key="test")
        response = make_response("```yaml\nkey: value\n```")

        with patch("theact.llm.inference._call_api", new_callable=AsyncMock) as mock:
            mock.return_value = response
            result = await complete_structured(
                [{"role": "user", "content": "test"}], config
            )

        assert isinstance(result, StructuredResult)
        assert result.data == {"key": "value"}
        assert result.attempts == 1

    @pytest.mark.asyncio
    async def test_retry_on_parse_failure(self):
        config = LLMConfig(api_key="test")
        # First call returns bad YAML, second returns good YAML
        bad_response = make_response("not valid yaml {[}")
        good_response = make_response("```yaml\nkey: value\n```")

        call_count = 0

        async def mock_call(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return bad_response
            return good_response

        with patch("theact.llm.inference._call_api", side_effect=mock_call):
            result = await complete_structured(
                [{"role": "user", "content": "test"}], config
            )

        assert result.data == {"key": "value"}
        assert result.attempts == 2

    @pytest.mark.asyncio
    async def test_exhausted_retries_raises(self):
        config = LLMConfig(api_key="test")
        agent_config = AgentLLMConfig(structured=True, max_retries=1)
        bad_response = make_response("not yaml at all {[}")

        with patch("theact.llm.inference._call_api", new_callable=AsyncMock) as mock:
            mock.return_value = bad_response
            with pytest.raises(YAMLParseError, match="Failed to parse YAML after"):
                await complete_structured(
                    [{"role": "user", "content": "test"}],
                    config,
                    agent_config,
                )

    @pytest.mark.asyncio
    async def test_yaml_hint_included_in_retry(self):
        config = LLMConfig(api_key="test")
        agent_config = AgentLLMConfig(structured=True, max_retries=1)
        bad_response = make_response("bad {[}")
        good_response = make_response("```yaml\nkey: value\n```")

        calls = []

        async def mock_call(messages, *args, **kwargs):
            calls.append(messages)
            if len(calls) == 1:
                return bad_response
            return good_response

        with patch("theact.llm.inference._call_api", side_effect=mock_call):
            await complete_structured(
                [{"role": "user", "content": "test"}],
                config,
                agent_config,
                yaml_hint="key: value",
            )

        # The second call should include the hint in the retry message
        assert len(calls) == 2
        last_message = calls[1][-1]  # last message in the retry
        assert "key: value" in last_message["content"]

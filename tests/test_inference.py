"""Tests for inference functions (using mocks — no live API)."""

from dataclasses import dataclass
from typing import Optional
from unittest.mock import AsyncMock, patch

import httpx
import openai
import pytest

from theact.llm.config import AgentLLMConfig, LLMConfig
from theact.llm.errors import LLMConnectionError, LLMRateLimitError, LLMResponseError
from theact.llm.inference import (
    _call_api,
    _extract_think_tags,
    complete,
    complete_structured,
    stream,
    stream_structured,
)
from theact.llm.parsing import YAMLParseError
from theact.llm.streaming import LLMResult, StreamChunk, StructuredResult


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


# --- Helpers for streaming tests ---


@dataclass
class FakeDelta:
    content: Optional[str] = None
    model_extra: Optional[dict] = None


@dataclass
class FakeStreamChoice:
    delta: FakeDelta
    finish_reason: Optional[str] = None


@dataclass
class FakeStreamChunk:
    choices: list[FakeStreamChoice]


class AsyncChunkIterator:
    """Async iterator over a list of fake stream chunks."""

    def __init__(self, chunks):
        self._chunks = chunks
        self._index = 0

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._index >= len(self._chunks):
            raise StopAsyncIteration
        chunk = self._chunks[self._index]
        self._index += 1
        return chunk


def make_stream_chunks(specs: list[dict]) -> list[FakeStreamChunk]:
    """Create fake streaming chunks from specs.

    Each spec can have: content, reasoning_content, finish_reason.
    """
    chunks = []
    for spec in specs:
        model_extra = None
        if "reasoning_content" in spec:
            model_extra = {"reasoning_content": spec["reasoning_content"]}
        delta = FakeDelta(
            content=spec.get("content"),
            model_extra=model_extra,
        )
        choice = FakeStreamChoice(
            delta=delta,
            finish_reason=spec.get("finish_reason"),
        )
        chunks.append(FakeStreamChunk(choices=[choice]))
    return chunks


def _make_fake_request() -> httpx.Request:
    """Create a fake httpx.Request for constructing openai exceptions."""
    return httpx.Request("POST", "https://api.venice.ai/api/v1/chat/completions")


def _make_fake_response(
    status_code: int, headers: dict | None = None
) -> httpx.Response:
    """Create a fake httpx.Response for constructing openai exceptions."""
    return httpx.Response(
        status_code=status_code,
        request=_make_fake_request(),
        headers=headers or {},
    )


# --- Tests for _call_api error wrapping ---


class TestCallApiErrorWrapping:
    """Test that _call_api wraps openai exceptions into our error hierarchy."""

    @pytest.mark.asyncio
    async def test_connection_error_wrapped(self):
        """openai.APIConnectionError -> LLMConnectionError."""
        config = LLMConfig(api_key="test")
        openai_err = openai.APIConnectionError(request=_make_fake_request())

        with patch("theact.llm.inference.get_client") as mock_get_client:
            mock_client = AsyncMock()
            mock_client.chat.completions.create.side_effect = openai_err
            mock_get_client.return_value = mock_client

            with pytest.raises(LLMConnectionError, match="Cannot reach"):
                await _call_api([{"role": "user", "content": "hi"}], config, None)

    @pytest.mark.asyncio
    async def test_rate_limit_error_wrapped(self):
        """openai.RateLimitError -> LLMRateLimitError with retry_after."""
        config = LLMConfig(api_key="test")
        fake_response = _make_fake_response(429, {"retry-after": "30"})
        openai_err = openai.RateLimitError(
            message="Rate limit exceeded",
            response=fake_response,
            body=None,
        )

        with patch("theact.llm.inference.get_client") as mock_get_client:
            mock_client = AsyncMock()
            mock_client.chat.completions.create.side_effect = openai_err
            mock_get_client.return_value = mock_client

            with pytest.raises(LLMRateLimitError) as exc_info:
                await _call_api([{"role": "user", "content": "hi"}], config, None)

            assert exc_info.value.retry_after == 30.0

    @pytest.mark.asyncio
    async def test_rate_limit_error_no_retry_after_header(self):
        """LLMRateLimitError.retry_after is None when header is absent."""
        config = LLMConfig(api_key="test")
        fake_response = _make_fake_response(429)
        openai_err = openai.RateLimitError(
            message="Rate limit exceeded",
            response=fake_response,
            body=None,
        )

        with patch("theact.llm.inference.get_client") as mock_get_client:
            mock_client = AsyncMock()
            mock_client.chat.completions.create.side_effect = openai_err
            mock_get_client.return_value = mock_client

            with pytest.raises(LLMRateLimitError) as exc_info:
                await _call_api([{"role": "user", "content": "hi"}], config, None)

            assert exc_info.value.retry_after is None

    @pytest.mark.asyncio
    async def test_api_status_error_wrapped(self):
        """openai.APIStatusError -> LLMResponseError."""
        config = LLMConfig(api_key="test")
        fake_response = _make_fake_response(500)
        openai_err = openai.APIStatusError(
            message="Internal server error",
            response=fake_response,
            body=None,
        )

        with patch("theact.llm.inference.get_client") as mock_get_client:
            mock_client = AsyncMock()
            mock_client.chat.completions.create.side_effect = openai_err
            mock_get_client.return_value = mock_client

            with pytest.raises(LLMResponseError, match="API error 500"):
                await _call_api([{"role": "user", "content": "hi"}], config, None)


# --- Tests for stream() ---


class TestStream:
    """Test the stream() function returns a proper AsyncIterator[StreamChunk]."""

    @pytest.mark.asyncio
    async def test_stream_returns_async_iterator(self):
        """stream() yields StreamChunk objects from the API stream."""
        chunks = make_stream_chunks(
            [
                {"content": "Hello "},
                {"content": "world!"},
                {"finish_reason": "stop"},
            ]
        )
        fake_api_response = AsyncChunkIterator(chunks)

        with patch("theact.llm.inference._call_api", new_callable=AsyncMock) as mock:
            mock.return_value = fake_api_response
            config = LLMConfig(api_key="test")
            result_stream = await stream([{"role": "user", "content": "hi"}], config)

            collected: list[StreamChunk] = []
            async for chunk in result_stream:
                collected.append(chunk)
                assert isinstance(chunk, StreamChunk)

            content_parts = [c.content for c in collected if c.is_content]
            assert "".join(content_parts) == "Hello world!"
            assert any(c.is_done for c in collected)

    @pytest.mark.asyncio
    async def test_stream_passes_agent_config(self):
        """stream() passes agent_config through to _call_api."""
        chunks = make_stream_chunks([{"finish_reason": "stop"}])
        fake_api_response = AsyncChunkIterator(chunks)

        with patch("theact.llm.inference._call_api", new_callable=AsyncMock) as mock:
            mock.return_value = fake_api_response
            config = LLMConfig(api_key="test")
            agent_config = AgentLLMConfig(temperature=0.5)

            result_stream = await stream(
                [{"role": "user", "content": "hi"}], config, agent_config
            )
            # Consume the stream
            async for _ in result_stream:
                pass

            mock.assert_called_once_with(
                [{"role": "user", "content": "hi"}],
                config,
                agent_config,
                stream_mode=True,
            )


# --- Tests for stream_structured() ---


class TestStreamStructured:
    """Test stream_structured() returns (stream, future) with correct behavior."""

    @pytest.mark.asyncio
    async def test_stream_and_future_on_valid_yaml(self):
        """Consuming the stream yields StreamChunks, and the future resolves
        to a StructuredResult when the content contains valid YAML."""
        # Split the YAML content across multiple chunks to simulate streaming
        chunks = make_stream_chunks(
            [
                {"content": "```yaml\n"},
                {"content": "status: complete\n"},
                {"content": "action: move_north\n"},
                {"content": "```"},
                {"finish_reason": "stop"},
            ]
        )
        fake_api_response = AsyncChunkIterator(chunks)

        with patch("theact.llm.inference._call_api", new_callable=AsyncMock) as mock:
            mock.return_value = fake_api_response
            config = LLMConfig(api_key="test")

            result_stream, future = await stream_structured(
                [{"role": "user", "content": "do something"}], config
            )

            # Consume the stream and verify we get StreamChunks
            collected: list[StreamChunk] = []
            async for chunk in result_stream:
                collected.append(chunk)
                assert isinstance(chunk, StreamChunk)

            assert len(collected) > 0
            assert any(c.is_content for c in collected)

            # After consuming stream, the future should resolve
            result = await future
            assert isinstance(result, StructuredResult)
            assert result.data == {"status": "complete", "action": "move_north"}
            assert result.finish_reason == "stop"

    @pytest.mark.asyncio
    async def test_future_receives_yaml_parse_error_on_invalid_content(self):
        """When streamed content has no valid YAML, the future gets a
        YAMLParseError exception."""
        chunks = make_stream_chunks(
            [
                {"content": "This is just plain text "},
                {"content": "with no YAML at all {[}"},
                {"finish_reason": "stop"},
            ]
        )
        fake_api_response = AsyncChunkIterator(chunks)

        with patch("theact.llm.inference._call_api", new_callable=AsyncMock) as mock:
            mock.return_value = fake_api_response
            config = LLMConfig(api_key="test")

            result_stream, future = await stream_structured(
                [{"role": "user", "content": "do something"}], config
            )

            # Consume the stream fully
            async for _ in result_stream:
                pass

            # The future should have a YAMLParseError
            with pytest.raises(YAMLParseError):
                await future

    @pytest.mark.asyncio
    async def test_stream_captures_thinking_chunks(self):
        """Thinking tokens are captured and included in the StructuredResult."""
        chunks = make_stream_chunks(
            [
                {"reasoning_content": "Let me think about this..."},
                {"content": "```yaml\nresult: ok\n```"},
                {"finish_reason": "stop"},
            ]
        )
        fake_api_response = AsyncChunkIterator(chunks)

        with patch("theact.llm.inference._call_api", new_callable=AsyncMock) as mock:
            mock.return_value = fake_api_response
            config = LLMConfig(api_key="test")

            result_stream, future = await stream_structured(
                [{"role": "user", "content": "do something"}], config
            )

            async for _ in result_stream:
                pass

            result = await future
            assert isinstance(result, StructuredResult)
            assert result.data == {"result": "ok"}
            assert "Let me think about this..." in result.thinking

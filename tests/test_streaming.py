"""Tests for streaming result types and stream processing."""

from dataclasses import dataclass
from typing import Optional

import pytest

from theact.llm.streaming import (
    LLMResult,
    StreamChunk,
    StructuredResult,
    collect_stream,
    process_stream,
)


class TestStreamChunkProperties:
    def test_is_thinking(self):
        chunk = StreamChunk(thinking="reasoning here")
        assert chunk.is_thinking is True
        assert chunk.is_content is False
        assert chunk.is_done is False

    def test_is_content(self):
        chunk = StreamChunk(content="hello")
        assert chunk.is_thinking is False
        assert chunk.is_content is True
        assert chunk.is_done is False

    def test_is_done(self):
        chunk = StreamChunk(finish_reason="stop")
        assert chunk.is_thinking is False
        assert chunk.is_content is False
        assert chunk.is_done is True

    def test_empty_chunk(self):
        chunk = StreamChunk()
        assert chunk.is_thinking is False
        assert chunk.is_content is False
        assert chunk.is_done is False


class TestLLMResult:
    def test_total_tokens_both_present(self):
        result = LLMResult(
            content="test",
            thinking="",
            finish_reason="stop",
            prompt_tokens=100,
            completion_tokens=50,
        )
        assert result.total_tokens == 150

    def test_total_tokens_none_when_missing(self):
        result = LLMResult(
            content="test",
            thinking="",
            finish_reason="stop",
        )
        assert result.total_tokens is None

    def test_total_tokens_none_partial(self):
        result = LLMResult(
            content="test",
            thinking="",
            finish_reason="stop",
            prompt_tokens=100,
        )
        assert result.total_tokens is None


class TestStructuredResult:
    def test_basic(self):
        result = StructuredResult(
            data={"key": "value"},
            raw_content="```yaml\nkey: value\n```",
            thinking="thought about it",
            attempts=1,
        )
        assert result.data["key"] == "value"
        assert result.attempts == 1


# --- Helpers for simulating OpenAI streaming responses ---


@dataclass
class FakeDelta:
    content: Optional[str] = None
    model_extra: Optional[dict] = None


@dataclass
class FakeChoice:
    delta: FakeDelta
    finish_reason: Optional[str] = None


@dataclass
class FakeChunk:
    choices: list[FakeChoice]


def make_chunks(specs: list[dict]) -> list[FakeChunk]:
    """Create fake streaming chunks from a list of specs.

    Each spec can have:
    - content: str -- delta content text
    - reasoning_content: str -- thinking via model_extra
    - finish_reason: str -- e.g. "stop"
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
        choice = FakeChoice(
            delta=delta,
            finish_reason=spec.get("finish_reason"),
        )
        chunks.append(FakeChunk(choices=[choice]))
    return chunks


class AsyncChunkIterator:
    """Async iterator over a list of fake chunks."""

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


class TestProcessStream:
    @pytest.mark.asyncio
    async def test_plain_content(self):
        chunks = make_chunks(
            [
                {"content": "Hello "},
                {"content": "world!"},
                {"finish_reason": "stop"},
            ]
        )
        result_chunks = []
        async for c in process_stream(AsyncChunkIterator(chunks)):
            result_chunks.append(c)

        contents = [c.content for c in result_chunks if c.is_content]
        assert "".join(contents) == "Hello world!"
        assert any(c.is_done for c in result_chunks)

    @pytest.mark.asyncio
    async def test_reasoning_via_model_extra(self):
        chunks = make_chunks(
            [
                {"reasoning_content": "Let me think..."},
                {"reasoning_content": " about this."},
                {"content": "The answer is 4."},
                {"finish_reason": "stop"},
            ]
        )
        result_chunks = []
        async for c in process_stream(AsyncChunkIterator(chunks)):
            result_chunks.append(c)

        thinking = [c.thinking for c in result_chunks if c.is_thinking]
        content = [c.content for c in result_chunks if c.is_content]
        assert "".join(thinking) == "Let me think... about this."
        assert "".join(content) == "The answer is 4."

    @pytest.mark.asyncio
    async def test_think_tags_single_chunk(self):
        chunks = make_chunks(
            [
                {"content": "<think>reasoning here</think>The answer."},
                {"finish_reason": "stop"},
            ]
        )
        result_chunks = []
        async for c in process_stream(AsyncChunkIterator(chunks)):
            result_chunks.append(c)

        thinking = [c.thinking for c in result_chunks if c.is_thinking]
        content = [c.content for c in result_chunks if c.is_content]
        assert "".join(thinking) == "reasoning here"
        assert "".join(content) == "The answer."

    @pytest.mark.asyncio
    async def test_think_tags_split_across_chunks(self):
        chunks = make_chunks(
            [
                {"content": "<think>start of thinking"},
                {"content": " more thinking</think>actual content"},
                {"finish_reason": "stop"},
            ]
        )
        result_chunks = []
        async for c in process_stream(AsyncChunkIterator(chunks)):
            result_chunks.append(c)

        thinking = [c.thinking for c in result_chunks if c.is_thinking]
        content = [c.content for c in result_chunks if c.is_content]
        assert "".join(thinking) == "start of thinking more thinking"
        assert "".join(content) == "actual content"

    @pytest.mark.asyncio
    async def test_empty_choices_skipped(self):
        chunks = [
            FakeChunk(choices=[]),
            FakeChunk(
                choices=[
                    FakeChoice(delta=FakeDelta(content="hello"), finish_reason="stop")
                ]
            ),
        ]
        result_chunks = []
        async for c in process_stream(AsyncChunkIterator(chunks)):
            result_chunks.append(c)

        assert len(result_chunks) == 2  # content + done
        assert result_chunks[0].content == "hello"

    @pytest.mark.asyncio
    async def test_content_before_think_tag(self):
        chunks = make_chunks(
            [
                {"content": "Before<think>thinking</think>After"},
                {"finish_reason": "stop"},
            ]
        )
        result_chunks = []
        async for c in process_stream(AsyncChunkIterator(chunks)):
            result_chunks.append(c)

        content = [c.content for c in result_chunks if c.is_content]
        thinking = [c.thinking for c in result_chunks if c.is_thinking]
        assert "".join(content) == "BeforeAfter"
        assert "".join(thinking) == "thinking"


class TestCollectStream:
    @pytest.mark.asyncio
    async def test_collect(self):
        async def fake_stream():
            yield StreamChunk(thinking="thought")
            yield StreamChunk(content="hello ")
            yield StreamChunk(content="world")
            yield StreamChunk(finish_reason="stop")

        result = await collect_stream(fake_stream())
        assert result.content == "hello world"
        assert result.thinking == "thought"
        assert result.finish_reason == "stop"

    @pytest.mark.asyncio
    async def test_collect_empty_stream(self):
        async def empty_stream():
            yield StreamChunk(finish_reason="stop")

        result = await collect_stream(empty_stream())
        assert result.content == ""
        assert result.thinking == ""
        assert result.finish_reason == "stop"

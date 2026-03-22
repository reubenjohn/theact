"""Edge-case tests for streaming think-tag buffer management.

Covers partial-tag buffering, model_extra.reasoning fallback,
tag buffer flushing on finish_reason, and other missed branches
in process_stream().
"""

from dataclasses import dataclass
from typing import Optional

import pytest

from theact.llm.streaming import collect_stream, process_stream


# --- Helpers (same pattern as test_streaming.py) ---


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


class AsyncChunkIterator:
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


def _make_chunk(
    content=None,
    reasoning_content=None,
    reasoning=None,
    finish_reason=None,
):
    """Build a single FakeChunk with the given fields."""
    model_extra = None
    if reasoning_content is not None:
        model_extra = {"reasoning_content": reasoning_content}
    elif reasoning is not None:
        # Use the "reasoning" key (fallback path, line 103)
        model_extra = {"reasoning": reasoning}

    delta = FakeDelta(content=content, model_extra=model_extra)
    choice = FakeChoice(delta=delta, finish_reason=finish_reason)
    return FakeChunk(choices=[choice])


async def _collect(chunks):
    """Run process_stream and gather all yielded StreamChunks."""
    result = []
    async for c in process_stream(AsyncChunkIterator(chunks)):
        result.append(c)
    return result


def _thinking(chunks):
    return "".join(c.thinking for c in chunks if c.is_thinking)


def _content(chunks):
    return "".join(c.content for c in chunks if c.is_content)


# ------------------------------------------------------------------
# Tests for the "reasoning" fallback key in model_extra (line 103)
# ------------------------------------------------------------------


class TestReasoningFallbackKey:
    @pytest.mark.asyncio
    async def test_reasoning_key_in_model_extra(self):
        """When reasoning_content is absent but 'reasoning' key exists,
        it should be treated as thinking content (line 103)."""
        chunks = [
            _make_chunk(reasoning="Thinking via reasoning key"),
            _make_chunk(content="Answer."),
            _make_chunk(finish_reason="stop"),
        ]
        result = await _collect(chunks)
        assert _thinking(result) == "Thinking via reasoning key"
        assert _content(result) == "Answer."

    @pytest.mark.asyncio
    async def test_reasoning_content_takes_priority(self):
        """When both keys exist, reasoning_content should win."""
        chunk = FakeChunk(
            choices=[
                FakeChoice(
                    delta=FakeDelta(
                        content=None,
                        model_extra={
                            "reasoning_content": "primary",
                            "reasoning": "fallback",
                        },
                    ),
                    finish_reason=None,
                )
            ]
        )
        result = await _collect([chunk, _make_chunk(finish_reason="stop")])
        assert _thinking(result) == "primary"

    @pytest.mark.asyncio
    async def test_model_extra_both_none(self):
        """When model_extra has both keys as None, should proceed to content."""
        chunk = FakeChunk(
            choices=[
                FakeChoice(
                    delta=FakeDelta(
                        content="real content",
                        model_extra={"reasoning_content": None, "reasoning": None},
                    ),
                    finish_reason=None,
                )
            ]
        )
        result = await _collect([chunk, _make_chunk(finish_reason="stop")])
        assert _content(result) == "real content"


# ------------------------------------------------------------------
# Tests for tag buffer prepending (lines 113-114)
# ------------------------------------------------------------------


class TestTagBufferPrepending:
    @pytest.mark.asyncio
    async def test_partial_open_tag_split(self):
        """'<thi' buffered from chunk1, then 'nk>thinking</think>done'
        completes the tag in chunk2."""
        chunks = [
            _make_chunk(content="Hello <thi"),
            _make_chunk(content="nk>thinking</think>done"),
            _make_chunk(finish_reason="stop"),
        ]
        result = await _collect(chunks)
        assert _content(result) == "Hello done"
        assert _thinking(result) == "thinking"

    @pytest.mark.asyncio
    async def test_partial_close_tag_split(self):
        """'</thi' buffered from within a think block, then 'nk>after'
        completes the close tag."""
        chunks = [
            _make_chunk(content="<think>thought</thi"),
            _make_chunk(content="nk>after"),
            _make_chunk(finish_reason="stop"),
        ]
        result = await _collect(chunks)
        assert _thinking(result) == "thought"
        assert _content(result) == "after"

    @pytest.mark.asyncio
    async def test_single_angle_bracket_buffered(self):
        """A trailing '<' should be buffered and prepended to the next chunk."""
        chunks = [
            _make_chunk(content="before<"),
            _make_chunk(content="think>deep thought</think>after"),
            _make_chunk(finish_reason="stop"),
        ]
        result = await _collect(chunks)
        assert _content(result) == "beforeafter"
        assert _thinking(result) == "deep thought"


# ------------------------------------------------------------------
# Tests for trailing partial-tag buffering (lines 120-122)
# ------------------------------------------------------------------


class TestTrailingPartialTagBuffering:
    @pytest.mark.asyncio
    async def test_various_partial_prefixes(self):
        """Each recognized tag prefix should be buffered."""
        for partial in ["<", "<t", "<th", "<thi", "<thin", "<think"]:
            chunks = [
                _make_chunk(content=f"text{partial}"),
                _make_chunk(content="remaining "),
                _make_chunk(finish_reason="stop"),
            ]
            result = await _collect(chunks)
            combined = _content(result)
            assert combined == f"text{partial}remaining ", (
                f"Failed for partial prefix {partial!r}"
            )

    @pytest.mark.asyncio
    async def test_close_tag_partial_prefixes(self):
        """Close-tag partial prefixes should also be buffered."""
        for partial in ["</", "</t", "</th", "</thi", "</thin", "</think"]:
            chunks = [
                _make_chunk(content=f"text{partial}"),
                _make_chunk(content="remaining "),
                _make_chunk(finish_reason="stop"),
            ]
            result = await _collect(chunks)
            combined = _content(result)
            assert combined == f"text{partial}remaining ", (
                f"Failed for close partial prefix {partial!r}"
            )


# ------------------------------------------------------------------
# Tests for tag buffer flushing with finish_reason (lines 141-147)
# ------------------------------------------------------------------


class TestTagBufferFlushOnFinishInThinkBlock:
    @pytest.mark.asyncio
    async def test_finish_reason_inside_open_think_tag(self):
        """When finish_reason arrives on the same chunk as <think>,
        and there is still buffered text, it must be flushed (lines 140-147)."""
        # Construct: content has <think> with trailing partial that gets buffered,
        # and finish_reason on same chunk
        chunks = [
            FakeChunk(
                choices=[
                    FakeChoice(
                        delta=FakeDelta(content="<think>thought<"),
                        finish_reason="stop",
                    )
                ]
            ),
        ]
        result = await _collect(chunks)
        thinking = _thinking(result)
        assert "thought" in thinking
        assert any(c.is_done for c in result)

    @pytest.mark.asyncio
    async def test_finish_reason_with_think_open_and_close_same_chunk(self):
        """<think>...</think> plus finish_reason in a single chunk."""
        chunks = [
            FakeChunk(
                choices=[
                    FakeChoice(
                        delta=FakeDelta(content="<think>thought</think>answer"),
                        finish_reason="stop",
                    )
                ]
            ),
        ]
        result = await _collect(chunks)
        assert _thinking(result) == "thought"
        assert _content(result) == "answer"
        assert any(c.is_done for c in result)


# ------------------------------------------------------------------
# Tests for tag buffer flushing when closing think tag (lines 158-164)
# ------------------------------------------------------------------


class TestTagBufferFlushOnCloseThinkTag:
    @pytest.mark.asyncio
    async def test_close_tag_with_finish_reason_and_tag_buffer(self):
        """</think> with finish_reason and leftover tag buffer (lines 157-164).
        The buffer should be flushed as content (in_think_tag=False after close)."""
        # First chunk opens the think tag
        # Second chunk closes it, has trailing partial that buffers,
        # plus finish_reason
        chunks = [
            _make_chunk(content="<think>reasoning"),
            FakeChunk(
                choices=[
                    FakeChoice(
                        delta=FakeDelta(content="</think>done<"),
                        finish_reason="stop",
                    )
                ]
            ),
        ]
        result = await _collect(chunks)
        assert _thinking(result) == "reasoning"
        # The content should include "done" plus the flushed buffer "<"
        content = _content(result)
        assert "done" in content
        assert any(c.is_done for c in result)

    @pytest.mark.asyncio
    async def test_close_tag_with_finish_reason_no_buffer(self):
        """</think> with finish_reason but no trailing tag buffer."""
        chunks = [
            _make_chunk(content="<think>thought"),
            FakeChunk(
                choices=[
                    FakeChoice(
                        delta=FakeDelta(content="</think>result"),
                        finish_reason="stop",
                    )
                ]
            ),
        ]
        result = await _collect(chunks)
        assert _thinking(result) == "thought"
        assert _content(result) == "result"
        assert any(c.is_done for c in result)


# ------------------------------------------------------------------
# Tests for streaming thinking content inside think tag (lines 168-169)
# ------------------------------------------------------------------


class TestStreamingThinkingContent:
    @pytest.mark.asyncio
    async def test_multi_chunk_thinking(self):
        """Multiple chunks of thinking content inside <think> tags."""
        chunks = [
            _make_chunk(content="<think>part1"),
            _make_chunk(content=" part2"),
            _make_chunk(content=" part3"),
            _make_chunk(content="</think>answer"),
            _make_chunk(finish_reason="stop"),
        ]
        result = await _collect(chunks)
        assert _thinking(result) == "part1 part2 part3"
        assert _content(result) == "answer"

    @pytest.mark.asyncio
    async def test_empty_content_inside_think_tag(self):
        """Empty content delta inside a think block should not yield."""
        chunks = [
            _make_chunk(content="<think>start"),
            _make_chunk(content=""),  # empty delta
            _make_chunk(content="end</think>done"),
            _make_chunk(finish_reason="stop"),
        ]
        result = await _collect(chunks)
        assert _thinking(result) == "startend"
        assert _content(result) == "done"


# ------------------------------------------------------------------
# Tests for final tag buffer flush at end of stream (lines 176-180)
# ------------------------------------------------------------------


class TestFinalTagBufferFlush:
    @pytest.mark.asyncio
    async def test_tag_buffer_flushed_as_content_on_finish(self):
        """Tag buffer with trailing partial '<t' should flush as content
        when finish_reason arrives (not inside think tag)."""
        chunks = [
            _make_chunk(content="Hello world<t"),
            _make_chunk(finish_reason="stop"),
        ]
        result = await _collect(chunks)
        content = _content(result)
        assert content == "Hello world<t"

    @pytest.mark.asyncio
    async def test_tag_buffer_flushed_as_thinking_on_finish(self):
        """Tag buffer should flush as thinking when inside a think tag."""
        chunks = [
            _make_chunk(content="<think>thought<t"),
            _make_chunk(finish_reason="stop"),
        ]
        result = await _collect(chunks)
        thinking = _thinking(result)
        assert "thought" in thinking
        assert "<t" in thinking

    @pytest.mark.asyncio
    async def test_tag_buffer_flushed_when_finish_reason_on_separate_chunk(self):
        """Finish reason comes in a chunk with no content — buffer still flushed."""
        chunks = [
            _make_chunk(content="data</"),
            _make_chunk(content=None, finish_reason="stop"),
        ]
        result = await _collect(chunks)
        content = _content(result)
        # The '</' was buffered, then flushed with finish_reason
        assert content == "data</"
        assert any(c.is_done for c in result)


# ------------------------------------------------------------------
# Additional integration-style edge cases
# ------------------------------------------------------------------


class TestMiscEdgeCases:
    @pytest.mark.asyncio
    async def test_think_tag_exactly_at_chunk_boundary(self):
        """<think> split as '<think' (buffered) then '>' next chunk."""
        chunks = [
            _make_chunk(content="before<think"),
            _make_chunk(content=">inside</think>after"),
            _make_chunk(finish_reason="stop"),
        ]
        result = await _collect(chunks)
        assert _content(result) == "beforeafter"
        assert _thinking(result) == "inside"

    @pytest.mark.asyncio
    async def test_no_model_extra_attribute(self):
        """Delta object without model_extra attr should not crash."""

        @dataclass
        class BareDelta:
            content: Optional[str] = None

        chunks = [
            FakeChunk(
                choices=[
                    FakeChoice(delta=BareDelta(content="hello"), finish_reason=None)
                ]
            ),
            FakeChunk(
                choices=[
                    FakeChoice(delta=BareDelta(content=None), finish_reason="stop")
                ]
            ),
        ]
        result = await _collect(chunks)
        assert _content(result) == "hello"

    @pytest.mark.asyncio
    async def test_model_extra_is_none(self):
        """Delta with model_extra=None should not crash."""
        chunks = [
            _make_chunk(content="text"),
            _make_chunk(finish_reason="stop"),
        ]
        # model_extra is None by default in _make_chunk when no reasoning
        result = await _collect(chunks)
        assert _content(result) == "text"

    @pytest.mark.asyncio
    async def test_collect_stream_finish_reason_propagated(self):
        """collect_stream should capture the finish reason from the final chunk."""
        chunks = [
            _make_chunk(content="<think>thought</think>answer"),
            _make_chunk(finish_reason="length"),
        ]

        async def gen():
            async for c in process_stream(AsyncChunkIterator(chunks)):
                yield c

        result = await collect_stream(gen())
        assert result.content == "answer"
        assert result.thinking == "thought"
        assert result.finish_reason == "length"

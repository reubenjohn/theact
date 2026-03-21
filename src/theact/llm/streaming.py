"""Result types and stream processing for LLM responses."""

from __future__ import annotations

from dataclasses import dataclass
from typing import AsyncIterator


@dataclass
class LLMResult:
    """Complete response from a non-streaming LLM call."""

    content: str
    thinking: str  # thinking/reasoning tokens (may be empty)
    finish_reason: str  # "stop", "length", etc.
    prompt_tokens: int | None = None
    completion_tokens: int | None = None

    @property
    def total_tokens(self) -> int | None:
        if self.prompt_tokens is not None and self.completion_tokens is not None:
            return self.prompt_tokens + self.completion_tokens
        return None


@dataclass
class StreamChunk:
    """A single chunk from a streaming response."""

    content: str = ""  # response content delta
    thinking: str = ""  # thinking content delta
    finish_reason: str | None = None

    @property
    def is_thinking(self) -> bool:
        return len(self.thinking) > 0

    @property
    def is_content(self) -> bool:
        return len(self.content) > 0

    @property
    def is_done(self) -> bool:
        return self.finish_reason is not None


@dataclass
class StructuredResult:
    """Result from a structured (YAML-parsed) LLM call."""

    data: dict  # parsed YAML as a Python dict
    raw_content: str  # the full text response
    thinking: str
    attempts: int = 1  # how many tries it took
    finish_reason: str = "stop"
    prompt_tokens: int | None = None
    completion_tokens: int | None = None


# Partial prefixes of <think> and </think> that could appear at the end
# of a streaming chunk. We buffer these to avoid splitting tags.
_TAG_PREFIXES = (
    "<",
    "<t",
    "<th",
    "<thi",
    "<thin",
    "<think",
    "</",
    "</t",
    "</th",
    "</thi",
    "</thin",
    "</think",
)


async def process_stream(
    response,  # AsyncStream[ChatCompletionChunk]
) -> AsyncIterator[StreamChunk]:
    """Process an OpenAI streaming response, separating thinking from content.

    Yields StreamChunk objects. Handles two strategies for thinking tokens:
    1. reasoning_content in model_extra (some providers)
    2. <think>...</think> tags in the content field
    """
    in_think_tag = False
    tag_buffer = ""

    async for chunk in response:
        if not chunk.choices:
            continue

        delta = chunk.choices[0].delta
        finish_reason = chunk.choices[0].finish_reason

        # Strategy 1: Check for reasoning_content in model_extra
        reasoning = None
        if hasattr(delta, "model_extra") and delta.model_extra:
            reasoning = delta.model_extra.get("reasoning_content")
            # Also check "reasoning" as a fallback key
            if reasoning is None:
                reasoning = delta.model_extra.get("reasoning")

        if reasoning:
            yield StreamChunk(thinking=reasoning)
            continue

        content = delta.content or ""

        # Prepend any buffered partial-tag characters from the previous chunk
        if tag_buffer:
            content = tag_buffer + content
            tag_buffer = ""

        # Buffer trailing characters that could be the start of a tag
        max_prefix_len = max(len(p) for p in _TAG_PREFIXES)
        for i in range(min(len(content), max_prefix_len), 0, -1):
            if content[-i:] in _TAG_PREFIXES:
                tag_buffer = content[-i:]
                content = content[:-i]
                break

        # Strategy 2: Detect <think>...</think> tags in content
        if "<think>" in content:
            in_think_tag = True
            before, _, after = content.partition("<think>")
            if before:
                yield StreamChunk(content=before)
            # Check if </think> also appears in the remainder (same chunk)
            if "</think>" in after:
                in_think_tag = False
                think_text, _, post_think = after.partition("</think>")
                if think_text:
                    yield StreamChunk(thinking=think_text)
                if post_think:
                    yield StreamChunk(content=post_think)
            elif after:
                yield StreamChunk(thinking=after)
            if finish_reason:
                if tag_buffer:
                    if in_think_tag:
                        yield StreamChunk(thinking=tag_buffer)
                    else:
                        yield StreamChunk(content=tag_buffer)
                    tag_buffer = ""
                yield StreamChunk(finish_reason=finish_reason)
            continue

        if "</think>" in content:
            in_think_tag = False
            before, _, after = content.partition("</think>")
            if before:
                yield StreamChunk(thinking=before)
            if after:
                yield StreamChunk(content=after)
            if finish_reason:
                if tag_buffer:
                    if in_think_tag:
                        yield StreamChunk(thinking=tag_buffer)
                    else:
                        yield StreamChunk(content=tag_buffer)
                    tag_buffer = ""
                yield StreamChunk(finish_reason=finish_reason)
            continue

        if in_think_tag:
            if content:
                yield StreamChunk(thinking=content)
        elif content:
            yield StreamChunk(content=content)

        if finish_reason:
            # Flush any remaining buffer as-is
            if tag_buffer:
                if in_think_tag:
                    yield StreamChunk(thinking=tag_buffer)
                else:
                    yield StreamChunk(content=tag_buffer)
                tag_buffer = ""
            yield StreamChunk(finish_reason=finish_reason)


async def collect_stream(
    stream: AsyncIterator[StreamChunk],
) -> LLMResult:
    """Consume an entire stream and collect into an LLMResult.

    Useful when you want streaming display but also need the final result.
    """
    content_parts: list[str] = []
    thinking_parts: list[str] = []
    finish_reason = "stop"

    async for chunk in stream:
        if chunk.content:
            content_parts.append(chunk.content)
        if chunk.thinking:
            thinking_parts.append(chunk.thinking)
        if chunk.finish_reason:
            finish_reason = chunk.finish_reason

    return LLMResult(
        content="".join(content_parts),
        thinking="".join(thinking_parts),
        finish_reason=finish_reason,
    )

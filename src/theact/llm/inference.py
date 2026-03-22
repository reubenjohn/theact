"""High-level inference functions: complete, stream, structured output."""

from __future__ import annotations

import asyncio
import re
from typing import AsyncIterator

import openai

from theact.llm.client import get_client
from theact.llm.config import AgentLLMConfig, LLMConfig
from theact.llm.errors import (
    LLMConnectionError,
    LLMRateLimitError,
    LLMResponseError,
)
from theact.llm.parsing import YAMLParseError, parse_yaml_response
from theact.llm.streaming import (
    LLMResult,
    StreamChunk,
    StructuredResult,
    process_stream,
)

Message = dict[str, str]  # {"role": "...", "content": "..."}


async def _call_api(
    messages: list[Message],
    llm_config: LLMConfig,
    agent_config: AgentLLMConfig | None,
    stream_mode: bool = False,
):
    """Internal: make the actual API call with error wrapping."""
    client = get_client(llm_config)
    temperature = (
        agent_config.temperature
        if agent_config and agent_config.temperature is not None
        else llm_config.default_temperature
    )
    max_tokens = (
        agent_config.max_tokens
        if agent_config and agent_config.max_tokens is not None
        else llm_config.default_max_tokens
    )

    try:
        return await client.chat.completions.create(
            model=llm_config.model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=stream_mode,
        )
    except openai.APIConnectionError as e:
        raise LLMConnectionError(f"Cannot reach {llm_config.base_url}: {e}") from e
    except openai.RateLimitError as e:
        retry_after = None
        if hasattr(e, "response") and e.response is not None:
            retry_after_header = e.response.headers.get("retry-after")
            if retry_after_header:
                retry_after = float(retry_after_header)
        raise LLMRateLimitError(str(e), retry_after=retry_after) from e
    except openai.APIStatusError as e:
        raise LLMResponseError(f"API error {e.status_code}: {e.message}") from e


def extract_think_tags(content: str) -> tuple[str, str]:
    """Extract <think>...</think> content from a string.

    Returns (clean_content, thinking_text).
    """
    thinking_parts: list[str] = []

    def _collect(match: re.Match) -> str:
        thinking_parts.append(match.group(1))
        return ""

    clean = re.sub(r"<think>(.*?)</think>", _collect, content, flags=re.DOTALL)
    return clean.strip(), "\n".join(thinking_parts)


def strip_think_tags(text: str) -> str:
    """Remove <think>...</think> tags from text, keeping surrounding content."""
    clean, _ = extract_think_tags(text)
    return clean


async def complete(
    messages: list[Message],
    llm_config: LLMConfig,
    agent_config: AgentLLMConfig | None = None,
) -> LLMResult:
    """Non-streaming completion. Returns the full response at once.

    Used for post-turn processing where streaming isn't needed.
    Extracts thinking tokens from reasoning_content or <think> tags.
    """
    response = await _call_api(messages, llm_config, agent_config)

    message = response.choices[0].message
    finish_reason = response.choices[0].finish_reason or "stop"
    content = message.content or ""
    thinking = ""

    # Check for reasoning_content in model_extra
    if hasattr(message, "model_extra") and message.model_extra:
        reasoning = message.model_extra.get("reasoning_content")
        if reasoning is None:
            reasoning = message.model_extra.get("reasoning")
        if reasoning:
            thinking = reasoning

    # Also parse <think>...</think> tags from content
    if "<think>" in content:
        content, tag_thinking = extract_think_tags(content)
        if tag_thinking:
            thinking = (thinking + "\n" + tag_thinking).strip()

    # Extract token usage if available
    prompt_tokens = None
    completion_tokens = None
    if response.usage:
        prompt_tokens = response.usage.prompt_tokens
        completion_tokens = response.usage.completion_tokens

    return LLMResult(
        content=content,
        thinking=thinking,
        finish_reason=finish_reason,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
    )


async def stream(
    messages: list[Message],
    llm_config: LLMConfig,
    agent_config: AgentLLMConfig | None = None,
) -> AsyncIterator[StreamChunk]:
    """Streaming completion. Yields StreamChunk objects as tokens arrive.

    Each chunk contains either thinking or content text (never both).
    Used by narrator and character agents for real-time CLI display.
    """
    response = await _call_api(messages, llm_config, agent_config, stream_mode=True)
    return process_stream(response)


async def complete_structured(
    messages: list[Message],
    llm_config: LLMConfig,
    agent_config: AgentLLMConfig | None = None,
    yaml_hint: str = "",
) -> StructuredResult:
    """Non-streaming completion that parses YAML from the response.

    Retries with error feedback on parse failure.
    yaml_hint is an optional description of the expected YAML structure,
    included in the retry prompt to help the model self-correct.
    """
    config = agent_config or AgentLLMConfig(structured=True)
    attempts = 0
    last_error = ""
    working_messages = list(messages)  # copy so retries don't pollute original
    result: LLMResult | None = None

    while attempts <= config.max_retries:
        attempts += 1
        temperature = config.temperature or llm_config.default_temperature
        if attempts > 1:
            temperature += config.retry_temperature_bump * (attempts - 1)

        result = await complete(
            working_messages,
            llm_config,
            AgentLLMConfig(
                temperature=temperature,
                max_tokens=config.max_tokens,
                structured=False,  # we parse ourselves
            ),
        )

        try:
            data = parse_yaml_response(result.content)
            return StructuredResult(
                data=data,
                raw_content=result.content,
                thinking=result.thinking,
                attempts=attempts,
                finish_reason=result.finish_reason,
                prompt_tokens=result.prompt_tokens,
                completion_tokens=result.completion_tokens,
            )
        except YAMLParseError as e:
            last_error = str(e)
            # Append correction message for retry.
            # Truncate failed response to limit context growth.
            working_messages.append(
                {
                    "role": "assistant",
                    "content": result.content[:200]
                    + ("..." if len(result.content) > 200 else ""),
                }
            )
            correction = f"Your response could not be parsed. Error: {last_error}"
            if yaml_hint:
                correction += (
                    f"\n\nPlease output valid YAML matching this structure:"
                    f"\n{yaml_hint}"
                )
            correction += (
                "\n\nPlease try again with valid YAML in a ```yaml``` code block."
            )
            working_messages.append({"role": "user", "content": correction})

    # All retries exhausted -- raise
    assert result is not None
    raise YAMLParseError(
        f"Failed to parse YAML after {attempts} attempts. Last error: {last_error}",
        raw_content=result.content,
    )


async def stream_structured(
    messages: list[Message],
    llm_config: LLMConfig,
    agent_config: AgentLLMConfig | None = None,
    yaml_hint: str = "",
) -> tuple[AsyncIterator[StreamChunk], "asyncio.Future[StructuredResult]"]:
    """Streaming completion that also parses YAML after the stream completes.

    Returns (stream, future) where:
    - stream is an AsyncIterator[StreamChunk] for live display
    - future is an asyncio.Future[StructuredResult] that resolves after
      the stream is fully consumed

    IMPORTANT: The caller MUST fully consume the stream iterator before
    awaiting the future. If the stream is not fully consumed, the future
    will never resolve.
    """
    loop = asyncio.get_running_loop()
    result_future: asyncio.Future[StructuredResult] = loop.create_future()
    content_parts: list[str] = []
    thinking_parts: list[str] = []

    raw_stream = await stream(messages, llm_config, agent_config)

    async def tee_stream() -> AsyncIterator[StreamChunk]:
        finish_reason = "stop"
        try:
            async for chunk in raw_stream:
                if chunk.content:
                    content_parts.append(chunk.content)
                if chunk.thinking:
                    thinking_parts.append(chunk.thinking)
                if chunk.finish_reason:
                    finish_reason = chunk.finish_reason
                yield chunk

            # Stream done -- parse YAML
            full_content = "".join(content_parts)
            full_thinking = "".join(thinking_parts)
            try:
                data = parse_yaml_response(full_content)
                result_future.set_result(
                    StructuredResult(
                        data=data,
                        raw_content=full_content,
                        thinking=full_thinking,
                        finish_reason=finish_reason,
                    )
                )
            except YAMLParseError as e:
                result_future.set_exception(e)
        except Exception as e:
            if not result_future.done():
                result_future.set_exception(e)

    return tee_stream(), result_future

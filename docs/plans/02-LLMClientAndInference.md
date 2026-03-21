# Phase 02: LLM Client, Inference Abstraction, and Constrained Output

## 1. Overview

This phase builds the LLM calling infrastructure that every agent in TheAct will use. It sits between the raw OpenAI Python library and the turn engine (Phase 03). The goal is a thin, focused layer that handles the concerns unique to our system:

- **Async support** -- post-turn processing (memory updates + game state check) runs in parallel via `asyncio.gather`
- **Streaming** -- tokens yield as they arrive so the CLI (Phase 04) can display them in real time
- **Thinking token separation** -- Venice AI's thinking model produces reasoning tokens before the actual response; we capture both streams separately
- **YAML-based structured output** -- small models cannot reliably produce JSON schema output; we ask for YAML in fenced blocks and parse it ourselves
- **Retry with feedback** -- when YAML parsing fails, we retry with the parse error so the model can self-correct
- **Token estimation** -- simple character-based estimation for context budget decisions in Phase 03
- **Per-agent configuration** -- different temperature, max_tokens, and system prompt patterns for narrator vs. character vs. post-turn agents

What this phase does NOT cover: prompt templates, context assembly, conversation history management, or turn orchestration. Those belong to Phase 03.

### File Layout

All code from this phase lives under `src/theact/llm/`:

```
src/theact/llm/
    __init__.py          # Public API re-exports
    config.py            # LLMConfig, AgentConfig, defaults
    client.py            # Thin wrapper around AsyncOpenAI
    inference.py         # complete(), stream(), complete_structured()
    streaming.py         # StreamResult, async generator, thinking separation
    parsing.py           # YAML extraction and parsing
    tokens.py            # Token estimation utilities
```

---

## 2. Architecture

The layers, bottom to top:

```
+----------------------------------------------------------+
|  Phase 03: Turn Engine / Agents                          |
|  (calls inference functions with messages + config)      |
+----------------------------------------------------------+
        |
        v
+----------------------------------------------------------+
|  inference.py                                            |
|  complete()         -- non-streaming, returns LLMResult  |
|  stream()           -- streaming, yields StreamChunk     |
|  complete_structured() -- YAML parse + retry loop        |
+----------------------------------------------------------+
        |
        v
+----------------------------------------------------------+
|  client.py                                               |
|  get_client() -> AsyncOpenAI (singleton)                 |
|  Configured from LLMConfig (base_url, api_key, model)   |
+----------------------------------------------------------+
        |
        v
+----------------------------------------------------------+
|  openai.AsyncOpenAI                                      |
|  chat.completions.create(stream=True/False)               |
+----------------------------------------------------------+
        |
        v
+----------------------------------------------------------+
|  Venice AI  (api.venice.ai/api/v1)                       |
+----------------------------------------------------------+
```

Key design choice: everything is async. Even "non-streaming" calls use `AsyncOpenAI` so that the turn engine can `asyncio.gather` multiple calls. The sync entry point is just `asyncio.run()` at the CLI layer.

---

## 3. API Design

### 3.1 Configuration (`config.py`)

```python
from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class LLMConfig:
    """Global LLM configuration. One instance per game session."""
    base_url: str = "https://api.venice.ai/api/v1"
    api_key: str = ""  # loaded from env
    model: str = "olafangensan-glm-4.7-flash-heretic"
    default_temperature: float = 1.0
    default_max_tokens: int = 900
    context_limit: int = 8192     # model's context window size


@dataclass(frozen=True)
class AgentLLMConfig:
    """Per-agent-type overrides. Merged with LLMConfig at call time."""
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    structured: bool = False          # whether to parse YAML from response
    max_retries: int = 2              # retries on YAML parse failure
    retry_temperature_bump: float = 0.1  # increase temp on each retry


# Sensible defaults for each agent type
NARRATOR_CONFIG = AgentLLMConfig(
    temperature=1.0,
    max_tokens=600,
    structured=True,
    max_retries=2,
)

CHARACTER_CONFIG = AgentLLMConfig(
    temperature=1.0,
    max_tokens=400,
    structured=False,
)

MEMORY_UPDATE_CONFIG = AgentLLMConfig(
    temperature=0.3,
    max_tokens=500,
    structured=True,
    max_retries=2,
)

GAME_STATE_CONFIG = AgentLLMConfig(
    temperature=0.2,
    max_tokens=200,
    structured=True,
    max_retries=2,
)
```

### 3.2 Client (`client.py`)

```python
from openai import AsyncOpenAI
from theact.llm.config import LLMConfig

_client: AsyncOpenAI | None = None


def get_client(config: LLMConfig) -> AsyncOpenAI:
    """Return a singleton AsyncOpenAI client configured for Venice AI."""
    global _client
    if _client is None:
        _client = AsyncOpenAI(
            base_url=config.base_url,
            api_key=config.api_key,
        )
    return _client


def reset_client() -> None:
    """Reset the singleton. Useful for tests."""
    global _client
    _client = None
```

### 3.3 Result Types (`streaming.py`)

```python
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class LLMResult:
    """Complete response from a non-streaming LLM call."""
    content: str
    thinking: str                   # thinking/reasoning tokens (may be empty)
    finish_reason: str              # "stop", "length", etc.
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None

    @property
    def total_tokens(self) -> Optional[int]:
        if self.prompt_tokens is not None and self.completion_tokens is not None:
            return self.prompt_tokens + self.completion_tokens
        return None


@dataclass
class StreamChunk:
    """A single chunk from a streaming response."""
    content: str = ""               # response content delta
    thinking: str = ""              # thinking content delta
    finish_reason: Optional[str] = None

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
    data: dict                      # parsed YAML as a Python dict
    raw_content: str                # the full text response
    thinking: str
    attempts: int = 1               # how many tries it took
    finish_reason: str = "stop"
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
```

### 3.4 Inference Functions (`inference.py`)

```python
from typing import AsyncIterator

from theact.llm.config import LLMConfig, AgentLLMConfig
from theact.llm.streaming import LLMResult, StreamChunk, StructuredResult

Message = dict[str, str]  # {"role": "...", "content": "..."}


async def complete(
    messages: list[Message],
    llm_config: LLMConfig,
    agent_config: AgentLLMConfig | None = None,
) -> LLMResult:
    """
    Non-streaming completion. Returns the full response at once.
    Used for post-turn processing where streaming isn't needed.
    """
    ...


async def stream(
    messages: list[Message],
    llm_config: LLMConfig,
    agent_config: AgentLLMConfig | None = None,
) -> AsyncIterator[StreamChunk]:
    """
    Streaming completion. Yields StreamChunk objects as tokens arrive.
    Each chunk contains either thinking or content text (never both).
    Used by narrator and character agents for real-time CLI display.
    """
    ...


async def complete_structured(
    messages: list[Message],
    llm_config: LLMConfig,
    agent_config: AgentLLMConfig | None = None,
    yaml_hint: str = "",
) -> StructuredResult:
    """
    Non-streaming completion that parses YAML from the response.
    Retries with error feedback on parse failure.

    yaml_hint is an optional description of the expected YAML structure,
    included in the retry prompt to help the model self-correct.
    """
    ...


async def stream_structured(
    messages: list[Message],
    llm_config: LLMConfig,
    agent_config: AgentLLMConfig | None = None,
    yaml_hint: str = "",
) -> tuple[AsyncIterator[StreamChunk], "asyncio.Future[StructuredResult]"]:
    """
    Streaming completion that also parses YAML after the stream completes.
    Returns both the stream (for live display) and a future that resolves
    to the parsed StructuredResult.

    The caller can iterate the stream for live display, and then await
    the future to get the parsed data.
    """
    ...
```

---

## 4. Structured Output

### 4.1 Strategy

Small 7B models cannot reliably use JSON mode or tool-call-based structured output. Instead:

1. The system prompt instructs the model to output YAML inside a fenced code block.
2. We extract the YAML block from the response text.
3. We parse it with `yaml.safe_load()`.
4. On failure, we retry by appending the parse error as a user message.

Only certain agent types need structured output:
- **Narrator** -- returns narration text + metadata
- **Memory update** -- returns structured diff
- **Game state check** -- returns a simple status object
- **Character** -- plain text, no structure needed

### 4.2 YAML Templates

These templates are included in the system prompt for each agent type. The model sees the template and fills it in.

#### Narrator Response

The system prompt includes:

```
Respond with your narration, then provide metadata in a YAML block:

```yaml
narration: |
  [Your narration text here. Can be multiple lines.
  Use the YAML literal block scalar.]
responding_characters:
  - character_id_1
  - character_id_2
mood: [tense | calm | urgent | mysterious | humorous | dramatic | melancholic]
```
```

#### Memory Update Response

```
Analyze what happened this turn and output a YAML block with memory updates:

```yaml
add:
  - "Short factual statement about something new learned or that happened"
  - "Another fact"
remove:
  - "Exact text of a memory entry that is no longer relevant"
update:
  - old: "Exact text of existing memory entry"
    new: "Updated version of that memory entry"
summary: "One-sentence summary of what changed this turn"
```
```

#### Game State Check Response

```
Based on what happened, output a YAML block:

```yaml
chapter_complete: false
reason: "Brief explanation of why the chapter is or is not complete"
important_event: false
event_description: ""
```
```

### 4.3 YAML Parsing (`parsing.py`)

```python
import re
import yaml
from typing import Any


class YAMLParseError(Exception):
    """Raised when YAML extraction or parsing fails."""
    def __init__(self, message: str, raw_content: str):
        super().__init__(message)
        self.raw_content = raw_content


def extract_yaml_block(text: str) -> str:
    """
    Extract YAML content from a fenced code block in the response.

    Looks for ```yaml ... ``` first.
    Falls back to ``` ... ``` (unfenced but code-blocked).
    Falls back to treating the entire response as YAML if no blocks found.
    """
    # Try ```yaml ... ``` first
    match = re.search(r"```yaml\s*\n(.*?)```", text, re.DOTALL)
    if match:
        return match.group(1).strip()

    # Try generic ``` ... ```
    match = re.search(r"```\s*\n(.*?)```", text, re.DOTALL)
    if match:
        return match.group(1).strip()

    # No code block found -- try the whole text as YAML
    return text.strip()


def parse_yaml_response(text: str) -> dict[str, Any]:
    """
    Extract and parse YAML from LLM response text.
    Raises YAMLParseError with a descriptive message on failure.
    """
    yaml_str = extract_yaml_block(text)

    try:
        result = yaml.safe_load(yaml_str)
    except yaml.YAMLError as e:
        raise YAMLParseError(
            f"YAML parse error: {e}",
            raw_content=text,
        ) from e

    if not isinstance(result, dict):
        raise YAMLParseError(
            f"Expected YAML to parse as a dictionary, got {type(result).__name__}",
            raw_content=text,
        )

    return result


def validate_yaml_fields(
    data: dict[str, Any],
    required_fields: list[str],
) -> list[str]:
    """
    Check that required fields are present. Returns list of missing field names.
    Does not raise -- caller decides whether to retry or proceed with partial data.
    """
    return [f for f in required_fields if f not in data]
```

### 4.4 Retry Flow

The retry logic lives in `complete_structured()` in `inference.py`. Pseudocode:

```python
async def complete_structured(messages, llm_config, agent_config, yaml_hint=""):
    config = agent_config or AgentLLMConfig(structured=True)
    attempts = 0
    last_error = ""
    working_messages = list(messages)  # copy so retries don't pollute original

    while attempts <= config.max_retries:
        attempts += 1
        temperature = (config.temperature or llm_config.default_temperature)
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
            # Append correction message for retry
            working_messages.append({
                "role": "assistant",
                "content": result.content,
            })
            correction = f"Your response could not be parsed. Error: {last_error}"
            if yaml_hint:
                correction += f"\n\nPlease output valid YAML matching this structure:\n{yaml_hint}"
            correction += "\n\nPlease try again with valid YAML in a ```yaml``` code block."
            working_messages.append({
                "role": "user",
                "content": correction,
            })

    # All retries exhausted -- raise
    raise YAMLParseError(
        f"Failed to parse YAML after {attempts} attempts. Last error: {last_error}",
        raw_content=result.content,
    )
```

---

## 5. Streaming

### 5.1 How Venice AI Returns Thinking Tokens

Venice AI's OpenAI-compatible endpoint for thinking models returns thinking/reasoning tokens as part of the streamed response. Since the official `openai` library (v2.29.0) does not have a dedicated `reasoning_content` field on `ChoiceDelta`, Venice AI delivers thinking tokens through one of these mechanisms (we must handle both):

1. **`reasoning_content` as an extra field on the delta dict** -- accessible via `getattr(chunk.choices[0].delta, "reasoning_content", None)` or through the raw dict representation `chunk.model_extra` / `chunk.choices[0].delta.model_extra`.
2. **Thinking content wrapped in `<think>...</think>` tags within the regular `content` field** -- some OpenAI-compatible endpoints embed thinking this way.

Our streaming layer will detect and handle both approaches.

### 5.2 Stream Processing

```python
from typing import AsyncIterator
from openai import AsyncOpenAI
from openai.types.chat import ChatCompletionChunk

from theact.llm.streaming import StreamChunk, LLMResult


async def _process_stream(
    response,  # AsyncStream[ChatCompletionChunk]
) -> AsyncIterator[StreamChunk]:
    """
    Process an OpenAI streaming response, separating thinking from content.
    Yields StreamChunk objects.
    """
    in_think_tag = False
    thinking_buffer = ""

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

        # Strategy 2: Detect <think>...</think> tags in content
        if "<think>" in content:
            in_think_tag = True
            # Split: anything before <think> is content, after is thinking
            before, _, after = content.partition("<think>")
            if before:
                yield StreamChunk(content=before)
            if after:
                yield StreamChunk(thinking=after)
            continue

        if "</think>" in content:
            in_think_tag = False
            before, _, after = content.partition("</think>")
            if before:
                yield StreamChunk(thinking=before)
            if after:
                yield StreamChunk(content=after)
            continue

        if in_think_tag:
            yield StreamChunk(thinking=content)
        elif content:
            yield StreamChunk(content=content)

        if finish_reason:
            yield StreamChunk(finish_reason=finish_reason)


async def collect_stream(
    stream: AsyncIterator[StreamChunk],
) -> LLMResult:
    """
    Consume an entire stream and collect into an LLMResult.
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
```

### 5.3 Tee Pattern for Stream + Parse

For `stream_structured()`, we need to both yield chunks for live display AND collect the full text for YAML parsing. We use an async tee pattern:

```python
import asyncio
from typing import AsyncIterator

from theact.llm.streaming import StreamChunk, StructuredResult


async def stream_structured(messages, llm_config, agent_config=None, yaml_hint=""):
    """
    Returns (stream, future) where:
    - stream is an AsyncIterator[StreamChunk] for live display
    - future is an asyncio.Future[StructuredResult] that resolves after
      the stream is fully consumed
    """
    result_future: asyncio.Future[StructuredResult] = asyncio.Future()
    content_parts: list[str] = []
    thinking_parts: list[str] = []

    raw_stream = stream(messages, llm_config, agent_config)

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
                result_future.set_result(StructuredResult(
                    data=data,
                    raw_content=full_content,
                    thinking=full_thinking,
                    finish_reason=finish_reason,
                ))
            except YAMLParseError as e:
                result_future.set_exception(e)
        except Exception as e:
            result_future.set_exception(e)

    return tee_stream(), result_future
```

### 5.4 How Phase 04 (CLI) Will Consume This

Phase 04 will consume the stream roughly like this (shown here for context, not implemented in this phase):

```python
# Pseudocode for CLI consumption
stream_iter = await stream(messages, config)
async for chunk in stream_iter:
    if chunk.is_thinking:
        ui.append_thinking(chunk.thinking)
    elif chunk.is_content:
        ui.append_content(chunk.content)
    elif chunk.is_done:
        ui.finalize()
```

---

## 6. Error Handling

### 6.1 Error Types

```python
class LLMError(Exception):
    """Base exception for LLM-related errors."""
    pass


class LLMConnectionError(LLMError):
    """Failed to connect to the API endpoint."""
    pass


class LLMRateLimitError(LLMError):
    """Rate limited by the API."""
    def __init__(self, message: str, retry_after: float | None = None):
        super().__init__(message)
        self.retry_after = retry_after


class LLMResponseError(LLMError):
    """The API returned an error response."""
    pass


# YAMLParseError is defined in parsing.py (see section 4.3)
```

### 6.2 API Error Handling

The `complete()` and `stream()` functions wrap OpenAI client exceptions:

```python
import openai
from theact.llm.config import LLMConfig, AgentLLMConfig

async def _call_api(messages, llm_config, agent_config, stream_mode=False):
    """Internal: make the actual API call with error wrapping."""
    client = get_client(llm_config)
    temperature = agent_config.temperature if agent_config and agent_config.temperature is not None else llm_config.default_temperature
    max_tokens = agent_config.max_tokens if agent_config and agent_config.max_tokens is not None else llm_config.default_max_tokens

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
```

### 6.3 Retry Strategy Summary

| Scenario | Retry? | Strategy |
|---|---|---|
| YAML parse failure | Yes, up to `max_retries` | Append error + assistant response to messages, bump temperature |
| API connection error | No | Raise immediately, let caller decide |
| Rate limit (429) | No at this layer | Raise `LLMRateLimitError` with `retry_after`; Phase 03 can implement backoff |
| API 500 error | No | Raise immediately |
| `finish_reason == "length"` | No | Return result as-is; caller can check `finish_reason` and re-request with higher `max_tokens` |

The retry logic is deliberately kept simple. Only YAML parse failures are retried automatically because that is the most common failure mode with small models and can be self-corrected by the model.

---

## 7. Token Estimation

### 7.1 Approach

We use a simple character-based heuristic. For English text with typical LLM tokenizers, the ratio is approximately 1 token per 4 characters. This is imprecise but sufficient for context budget management (deciding when to summarize history, how much context to include, etc.).

We do NOT add `tiktoken` as a dependency. Reasons:
- The Venice AI model uses its own tokenizer, not OpenAI's
- Exact counts are not needed -- we only need rough estimates for budget decisions
- Keeps dependencies minimal

### 7.2 Implementation (`tokens.py`)

```python
# Approximate characters-per-token ratio for English text.
# This is a rough heuristic. Real tokenizers vary (3.5-4.5 chars/token).
CHARS_PER_TOKEN = 4

# Overhead per message in a chat completion (role, formatting, separators).
# OpenAI charges ~4 tokens per message for formatting.
MESSAGE_OVERHEAD_TOKENS = 4


def estimate_tokens(text: str) -> int:
    """Estimate the token count for a string of text."""
    if not text:
        return 0
    return max(1, len(text) // CHARS_PER_TOKEN)


def estimate_messages_tokens(messages: list[dict[str, str]]) -> int:
    """
    Estimate total token count for a list of chat messages.
    Accounts for per-message overhead (role, separators).
    """
    total = 0
    for msg in messages:
        total += MESSAGE_OVERHEAD_TOKENS
        total += estimate_tokens(msg.get("content", ""))
        total += estimate_tokens(msg.get("role", ""))
    # Every conversation has a base overhead of ~3 tokens
    total += 3
    return total


def tokens_remaining(
    messages: list[dict[str, str]],
    context_limit: int,
    max_completion_tokens: int,
) -> int:
    """
    Estimate how many tokens are available for additional context
    (e.g., memory injection, world description) before hitting the limit.

    Returns negative if already over budget.
    """
    used = estimate_messages_tokens(messages)
    return context_limit - used - max_completion_tokens
```

### 7.3 Context Budget

The context limit is configured on `LLMConfig.context_limit` (default 8192). Phase 03's context assembly uses `tokens_remaining()` with this value to decide when to summarize and how much history to include.

---

## 8. Configuration

### 8.1 What Is Configurable

| Setting | Source | Default |
|---|---|---|
| `base_url` | `VENICE_BASE_URL` env var or constructor | `https://api.venice.ai/api/v1` |
| `api_key` | `VENICE_API_KEY` env var (required) | -- |
| `model` | `VENICE_MODEL` env var or constructor | `olafangensan-glm-4.7-flash-heretic` |
| `default_temperature` | constructor | `1.0` |
| `default_max_tokens` | constructor | `900` |
| Per-agent `temperature` | `AgentLLMConfig` | Falls back to `default_temperature` |
| Per-agent `max_tokens` | `AgentLLMConfig` | Falls back to `default_max_tokens` |
| Per-agent `max_retries` | `AgentLLMConfig` | `2` |

### 8.2 Loading Config

```python
import os
from theact.llm.config import LLMConfig


def load_llm_config() -> LLMConfig:
    """Load LLM configuration from environment variables."""
    api_key = os.environ.get("VENICE_API_KEY", "")
    if not api_key:
        raise ValueError(
            "VENICE_API_KEY environment variable is required. "
            "Set it in your .env file or shell environment."
        )

    return LLMConfig(
        base_url=os.environ.get("VENICE_BASE_URL", "https://api.venice.ai/api/v1"),
        api_key=api_key,
        model=os.environ.get("VENICE_MODEL", "olafangensan-glm-4.7-flash-heretic"),
    )
```

---

## 9. Implementation Steps

Build in this order. Each step is a single file or small commit.

### Step 1: Package structure

Create `src/theact/llm/` with `__init__.py`. Ensure the package is importable.

Add `pyyaml` to `pyproject.toml` dependencies.

### Step 2: `config.py`

Implement `LLMConfig`, `AgentLLMConfig`, the four agent-type defaults (`NARRATOR_CONFIG`, `CHARACTER_CONFIG`, `MEMORY_UPDATE_CONFIG`, `GAME_STATE_CONFIG`), and `load_llm_config()`.

### Step 3: `client.py`

Implement `get_client()` and `reset_client()`. Singleton `AsyncOpenAI` instance.

### Step 4: `tokens.py`

Implement `estimate_tokens()`, `estimate_messages_tokens()`, `tokens_remaining()`, and the context limit constants.

### Step 5: `parsing.py`

Implement `extract_yaml_block()`, `parse_yaml_response()`, `validate_yaml_fields()`, and `YAMLParseError`.

### Step 6: `streaming.py`

Implement `LLMResult`, `StreamChunk`, `StructuredResult` dataclasses. Implement `_process_stream()` for thinking token separation and `collect_stream()`.

### Step 7: `inference.py`

Implement `complete()`, `stream()`, `complete_structured()`, `stream_structured()`, error types, and `_call_api()`.

### Step 8: `__init__.py`

Re-export the public API:

```python
from theact.llm.config import (
    LLMConfig,
    AgentLLMConfig,
    load_llm_config,
    NARRATOR_CONFIG,
    CHARACTER_CONFIG,
    MEMORY_UPDATE_CONFIG,
    GAME_STATE_CONFIG,
)
from theact.llm.inference import complete, stream, complete_structured, stream_structured
from theact.llm.streaming import LLMResult, StreamChunk, StructuredResult
from theact.llm.parsing import parse_yaml_response, YAMLParseError
from theact.llm.tokens import estimate_tokens, estimate_messages_tokens, tokens_remaining
from theact.llm.client import get_client, reset_client
```

### Step 9: Verification script

Write `scripts/test_llm.py` (see Section 10).

---

## 10. Verification

### 10.1 Test Script (`scripts/test_llm.py`)

A standalone script that exercises all the key functionality against the live Venice AI endpoint:

```python
"""
Smoke test for the LLM client layer.
Run: uv run python scripts/test_llm.py

Requires VENICE_API_KEY in environment or .env file.
"""
import asyncio
from dotenv import load_dotenv

load_dotenv()

from theact.llm import (
    load_llm_config,
    complete,
    stream,
    complete_structured,
    estimate_tokens,
    estimate_messages_tokens,
    LLMResult,
    StreamChunk,
    StructuredResult,
    AgentLLMConfig,
    NARRATOR_CONFIG,
)


async def test_complete():
    """Test basic non-streaming completion."""
    print("=== Test: complete() ===")
    config = load_llm_config()
    result = await complete(
        messages=[{"role": "user", "content": "Say hello in exactly 5 words."}],
        llm_config=config,
    )
    assert isinstance(result, LLMResult)
    print(f"  Content: {result.content}")
    print(f"  Thinking: {result.thinking[:100]}..." if result.thinking else "  Thinking: (none)")
    print(f"  Finish reason: {result.finish_reason}")
    print("  PASSED\n")


async def test_stream():
    """Test streaming completion with thinking separation."""
    print("=== Test: stream() ===")
    config = load_llm_config()
    thinking_parts = []
    content_parts = []

    async for chunk in await stream(
        messages=[{"role": "user", "content": "What is 2+2? Explain briefly."}],
        llm_config=config,
    ):
        if chunk.is_thinking:
            thinking_parts.append(chunk.thinking)
        elif chunk.is_content:
            content_parts.append(chunk.content)

    content = "".join(content_parts)
    thinking = "".join(thinking_parts)
    print(f"  Content: {content}")
    print(f"  Thinking: {thinking[:100]}..." if thinking else "  Thinking: (none)")
    print("  PASSED\n")


async def test_structured():
    """Test YAML-parsed structured output."""
    print("=== Test: complete_structured() ===")
    config = load_llm_config()
    result = await complete_structured(
        messages=[
            {"role": "system", "content": (
                "You are a narrator for a text RPG. "
                "Respond with a brief narration and metadata in a YAML block.\n\n"
                "```yaml\n"
                "narration: |\n"
                "  [Your narration here]\n"
                "responding_characters:\n"
                "  - character_1\n"
                "mood: calm\n"
                "```"
            )},
            {"role": "user", "content": "I enter the tavern."},
        ],
        llm_config=config,
        agent_config=NARRATOR_CONFIG,
        yaml_hint="narration: |\\n  ...\\nresponding_characters:\\n  - ...\\nmood: calm|tense|urgent",
    )
    assert isinstance(result, StructuredResult)
    print(f"  Parsed data: {result.data}")
    print(f"  Attempts: {result.attempts}")
    print(f"  Raw content: {result.raw_content[:200]}...")
    print("  PASSED\n")


async def test_token_estimation():
    """Test token estimation utilities (no API call needed)."""
    print("=== Test: token estimation ===")
    text = "Hello, world! This is a test of token estimation."
    tokens = estimate_tokens(text)
    print(f"  '{text}' -> ~{tokens} tokens")

    messages = [
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "Hello!"},
    ]
    msg_tokens = estimate_messages_tokens(messages)
    print(f"  2-message conversation -> ~{msg_tokens} tokens")
    print("  PASSED\n")


async def test_parallel():
    """Test parallel calls via asyncio.gather (simulates post-turn processing)."""
    print("=== Test: parallel calls ===")
    config = load_llm_config()

    async def call(prompt: str) -> str:
        result = await complete(
            messages=[{"role": "user", "content": prompt}],
            llm_config=config,
            agent_config=AgentLLMConfig(max_tokens=100),
        )
        return result.content

    results = await asyncio.gather(
        call("Say 'alpha' and nothing else."),
        call("Say 'beta' and nothing else."),
        call("Say 'gamma' and nothing else."),
    )

    for i, r in enumerate(results):
        print(f"  Call {i}: {r.strip()}")
    print("  PASSED\n")


async def main():
    await test_token_estimation()  # no API call, always safe
    await test_complete()
    await test_stream()
    await test_structured()
    await test_parallel()
    print("All tests passed.")


if __name__ == "__main__":
    asyncio.run(main())
```

### 10.2 What to Check Manually

- Thinking tokens appear in `result.thinking` (not empty for the thinking model)
- Streaming chunks arrive incrementally (not all at once)
- YAML parsing succeeds on first attempt for well-prompted requests
- Retry works when YAML is intentionally malformed (can test by corrupting the response in a mock)
- Parallel calls complete faster than sequential (wall-clock time)
- Token estimation gives reasonable numbers (~1 token per 4 chars)

### 10.3 Unit Tests (No API Required)

These can be plain pytest tests that don't hit the network:

- `test_extract_yaml_block` -- various formats (fenced, unfenced, no block)
- `test_parse_yaml_response` -- valid YAML, invalid YAML, non-dict YAML
- `test_validate_yaml_fields` -- missing fields, all present
- `test_estimate_tokens` -- empty string, short string, long string
- `test_estimate_messages_tokens` -- various message lists
- `test_stream_chunk_properties` -- `is_thinking`, `is_content`, `is_done`

### 10.4 Live Testing & Regression Capture

After the smoke test (`scripts/test_llm.py`) passes, perform deeper live API validation. The goal is to discover how the real Venice AI endpoint behaves and lock down edge cases as automated tests.

**Step 1 — Exploratory testing against the real API:**
- Run `scripts/test_llm.py` and carefully inspect output. Pay attention to:
  - Do thinking tokens actually appear in `result.thinking`? If empty, the thinking token extraction strategy may need adjustment for this endpoint.
  - Does the model output YAML in fenced blocks when asked? Try multiple prompts. Note which phrasing works best.
  - What happens when `max_tokens` is too low and the response is truncated mid-YAML? Does `finish_reason == "length"` get set?
  - Does streaming actually yield chunks incrementally, or does the endpoint buffer?
- Test `complete_structured()` with a deliberately bad system prompt (one that's unlikely to produce YAML). Verify retry logic works — the model gets the error feedback and self-corrects.
- Test parallel calls with `asyncio.gather` of 5+ simultaneous requests. Check for rate limiting behavior.
- Send a very long prompt (close to context limit). Verify the response isn't empty or garbled.

**Step 2 — Fix and capture:**
- For each unexpected behavior, fix the code and write a regression test.
- If the endpoint uses `<think>` tags instead of `reasoning_content`, write a test with a real captured response chunk to verify parsing.
- If YAML extraction fails on a specific model output pattern (e.g., model writes `yaml` after the triple backticks with no newline), add that pattern to `test_extract_yaml_block`.
- Save representative real model responses as test fixtures in `tests/fixtures/` for offline replay tests.

**Step 3 — Verify regression suite:**
- Run `uv run pytest tests/ -v` and confirm all new regression tests pass.
- Re-run `scripts/test_llm.py` to confirm live behavior still works after any code changes.

---

## 11. Dependencies

### New Dependencies to Add

| Package | Purpose | Version |
|---|---|---|
| `pyyaml` | YAML parsing for structured output | `>=6.0` |

### Already Present (No Changes)

| Package | Purpose |
|---|---|
| `openai` (>=2.29.0) | OpenAI-compatible API client (includes `AsyncOpenAI`) |
| `python-dotenv` (>=1.2.2) | `.env` file loading |

### Not Adding

| Package | Why Not |
|---|---|
| `tiktoken` | Model uses its own tokenizer; char-based estimation is sufficient |
| `pydantic` | Already a transitive dependency via `openai`, but we use plain dataclasses to keep the layer thin |
| `tenacity` | Our retry logic is simple enough (1 loop) that a retry library is overkill |
| `aiohttp` | `openai` already handles async HTTP via `httpx` |

### Updated `pyproject.toml` Dependencies

```toml
dependencies = [
    "openai>=2.29.0",
    "python-dotenv>=1.2.2",
    "pyyaml>=6.0",
]
```

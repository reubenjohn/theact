# Phase 09: Observability & Diagnostics

## 1. Overview

Phases 01-05 built the turn engine, agents, and playtest framework. Prompt iteration is now the main activity, but it is currently guesswork: there is no structured data about what the LLM does, how many tokens it uses, or why structured output parsing fails. This phase adds **passive instrumentation** so that every future prompt change is data-driven.

After this phase is complete:
- Every LLM call logs structured metadata (agent, turn, tokens, latency, parse result, finish reason)
- Debug mode writes full prompt/response artifacts to a diagnostics filesystem
- Automated prompt lint tests catch budget violations and formatting errors
- Structured output failures are categorized into an explicit error taxonomy
- A context window profiler reports per-agent token allocation
- The playtest framework aggregates call-level data into actionable reports

### What This Phase Does NOT Do

- No prompt changes. Prompts are untouched — this phase builds the tools to make prompt changes safe.
- No new agents or game mechanics.
- No UI changes to the CLI or web interface.
- No architecture changes. The turn flow remains: narrator -> characters -> post-turn (parallel).

### Dependencies

- Phase 01 (data models, YAML I/O, save manager)
- Phase 02 (LLM client, streaming, structured output)
- Phase 03 (turn engine, agents, context assembly)
- Phase 05 (playtest framework)

---

## 2. Error Taxonomy

Before building logging, define the vocabulary for structured output failures. This taxonomy is used throughout call logging, diagnostics, and playtest reporting.

### 2.1 Failure Categories

Create `src/theact/llm/errors.py` (extend the existing file) with an enum:

```python
# src/theact/llm/errors.py (add to existing file)

from enum import Enum

class ParseFailureType(str, Enum):
    """Categorization of structured output parse failures."""
    success = "success"
    no_yaml_block = "no_yaml_block"       # Model didn't produce fenced YAML
    invalid_yaml = "invalid_yaml"         # Fenced block present but YAML syntax error
    wrong_schema = "wrong_schema"         # Valid YAML but missing required fields or wrong types
    empty_response = "empty_response"     # Model returned empty or whitespace-only content
    echo_prompt = "echo_prompt"           # Model echoed back part of the prompt
    json_instead = "json_instead"         # Model produced JSON instead of YAML
```

### 2.2 Classification Function

Add a classifier to `src/theact/llm/parsing.py`:

```python
def classify_parse_failure(raw_content: str, error: Exception | None = None) -> ParseFailureType:
    """Classify a structured output failure into a category.

    Called when YAML parsing fails to produce a descriptive category
    for logging and diagnostics.
    """
    if not raw_content or not raw_content.strip():
        return ParseFailureType.empty_response

    stripped = raw_content.strip()

    # Check for JSON output
    if stripped.startswith("{") or stripped.startswith("["):
        return ParseFailureType.json_instead

    # Check for echoed prompt (heuristic: starts with "You are" or "SETTING:")
    prompt_indicators = ["You are", "SETTING:", "YOUR TASK:", "Output a YAML"]
    if any(stripped.startswith(ind) for ind in prompt_indicators):
        return ParseFailureType.echo_prompt

    # Check if there's a YAML fence at all
    if "```yaml" not in raw_content and "```" not in raw_content:
        # Try to determine if it's valid YAML without fences
        try:
            import yaml
            result = yaml.safe_load(stripped)
            if isinstance(result, dict):
                return ParseFailureType.no_yaml_block  # valid YAML but no fence
        except yaml.YAMLError:
            pass
        return ParseFailureType.no_yaml_block

    # Has a fence but parsing failed — must be invalid YAML syntax
    if error and "parse" in str(error).lower():
        return ParseFailureType.invalid_yaml

    return ParseFailureType.invalid_yaml
```

### 2.3 Wire into Existing Parse Pipeline

Modify `parse_yaml_response()` and `complete_structured()` so that when a `YAMLParseError` is raised, the error includes the failure category:

```python
# In YAMLParseError (src/theact/llm/parsing.py):
class YAMLParseError(Exception):
    def __init__(self, message: str, raw_content: str, failure_type: ParseFailureType | None = None):
        super().__init__(message)
        self.raw_content = raw_content
        self.failure_type = failure_type or classify_parse_failure(raw_content)
```

### Verification

- `classify_parse_failure()` returns correct categories for: empty string, JSON string, string with `You are` prefix, string with `yaml` fence but broken syntax, string with valid YAML but no fence.
- Existing `YAMLParseError` callers continue to work (new parameter is optional with default).

---

## 3. Structured LLM Call Logging

### 3.1 Call Record Dataclass

Create `src/theact/llm/call_log.py`:

```python
"""Structured logging for LLM API calls."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

import yaml

from theact.llm.errors import ParseFailureType


@dataclass
class LLMCallRecord:
    """One LLM API call with all metadata."""

    timestamp: str              # ISO 8601
    agent: str                  # e.g. "narrator", "character:maya", "memory:joaquin",
                                #      "game_state", "summarizer", "player"
    turn: int                   # turn number in the session
    prompt_tokens: int          # estimated tokens in the prompt
    thinking_tokens: int        # tokens consumed by <think> reasoning
    content_tokens: int         # tokens in the actual response content
    latency_ms: int             # wall-clock time for the call
    finish_reason: str          # "stop", "length", etc.
    parse_result: str           # ParseFailureType value ("success", "no_yaml_block", etc.)
    parse_attempts: int         # total attempts (1 = first try worked)
    retry_count: int            # number of retries (0 = no retries)
    temperature: float          # temperature used for this call
    max_tokens: int             # max_tokens budget for this call


@dataclass
class LLMCallLog:
    """Accumulates LLM call records for a session.

    Thread-safe for asyncio (single-threaded event loop).
    """

    records: list[LLMCallRecord] = field(default_factory=list)

    def log(self, record: LLMCallRecord) -> None:
        """Append a call record."""
        self.records.append(record)

    def records_for_turn(self, turn: int) -> list[LLMCallRecord]:
        """Return all records for a given turn."""
        return [r for r in self.records if r.turn == turn]

    def records_for_agent(self, agent: str) -> list[LLMCallRecord]:
        """Return all records for a given agent prefix (e.g. 'character' matches 'character:maya')."""
        return [r for r in self.records if r.agent == agent or r.agent.startswith(f"{agent}:")]

    def summary(self) -> dict:
        """Aggregate stats across all records."""
        if not self.records:
            return {}
        total = len(self.records)
        return {
            "total_calls": total,
            "mean_latency_ms": sum(r.latency_ms for r in self.records) // total,
            "parse_success_rate": round(
                sum(1 for r in self.records if r.parse_result == "success") / total, 3
            ),
            "total_prompt_tokens": sum(r.prompt_tokens for r in self.records),
            "total_thinking_tokens": sum(r.thinking_tokens for r in self.records),
            "total_content_tokens": sum(r.content_tokens for r in self.records),
            "length_finishes": sum(1 for r in self.records if r.finish_reason == "length"),
            "total_retries": sum(r.retry_count for r in self.records),
        }

    def agent_summary(self) -> dict[str, dict]:
        """Per-agent aggregate stats, keyed by agent name."""
        agents: dict[str, list[LLMCallRecord]] = {}
        for r in self.records:
            agents.setdefault(r.agent, []).append(r)

        result = {}
        for agent, recs in sorted(agents.items()):
            n = len(recs)
            result[agent] = {
                "calls": n,
                "mean_latency_ms": sum(r.latency_ms for r in recs) // n,
                "mean_thinking_tokens": sum(r.thinking_tokens for r in recs) // n,
                "mean_content_tokens": sum(r.content_tokens for r in recs) // n,
                "parse_success_rate": round(
                    sum(1 for r in recs if r.parse_result == "success") / n, 3
                ),
                "length_finishes": sum(1 for r in recs if r.finish_reason == "length"),
            }
        return result

    def dump_yaml(self, path: Path) -> None:
        """Write all records to a YAML file."""
        data = [asdict(r) for r in self.records]
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False)
```

### 3.2 Recording Calls in the Inference Layer

The `complete()` and `stream()` functions in `src/theact/llm/inference.py` do not know the agent name or turn number — those are higher-level concepts. Rather than threading a logger through the low-level inference functions, each **agent function** is responsible for creating a call record after its LLM call completes.

Add an optional `call_log: LLMCallLog | None` parameter to each agent function:

```python
# Example for run_narrator in src/theact/agents/narrator.py:

async def run_narrator(
    game: LoadedGame,
    player_input: str,
    llm_config: LLMConfig,
    on_token: StreamCallback | None = None,
    call_log: LLMCallLog | None = None,    # NEW
    turn: int = 0,                          # NEW
) -> NarratorOutput:
```

After the LLM call completes, create and log a record:

```python
import time
from datetime import datetime, timezone
from theact.llm.tokens import estimate_tokens

start = time.monotonic()
# ... existing LLM call ...
elapsed_ms = int((time.monotonic() - start) * 1000)

if call_log is not None:
    call_log.log(LLMCallRecord(
        timestamp=datetime.now(timezone.utc).isoformat(),
        agent="narrator",
        turn=turn,
        prompt_tokens=estimate_tokens(messages[0]["content"]) + estimate_tokens(messages[1]["content"]),
        thinking_tokens=estimate_tokens(result.thinking) if hasattr(result, "thinking") else 0,
        content_tokens=estimate_tokens(result.raw_content if hasattr(result, "raw_content") else result.content),
        latency_ms=elapsed_ms,
        finish_reason=result.finish_reason,
        parse_result="success",  # or classify_parse_failure() on exception
        parse_attempts=result.attempts if hasattr(result, "attempts") else 1,
        retry_count=max(0, (result.attempts if hasattr(result, "attempts") else 1) - 1),
        temperature=NARRATOR_CONFIG.temperature or llm_config.default_temperature,
        max_tokens=NARRATOR_CONFIG.max_tokens or llm_config.default_max_tokens,
    ))
```

On `YAMLParseError`, the catch block records a failure:

```python
except YAMLParseError as e:
    if call_log is not None:
        call_log.log(LLMCallRecord(
            # ... same fields ...
            parse_result=e.failure_type.value if e.failure_type else "invalid_yaml",
            # ...
        ))
```

Apply the same pattern to:
- `run_character()` — agent name `character:{char_id}`
- `run_memory_update()` — agent name `memory:{char_id}`
- `run_game_state()` — agent name `game_state`
- `run_chapter_summary()` and `run_rolling_summary()` — agent name `summarizer`

### 3.3 Wiring Through the Turn Engine

Add an optional `call_log` parameter to `run_turn()` in `src/theact/engine/turn.py`:

```python
async def run_turn(
    game: LoadedGame,
    player_input: str,
    llm_config: LLMConfig,
    on_token: StreamCallback | None = None,
    call_log: LLMCallLog | None = None,    # NEW
) -> TurnResult:
```

Pass `call_log` and `new_turn` to each agent call. The `call_log` is optional — if `None`, no logging occurs, preserving backward compatibility.

### 3.4 Token Estimation for Records

Use the existing `estimate_tokens()` from `src/theact/llm/tokens.py` for prompt and content token counts. For thinking tokens, use the same function on the thinking text. When the API returns actual `prompt_tokens` or `completion_tokens` in the response, prefer those over estimates.

Add a helper to `src/theact/llm/tokens.py`:

```python
def estimate_messages_content_tokens(messages: list[dict[str, str]]) -> int:
    """Estimate total content tokens across all messages (excluding overhead)."""
    return sum(estimate_tokens(m.get("content", "")) for m in messages)
```

### Verification

- `LLMCallLog.log()` appends records correctly.
- `LLMCallLog.summary()` computes correct aggregates from test records.
- `LLMCallLog.agent_summary()` groups by agent name.
- `LLMCallLog.dump_yaml()` writes valid YAML that can be read back.
- Passing `call_log=None` to all agent functions has no effect (backward compatible).
- Passing a real `LLMCallLog` produces one record per agent call during a turn.

---

## 4. Diagnostics Filesystem

### 4.1 Design

When `run_turn()` is called with `debug=True`, write detailed artifacts to disk for every agent call within that turn. The structure:

```
saves/<save-id>/diagnostics/
  turn-001/
    summary.yaml              # aggregated turn stats
    narrator/
      system_prompt.txt       # fully rendered system prompt
      user_message.txt        # fully rendered user message
      raw_response.txt        # complete model output (thinking + content)
      parsed.yaml             # successfully parsed structured output (if any)
      call_log.yaml           # structured call metadata
    character-maya/
      system_prompt.txt
      user_message.txt
      raw_response.txt
      call_log.yaml
    character-joaquin/
      system_prompt.txt
      user_message.txt
      raw_response.txt
      call_log.yaml
    memory-maya/
      system_prompt.txt
      user_message.txt
      raw_response.txt
      parsed.yaml
      call_log.yaml
    game_state/
      system_prompt.txt
      user_message.txt
      raw_response.txt
      parsed.yaml
      call_log.yaml
  turn-002/
    ...
```

### 4.2 Diagnostics Writer

Create `src/theact/engine/diagnostics.py`:

```python
"""Diagnostics filesystem writer for debug mode."""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

import yaml

from theact.llm.call_log import LLMCallRecord


class DiagnosticsWriter:
    """Writes per-agent diagnostics artifacts to disk.

    Created per-turn. Call write_agent() for each agent that runs,
    then write_summary() at the end of the turn.
    """

    def __init__(self, save_path: Path, turn: int):
        self.turn_dir = save_path / "diagnostics" / f"turn-{turn:03d}"
        self.turn_dir.mkdir(parents=True, exist_ok=True)

    def write_agent(
        self,
        agent_dir_name: str,
        messages: list[dict[str, str]],
        raw_response: str,
        thinking: str,
        parsed_data: dict | None,
        call_record: LLMCallRecord | None,
    ) -> None:
        """Write all artifacts for a single agent call."""
        agent_dir = self.turn_dir / agent_dir_name
        agent_dir.mkdir(parents=True, exist_ok=True)

        # System prompt
        system_msgs = [m for m in messages if m.get("role") == "system"]
        if system_msgs:
            (agent_dir / "system_prompt.txt").write_text(
                system_msgs[0].get("content", ""), encoding="utf-8"
            )

        # User message(s)
        user_msgs = [m for m in messages if m.get("role") == "user"]
        if user_msgs:
            user_text = "\n\n---\n\n".join(m.get("content", "") for m in user_msgs)
            (agent_dir / "user_message.txt").write_text(user_text, encoding="utf-8")

        # Raw response (thinking + content)
        raw_parts = []
        if thinking:
            raw_parts.append(f"<think>\n{thinking}\n</think>\n")
        raw_parts.append(raw_response)
        (agent_dir / "raw_response.txt").write_text(
            "\n".join(raw_parts), encoding="utf-8"
        )

        # Parsed YAML output
        if parsed_data is not None:
            with open(agent_dir / "parsed.yaml", "w") as f:
                yaml.dump(parsed_data, f, default_flow_style=False, sort_keys=False)

        # Call metadata
        if call_record is not None:
            with open(agent_dir / "call_log.yaml", "w") as f:
                yaml.dump(asdict(call_record), f, default_flow_style=False, sort_keys=False)

    def write_summary(self, call_records: list[LLMCallRecord]) -> None:
        """Write aggregated turn-level summary."""
        if not call_records:
            return

        total_latency = sum(r.latency_ms for r in call_records)
        total_prompt = sum(r.prompt_tokens for r in call_records)
        total_thinking = sum(r.thinking_tokens for r in call_records)
        total_content = sum(r.content_tokens for r in call_records)
        parse_failures = [r for r in call_records if r.parse_result != "success"]

        summary = {
            "turn": call_records[0].turn,
            "agent_count": len(call_records),
            "total_latency_ms": total_latency,
            "total_prompt_tokens": total_prompt,
            "total_thinking_tokens": total_thinking,
            "total_content_tokens": total_content,
            "parse_failures": [
                {"agent": r.agent, "type": r.parse_result} for r in parse_failures
            ],
            "agents": [
                {
                    "agent": r.agent,
                    "latency_ms": r.latency_ms,
                    "prompt_tokens": r.prompt_tokens,
                    "thinking_tokens": r.thinking_tokens,
                    "content_tokens": r.content_tokens,
                    "parse_result": r.parse_result,
                    "finish_reason": r.finish_reason,
                }
                for r in call_records
            ],
        }

        with open(self.turn_dir / "summary.yaml", "w") as f:
            yaml.dump(summary, f, default_flow_style=False, sort_keys=False)
```

### 4.3 Integration with Turn Engine

Add a `debug: bool = False` parameter to `run_turn()`. When `True`:

1. Create a `DiagnosticsWriter(game.save_path, new_turn)`
2. After each agent call, call `writer.write_agent()` with the messages, response, and record
3. At the end of the turn, call `writer.write_summary()` with all records from that turn

Each agent function returns its messages alongside its result. The simplest approach: have each agent function accept an optional `_return_messages: bool = False` internal flag, or capture messages in the turn engine before calling the agent. The cleaner approach is to capture messages in the turn engine by calling the context builder directly:

```python
# In run_turn(), before calling run_narrator():
if debug:
    diag = DiagnosticsWriter(game.save_path, new_turn)
    narrator_messages = build_narrator_messages(game, player_input, llm_config)
```

Then after the agent completes:

```python
if debug:
    diag.write_agent(
        agent_dir_name="narrator",
        messages=narrator_messages,
        raw_response=narrator_output.narration,
        thinking="",  # thinking from stream is not retained — see Section 4.4
        parsed_data=result.data if not isinstance(result, Exception) else None,
        call_record=turn_records[-1] if turn_records else None,
    )
```

### 4.4 Capturing Thinking Tokens from Streaming

The narrator and character agents use streaming, which currently discards thinking tokens after display. To capture them for diagnostics, accumulate thinking chunks alongside content chunks in the agent functions:

```python
# In run_narrator():
thinking_parts: list[str] = []
async for chunk in stream_iter:
    if on_token and chunk.content:
        await on_token(chunk.content)
    if chunk.thinking:
        thinking_parts.append(chunk.thinking)
full_thinking = "".join(thinking_parts)
```

Store `full_thinking` on the result or pass it directly to the diagnostics writer.

### 4.5 CLI and Playtest Integration

Add a `--debug` flag to:
- `scripts/playtest.py` — enables diagnostics filesystem for every turn
- The CLI (`python -m theact`) — enables diagnostics for the current session

When `--debug` is active, print a message at the end of each turn:

```
[debug] Diagnostics written to saves/<save-id>/diagnostics/turn-001/
```

### Verification

- `DiagnosticsWriter.write_agent()` creates the expected directory structure and files.
- `DiagnosticsWriter.write_summary()` produces valid YAML with correct aggregates.
- Running a turn with `debug=True` creates `saves/<save>/diagnostics/turn-001/` with subdirectories for each agent.
- Each `system_prompt.txt` contains the fully rendered prompt (no `{placeholders}`).
- Each `raw_response.txt` contains the model's actual output.
- Running with `debug=False` (default) creates no diagnostics files.

---

## 5. Context Window Profiler

### 5.1 Design

A utility that computes and reports per-agent token allocation for a turn. This answers the question: "How close is each agent to its context window limit?"

Create `src/theact/llm/profiler.py`:

```python
"""Context window profiler for per-agent token analysis."""

from __future__ import annotations

from dataclasses import dataclass

from theact.llm.tokens import estimate_tokens


@dataclass
class AgentProfile:
    """Token allocation for a single agent call."""

    agent: str
    system_prompt_tokens: int
    user_message_tokens: int
    total_prompt_tokens: int
    max_tokens_budget: int      # the agent's max_tokens setting
    context_limit: int          # the model's context window (8192)
    headroom: int               # context_limit - total_prompt - max_tokens_budget

    # Breakdown of user message components (if available)
    summary_tokens: int = 0         # rolling summary
    conversation_tokens: int = 0    # recent conversation history
    chapter_context_tokens: int = 0 # chapter beats, completion criteria
    current_input_tokens: int = 0   # player input for this turn

    # Actual response data (filled after the call completes)
    actual_thinking_tokens: int = 0
    actual_content_tokens: int = 0


def profile_messages(
    agent: str,
    messages: list[dict[str, str]],
    max_tokens_budget: int,
    context_limit: int = 8192,
) -> AgentProfile:
    """Profile a set of messages for token allocation."""
    system_tokens = 0
    user_tokens = 0
    for msg in messages:
        content = msg.get("content", "")
        if msg.get("role") == "system":
            system_tokens += estimate_tokens(content)
        elif msg.get("role") == "user":
            user_tokens += estimate_tokens(content)

    total = system_tokens + user_tokens
    headroom = context_limit - total - max_tokens_budget

    return AgentProfile(
        agent=agent,
        system_prompt_tokens=system_tokens,
        user_message_tokens=user_tokens,
        total_prompt_tokens=total,
        max_tokens_budget=max_tokens_budget,
        context_limit=context_limit,
        headroom=headroom,
    )


def format_profile(profile: AgentProfile) -> str:
    """Format a profile as a human-readable string."""
    bar_width = 40
    pct_prompt = profile.total_prompt_tokens / profile.context_limit
    pct_budget = profile.max_tokens_budget / profile.context_limit
    pct_headroom = max(0, profile.headroom) / profile.context_limit

    prompt_bar = int(pct_prompt * bar_width)
    budget_bar = int(pct_budget * bar_width)
    headroom_bar = bar_width - prompt_bar - budget_bar

    bar = "#" * prompt_bar + "=" * budget_bar + "." * max(0, headroom_bar)

    lines = [
        f"Agent: {profile.agent}",
        f"  System prompt:    {profile.system_prompt_tokens:>5} tokens",
        f"  User message:     {profile.user_message_tokens:>5} tokens",
        f"  Total prompt:     {profile.total_prompt_tokens:>5} tokens  ({pct_prompt:.1%})",
        f"  Max tokens:       {profile.max_tokens_budget:>5} tokens  ({pct_budget:.1%})",
        f"  Headroom:         {profile.headroom:>5} tokens  ({pct_headroom:.1%})",
        f"  [{bar}]  {profile.context_limit}",
    ]

    if profile.headroom < 0:
        lines.append(f"  WARNING: Over budget by {-profile.headroom} tokens!")

    if profile.actual_thinking_tokens or profile.actual_content_tokens:
        lines.append(f"  Actual thinking:  {profile.actual_thinking_tokens:>5} tokens")
        lines.append(f"  Actual content:   {profile.actual_content_tokens:>5} tokens")
        ratio = profile.actual_thinking_tokens / max(profile.actual_content_tokens, 1)
        lines.append(f"  Thinking:content: {ratio:.1f}:1")

    return "\n".join(lines)


def format_turn_profile(profiles: list[AgentProfile]) -> str:
    """Format all agent profiles for a complete turn."""
    sections = ["=== CONTEXT WINDOW PROFILE ===", ""]
    for p in profiles:
        sections.append(format_profile(p))
        sections.append("")
    return "\n".join(sections)
```

### 5.2 Integration Points

The profiler can be used from:

1. **Diagnostics filesystem** — when `debug=True`, include a `context_profile.yaml` in each turn's diagnostics directory with all agent profiles.

2. **Scripts** — a `--profile-context` flag on `scripts/diagnose_agent.py` that outputs the profile before making the LLM call:

```bash
uv run python scripts/diagnose_agent.py --profile-context narrator "I search for water."
```

3. **Playtest reports** — aggregate context profiles across turns to show how prompt sizes grow over a session (see Section 7).

### 5.3 User Message Breakdown

For the narrator agent, break down the user message into its components (summary, conversation, chapter context, player input). This requires collaboration with the context assembly code.

Add an optional `_profile: bool = False` parameter to `build_narrator_messages()` that, when `True`, returns the message list alongside a breakdown dict:

```python
def build_narrator_messages(
    game: LoadedGame,
    player_input: str,
    llm_config: LLMConfig,
    profile: bool = False,
) -> list[Message] | tuple[list[Message], dict[str, int]]:
    """Build narrator messages. If profile=True, also return token breakdown."""
    # ... existing logic ...

    if profile:
        breakdown = {
            "summary_tokens": estimate_tokens(game.state.rolling_summary),
            "conversation_tokens": estimate_tokens(recent_text),
            "chapter_context_tokens": estimate_tokens(chapter_context),
            "current_input_tokens": estimate_tokens(player_input),
        }
        return messages, breakdown
    return messages
```

### Verification

- `profile_messages()` returns correct token counts for test messages.
- `format_profile()` produces readable output with a visual bar.
- Headroom correctly goes negative when prompt + max_tokens > context_limit.
- Profile integration with diagnostics filesystem writes `context_profile.yaml`.

---

## 6. Prompt Linting

### 6.1 Design

Automated tests that catch prompt-level problems without making LLM calls. These run as part of the standard `pytest` suite.

Create `tests/test_prompt_lint.py`:

```python
"""Prompt linting tests — catch prompt problems without LLM calls."""

import re

import pytest

from theact.agents.prompts import (
    CHARACTER_SYSTEM,
    CHAPTER_SUMMARY_SYSTEM,
    GAME_STATE_SYSTEM,
    MEMORY_UPDATE_SYSTEM,
    NARRATOR_SYSTEM,
    ROLLING_SUMMARY_SYSTEM,
)
from theact.llm.tokens import estimate_tokens


# --- Token budget tests ---

PROMPT_TOKEN_BUDGETS = {
    "NARRATOR_SYSTEM": (NARRATOR_SYSTEM, 300),
    "CHARACTER_SYSTEM": (CHARACTER_SYSTEM, 300),
    "MEMORY_UPDATE_SYSTEM": (MEMORY_UPDATE_SYSTEM, 300),
    "GAME_STATE_SYSTEM": (GAME_STATE_SYSTEM, 300),
    "CHAPTER_SUMMARY_SYSTEM": (CHAPTER_SUMMARY_SYSTEM, 300),
    "ROLLING_SUMMARY_SYSTEM": (ROLLING_SUMMARY_SYSTEM, 300),
}


@pytest.mark.parametrize("name,spec", PROMPT_TOKEN_BUDGETS.items())
def test_system_prompt_token_budget(name, spec):
    """System prompts must stay under their token budget.

    Per CLAUDE.md: system prompts should stay under ~300 tokens.
    This tests the TEMPLATE before variable substitution. Rendered
    prompts will be slightly larger due to injected game content.
    """
    template, budget = spec
    # Strip format placeholders for estimation (they'll be replaced with real content)
    stripped = re.sub(r"\{[^}]+\}", "PLACEHOLDER", template)
    tokens = estimate_tokens(stripped)
    assert tokens <= budget, (
        f"{name} template is ~{tokens} tokens (budget: {budget}). "
        f"Trim the prompt to fit."
    )


# --- Orphan placeholder tests ---

def _render_narrator_prompt():
    """Render the narrator prompt with dummy values to check for orphan placeholders."""
    return NARRATOR_SYSTEM.format(
        world_setting="A tropical island.",
        world_tone="Tense survival.",
        world_rules="No magic.",
        chapter_context="Chapter 1: The Crash",
        active_characters="maya (Maya Chen), joaquin (Father Joaquin)",
    )


def _render_character_prompt():
    """Render the character prompt with dummy values."""
    return CHARACTER_SYSTEM.format(
        name="Maya",
        role="Engineer",
        personality="Practical, direct.",
        secret="She caused the crash.",
        relationships="Player: cautious ally",
        memory_block="No memories yet.",
    )


def _render_memory_prompt():
    return MEMORY_UPDATE_SYSTEM.format(name="Maya")


RENDERED_PROMPTS = {
    "narrator": _render_narrator_prompt,
    "character": _render_character_prompt,
    "memory": _render_memory_prompt,
}


@pytest.mark.parametrize("name,renderer", RENDERED_PROMPTS.items())
def test_no_orphan_placeholders(name, renderer):
    """After rendering, no {placeholder} strings should remain."""
    rendered = renderer()
    orphans = re.findall(r"\{[a-z_]+\}", rendered)
    assert not orphans, (
        f"{name} prompt has orphan placeholders after rendering: {orphans}"
    )


# --- YAML hint consistency tests ---

def test_narrator_yaml_hint_fields():
    """The narrator YAML example in the prompt must include all parsed fields."""
    required_fields = ["narration", "responding_characters", "mood"]
    for field in required_fields:
        assert field in NARRATOR_SYSTEM, (
            f"Narrator prompt missing YAML field '{field}' in example"
        )


def test_memory_yaml_hint_fields():
    """The memory YAML example must include all parsed fields."""
    required_fields = ["summary", "add", "remove", "update"]
    for field in required_fields:
        assert field in MEMORY_UPDATE_SYSTEM, (
            f"Memory prompt missing YAML field '{field}' in example"
        )


def test_game_state_yaml_hint_fields():
    """The game state YAML example must include all parsed fields."""
    required_fields = ["chapter_complete", "new_beats"]
    for field in required_fields:
        assert field in GAME_STATE_SYSTEM, (
            f"Game state prompt missing YAML field '{field}' in example"
        )


# --- Rendered prompt budget tests ---

def test_rendered_narrator_prompt_budget():
    """Fully rendered narrator prompt should stay under 400 tokens.

    The template is ~300 tokens; rendered with real game content
    it should not exceed ~400.
    """
    rendered = _render_narrator_prompt()
    tokens = estimate_tokens(rendered)
    assert tokens <= 400, (
        f"Rendered narrator prompt is ~{tokens} tokens (budget: 400)"
    )
```

### 6.2 Context Assembly Lint Tests

Add tests in `tests/test_context_lint.py` that verify context assembly with realistic game data stays within budgets:

```python
"""Context assembly budget tests using realistic game fixtures."""

from theact.engine.context import (
    build_character_messages,
    build_game_state_messages,
    build_memory_messages,
    build_narrator_messages,
)
from theact.llm.config import (
    CHARACTER_CONFIG,
    GAME_STATE_CONFIG,
    LLMConfig,
    MEMORY_UPDATE_CONFIG,
    NARRATOR_CONFIG,
)
from theact.llm.profiler import profile_messages


def test_narrator_context_fits_window(sample_game):
    """Narrator prompt + max_tokens must fit within 8192 context limit."""
    llm_config = LLMConfig(api_key="test")
    messages = build_narrator_messages(sample_game, "I search for water.", llm_config)
    profile = profile_messages(
        "narrator", messages,
        NARRATOR_CONFIG.max_tokens or llm_config.default_max_tokens,
        llm_config.context_limit,
    )
    assert profile.headroom >= 0, (
        f"Narrator prompt ({profile.total_prompt_tokens} tokens) + "
        f"max_tokens ({profile.max_tokens_budget}) exceeds context limit "
        f"({profile.context_limit}). Headroom: {profile.headroom}"
    )


# Similar tests for character, memory, game_state agents...
```

These tests use existing `sample_game` fixtures from `tests/conftest.py`.

### Verification

- All prompt lint tests pass on the current codebase.
- Intentionally breaking a prompt (e.g., adding a `{missing}` placeholder) causes the orphan test to fail.
- Inflating a prompt beyond 300 tokens causes the budget test to fail.

---

## 7. Playtest Integration

### 7.1 Call Log in Playtest Runner

Modify `PlaytestRunner` in `src/theact/playtest/runner.py` to create an `LLMCallLog` and pass it through to `run_turn()`:

```python
class PlaytestRunner:
    def __init__(self, config: PlaytestConfig) -> None:
        self.config = config
        self.logger = PlaytestLogger()
        self.call_log = LLMCallLog()      # NEW
        self.player_agent = PlayerAgent(...)

    async def run(self) -> PlaytestReport:
        # ... existing code ...

        result = await run_turn(
            game, player_input,
            llm_config=self.config.llm_config,
            call_log=self.call_log,          # NEW
        )
```

### 7.2 Call Log Persistence

In `_finalize()`, write the call log to disk alongside the report:

```python
def _finalize(self, run_start: float) -> PlaytestReport:
    # ... existing code ...

    # Write call log
    out_path = Path(self.config.output_dir) / self.config.timestamp
    self.call_log.dump_yaml(out_path / "llm_calls.yaml")

    # ... existing report generation ...
```

Also flush the call log incrementally in the main loop (same pattern as `logger.flush_to_disk()`).

### 7.3 Report Enhancements

Add an "LLM Call Summary" section to the playtest report. Modify `generate_report_markdown()` in `src/theact/playtest/report.py`:

```python
def generate_report_markdown(report: PlaytestReport) -> str:
    # ... existing sections ...

    # LLM Call Summary
    if report.call_log_summary:
        lines.append("## LLM Call Summary")
        lines.append("")
        lines.append("| Agent | Calls | Avg Latency | Avg Think Tok | Avg Content Tok | Parse Success | Length Finishes |")
        lines.append("|-------|-------|-------------|---------------|-----------------|---------------|-----------------|")
        for agent, stats in report.call_log_summary.items():
            lines.append(
                f"| {agent} | {stats['calls']} | {stats['mean_latency_ms']}ms "
                f"| {stats['mean_thinking_tokens']} | {stats['mean_content_tokens']} "
                f"| {stats['parse_success_rate']:.0%} | {stats['length_finishes']} |"
            )
        lines.append("")

        totals = report.call_log_totals
        if totals:
            lines.append(
                f"**Total tokens:** {totals['total_prompt_tokens']} prompt + "
                f"{totals['total_thinking_tokens']} thinking + "
                f"{totals['total_content_tokens']} content"
            )
            lines.append("")

    # Parse failure breakdown
    if report.parse_failure_breakdown:
        lines.append("## Parse Failures")
        lines.append("")
        lines.append("| Type | Count |")
        lines.append("|------|-------|")
        for ftype, count in report.parse_failure_breakdown.items():
            lines.append(f"| {ftype} | {count} |")
        lines.append("")
```

### 7.4 New Report Fields

Add these fields to `PlaytestReport` in `src/theact/playtest/report.py`:

```python
@dataclass
class PlaytestReport:
    # ... existing fields ...

    # LLM call data (populated from LLMCallLog)
    call_log_summary: dict[str, dict] = field(default_factory=dict)   # agent -> stats
    call_log_totals: dict = field(default_factory=dict)               # aggregate totals
    parse_failure_breakdown: dict[str, int] = field(default_factory=dict)  # type -> count
```

Populate them in `generate_report()`:

```python
def generate_report(
    logger: PlaytestLogger,
    config: PlaytestConfig,
    game_title: str,
    total_duration: float,
    memory_final: dict[str, str] | None = None,
    call_log: LLMCallLog | None = None,    # NEW
) -> PlaytestReport:
    # ... existing code ...

    call_log_summary = {}
    call_log_totals = {}
    parse_failure_breakdown = {}
    if call_log:
        call_log_summary = call_log.agent_summary()
        call_log_totals = call_log.summary()
        # Count parse failures by type
        for r in call_log.records:
            if r.parse_result != "success":
                parse_failure_breakdown[r.parse_result] = (
                    parse_failure_breakdown.get(r.parse_result, 0) + 1
                )

    return PlaytestReport(
        # ... existing fields ...
        call_log_summary=call_log_summary,
        call_log_totals=call_log_totals,
        parse_failure_breakdown=parse_failure_breakdown,
    )
```

### 7.5 Per-Turn Token Usage in TurnLog

Extend `TurnLog` in `src/theact/playtest/logger.py` to include actual token data:

```python
@dataclass
class TurnLog:
    # ... existing fields ...

    # Per-agent token data (from call log)
    agent_tokens: dict[str, dict] = field(default_factory=dict)
    # e.g. {"narrator": {"prompt": 340, "thinking": 680, "content": 320}, ...}
```

Populate this from the call log after each turn:

```python
# In PlaytestRunner, after run_turn():
turn_records = self.call_log.records_for_turn(turn_num)
agent_tokens = {}
for r in turn_records:
    agent_tokens[r.agent] = {
        "prompt": r.prompt_tokens,
        "thinking": r.thinking_tokens,
        "content": r.content_tokens,
        "latency_ms": r.latency_ms,
    }
```

### Verification

- A 3-turn playtest with `call_log` enabled produces `llm_calls.yaml` with one record per agent call per turn.
- The playtest report markdown includes the "LLM Call Summary" table.
- Parse failure breakdown correctly counts failures by type.
- `TurnLog.agent_tokens` is populated for each turn.

---

## 8. Implementation Steps

### Step 1: Error Taxonomy (Section 2)

**Files to create/modify:**
- Modify: `src/theact/llm/errors.py` — add `ParseFailureType` enum
- Modify: `src/theact/llm/parsing.py` — add `classify_parse_failure()`, update `YAMLParseError`
- Create: `tests/test_error_taxonomy.py`

**Verification:**
```bash
uv run pytest tests/test_error_taxonomy.py -v
```

### Step 2: Call Log Module (Section 3.1)

**Files to create:**
- `src/theact/llm/call_log.py` — `LLMCallRecord`, `LLMCallLog`
- `tests/test_call_log.py`

**Verification:**
```bash
uv run pytest tests/test_call_log.py -v
```

### Step 3: Wire Call Logging into Agents (Section 3.2-3.3)

**Files to modify:**
- `src/theact/agents/narrator.py` — add `call_log` and `turn` params, record calls
- `src/theact/agents/character.py` — same
- `src/theact/agents/memory.py` — same
- `src/theact/agents/game_state.py` — same
- `src/theact/agents/summarizer.py` — same
- `src/theact/engine/turn.py` — add `call_log` param, pass to agents

**Verification:**
- Existing tests still pass (backward compatible).
- Manual test: run a turn with a real `LLMCallLog`, verify records are created.

### Step 4: Diagnostics Filesystem (Section 4)

**Files to create:**
- `src/theact/engine/diagnostics.py` — `DiagnosticsWriter`
- `tests/test_diagnostics.py`

**Files to modify:**
- `src/theact/engine/turn.py` — add `debug` param, create writer, write artifacts

**Verification:**
```bash
uv run pytest tests/test_diagnostics.py -v
```

### Step 5: Context Window Profiler (Section 5)

**Files to create:**
- `src/theact/llm/profiler.py` — `AgentProfile`, `profile_messages()`, `format_profile()`
- `tests/test_profiler.py`

**Verification:**
```bash
uv run pytest tests/test_profiler.py -v
```

### Step 6: Prompt Linting Tests (Section 6)

**Files to create:**
- `tests/test_prompt_lint.py`
- `tests/test_context_lint.py`

**Verification:**
```bash
uv run pytest tests/test_prompt_lint.py tests/test_context_lint.py -v
```

### Step 7: Playtest Integration (Section 7)

**Files to modify:**
- `src/theact/playtest/runner.py` — add `LLMCallLog`, pass to `run_turn()`, persist
- `src/theact/playtest/report.py` — add call log fields to `PlaytestReport`, markdown section
- `src/theact/playtest/logger.py` — extend `TurnLog` with `agent_tokens`

**Verification:**
```bash
uv run pytest tests/ -v
```

### Step 8: Integration Test

Run a full integration check:

```bash
# Run all unit tests
uv run pytest tests/ -v

# Run lint/format
uv run prek run --all-files

# If LLM_API_KEY is available, run a short playtest with debug + call logging
uv run python scripts/playtest.py --game lost-island --turns 3 --debug
```

Verify:
- `playtests/<timestamp>/llm_calls.yaml` exists and contains structured records
- `playtests/<timestamp>/report.md` includes the "LLM Call Summary" section
- `saves/playtest-<timestamp>/diagnostics/turn-001/` contains agent subdirectories
- Each agent subdirectory contains `system_prompt.txt`, `user_message.txt`, `raw_response.txt`
- `turn-001/summary.yaml` contains aggregated turn stats

---

## 9. Files Summary

### New files

| File | Purpose |
|------|---------|
| `src/theact/llm/call_log.py` | `LLMCallRecord` and `LLMCallLog` dataclasses |
| `src/theact/llm/profiler.py` | Context window profiler |
| `src/theact/engine/diagnostics.py` | Diagnostics filesystem writer |
| `tests/test_error_taxonomy.py` | Tests for `ParseFailureType` and classifier |
| `tests/test_call_log.py` | Tests for call log accumulation and aggregation |
| `tests/test_diagnostics.py` | Tests for diagnostics writer |
| `tests/test_profiler.py` | Tests for context window profiler |
| `tests/test_prompt_lint.py` | Prompt token budget and format lint tests |
| `tests/test_context_lint.py` | Context assembly budget tests |

### Modified files

| File | Changes |
|------|---------|
| `src/theact/llm/errors.py` | Add `ParseFailureType` enum |
| `src/theact/llm/parsing.py` | Add `classify_parse_failure()`, update `YAMLParseError` |
| `src/theact/agents/narrator.py` | Add `call_log`/`turn` params, record calls |
| `src/theact/agents/character.py` | Add `call_log`/`turn` params, record calls |
| `src/theact/agents/memory.py` | Add `call_log`/`turn` params, record calls |
| `src/theact/agents/game_state.py` | Add `call_log`/`turn` params, record calls |
| `src/theact/agents/summarizer.py` | Add `call_log`/`turn` params, record calls |
| `src/theact/engine/turn.py` | Add `call_log`/`debug` params, wire diagnostics |
| `src/theact/engine/context.py` | Optional profile breakdown in message builders |
| `src/theact/llm/tokens.py` | Add `estimate_messages_content_tokens()` |
| `src/theact/playtest/runner.py` | Create and pass `LLMCallLog`, persist call log |
| `src/theact/playtest/report.py` | Add call log summary fields and markdown section |
| `src/theact/playtest/logger.py` | Extend `TurnLog` with `agent_tokens` |
| `scripts/diagnose_agent.py` | Add `--profile-context` flag for token profiling |

"""Data types for the turn debugger."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class AgentResult:
    """Captured result from a single agent call."""

    agent: str  # "narrator", "character:maya", "memory:maya", "game_state"
    messages: list[dict[str, str]]  # prompt messages sent to model
    raw_response: str  # full response text
    thinking: str  # thinking content
    content: str  # actual response content
    parsed_data: dict[str, Any] | None  # parsed YAML data (None for unstructured)
    prompt_tokens: int
    thinking_tokens: int
    content_tokens: int
    latency_ms: int
    finish_reason: str
    parse_success: bool
    parse_attempts: int


@dataclass
class DebugStep:
    """A single step in the debug session."""

    agent: str
    result: AgentResult
    skipped: bool = False


@dataclass
class DebugSession:
    """State for an interactive debug session."""

    game_id: str
    save_id: str
    player_input: str
    steps: list[DebugStep] = field(default_factory=list)
    history: dict[str, list[AgentResult]] = field(default_factory=dict)
    narrator_output: Any = None
    character_responses: list[Any] = field(default_factory=list)

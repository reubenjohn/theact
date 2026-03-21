"""Helper functions for the turn debugger."""

from __future__ import annotations

import difflib
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

from theact.models.conversation import ConversationEntry

if TYPE_CHECKING:
    from theact.debugger.types import AgentResult, DebugSession


def _extract_turn_entries(session: DebugSession) -> list[ConversationEntry]:
    """Build ConversationEntry list from completed debug steps.

    Constructs entries for the player input, narrator output, and any
    character responses that have been collected so far.
    """
    entries: list[ConversationEntry] = []

    # Player entry
    entries.append(
        ConversationEntry(
            turn=0,
            role="player",
            content=session.player_input,
        )
    )

    # Narrator entry from session
    if session.narrator_output is not None:
        entries.append(
            ConversationEntry(
                turn=0,
                role="narrator",
                content=session.narrator_output.narration,
            )
        )

    # Character entries
    for cr in session.character_responses:
        entries.append(
            ConversationEntry(
                turn=0,
                role="character",
                character=cr.character,
                content=cr.response,
            )
        )

    return entries


def _format_inspection(result: AgentResult, field: str = "all") -> str:
    """Format agent result for display.

    Fields: all, prompt, response, parsed, stats
    """
    parts: list[str] = []

    if field in ("all", "prompt"):
        parts.append("=== PROMPT ===")
        for msg in result.messages:
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            parts.append(f"[{role}]")
            parts.append(content)
            parts.append("")

    if field in ("all", "response"):
        parts.append("=== RESPONSE ===")
        if result.thinking:
            parts.append(f"[thinking]\n{result.thinking}\n")
        parts.append(f"[content]\n{result.content}")
        parts.append("")

    if field in ("all", "parsed"):
        parts.append("=== PARSED ===")
        if result.parsed_data is not None:
            parts.append(
                yaml.dump(
                    result.parsed_data,
                    default_flow_style=False,
                    allow_unicode=True,
                    sort_keys=False,
                )
            )
        else:
            parts.append("(unstructured agent, no parsed data)")
        parts.append("")

    if field in ("all", "stats"):
        parts.append("=== STATS ===")
        parts.append(f"Agent: {result.agent}")
        parts.append(f"Prompt tokens: {result.prompt_tokens}")
        parts.append(f"Thinking tokens: {result.thinking_tokens}")
        parts.append(f"Content tokens: {result.content_tokens}")
        parts.append(f"Latency: {result.latency_ms}ms")
        parts.append(f"Finish reason: {result.finish_reason}")
        parts.append(f"Parse success: {result.parse_success}")
        parts.append(f"Parse attempts: {result.parse_attempts}")

    return "\n".join(parts)


def _format_comparison(a: AgentResult, b: AgentResult) -> str:
    """Word-level diff of two results plus stats comparison."""
    parts: list[str] = []

    # Content diff
    parts.append("=== CONTENT DIFF ===")
    diff = difflib.unified_diff(
        a.content.splitlines(keepends=True),
        b.content.splitlines(keepends=True),
        fromfile="run-1",
        tofile="run-2",
    )
    diff_text = "".join(diff)
    if diff_text:
        parts.append(diff_text)
    else:
        parts.append("(no differences)")
    parts.append("")

    # Stats comparison
    parts.append("=== STATS COMPARISON ===")
    parts.append(f"{'':15s} {'Run 1':>10s} {'Run 2':>10s}")
    parts.append(f"{'Prompt tok':15s} {a.prompt_tokens:>10d} {b.prompt_tokens:>10d}")
    parts.append(
        f"{'Thinking tok':15s} {a.thinking_tokens:>10d} {b.thinking_tokens:>10d}"
    )
    parts.append(f"{'Content tok':15s} {a.content_tokens:>10d} {b.content_tokens:>10d}")
    parts.append(f"{'Latency ms':15s} {a.latency_ms:>10d} {b.latency_ms:>10d}")
    parts.append(f"{'Finish':15s} {a.finish_reason:>10s} {b.finish_reason:>10s}")

    return "\n".join(parts)


def _save_fixture(result: AgentResult, fixture_name: str) -> Path:
    """Save AgentResult as YAML fixture to tests/fixtures/{fixture_name}.yaml."""
    fixtures_dir = Path(__file__).parent.parent.parent.parent / "tests" / "fixtures"
    fixtures_dir.mkdir(parents=True, exist_ok=True)

    fixture_path = fixtures_dir / f"{fixture_name}.yaml"

    data = {
        "agent": result.agent,
        "messages": result.messages,
        "raw_response": result.raw_response,
        "thinking": result.thinking,
        "content": result.content,
        "parsed_data": result.parsed_data,
        "prompt_tokens": result.prompt_tokens,
        "thinking_tokens": result.thinking_tokens,
        "content_tokens": result.content_tokens,
        "latency_ms": result.latency_ms,
        "finish_reason": result.finish_reason,
        "parse_success": result.parse_success,
        "parse_attempts": result.parse_attempts,
    }

    with open(fixture_path, "w") as f:
        yaml.dump(
            data,
            f,
            default_flow_style=False,
            allow_unicode=True,
            sort_keys=False,
        )

    return fixture_path

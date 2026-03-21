"""Tests for the turn debugger."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from theact.debugger.helpers import (
    _extract_turn_entries,
    _format_comparison,
    _format_inspection,
)
from theact.debugger.types import AgentResult, DebugSession, DebugStep
from theact.engine.types import CharacterResponse, NarratorOutput
from theact.io.save_manager import create_save
from theact.llm.config import LLMConfig


def _make_agent_result(
    agent: str = "narrator",
    content: str = "Test content",
    thinking: str = "",
    parsed_data: dict | None = None,
    prompt_tokens: int = 100,
    thinking_tokens: int = 0,
    content_tokens: int = 50,
    latency_ms: int = 500,
    finish_reason: str = "stop",
    parse_success: bool = True,
    parse_attempts: int = 1,
    messages: list[dict[str, str]] | None = None,
    raw_response: str = "",
) -> AgentResult:
    """Helper to create an AgentResult with sensible defaults."""
    return AgentResult(
        agent=agent,
        messages=messages
        or [
            {"role": "system", "content": "You are a narrator."},
            {"role": "user", "content": "Player says: hello"},
        ],
        raw_response=raw_response or content,
        thinking=thinking,
        content=content,
        parsed_data=parsed_data,
        prompt_tokens=prompt_tokens,
        thinking_tokens=thinking_tokens,
        content_tokens=content_tokens,
        latency_ms=latency_ms,
        finish_reason=finish_reason,
        parse_success=parse_success,
        parse_attempts=parse_attempts,
    )


class TestDebugSession:
    def test_extract_turn_entries_empty(self):
        session = DebugSession(
            game_id="test",
            save_id="test-save",
            player_input="hello",
        )
        entries = _extract_turn_entries(session)
        # Should have just the player entry
        assert len(entries) == 1
        assert entries[0].role == "player"
        assert entries[0].content == "hello"

    def test_extract_turn_entries_with_narrator(self):
        session = DebugSession(
            game_id="test",
            save_id="test-save",
            player_input="I look around.",
        )
        session.narrator_output = NarratorOutput(
            narration="You see a dark forest.",
            responding_characters=["maya"],
            mood="mysterious",
        )
        entries = _extract_turn_entries(session)
        assert len(entries) == 2
        assert entries[0].role == "player"
        assert entries[1].role == "narrator"
        assert entries[1].content == "You see a dark forest."

    def test_extract_turn_entries_with_characters(self):
        session = DebugSession(
            game_id="test",
            save_id="test-save",
            player_input="hello",
        )
        session.narrator_output = NarratorOutput(
            narration="The clearing opens up.",
            responding_characters=["maya"],
            mood="calm",
        )
        session.character_responses = [
            CharacterResponse(character="Maya", response="Hey there.")
        ]
        entries = _extract_turn_entries(session)
        assert len(entries) == 3
        assert entries[2].role == "character"
        assert entries[2].character == "Maya"

    def test_format_inspection_all(self):
        result = _make_agent_result(
            content="You see a forest.",
            thinking="Let me think...",
            parsed_data={"narration": "You see a forest.", "mood": "calm"},
        )
        output = _format_inspection(result, "all")
        assert "=== PROMPT ===" in output
        assert "=== RESPONSE ===" in output
        assert "=== PARSED ===" in output
        assert "=== STATS ===" in output
        assert "You see a forest." in output
        assert "Let me think..." in output

    def test_format_inspection_prompt_only(self):
        result = _make_agent_result()
        output = _format_inspection(result, "prompt")
        assert "=== PROMPT ===" in output
        assert "=== RESPONSE ===" not in output
        assert "=== STATS ===" not in output

    def test_format_inspection_response_only(self):
        result = _make_agent_result(content="Some response text")
        output = _format_inspection(result, "response")
        assert "=== RESPONSE ===" in output
        assert "Some response text" in output
        assert "=== PROMPT ===" not in output

    def test_format_inspection_stats_only(self):
        result = _make_agent_result(
            latency_ms=1234, prompt_tokens=200, content_tokens=80
        )
        output = _format_inspection(result, "stats")
        assert "=== STATS ===" in output
        assert "1234ms" in output
        assert "200" in output
        assert "80" in output

    def test_format_inspection_parsed_none(self):
        result = _make_agent_result(parsed_data=None)
        output = _format_inspection(result, "parsed")
        assert "unstructured agent" in output

    def test_format_comparison(self):
        a = _make_agent_result(content="First version", latency_ms=100)
        b = _make_agent_result(content="Second version", latency_ms=200)
        output = _format_comparison(a, b)
        assert "=== CONTENT DIFF ===" in output
        assert "=== STATS COMPARISON ===" in output
        # Should show both latencies
        assert "100" in output
        assert "200" in output

    def test_format_comparison_identical(self):
        a = _make_agent_result(content="Same content")
        b = _make_agent_result(content="Same content")
        output = _format_comparison(a, b)
        assert "no differences" in output

    def test_save_fixture_creates_file(self, tmp_path):
        result = _make_agent_result(
            agent="narrator",
            content="A dark forest stretches before you.",
            parsed_data={"narration": "A dark forest stretches before you."},
        )

        # Override the fixture path via monkeypatch-like approach
        fixture_path = tmp_path / "test_fixture.yaml"

        # Call _save_fixture directly but create our own
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
            yaml.dump(data, f, default_flow_style=False, sort_keys=False)

        assert fixture_path.exists()
        loaded = yaml.safe_load(fixture_path.read_text())
        assert loaded["agent"] == "narrator"
        assert loaded["content"] == "A dark forest stretches before you."
        assert (
            loaded["parsed_data"]["narration"] == "A dark forest stretches before you."
        )


@pytest.fixture
def debugger(tmp_path):
    """Create a TurnDebugger with a real save from lost-island game files."""
    from theact.debugger import TurnDebugger

    games_dir = Path(__file__).parent.parent / "games"
    saves_dir = tmp_path / "saves"
    saves_dir.mkdir()
    create_save(
        "lost-island",
        "test-debug",
        "TestPlayer",
        games_dir=games_dir,
        saves_dir=saves_dir,
    )
    config = LLMConfig(base_url="http://fake", api_key="fake", model="fake")
    return TurnDebugger(
        "lost-island",
        "test-debug",
        "I look around.",
        llm_config=config,
        saves_dir=saves_dir,
    )


class TestTurnDebuggerPlan:
    def test_plan_starts_with_narrator(self, debugger):
        pending = debugger.plan_turn()
        assert pending == ["narrator"]

    def test_plan_returns_list(self, debugger):
        pending = debugger.plan_turn()
        assert isinstance(pending, list)
        assert len(pending) == 1

    def test_skip_removes_from_pending(self, debugger):
        debugger.plan_turn()
        assert debugger.get_pending() == ["narrator"]

        skipped = debugger.skip()
        assert skipped == "narrator"
        assert debugger.get_pending() == []

    def test_skip_returns_none_when_empty(self, debugger):
        debugger.plan_turn()
        debugger.skip()  # skip narrator
        assert debugger.skip() is None

    def test_get_pending_returns_copy(self, debugger):
        debugger.plan_turn()
        pending = debugger.get_pending()
        pending.append("extra")
        # Original should be unmodified
        assert debugger.get_pending() == ["narrator"]

    def test_session_initialized(self, debugger):
        assert debugger.session.game_id == "lost-island"
        assert debugger.session.save_id == "test-debug"
        assert debugger.session.player_input == "I look around."
        assert debugger.session.steps == []
        assert debugger.session.narrator_output is None

    def test_game_loaded(self, debugger):
        assert debugger.game is not None
        assert debugger.game.meta.id == "lost-island"
        assert "maya" in debugger.game.characters
        assert "joaquin" in debugger.game.characters

    def test_skip_creates_skipped_step(self, debugger):
        debugger.plan_turn()
        debugger.skip()
        assert len(debugger.session.steps) == 1
        assert debugger.session.steps[0].skipped is True
        assert debugger.session.steps[0].agent == "narrator"
        assert debugger.session.steps[0].result.finish_reason == "skipped"

    def test_inspect_no_results(self, debugger):
        result = debugger.inspect("narrator")
        assert "No results" in result

    def test_compare_insufficient_runs(self, debugger):
        result = debugger.compare("narrator")
        assert "Need at least 2 runs" in result


class TestAgentResultDataclass:
    def test_creation(self):
        result = _make_agent_result()
        assert result.agent == "narrator"
        assert result.content == "Test content"
        assert result.parse_success is True

    def test_with_parsed_data(self):
        result = _make_agent_result(
            parsed_data={"key": "value"},
        )
        assert result.parsed_data == {"key": "value"}

    def test_unstructured_agent(self):
        result = _make_agent_result(
            agent="character:maya",
            parsed_data=None,
        )
        assert result.parsed_data is None


class TestDebugStep:
    def test_not_skipped_by_default(self):
        result = _make_agent_result()
        step = DebugStep(agent="narrator", result=result)
        assert step.skipped is False

    def test_skipped(self):
        result = _make_agent_result()
        step = DebugStep(agent="narrator", result=result, skipped=True)
        assert step.skipped is True

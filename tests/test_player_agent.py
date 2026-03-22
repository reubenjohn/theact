"""Tests for PlayerAgent — covers decide(), decide_with_metadata(), and all
injection paths: direct, nonsense, repeat, LLM normal, LLM edge case, and
the empty-response fallback."""

from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import AsyncMock, patch

import pytest

from theact.llm.config import LLMConfig
from theact.models.chapter import Chapter
from theact.models.conversation import ConversationEntry
from theact.playtest.player_agent import (
    DIRECT_INJECTION_ALL,
    DIRECT_INJECTION_NONSENSE,
    EDGE_CASE_PROMPTS,
    PLAYER_AGENT_CONFIG,
    PLAYER_SYSTEM_PROMPT,
    PlayerAgent,
)


# -- Helpers ---------------------------------------------------------------


def _make_chapter(**kwargs) -> Chapter:
    defaults = dict(
        id="01-the-crash",
        title="The Crash",
        summary="You wake up on the beach after a plane crash.",
        beats=["Player wakes up", "Player meets Maya"],
        completion="Player has explored the crash site.",
        characters=["maya"],
        next="02-the-discovery",
    )
    defaults.update(kwargs)
    return Chapter(**defaults)


def _make_conversation_tail() -> list[ConversationEntry]:
    return [
        ConversationEntry(turn=1, role="narrator", content="You wake up on the sand."),
        ConversationEntry(turn=1, role="player", content="I look around."),
        ConversationEntry(
            turn=1,
            role="character",
            character="Maya Chen",
            content="Hey, you're awake!",
        ),
    ]


def _make_agent(**kwargs) -> PlayerAgent:
    llm_config = LLMConfig(model="test-model", api_key="test-key")
    return PlayerAgent(llm_config, **kwargs)


# -- Direct injection path -------------------------------------------------


class TestDirectInjection:
    @pytest.mark.asyncio
    async def test_direct_injection_triggered(self, monkeypatch):
        """When random() < direct_edge_case_frequency, returns a direct injection."""
        agent = _make_agent(direct_edge_case_frequency=1.0)  # always triggers

        # Fix random.choice to return a known value
        monkeypatch.setattr(
            "theact.playtest.player_agent.random.choice", lambda x: x[0]
        )
        # Fix random.random to return 0 (below 1.0 threshold)
        monkeypatch.setattr("theact.playtest.player_agent.random.random", lambda: 0.0)

        decision = await agent.decide_with_metadata(
            _make_conversation_tail(), _make_chapter(), turn_number=2
        )
        assert decision.edge_case_type == "direct_injection"
        assert decision.action in DIRECT_INJECTION_ALL

    @pytest.mark.asyncio
    async def test_direct_injection_sets_last_action(self, monkeypatch):
        agent = _make_agent(direct_edge_case_frequency=1.0)
        monkeypatch.setattr(
            "theact.playtest.player_agent.random.choice", lambda x: x[0]
        )
        monkeypatch.setattr("theact.playtest.player_agent.random.random", lambda: 0.0)

        decision = await agent.decide_with_metadata(
            _make_conversation_tail(), _make_chapter(), turn_number=2
        )
        assert agent._last_action == decision.action


# -- Nonsense injection path -----------------------------------------------


class TestNonsenseInjection:
    @pytest.mark.asyncio
    async def test_nonsense_injection_triggered(self, monkeypatch):
        """Nonsense injection: skip direct injection, trigger nonsense."""
        agent = _make_agent(
            direct_edge_case_frequency=0.0,  # never direct
            nonsense_frequency=1.0,  # always nonsense
        )
        monkeypatch.setattr(
            "theact.playtest.player_agent.random.choice", lambda x: x[0]
        )

        random_calls = iter(
            [0.5, 0.0]
        )  # first: skip direct (0.5 > 0.0), second: trigger nonsense (0.0 < 1.0)
        monkeypatch.setattr(
            "theact.playtest.player_agent.random.random",
            lambda: next(random_calls),
        )

        decision = await agent.decide_with_metadata(
            _make_conversation_tail(), _make_chapter(), turn_number=2
        )
        assert decision.edge_case_type == "nonsense_injection"
        assert decision.action in DIRECT_INJECTION_NONSENSE


# -- Repeat injection path -------------------------------------------------


class TestRepeatInjection:
    @pytest.mark.asyncio
    async def test_repeat_injection_triggered(self, monkeypatch):
        """Repeat injection: skip direct & nonsense, trigger repeat."""
        agent = _make_agent(
            direct_edge_case_frequency=0.0,
            nonsense_frequency=0.0,
            repeat_frequency=1.0,
        )
        agent._last_action = "I searched the cave."

        # All random.random() calls return 0.5 (skip direct/nonsense at freq 0.0, trigger repeat at freq 1.0)
        monkeypatch.setattr("theact.playtest.player_agent.random.random", lambda: 0.5)

        decision = await agent.decide_with_metadata(
            _make_conversation_tail(), _make_chapter(), turn_number=3
        )
        assert decision.edge_case_type == "repeat_injection"
        assert decision.action == "I searched the cave."

    @pytest.mark.asyncio
    async def test_repeat_injection_skipped_when_no_last_action(self, monkeypatch):
        """Cannot repeat if _last_action is None — falls through to LLM."""
        agent = _make_agent(
            direct_edge_case_frequency=0.0,
            nonsense_frequency=0.0,
            repeat_frequency=1.0,
        )
        assert agent._last_action is None

        # All random.random returns 0
        monkeypatch.setattr("theact.playtest.player_agent.random.random", lambda: 0.5)

        @dataclass
        class FakeLLMResult:
            content: str = "I explore the wreckage."
            thinking: str = ""
            finish_reason: str = "stop"

        with patch(
            "theact.playtest.player_agent.complete",
            new_callable=AsyncMock,
            return_value=FakeLLMResult(),
        ):
            decision = await agent.decide_with_metadata(
                _make_conversation_tail(), _make_chapter(), turn_number=2
            )
        # Should have fallen through to normal LLM
        assert (
            decision.edge_case_type == "normal"
            or decision.edge_case_type == "llm_edge_case"
        )
        assert decision.action == "I explore the wreckage."


# -- Normal LLM generation path -------------------------------------------


class TestNormalLLMGeneration:
    @pytest.mark.asyncio
    async def test_normal_llm_call(self, monkeypatch):
        """When no injection fires, calls LLM and returns the result."""
        agent = _make_agent(
            direct_edge_case_frequency=0.0,
            nonsense_frequency=0.0,
            repeat_frequency=0.0,
            edge_case_frequency=0.0,  # no edge case prompt
        )

        # All random calls skip injections
        monkeypatch.setattr("theact.playtest.player_agent.random.random", lambda: 0.5)

        @dataclass
        class FakeLLMResult:
            content: str = "I walk toward the jungle."
            thinking: str = ""
            finish_reason: str = "stop"

        with patch(
            "theact.playtest.player_agent.complete",
            new_callable=AsyncMock,
            return_value=FakeLLMResult(),
        ) as mock_complete:
            decision = await agent.decide_with_metadata(
                _make_conversation_tail(), _make_chapter(), turn_number=2
            )

        assert decision.edge_case_type == "normal"
        assert decision.action == "I walk toward the jungle."
        assert agent._last_action == "I walk toward the jungle."

        # Verify LLM was called with correct structure
        call_args = mock_complete.call_args
        messages = call_args.kwargs.get("messages") or call_args.args[0]
        # System message, chapter context, conversation entries, action prompt
        assert messages[0]["role"] == "system"
        assert PLAYER_SYSTEM_PROMPT in messages[0]["content"]
        assert messages[-1]["content"] == "What do you do? (1-2 sentences)"

    @pytest.mark.asyncio
    async def test_edge_case_llm_call(self, monkeypatch):
        """When edge_case fires, adds an edge case prompt to system."""
        agent = _make_agent(
            direct_edge_case_frequency=0.0,
            nonsense_frequency=0.0,
            repeat_frequency=0.0,
            edge_case_frequency=1.0,  # always edge case
        )

        # First 3 calls skip injections; 4th triggers edge case
        random_values = iter([0.5, 0.5, 0.5, 0.0])
        monkeypatch.setattr(
            "theact.playtest.player_agent.random.random",
            lambda: next(random_values),
        )
        monkeypatch.setattr(
            "theact.playtest.player_agent.random.choice",
            lambda x: x[0],
        )

        @dataclass
        class FakeLLMResult:
            content: str = "I try something unexpected."
            thinking: str = ""
            finish_reason: str = "stop"

        with patch(
            "theact.playtest.player_agent.complete",
            new_callable=AsyncMock,
            return_value=FakeLLMResult(),
        ) as mock_complete:
            decision = await agent.decide_with_metadata(
                _make_conversation_tail(), _make_chapter(), turn_number=2
            )

        assert decision.edge_case_type == "llm_edge_case"
        # System prompt should include the edge case addition
        call_args = mock_complete.call_args
        messages = call_args.kwargs.get("messages") or call_args.args[0]
        system_content = messages[0]["content"]
        assert EDGE_CASE_PROMPTS[0] in system_content

    @pytest.mark.asyncio
    async def test_empty_llm_response_fallback(self, monkeypatch):
        """If LLM returns empty string, a fallback action is chosen."""
        agent = _make_agent(
            direct_edge_case_frequency=0.0,
            nonsense_frequency=0.0,
            repeat_frequency=0.0,
            edge_case_frequency=0.0,
        )

        monkeypatch.setattr("theact.playtest.player_agent.random.random", lambda: 0.5)

        @dataclass
        class FakeLLMResult:
            content: str = ""  # empty response
            thinking: str = ""
            finish_reason: str = "length"

        fallback_action = "I look around for anything useful."
        monkeypatch.setattr(
            "theact.playtest.player_agent.random.choice",
            lambda x: fallback_action,
        )

        with patch(
            "theact.playtest.player_agent.complete",
            new_callable=AsyncMock,
            return_value=FakeLLMResult(),
        ):
            decision = await agent.decide_with_metadata(
                _make_conversation_tail(), _make_chapter(), turn_number=2
            )

        assert decision.action == fallback_action
        assert agent._last_action == fallback_action

    @pytest.mark.asyncio
    async def test_whitespace_only_response_triggers_fallback(self, monkeypatch):
        """Whitespace-only content also triggers fallback."""
        agent = _make_agent(
            direct_edge_case_frequency=0.0,
            nonsense_frequency=0.0,
            repeat_frequency=0.0,
            edge_case_frequency=0.0,
        )

        monkeypatch.setattr("theact.playtest.player_agent.random.random", lambda: 0.5)

        @dataclass
        class FakeLLMResult:
            content: str = "   \n\t  "
            thinking: str = ""
            finish_reason: str = "stop"

        fallback_action = "I search for supplies."
        monkeypatch.setattr(
            "theact.playtest.player_agent.random.choice",
            lambda x: fallback_action,
        )

        with patch(
            "theact.playtest.player_agent.complete",
            new_callable=AsyncMock,
            return_value=FakeLLMResult(),
        ):
            decision = await agent.decide_with_metadata(
                _make_conversation_tail(), _make_chapter(), turn_number=2
            )

        assert decision.action == fallback_action


# -- decide() wrapper -----------------------------------------------------


class TestDecideWrapper:
    @pytest.mark.asyncio
    async def test_decide_returns_action_string(self, monkeypatch):
        """decide() delegates to decide_with_metadata() and returns just the action."""
        agent = _make_agent(direct_edge_case_frequency=1.0)
        monkeypatch.setattr(
            "theact.playtest.player_agent.random.choice", lambda x: "ok"
        )
        monkeypatch.setattr("theact.playtest.player_agent.random.random", lambda: 0.0)

        result = await agent.decide(
            _make_conversation_tail(), _make_chapter(), turn_number=2
        )
        assert isinstance(result, str)
        assert result == "ok"


# -- Message construction --------------------------------------------------


class TestMessageConstruction:
    @pytest.mark.asyncio
    async def test_conversation_entries_mapped_correctly(self, monkeypatch):
        """Player entries become 'user' role, others become 'assistant'."""
        agent = _make_agent(
            direct_edge_case_frequency=0.0,
            nonsense_frequency=0.0,
            repeat_frequency=0.0,
            edge_case_frequency=0.0,
        )
        monkeypatch.setattr("theact.playtest.player_agent.random.random", lambda: 0.5)

        @dataclass
        class FakeLLMResult:
            content: str = "I proceed."
            thinking: str = ""
            finish_reason: str = "stop"

        with patch(
            "theact.playtest.player_agent.complete",
            new_callable=AsyncMock,
            return_value=FakeLLMResult(),
        ) as mock_complete:
            await agent.decide_with_metadata(
                _make_conversation_tail(), _make_chapter(), turn_number=2
            )

        call_args = mock_complete.call_args
        messages = call_args.kwargs.get("messages") or call_args.args[0]

        # messages[0] = system, messages[1] = chapter context, then conversation
        # Narrator entry -> assistant role
        assert messages[2]["role"] == "assistant"
        assert "[Narrator]" in messages[2]["content"]
        # Player entry -> user role
        assert messages[3]["role"] == "user"
        assert "[Player]" in messages[3]["content"]
        # Character entry -> assistant role
        assert messages[4]["role"] == "assistant"
        assert "[Maya Chen]" in messages[4]["content"]

    @pytest.mark.asyncio
    async def test_chapter_context_included(self, monkeypatch):
        """Chapter title and summary are included in messages."""
        agent = _make_agent(
            direct_edge_case_frequency=0.0,
            nonsense_frequency=0.0,
            repeat_frequency=0.0,
            edge_case_frequency=0.0,
        )
        monkeypatch.setattr("theact.playtest.player_agent.random.random", lambda: 0.5)

        @dataclass
        class FakeLLMResult:
            content: str = "I proceed."
            thinking: str = ""
            finish_reason: str = "stop"

        chapter = _make_chapter(
            title="The Discovery", summary="You find ancient ruins."
        )

        with patch(
            "theact.playtest.player_agent.complete",
            new_callable=AsyncMock,
            return_value=FakeLLMResult(),
        ) as mock_complete:
            await agent.decide_with_metadata(
                _make_conversation_tail(), chapter, turn_number=2
            )

        call_args = mock_complete.call_args
        messages = call_args.kwargs.get("messages") or call_args.args[0]
        chapter_msg = messages[1]
        assert "The Discovery" in chapter_msg["content"]
        assert "ancient ruins" in chapter_msg["content"]

    @pytest.mark.asyncio
    async def test_agent_config_passed_to_complete(self, monkeypatch):
        agent = _make_agent(
            direct_edge_case_frequency=0.0,
            nonsense_frequency=0.0,
            repeat_frequency=0.0,
            edge_case_frequency=0.0,
        )
        monkeypatch.setattr("theact.playtest.player_agent.random.random", lambda: 0.5)

        @dataclass
        class FakeLLMResult:
            content: str = "I proceed."
            thinking: str = ""
            finish_reason: str = "stop"

        with patch(
            "theact.playtest.player_agent.complete",
            new_callable=AsyncMock,
            return_value=FakeLLMResult(),
        ) as mock_complete:
            await agent.decide_with_metadata(
                _make_conversation_tail(), _make_chapter(), turn_number=2
            )

        call_args = mock_complete.call_args
        assert call_args.kwargs["agent_config"] is PLAYER_AGENT_CONFIG

"""Tests for agent modules: game_state, memory, summarizer, character, narrator.

Covers the actual async function bodies with mocked LLM calls,
plus lazy-import __getattr__ in agents/__init__ and engine/__init__.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from theact.engine.types import (
    GameStateResult,
    NarratorOutput,
)
from theact.llm.call_log import LLMCallLog
from theact.llm.config import (
    LLMConfig,
)
from theact.llm.errors import ParseFailureType
from theact.llm.parsing import YAMLParseError
from theact.llm.streaming import LLMResult, StreamChunk, StructuredResult


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _make_llm_config() -> LLMConfig:
    return LLMConfig(
        base_url="http://test:1234/v1",
        api_key="test-key",
        model="test-model",
        default_temperature=1.0,
        default_max_tokens=1500,
    )


MESSAGES_STUB = [{"role": "system", "content": "hello"}]


# ===================================================================
# 1. game_state.run_game_state
# ===================================================================


class TestRunGameState:
    """Tests for theact.agents.game_state.run_game_state."""

    @pytest.mark.asyncio
    async def test_early_return_when_no_messages(self):
        """If build_game_state_messages returns [], return empty result."""
        from theact.agents.game_state import run_game_state

        game = MagicMock()
        llm_config = _make_llm_config()

        with patch(
            "theact.agents.game_state.build_game_state_messages", return_value=[]
        ):
            result = await run_game_state(game, [], llm_config)

        assert result == GameStateResult(beats_hit=[], completed=False)

    @pytest.mark.asyncio
    async def test_successful_parse(self):
        """Successful YAML parse returns beats_hit and completed."""
        from theact.agents.game_state import run_game_state

        structured = StructuredResult(
            data={
                "chapter_complete": False,
                "reason": "still exploring",
                "new_beats": ["Found the cave"],
            },
            raw_content="raw yaml",
            thinking="thought about it",
            attempts=1,
            finish_reason="stop",
            prompt_tokens=100,
            completion_tokens=50,
        )

        game = MagicMock()
        llm_config = _make_llm_config()

        with (
            patch(
                "theact.agents.game_state.build_game_state_messages",
                return_value=MESSAGES_STUB,
            ),
            patch(
                "theact.agents.game_state.complete_structured",
                new_callable=AsyncMock,
                return_value=structured,
            ),
        ):
            result = await run_game_state(game, [], llm_config)

        assert result.beats_hit == ["Found the cave"]
        assert result.completed is False
        assert result.reasoning == "still exploring"

    @pytest.mark.asyncio
    async def test_chapter_complete_true(self):
        """chapter_complete: true (bool) yields completed=True."""
        from theact.agents.game_state import run_game_state

        structured = StructuredResult(
            data={"chapter_complete": True, "reason": "done", "new_beats": []},
            raw_content="raw",
            thinking="",
            attempts=1,
        )

        with (
            patch(
                "theact.agents.game_state.build_game_state_messages",
                return_value=MESSAGES_STUB,
            ),
            patch(
                "theact.agents.game_state.complete_structured",
                new_callable=AsyncMock,
                return_value=structured,
            ),
        ):
            result = await run_game_state(MagicMock(), [], _make_llm_config())

        assert result.completed is True

    @pytest.mark.asyncio
    async def test_string_false_stays_false(self):
        """String 'false' must NOT become True (Python bool('false') is True)."""
        from theact.agents.game_state import run_game_state

        structured = StructuredResult(
            data={"chapter_complete": "false", "new_beats": []},
            raw_content="raw",
            thinking="",
            attempts=1,
        )

        with (
            patch(
                "theact.agents.game_state.build_game_state_messages",
                return_value=MESSAGES_STUB,
            ),
            patch(
                "theact.agents.game_state.complete_structured",
                new_callable=AsyncMock,
                return_value=structured,
            ),
        ):
            result = await run_game_state(MagicMock(), [], _make_llm_config())

        assert result.completed is False

    @pytest.mark.asyncio
    async def test_string_true_becomes_true(self):
        """String 'true' is coerced to True."""
        from theact.agents.game_state import run_game_state

        structured = StructuredResult(
            data={"chapter_complete": "true", "new_beats": []},
            raw_content="raw",
            thinking="",
            attempts=1,
        )

        with (
            patch(
                "theact.agents.game_state.build_game_state_messages",
                return_value=MESSAGES_STUB,
            ),
            patch(
                "theact.agents.game_state.complete_structured",
                new_callable=AsyncMock,
                return_value=structured,
            ),
        ):
            result = await run_game_state(MagicMock(), [], _make_llm_config())

        assert result.completed is True

    @pytest.mark.asyncio
    async def test_string_yes_becomes_true(self):
        """String 'yes' is coerced to True."""
        from theact.agents.game_state import run_game_state

        structured = StructuredResult(
            data={"chapter_complete": "yes", "new_beats": []},
            raw_content="raw",
            thinking="",
            attempts=1,
        )

        with (
            patch(
                "theact.agents.game_state.build_game_state_messages",
                return_value=MESSAGES_STUB,
            ),
            patch(
                "theact.agents.game_state.complete_structured",
                new_callable=AsyncMock,
                return_value=structured,
            ),
        ):
            result = await run_game_state(MagicMock(), [], _make_llm_config())

        assert result.completed is True

    @pytest.mark.asyncio
    async def test_yaml_parse_error_fallback(self):
        """YAMLParseError returns empty result."""
        from theact.agents.game_state import run_game_state

        err = YAMLParseError("bad yaml", raw_content="garbage")

        with (
            patch(
                "theact.agents.game_state.build_game_state_messages",
                return_value=MESSAGES_STUB,
            ),
            patch(
                "theact.agents.game_state.complete_structured",
                new_callable=AsyncMock,
                side_effect=err,
            ),
        ):
            result = await run_game_state(MagicMock(), [], _make_llm_config())

        assert result == GameStateResult(beats_hit=[], completed=False)

    @pytest.mark.asyncio
    async def test_yaml_parse_error_logs_to_call_log(self):
        """On YAMLParseError, an error record is logged."""
        from theact.agents.game_state import run_game_state

        err = YAMLParseError(
            "bad yaml",
            raw_content="garbage",
            failure_type=ParseFailureType.invalid_yaml,
        )
        call_log = LLMCallLog()

        with (
            patch(
                "theact.agents.game_state.build_game_state_messages",
                return_value=MESSAGES_STUB,
            ),
            patch(
                "theact.agents.game_state.complete_structured",
                new_callable=AsyncMock,
                side_effect=err,
            ),
        ):
            await run_game_state(
                MagicMock(), [], _make_llm_config(), call_log=call_log, turn=3
            )

        assert len(call_log.records) == 1
        rec = call_log.records[0]
        assert rec.agent == "game_state"
        assert rec.turn == 3
        assert rec.finish_reason == "error"
        assert rec.parse_result == ParseFailureType.invalid_yaml.value

    @pytest.mark.asyncio
    async def test_successful_call_logging(self):
        """Successful parse logs a success record."""
        from theact.agents.game_state import run_game_state

        structured = StructuredResult(
            data={"chapter_complete": False, "new_beats": ["a beat"]},
            raw_content="raw",
            thinking="think",
            attempts=2,
            finish_reason="stop",
            prompt_tokens=120,
            completion_tokens=60,
        )
        call_log = LLMCallLog()

        with (
            patch(
                "theact.agents.game_state.build_game_state_messages",
                return_value=MESSAGES_STUB,
            ),
            patch(
                "theact.agents.game_state.complete_structured",
                new_callable=AsyncMock,
                return_value=structured,
            ),
        ):
            await run_game_state(
                MagicMock(), [], _make_llm_config(), call_log=call_log, turn=5
            )

        assert len(call_log.records) == 1
        rec = call_log.records[0]
        assert rec.agent == "game_state"
        assert rec.turn == 5
        assert rec.parse_result == ParseFailureType.success.value
        assert rec.prompt_tokens == 120
        assert rec.retry_count == 1  # attempts=2 -> max(0, 2-1)=1

    @pytest.mark.asyncio
    async def test_new_beats_none_coerced_to_empty(self):
        """new_beats: null in YAML should yield empty list."""
        from theact.agents.game_state import run_game_state

        structured = StructuredResult(
            data={"chapter_complete": False, "new_beats": None},
            raw_content="raw",
            thinking="",
            attempts=1,
        )

        with (
            patch(
                "theact.agents.game_state.build_game_state_messages",
                return_value=MESSAGES_STUB,
            ),
            patch(
                "theact.agents.game_state.complete_structured",
                new_callable=AsyncMock,
                return_value=structured,
            ),
        ):
            result = await run_game_state(MagicMock(), [], _make_llm_config())

        assert result.beats_hit == []


# ===================================================================
# 2. memory.run_memory_update
# ===================================================================


class TestRunMemoryUpdate:
    """Tests for theact.agents.memory.run_memory_update."""

    def _make_character(self):
        from theact.models.character import Character

        return Character(
            name="Maya Chen",
            role="Scientist",
            personality="Curious and brave.",
            secret="Knows the truth.",
            relationships={"player": "ally"},
        )

    def _make_memory(self):
        from theact.models.memory import CharacterMemory

        return CharacterMemory(
            character="Maya Chen",
            summary="Maya has been exploring.",
            key_facts=["Found a map", "Trusts the player"],
        )

    @pytest.mark.asyncio
    async def test_successful_parse(self):
        """Successful parse returns a MemoryDiff with updated summary and facts."""
        from theact.agents.memory import run_memory_update

        structured = StructuredResult(
            data={
                "summary": "Maya discovered a hidden passage.",
                "key_facts": ["Found a map", "Trusts the player", "Discovered passage"],
            },
            raw_content="raw",
            thinking="thought",
            attempts=1,
            finish_reason="stop",
            prompt_tokens=200,
            completion_tokens=80,
        )

        with (
            patch(
                "theact.agents.memory.build_memory_messages",
                return_value=MESSAGES_STUB,
            ),
            patch(
                "theact.agents.memory.complete_structured",
                new_callable=AsyncMock,
                return_value=structured,
            ),
        ):
            result = await run_memory_update(
                self._make_character(),
                self._make_memory(),
                [],
                _make_llm_config(),
            )

        assert result.character == "Maya Chen"
        assert result.new_summary == "Maya discovered a hidden passage."
        assert result.new_facts == [
            "Found a map",
            "Trusts the player",
            "Discovered passage",
        ]
        assert result.old_summary == "Maya has been exploring."
        assert result.old_facts == ["Found a map", "Trusts the player"]

    @pytest.mark.asyncio
    async def test_no_existing_memory(self):
        """When memory is None, old values are empty."""
        from theact.agents.memory import run_memory_update

        structured = StructuredResult(
            data={"summary": "First memory.", "key_facts": ["fact1"]},
            raw_content="raw",
            thinking="",
            attempts=1,
        )

        with (
            patch(
                "theact.agents.memory.build_memory_messages",
                return_value=MESSAGES_STUB,
            ),
            patch(
                "theact.agents.memory.complete_structured",
                new_callable=AsyncMock,
                return_value=structured,
            ),
        ):
            result = await run_memory_update(
                self._make_character(), None, [], _make_llm_config()
            )

        assert result.old_summary == ""
        assert result.old_facts == []
        assert result.new_summary == "First memory."

    @pytest.mark.asyncio
    async def test_yaml_parse_error_returns_old_data(self):
        """YAMLParseError falls back to old summary/facts."""
        from theact.agents.memory import run_memory_update

        err = YAMLParseError("bad", raw_content="garbage")

        with (
            patch(
                "theact.agents.memory.build_memory_messages",
                return_value=MESSAGES_STUB,
            ),
            patch(
                "theact.agents.memory.complete_structured",
                new_callable=AsyncMock,
                side_effect=err,
            ),
        ):
            result = await run_memory_update(
                self._make_character(),
                self._make_memory(),
                [],
                _make_llm_config(),
            )

        assert result.new_summary == "Maya has been exploring."
        assert result.new_facts == ["Found a map", "Trusts the player"]

    @pytest.mark.asyncio
    async def test_yaml_parse_error_logs(self):
        """Error logging on YAMLParseError."""
        from theact.agents.memory import run_memory_update

        err = YAMLParseError(
            "bad",
            raw_content="garbage",
            failure_type=ParseFailureType.no_yaml_block,
        )
        call_log = LLMCallLog()

        with (
            patch(
                "theact.agents.memory.build_memory_messages",
                return_value=MESSAGES_STUB,
            ),
            patch(
                "theact.agents.memory.complete_structured",
                new_callable=AsyncMock,
                side_effect=err,
            ),
        ):
            await run_memory_update(
                self._make_character(),
                self._make_memory(),
                [],
                _make_llm_config(),
                call_log=call_log,
                turn=7,
            )

        assert len(call_log.records) == 1
        rec = call_log.records[0]
        assert rec.agent == "memory:maya_chen"
        assert rec.turn == 7
        assert rec.finish_reason == "error"
        assert rec.parse_result == ParseFailureType.no_yaml_block.value

    @pytest.mark.asyncio
    async def test_successful_call_logging(self):
        """Successful parse logs a success record."""
        from theact.agents.memory import run_memory_update

        structured = StructuredResult(
            data={"summary": "Updated.", "key_facts": ["f1"]},
            raw_content="raw",
            thinking="think",
            attempts=1,
            finish_reason="stop",
            prompt_tokens=150,
            completion_tokens=40,
        )
        call_log = LLMCallLog()

        with (
            patch(
                "theact.agents.memory.build_memory_messages",
                return_value=MESSAGES_STUB,
            ),
            patch(
                "theact.agents.memory.complete_structured",
                new_callable=AsyncMock,
                return_value=structured,
            ),
        ):
            await run_memory_update(
                self._make_character(),
                self._make_memory(),
                [],
                _make_llm_config(),
                call_log=call_log,
                turn=2,
            )

        assert len(call_log.records) == 1
        rec = call_log.records[0]
        assert rec.agent == "memory:maya_chen"
        assert rec.parse_result == ParseFailureType.success.value
        assert rec.prompt_tokens == 150

    @pytest.mark.asyncio
    async def test_fact_truncation_to_max(self):
        """Facts beyond MAX_KEY_FACTS are truncated."""
        from theact.agents.memory import run_memory_update
        from theact.agents.prompts import MAX_KEY_FACTS

        many_facts = [f"fact {i}" for i in range(MAX_KEY_FACTS + 5)]
        structured = StructuredResult(
            data={"summary": "Big update.", "key_facts": many_facts},
            raw_content="raw",
            thinking="",
            attempts=1,
        )

        with (
            patch(
                "theact.agents.memory.build_memory_messages",
                return_value=MESSAGES_STUB,
            ),
            patch(
                "theact.agents.memory.complete_structured",
                new_callable=AsyncMock,
                return_value=structured,
            ),
        ):
            result = await run_memory_update(
                self._make_character(), None, [], _make_llm_config()
            )

        assert len(result.new_facts) == MAX_KEY_FACTS

    @pytest.mark.asyncio
    async def test_legacy_add_field(self):
        """Legacy 'add' field is used when 'key_facts' is absent."""
        from theact.agents.memory import run_memory_update

        structured = StructuredResult(
            data={"summary": "New.", "add": ["legacy fact 1", "legacy fact 2"]},
            raw_content="raw",
            thinking="",
            attempts=1,
        )

        with (
            patch(
                "theact.agents.memory.build_memory_messages",
                return_value=MESSAGES_STUB,
            ),
            patch(
                "theact.agents.memory.complete_structured",
                new_callable=AsyncMock,
                return_value=structured,
            ),
        ):
            result = await run_memory_update(
                self._make_character(), None, [], _make_llm_config()
            )

        assert result.new_facts == ["legacy fact 1", "legacy fact 2"]

    @pytest.mark.asyncio
    async def test_falsy_facts_filtered(self):
        """None/empty values in facts list are filtered out."""
        from theact.agents.memory import run_memory_update

        structured = StructuredResult(
            data={"summary": "S.", "key_facts": ["good", None, "", "also good"]},
            raw_content="raw",
            thinking="",
            attempts=1,
        )

        with (
            patch(
                "theact.agents.memory.build_memory_messages",
                return_value=MESSAGES_STUB,
            ),
            patch(
                "theact.agents.memory.complete_structured",
                new_callable=AsyncMock,
                return_value=structured,
            ),
        ):
            result = await run_memory_update(
                self._make_character(), None, [], _make_llm_config()
            )

        assert result.new_facts == ["good", "also good"]

    @pytest.mark.asyncio
    async def test_summary_defaults_to_old_when_missing(self):
        """If model omits summary, old summary is preserved."""
        from theact.agents.memory import run_memory_update

        structured = StructuredResult(
            data={"key_facts": ["f1"]},
            raw_content="raw",
            thinking="",
            attempts=1,
        )

        with (
            patch(
                "theact.agents.memory.build_memory_messages",
                return_value=MESSAGES_STUB,
            ),
            patch(
                "theact.agents.memory.complete_structured",
                new_callable=AsyncMock,
                return_value=structured,
            ),
        ):
            result = await run_memory_update(
                self._make_character(),
                self._make_memory(),
                [],
                _make_llm_config(),
            )

        assert result.new_summary == "Maya has been exploring."


# ===================================================================
# 3. summarizer.run_chapter_summary / run_rolling_summary
# ===================================================================


class TestRunChapterSummary:
    """Tests for theact.agents.summarizer.run_chapter_summary."""

    @pytest.mark.asyncio
    async def test_returns_stripped_content(self):
        from theact.agents.summarizer import run_chapter_summary

        llm_result = LLMResult(
            content="  The chapter was about survival.  ",
            thinking="reasoning here",
            finish_reason="stop",
            prompt_tokens=100,
            completion_tokens=30,
        )

        with (
            patch(
                "theact.agents.summarizer.build_summary_messages",
                return_value=MESSAGES_STUB,
            ),
            patch(
                "theact.agents.summarizer.complete",
                new_callable=AsyncMock,
                return_value=llm_result,
            ),
        ):
            result = await run_chapter_summary(
                MagicMock(), MagicMock(), _make_llm_config()
            )

        assert result == "The chapter was about survival."

    @pytest.mark.asyncio
    async def test_call_logging(self):
        from theact.agents.summarizer import run_chapter_summary

        llm_result = LLMResult(
            content="Summary text.",
            thinking="thought",
            finish_reason="stop",
            prompt_tokens=80,
            completion_tokens=20,
        )
        call_log = LLMCallLog()

        with (
            patch(
                "theact.agents.summarizer.build_summary_messages",
                return_value=MESSAGES_STUB,
            ),
            patch(
                "theact.agents.summarizer.complete",
                new_callable=AsyncMock,
                return_value=llm_result,
            ),
        ):
            await run_chapter_summary(
                MagicMock(),
                MagicMock(),
                _make_llm_config(),
                call_log=call_log,
                turn=4,
            )

        assert len(call_log.records) == 1
        rec = call_log.records[0]
        assert rec.agent == "summarizer"
        assert rec.turn == 4
        assert rec.parse_result == ParseFailureType.success.value
        assert rec.prompt_tokens == 80
        assert rec.finish_reason == "stop"

    @pytest.mark.asyncio
    async def test_thinking_tokens_captured(self):
        """Thinking tokens from the model are recorded in call log."""
        from theact.agents.summarizer import run_chapter_summary

        llm_result = LLMResult(
            content="Summary.",
            thinking="A long chain of thought about the chapter.",
            finish_reason="stop",
            prompt_tokens=50,
            completion_tokens=10,
        )
        call_log = LLMCallLog()

        with (
            patch(
                "theact.agents.summarizer.build_summary_messages",
                return_value=MESSAGES_STUB,
            ),
            patch(
                "theact.agents.summarizer.complete",
                new_callable=AsyncMock,
                return_value=llm_result,
            ),
        ):
            await run_chapter_summary(
                MagicMock(),
                MagicMock(),
                _make_llm_config(),
                call_log=call_log,
                turn=1,
            )

        rec = call_log.records[0]
        assert rec.thinking_tokens > 0


class TestRunRollingSummary:
    """Tests for theact.agents.summarizer.run_rolling_summary."""

    @pytest.mark.asyncio
    async def test_returns_stripped_content(self):
        from theact.agents.summarizer import run_rolling_summary

        llm_result = LLMResult(
            content="  Updated rolling summary.  ",
            thinking="",
            finish_reason="stop",
            prompt_tokens=90,
            completion_tokens=25,
        )

        with (
            patch(
                "theact.agents.summarizer.build_rolling_summary_messages",
                return_value=MESSAGES_STUB,
            ),
            patch(
                "theact.agents.summarizer.complete",
                new_callable=AsyncMock,
                return_value=llm_result,
            ),
        ):
            result = await run_rolling_summary("Old summary.", [], _make_llm_config())

        assert result == "Updated rolling summary."

    @pytest.mark.asyncio
    async def test_call_logging(self):
        from theact.agents.summarizer import run_rolling_summary

        llm_result = LLMResult(
            content="Rolling.",
            thinking="some thought",
            finish_reason="stop",
            prompt_tokens=110,
            completion_tokens=35,
        )
        call_log = LLMCallLog()

        with (
            patch(
                "theact.agents.summarizer.build_rolling_summary_messages",
                return_value=MESSAGES_STUB,
            ),
            patch(
                "theact.agents.summarizer.complete",
                new_callable=AsyncMock,
                return_value=llm_result,
            ),
        ):
            await run_rolling_summary(
                "Old.",
                [],
                _make_llm_config(),
                call_log=call_log,
                turn=10,
            )

        assert len(call_log.records) == 1
        rec = call_log.records[0]
        assert rec.agent == "summarizer"
        assert rec.turn == 10
        assert rec.parse_result == ParseFailureType.success.value
        assert rec.prompt_tokens == 110


# ===================================================================
# 4. character.run_character
# ===================================================================


async def _fake_stream_chunks(chunks: list[StreamChunk]):
    """Helper: create an async iterator of StreamChunk objects."""
    for chunk in chunks:
        yield chunk


class TestRunCharacter:
    """Tests for theact.agents.character.run_character."""

    def _make_character(self):
        from theact.models.character import Character

        return Character(
            name="Maya Chen",
            role="Scientist",
            personality="Curious.",
            secret="Knows the truth.",
            relationships={"player": "ally"},
        )

    @pytest.mark.asyncio
    async def test_successful_stream(self):
        """Normal stream with enough content returns the text."""
        from theact.agents.character import run_character

        chunks = [
            StreamChunk(thinking="let me think"),
            StreamChunk(content="Maya looks at you and says, "),
            StreamChunk(content='"Hello there, friend."'),
            StreamChunk(finish_reason="stop"),
        ]

        with (
            patch(
                "theact.agents.character.build_character_messages",
                return_value=MESSAGES_STUB,
            ),
            patch(
                "theact.agents.character.stream",
                new_callable=AsyncMock,
                return_value=_fake_stream_chunks(chunks),
            ),
        ):
            result = await run_character(
                game=MagicMock(),
                character=self._make_character(),
                memory=None,
                player_input="I greet Maya",
                narrator_output=NarratorOutput(
                    narration="You approach.",
                    responding_characters=["maya"],
                    mood="calm",
                ),
                prior_responses=[],
                llm_config=_make_llm_config(),
            )

        assert result.character == "Maya Chen"
        assert "Hello there" in result.response
        assert result.thinking == "let me think"

    @pytest.mark.asyncio
    async def test_on_token_callback(self):
        """on_token callback receives both thinking and content tokens."""
        from theact.agents.character import run_character

        chunks = [
            StreamChunk(thinking="think"),
            StreamChunk(content="A sufficiently long response from the character."),
            StreamChunk(finish_reason="stop"),
        ]
        received = []

        async def on_token(text: str, is_thinking: bool):
            received.append((text, is_thinking))

        with (
            patch(
                "theact.agents.character.build_character_messages",
                return_value=MESSAGES_STUB,
            ),
            patch(
                "theact.agents.character.stream",
                new_callable=AsyncMock,
                return_value=_fake_stream_chunks(chunks),
            ),
        ):
            await run_character(
                game=MagicMock(),
                character=self._make_character(),
                memory=None,
                player_input="test",
                narrator_output=NarratorOutput(
                    narration="N.", responding_characters=[], mood="calm"
                ),
                prior_responses=[],
                llm_config=_make_llm_config(),
                on_token=on_token,
            )

        assert ("think", True) in received
        assert any(not t[1] for t in received)  # at least one content token

    @pytest.mark.asyncio
    async def test_short_response_triggers_retry(self):
        """Response < 10 chars triggers one retry."""
        from theact.agents.character import run_character

        short_chunks = [
            StreamChunk(content="Hi"),
            StreamChunk(finish_reason="stop"),
        ]
        good_chunks = [
            StreamChunk(content="Maya nods thoughtfully and reaches for her notebook."),
            StreamChunk(finish_reason="stop"),
        ]

        call_count = 0

        async def fake_stream(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _fake_stream_chunks(short_chunks)
            return _fake_stream_chunks(good_chunks)

        with (
            patch(
                "theact.agents.character.build_character_messages",
                return_value=MESSAGES_STUB,
            ),
            patch(
                "theact.agents.character.stream",
                side_effect=fake_stream,
            ),
        ):
            result = await run_character(
                game=MagicMock(),
                character=self._make_character(),
                memory=None,
                player_input="test",
                narrator_output=NarratorOutput(
                    narration="N.", responding_characters=[], mood="calm"
                ),
                prior_responses=[],
                llm_config=_make_llm_config(),
            )

        assert call_count == 2
        assert "notebook" in result.response

    @pytest.mark.asyncio
    async def test_both_attempts_short_uses_fallback(self):
        """Both attempts returning short text yields '*name remains silent.*'."""
        from theact.agents.character import run_character

        short_chunks = [
            StreamChunk(content=""),
            StreamChunk(finish_reason="stop"),
        ]

        with (
            patch(
                "theact.agents.character.build_character_messages",
                return_value=MESSAGES_STUB,
            ),
            patch(
                "theact.agents.character.stream",
                new_callable=AsyncMock,
                return_value=_fake_stream_chunks(short_chunks),
            ),
        ):
            result = await run_character(
                game=MagicMock(),
                character=self._make_character(),
                memory=None,
                player_input="test",
                narrator_output=NarratorOutput(
                    narration="N.", responding_characters=[], mood="calm"
                ),
                prior_responses=[],
                llm_config=_make_llm_config(),
            )

        assert result.response == "*Maya Chen remains silent.*"

    @pytest.mark.asyncio
    async def test_call_logging_no_retry(self):
        """Call log records retry_count=0 on first-attempt success."""
        from theact.agents.character import run_character

        chunks = [
            StreamChunk(content="A perfectly fine response from Maya Chen."),
            StreamChunk(finish_reason="stop"),
        ]
        call_log = LLMCallLog()

        with (
            patch(
                "theact.agents.character.build_character_messages",
                return_value=MESSAGES_STUB,
            ),
            patch(
                "theact.agents.character.stream",
                new_callable=AsyncMock,
                return_value=_fake_stream_chunks(chunks),
            ),
        ):
            await run_character(
                game=MagicMock(),
                character=self._make_character(),
                memory=None,
                player_input="test",
                narrator_output=NarratorOutput(
                    narration="N.", responding_characters=[], mood="calm"
                ),
                prior_responses=[],
                llm_config=_make_llm_config(),
                call_log=call_log,
                turn=3,
            )

        assert len(call_log.records) == 1
        rec = call_log.records[0]
        assert rec.agent == "character:maya_chen"
        assert rec.retry_count == 0
        assert rec.parse_attempts == 1

    @pytest.mark.asyncio
    async def test_call_logging_with_retry(self):
        """Call log records retry_count=1 after a retry."""
        from theact.agents.character import run_character

        short_chunks = [StreamChunk(content=""), StreamChunk(finish_reason="stop")]
        good_chunks = [
            StreamChunk(
                content="Maya says something sufficiently long and interesting."
            ),
            StreamChunk(finish_reason="stop"),
        ]

        call_count = 0

        async def fake_stream(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _fake_stream_chunks(short_chunks)
            return _fake_stream_chunks(good_chunks)

        call_log = LLMCallLog()

        with (
            patch(
                "theact.agents.character.build_character_messages",
                return_value=MESSAGES_STUB,
            ),
            patch(
                "theact.agents.character.stream",
                side_effect=fake_stream,
            ),
        ):
            await run_character(
                game=MagicMock(),
                character=self._make_character(),
                memory=None,
                player_input="test",
                narrator_output=NarratorOutput(
                    narration="N.", responding_characters=[], mood="calm"
                ),
                prior_responses=[],
                llm_config=_make_llm_config(),
                call_log=call_log,
                turn=2,
            )

        assert len(call_log.records) == 1
        rec = call_log.records[0]
        assert rec.retry_count == 1
        assert rec.parse_attempts == 2


# ===================================================================
# 5. narrator.run_narrator
# ===================================================================


class TestRunNarrator:
    """Tests for theact.agents.narrator.run_narrator."""

    @pytest.mark.asyncio
    async def test_successful_streaming_parse(self):
        """Happy path: stream + parse succeeds."""
        from theact.agents.narrator import run_narrator

        chunks = [
            StreamChunk(thinking="narrator thinking"),
            StreamChunk(content="yaml content"),
            StreamChunk(finish_reason="stop"),
        ]

        structured = StructuredResult(
            data={
                "narration": "The jungle parts before you.",
                "responding_characters": ["maya"],
                "mood": "tense",
            },
            raw_content="yaml content",
            thinking="narrator thinking",
            attempts=1,
            finish_reason="stop",
            prompt_tokens=200,
            completion_tokens=100,
        )

        # Build a future that resolves to the structured result
        loop = asyncio.get_event_loop()
        fut = loop.create_future()
        fut.set_result(structured)

        with (
            patch(
                "theact.agents.narrator.build_narrator_messages",
                return_value=MESSAGES_STUB,
            ),
            patch(
                "theact.agents.narrator.stream_structured",
                new_callable=AsyncMock,
                return_value=(_fake_stream_chunks(chunks), fut),
            ),
        ):
            result = await run_narrator(
                MagicMock(), "I look around", _make_llm_config()
            )

        assert result.narration == "The jungle parts before you."
        assert result.responding_characters == ["maya"]
        assert result.mood == "tense"

    @pytest.mark.asyncio
    async def test_on_token_callback(self):
        """on_token receives thinking and content chunks."""
        from theact.agents.narrator import run_narrator

        chunks = [
            StreamChunk(thinking="think"),
            StreamChunk(content="content"),
            StreamChunk(finish_reason="stop"),
        ]

        structured = StructuredResult(
            data={
                "narration": "Text.",
                "responding_characters": [],
                "mood": "calm",
            },
            raw_content="content",
            thinking="think",
            attempts=1,
        )

        loop = asyncio.get_event_loop()
        fut = loop.create_future()
        fut.set_result(structured)

        received = []

        async def on_token(text, is_thinking):
            received.append((text, is_thinking))

        with (
            patch(
                "theact.agents.narrator.build_narrator_messages",
                return_value=MESSAGES_STUB,
            ),
            patch(
                "theact.agents.narrator.stream_structured",
                new_callable=AsyncMock,
                return_value=(_fake_stream_chunks(chunks), fut),
            ),
        ):
            await run_narrator(
                MagicMock(), "test", _make_llm_config(), on_token=on_token
            )

        assert ("think", True) in received
        assert ("content", False) in received

    @pytest.mark.asyncio
    async def test_streaming_parse_fail_retries_non_streaming(self):
        """YAMLParseError from stream triggers non-streaming retry."""
        from theact.agents.narrator import run_narrator

        # stream_structured raises YAMLParseError
        err = YAMLParseError("bad yaml", raw_content="bad content")

        # The non-streaming retry succeeds
        retry_result = StructuredResult(
            data={
                "narration": "Retry narration.",
                "responding_characters": ["maya"],
                "mood": "mysterious",
            },
            raw_content="retry raw",
            thinking="retry thought",
            attempts=1,
            finish_reason="stop",
            prompt_tokens=200,
            completion_tokens=80,
        )

        # We need stream_structured to actually raise after streaming.
        # The code does: stream_iter, result_future = await stream_structured(...)
        #   async for chunk in stream_iter: ...
        #   result = await result_future
        # Then catches YAMLParseError.
        # Simplest: make stream_structured raise directly.
        # But that's not how it works -- the error comes from result_future.
        # Actually, looking at the narrator code more carefully, the entire
        # try block wraps both the streaming and the future await.
        # A YAMLParseError from result_future will be caught.

        # Let's make result_future raise
        loop = asyncio.get_event_loop()
        fail_fut = loop.create_future()
        fail_fut.set_exception(err)

        async def empty_stream():
            yield StreamChunk(content="streamed stuff")
            yield StreamChunk(finish_reason="stop")

        with (
            patch(
                "theact.agents.narrator.build_narrator_messages",
                return_value=MESSAGES_STUB,
            ),
            patch(
                "theact.agents.narrator.stream_structured",
                new_callable=AsyncMock,
                return_value=(empty_stream(), fail_fut),
            ),
            patch(
                "theact.agents.narrator.complete_structured",
                new_callable=AsyncMock,
                return_value=retry_result,
            ) as mock_cs,
        ):
            result = await run_narrator(MagicMock(), "test", _make_llm_config())

        mock_cs.assert_awaited_once()
        assert result.narration == "Retry narration."
        assert result.mood == "mysterious"

    @pytest.mark.asyncio
    async def test_both_fail_returns_fallback(self):
        """Both streaming and non-streaming fail -> fallback narration."""
        from theact.agents.narrator import run_narrator

        err1 = YAMLParseError("first fail", raw_content="bad1")
        err2 = YAMLParseError("second fail", raw_content="bad2")

        loop = asyncio.get_event_loop()
        fail_fut = loop.create_future()
        fail_fut.set_exception(err1)

        async def empty_stream():
            yield StreamChunk(finish_reason="stop")

        with (
            patch(
                "theact.agents.narrator.build_narrator_messages",
                return_value=MESSAGES_STUB,
            ),
            patch(
                "theact.agents.narrator.stream_structured",
                new_callable=AsyncMock,
                return_value=(empty_stream(), fail_fut),
            ),
            patch(
                "theact.agents.narrator.complete_structured",
                new_callable=AsyncMock,
                side_effect=err2,
            ),
        ):
            result = await run_narrator(MagicMock(), "test", _make_llm_config())

        assert result.narration == "bad2"  # raw_content from second error
        assert result.mood == "calm"
        assert result.responding_characters == []

    @pytest.mark.asyncio
    async def test_both_fail_empty_raw_uses_silent_fallback(self):
        """Both fail with empty raw_content -> '(The narrator is silent.)'."""
        from theact.agents.narrator import run_narrator

        err1 = YAMLParseError("first", raw_content="")
        err2 = YAMLParseError("second", raw_content="")

        loop = asyncio.get_event_loop()
        fail_fut = loop.create_future()
        fail_fut.set_exception(err1)

        async def empty_stream():
            yield StreamChunk(finish_reason="stop")

        with (
            patch(
                "theact.agents.narrator.build_narrator_messages",
                return_value=MESSAGES_STUB,
            ),
            patch(
                "theact.agents.narrator.stream_structured",
                new_callable=AsyncMock,
                return_value=(empty_stream(), fail_fut),
            ),
            patch(
                "theact.agents.narrator.complete_structured",
                new_callable=AsyncMock,
                side_effect=err2,
            ),
        ):
            result = await run_narrator(MagicMock(), "test", _make_llm_config())

        assert result.narration == "(The narrator is silent.)"

    @pytest.mark.asyncio
    async def test_both_fail_logs_error(self):
        """Double failure logs an error record to call_log."""
        from theact.agents.narrator import run_narrator

        err1 = YAMLParseError("first", raw_content="raw1")
        err2 = YAMLParseError(
            "second",
            raw_content="raw2",
            failure_type=ParseFailureType.invalid_yaml,
        )

        loop = asyncio.get_event_loop()
        fail_fut = loop.create_future()
        fail_fut.set_exception(err1)
        call_log = LLMCallLog()

        async def empty_stream():
            yield StreamChunk(finish_reason="stop")

        with (
            patch(
                "theact.agents.narrator.build_narrator_messages",
                return_value=MESSAGES_STUB,
            ),
            patch(
                "theact.agents.narrator.stream_structured",
                new_callable=AsyncMock,
                return_value=(empty_stream(), fail_fut),
            ),
            patch(
                "theact.agents.narrator.complete_structured",
                new_callable=AsyncMock,
                side_effect=err2,
            ),
        ):
            await run_narrator(
                MagicMock(), "test", _make_llm_config(), call_log=call_log, turn=5
            )

        assert len(call_log.records) == 1
        rec = call_log.records[0]
        assert rec.agent == "narrator"
        assert rec.finish_reason == "error"
        assert rec.parse_attempts == 2
        assert rec.retry_count == 1
        assert rec.parse_result == ParseFailureType.invalid_yaml.value

    @pytest.mark.asyncio
    async def test_successful_call_logging(self):
        """Successful parse logs a success record."""
        from theact.agents.narrator import run_narrator

        structured = StructuredResult(
            data={
                "narration": "You see the cave.",
                "responding_characters": [],
                "mood": "calm",
            },
            raw_content="raw yaml",
            thinking="thought",
            attempts=1,
            finish_reason="stop",
            prompt_tokens=250,
            completion_tokens=120,
        )

        loop = asyncio.get_event_loop()
        fut = loop.create_future()
        fut.set_result(structured)

        call_log = LLMCallLog()

        with (
            patch(
                "theact.agents.narrator.build_narrator_messages",
                return_value=MESSAGES_STUB,
            ),
            patch(
                "theact.agents.narrator.stream_structured",
                new_callable=AsyncMock,
                return_value=(
                    _fake_stream_chunks([StreamChunk(finish_reason="stop")]),
                    fut,
                ),
            ),
        ):
            await run_narrator(
                MagicMock(),
                "test",
                _make_llm_config(),
                call_log=call_log,
                turn=8,
            )

        assert len(call_log.records) == 1
        rec = call_log.records[0]
        assert rec.agent == "narrator"
        assert rec.turn == 8
        assert rec.parse_result == ParseFailureType.success.value
        assert rec.prompt_tokens == 250
        assert rec.retry_count == 0

    @pytest.mark.asyncio
    async def test_successful_call_logging_after_retry(self):
        """When streaming fails but non-streaming succeeds, retry_count reflects both."""
        from theact.agents.narrator import run_narrator

        err = YAMLParseError("stream fail", raw_content="bad")

        loop = asyncio.get_event_loop()
        fail_fut = loop.create_future()
        fail_fut.set_exception(err)

        retry_result = StructuredResult(
            data={
                "narration": "Retry success.",
                "responding_characters": [],
                "mood": "calm",
            },
            raw_content="raw",
            thinking="",
            attempts=2,  # complete_structured needed 2 attempts
            finish_reason="stop",
            prompt_tokens=200,
            completion_tokens=80,
        )
        call_log = LLMCallLog()

        async def empty_stream():
            yield StreamChunk(finish_reason="stop")

        with (
            patch(
                "theact.agents.narrator.build_narrator_messages",
                return_value=MESSAGES_STUB,
            ),
            patch(
                "theact.agents.narrator.stream_structured",
                new_callable=AsyncMock,
                return_value=(empty_stream(), fail_fut),
            ),
            patch(
                "theact.agents.narrator.complete_structured",
                new_callable=AsyncMock,
                return_value=retry_result,
            ),
        ):
            await run_narrator(
                MagicMock(),
                "test",
                _make_llm_config(),
                call_log=call_log,
                turn=6,
            )

        rec = call_log.records[0]
        # retried=True: retry_count = max(0, 2-1) + 1 = 2
        assert rec.retry_count == 2
        # parse_attempts = 2 + 1 (retried) = 3
        assert rec.parse_attempts == 3

    @pytest.mark.asyncio
    async def test_mood_normalization(self):
        """Mood synonyms are normalized to canonical values."""
        from theact.agents.narrator import run_narrator

        structured = StructuredResult(
            data={
                "narration": "Story text.",
                "responding_characters": [],
                "mood": "scary",  # synonym -> "tense"
            },
            raw_content="raw",
            thinking="",
            attempts=1,
        )

        loop = asyncio.get_event_loop()
        fut = loop.create_future()
        fut.set_result(structured)

        with (
            patch(
                "theact.agents.narrator.build_narrator_messages",
                return_value=MESSAGES_STUB,
            ),
            patch(
                "theact.agents.narrator.stream_structured",
                new_callable=AsyncMock,
                return_value=(
                    _fake_stream_chunks([StreamChunk(finish_reason="stop")]),
                    fut,
                ),
            ),
        ):
            result = await run_narrator(MagicMock(), "test", _make_llm_config())

        assert result.mood == "tense"

    @pytest.mark.asyncio
    async def test_missing_mood_defaults_to_calm(self):
        """Missing mood field defaults to 'calm'."""
        from theact.agents.narrator import run_narrator

        structured = StructuredResult(
            data={
                "narration": "Text.",
                "responding_characters": [],
                # mood is missing
            },
            raw_content="raw",
            thinking="",
            attempts=1,
        )

        loop = asyncio.get_event_loop()
        fut = loop.create_future()
        fut.set_result(structured)

        with (
            patch(
                "theact.agents.narrator.build_narrator_messages",
                return_value=MESSAGES_STUB,
            ),
            patch(
                "theact.agents.narrator.stream_structured",
                new_callable=AsyncMock,
                return_value=(
                    _fake_stream_chunks([StreamChunk(finish_reason="stop")]),
                    fut,
                ),
            ),
        ):
            result = await run_narrator(MagicMock(), "test", _make_llm_config())

        assert result.mood == "calm"


# ===================================================================
# 6. agents/__init__.py lazy imports
# ===================================================================


class TestAgentsLazyImport:
    """Tests for theact.agents.__getattr__ lazy import."""

    def test_import_run_narrator(self):
        """run_narrator is importable via agents.__getattr__."""
        from theact.agents import run_narrator

        assert callable(run_narrator)

    def test_import_run_character(self):
        from theact.agents import run_character

        assert callable(run_character)

    def test_import_run_memory_update(self):
        from theact.agents import run_memory_update

        assert callable(run_memory_update)

    def test_import_run_game_state(self):
        from theact.agents import run_game_state

        assert callable(run_game_state)

    def test_import_run_chapter_summary(self):
        from theact.agents import run_chapter_summary

        assert callable(run_chapter_summary)

    def test_import_run_rolling_summary(self):
        from theact.agents import run_rolling_summary

        assert callable(run_rolling_summary)

    def test_unknown_attribute_raises(self):
        """Accessing an unknown name raises AttributeError."""
        import theact.agents

        with pytest.raises(AttributeError, match="no attribute"):
            _ = theact.agents.nonexistent_function


# ===================================================================
# 7. engine/__init__.py lazy imports
# ===================================================================


class TestEngineLazyImport:
    """Tests for theact.engine.__getattr__ lazy import."""

    def test_import_build_narrator_messages(self):
        from theact.engine import build_narrator_messages

        assert callable(build_narrator_messages)

    def test_import_build_character_messages(self):
        from theact.engine import build_character_messages

        assert callable(build_character_messages)

    def test_import_build_memory_messages(self):
        from theact.engine import build_memory_messages

        assert callable(build_memory_messages)

    def test_import_build_game_state_messages(self):
        from theact.engine import build_game_state_messages

        assert callable(build_game_state_messages)

    def test_import_build_summary_messages(self):
        from theact.engine import build_summary_messages

        assert callable(build_summary_messages)

    def test_import_build_rolling_summary_messages(self):
        from theact.engine import build_rolling_summary_messages

        assert callable(build_rolling_summary_messages)

    def test_import_format_chapter_context(self):
        from theact.engine import format_chapter_context

        assert callable(format_chapter_context)

    def test_import_format_conversation(self):
        from theact.engine import format_conversation

        assert callable(format_conversation)

    def test_import_get_recent_conversation(self):
        from theact.engine import get_recent_conversation

        assert callable(get_recent_conversation)

    def test_import_run_turn(self):
        from theact.engine import run_turn

        assert callable(run_turn)

    def test_unknown_attribute_raises(self):
        """Accessing an unknown name raises AttributeError."""
        import theact.engine

        with pytest.raises(AttributeError, match="no attribute"):
            _ = theact.engine.nonexistent_thing

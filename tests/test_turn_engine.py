"""Tests for the turn engine orchestrator (src/theact/engine/turn.py).

Covers:
- resolve_beat() edge cases (empty canonical beats, no word overlap)
- _apply_memory_diff() (new memory creation, existing memory update)
- _advance_chapter() (final chapter, mid-chapter, summarizer integration)
- _maybe_update_rolling_summary() (below threshold, above threshold, edge cases)
- run_turn() (full orchestration with mocked agents: basic flow, duplicate
  character IDs, memory exception handling, game state exception handling,
  chapter advancement, rolling summary trigger, diagnostics path)
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from theact.engine.turn import (
    _advance_chapter,
    _apply_memory_diff,
    _maybe_update_rolling_summary,
    resolve_beat,
    resolve_character_id,
    run_turn,
)
from theact.engine.types import (
    CharacterResponse,
    GameStateResult,
    MemoryDiff,
    NarratorOutput,
    TurnResult,
)
from theact.llm.call_log import LLMCallLog, LLMCallRecord
from theact.llm.config import LLMConfig
from theact.models.chapter import Chapter
from theact.models.character import Character
from theact.models.conversation import ConversationEntry
from theact.models.game import GameMeta, LoadedGame
from theact.models.memory import CharacterMemory
from theact.models.state import GameState
from theact.models.world import World


# ---------------------------------------------------------------------------
# Fixtures: minimal but realistic game data
# ---------------------------------------------------------------------------


def _make_llm_config() -> LLMConfig:
    return LLMConfig(
        base_url="http://localhost:1234/v1",
        api_key="test-key",
        model="test-model",
    )


def _make_character(name: str = "Maya Chen", role: str = "engineer") -> Character:
    return Character(
        name=name,
        role=role,
        personality="Resourceful, direct.",
        secret="Knows more than she says.",
        relationships={"player": "wary ally"},
    )


def _make_chapter(
    chapter_id: str = "ch1",
    title: str = "The Crash",
    next_chapter: str | None = "ch2",
    beats: list[str] | None = None,
) -> Chapter:
    return Chapter(
        id=chapter_id,
        title=title,
        summary="Survivors wake on a beach.",
        beats=beats
        or [
            "Player wakes on the beach",
            "Explores wreckage finds supplies",
            "Discovers a body",
        ],
        completion="All survivors have met.",
        characters=["maya"],
        next=next_chapter,
    )


def _make_game(
    tmp_path: Path,
    characters: dict[str, Character] | None = None,
    chapters: dict[str, Chapter] | None = None,
    memories: dict[str, CharacterMemory] | None = None,
    turn: int = 0,
    conversation: list[ConversationEntry] | None = None,
    current_chapter: str = "ch1",
    rolling_summary: str = "",
    last_summarized_turn: int = 0,
    game_complete: bool = False,
) -> LoadedGame:
    maya = _make_character()
    ch1 = _make_chapter()
    ch2 = _make_chapter(chapter_id="ch2", title="The Jungle", next_chapter=None)

    return LoadedGame(
        meta=GameMeta(
            id="test-game",
            title="Test Game",
            description="A test game.",
            characters=["maya"],
            chapters=["ch1", "ch2"],
        ),
        world=World(
            setting="A tropical island.",
            tone="Tense survival.",
            rules="No magic.",
        ),
        characters=characters or {"maya": maya},
        chapters=chapters or {"ch1": ch1, "ch2": ch2},
        state=GameState(
            player_name="TestPlayer",
            current_chapter=current_chapter,
            turn=turn,
            beats_hit=[],
            flags={},
            chapter_history=[],
            rolling_summary=rolling_summary,
            last_summarized_turn=last_summarized_turn,
            game_complete=game_complete,
        ),
        conversation=conversation or [],
        memories=memories or {},
        chapter_summaries=[],
        save_path=tmp_path,
    )


# ---------------------------------------------------------------------------
# resolve_beat() edge cases
# ---------------------------------------------------------------------------


class TestResolveCharacterIdEdgeCases:
    """Cover line 119: resolve_character_id with empty/whitespace model_id."""

    def test_empty_string_returns_none(self):
        chars = {"maya": _make_character()}
        assert resolve_character_id("", chars) is None

    def test_whitespace_only_returns_none(self):
        chars = {"maya": _make_character()}
        assert resolve_character_id("   ", chars) is None


class TestResolveBeatEdgeCases:
    """Cover lines 100, 119: canonical beat with empty words, and no match."""

    def test_canonical_beat_with_only_short_words(self):
        """A canonical beat whose words are all <= 2 chars produces no words,
        so the fuzzy loop should skip it (line 100: continue).
        The model beat must NOT match any canonical exactly or case-insensitively
        to reach the fuzzy section."""
        beats = ["a b c", "Player wakes on the beach disoriented"]
        # Fuzzy match — not exact, not case-insensitive, reaches fuzzy loop
        assert resolve_beat("Player wakes on beach", beats) == (
            "Player wakes on the beach disoriented"
        )

    def test_model_beat_with_only_short_words(self):
        """Model beat with all short words yields empty word set -> None (line 93-94)."""
        beats = ["Player wakes on the beach"]
        assert resolve_beat("a b c", beats) is None

    def test_below_threshold_returns_none(self):
        """Overlap below 0.6 threshold returns None (line 109)."""
        beats = ["Player wakes on the beach disoriented"]
        # Only 1 meaningful word overlaps out of many
        assert resolve_beat("volcano erupts destroying beach", beats) is None

    def test_empty_canonical_beats(self):
        """Empty beats list returns None immediately."""
        assert resolve_beat("anything", []) is None


# ---------------------------------------------------------------------------
# _apply_memory_diff()
# ---------------------------------------------------------------------------


class TestApplyMemoryDiff:
    """Cover _apply_memory_diff: creates new memory or updates existing."""

    def test_creates_memory_when_missing(self, tmp_path: Path):
        """When char_id has no existing memory, creates a new CharacterMemory."""
        game = _make_game(tmp_path)
        assert "maya" not in game.memories

        diff = MemoryDiff(
            character="Maya Chen",
            old_summary="",
            new_summary="Met the player on the beach.",
            old_facts=[],
            new_facts=["Player seems disoriented"],
        )
        _apply_memory_diff(game, "maya", diff)

        assert "maya" in game.memories
        mem = game.memories["maya"]
        assert mem.character == "Maya Chen"
        assert mem.summary == "Met the player on the beach."
        assert mem.key_facts == ["Player seems disoriented"]

    def test_creates_memory_with_fallback_name(self, tmp_path: Path):
        """When char_id not in characters either, falls back to diff.character."""
        game = _make_game(tmp_path)
        diff = MemoryDiff(
            character="Unknown NPC",
            old_summary="",
            new_summary="Some memory.",
            new_facts=["fact1"],
        )
        _apply_memory_diff(game, "unknown_npc", diff)

        mem = game.memories["unknown_npc"]
        assert mem.character == "Unknown NPC"

    def test_updates_existing_memory(self, tmp_path: Path):
        """When memory already exists, updates summary and facts in place."""
        existing = CharacterMemory(
            character="Maya Chen",
            summary="Old summary.",
            key_facts=["old fact"],
        )
        game = _make_game(tmp_path, memories={"maya": existing})

        diff = MemoryDiff(
            character="Maya Chen",
            old_summary="Old summary.",
            new_summary="Updated summary.",
            old_facts=["old fact"],
            new_facts=["old fact", "new fact"],
        )
        _apply_memory_diff(game, "maya", diff)

        mem = game.memories["maya"]
        assert mem.summary == "Updated summary."
        assert mem.key_facts == ["old fact", "new fact"]


# ---------------------------------------------------------------------------
# _advance_chapter()
# ---------------------------------------------------------------------------


class TestAdvanceChapter:
    """Cover lines 406-413, 439: chapter advancement with summarizer."""

    @pytest.mark.asyncio
    async def test_final_chapter_marks_game_complete(self, tmp_path: Path):
        """When current chapter has no next, sets game_complete=True."""
        game = _make_game(tmp_path, current_chapter="ch2")
        # ch2 has next=None (final chapter)
        config = _make_llm_config()

        advanced, new_chapter = await _advance_chapter(game, config)

        assert advanced is False
        assert new_chapter is None
        assert game.state.game_complete is True

    @pytest.mark.asyncio
    async def test_missing_chapter_returns_false(self, tmp_path: Path):
        """When current_chapter is not in chapters dict."""
        game = _make_game(tmp_path, current_chapter="nonexistent")
        config = _make_llm_config()

        advanced, new_chapter = await _advance_chapter(game, config)

        assert advanced is False
        assert new_chapter is None
        assert game.state.game_complete is False

    @pytest.mark.asyncio
    @patch("theact.engine.turn.run_chapter_summary", new_callable=AsyncMock)
    @patch("theact.engine.turn.save_summaries")
    async def test_advances_to_next_chapter(
        self, mock_save_summaries, mock_chapter_summary, tmp_path: Path
    ):
        """When current chapter has a next, advances and generates summary."""
        mock_chapter_summary.return_value = "Chapter 1 summary text."

        game = _make_game(tmp_path, current_chapter="ch1")
        config = _make_llm_config()

        advanced, new_chapter = await _advance_chapter(game, config)

        assert advanced is True
        assert new_chapter == "ch2"
        assert game.state.current_chapter == "ch2"
        assert game.state.beats_hit == []
        assert "ch1" in game.state.chapter_history
        assert game.state.chapter_just_advanced is True
        assert len(game.chapter_summaries) == 1
        assert game.chapter_summaries[0].chapter_id == "ch1"
        mock_chapter_summary.assert_awaited_once()
        mock_save_summaries.assert_called_once()


# ---------------------------------------------------------------------------
# _maybe_update_rolling_summary()
# ---------------------------------------------------------------------------


class TestMaybeUpdateRollingSummary:
    """Cover lines 502-521: rolling summary logic."""

    @pytest.mark.asyncio
    async def test_below_threshold_returns_false(self, tmp_path: Path):
        """Short conversation does not trigger summarization."""
        game = _make_game(tmp_path)
        # Add only a few entries (well below 1500 token threshold)
        game.conversation = [
            ConversationEntry(turn=1, role="narrator", content="You wake up."),
            ConversationEntry(turn=1, role="player", content="I look around."),
        ]
        config = _make_llm_config()

        result = await _maybe_update_rolling_summary(game, config)
        assert result is False

    @pytest.mark.asyncio
    @patch("theact.engine.turn.run_rolling_summary", new_callable=AsyncMock)
    async def test_above_threshold_triggers_summary(
        self, mock_rolling_summary, tmp_path: Path
    ):
        """Long conversation triggers rolling summary."""
        mock_rolling_summary.return_value = "Updated rolling summary."

        game = _make_game(tmp_path)
        # Create enough entries to exceed 1500 tokens (est ~4 chars/token)
        # Need ~6000 chars minimum
        long_text = "This is a long narration text. " * 50  # ~1550 chars per entry
        entries = []
        for t in range(1, 12):
            entries.append(
                ConversationEntry(turn=t, role="narrator", content=long_text)
            )
            entries.append(
                ConversationEntry(turn=t, role="player", content="I do something.")
            )
        game.conversation = entries
        config = _make_llm_config()

        result = await _maybe_update_rolling_summary(game, config)

        assert result is True
        assert game.state.rolling_summary == "Updated rolling summary."
        assert game.state.last_summarized_turn > 0
        mock_rolling_summary.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_already_summarized_entries_not_recounted(self, tmp_path: Path):
        """Entries before last_summarized_turn are not counted toward threshold."""
        game = _make_game(tmp_path, last_summarized_turn=5)
        # Add entries for turns 1-5 (already summarized) and turn 6 (short)
        long_text = "x " * 3000
        for t in range(1, 6):
            game.conversation.append(
                ConversationEntry(turn=t, role="narrator", content=long_text)
            )
        game.conversation.append(
            ConversationEntry(turn=6, role="narrator", content="Short.")
        )
        config = _make_llm_config()

        result = await _maybe_update_rolling_summary(game, config)
        assert result is False

    @pytest.mark.asyncio
    @patch("theact.engine.turn.estimate_tokens", return_value=9999)
    async def test_cutoff_at_zero_returns_false(self, mock_estimate, tmp_path: Path):
        """When conversation is empty but estimate_tokens is mocked high,
        cutoff_idx stays at len(conversation)=0, triggering the <= 0 guard
        (line 560-561)."""
        game = _make_game(tmp_path)
        # Empty conversation but fake high token count
        game.conversation = []
        config = _make_llm_config()

        result = await _maybe_update_rolling_summary(game, config)
        assert result is False

    @pytest.mark.asyncio
    @patch("theact.engine.turn.run_rolling_summary", new_callable=AsyncMock)
    async def test_few_recent_turns_still_summarizes_all(
        self, mock_rolling_summary, tmp_path: Path
    ):
        """When KEEP_RECENT=4 and only 4 turns exist, cutoff_idx equals
        len(conversation) and old_entries contains everything.
        This exercises the path where the for-loop never breaks (line 551-558)."""
        mock_rolling_summary.return_value = "Summary of all turns."
        game = _make_game(tmp_path)
        long_text = "word " * 2000
        for t in range(1, 5):
            game.conversation.append(
                ConversationEntry(turn=t, role="narrator", content=long_text)
            )
        config = _make_llm_config()

        result = await _maybe_update_rolling_summary(game, config)
        # All entries become old_entries because loop never breaks
        assert result is True
        mock_rolling_summary.assert_awaited_once()
        # All 4 turns' entries were passed as old_entries
        old_entries_arg = mock_rolling_summary.call_args[0][1]
        assert len(old_entries_arg) == 4


# ---------------------------------------------------------------------------
# run_turn() — full orchestration tests
# ---------------------------------------------------------------------------

# Module paths for patching
_TURN = "theact.engine.turn"


def _narrator_output(
    chars: list[str] | None = None, narration: str = "The jungle stirs around you."
) -> NarratorOutput:
    return NarratorOutput(
        narration=narration,
        responding_characters=["maya"] if chars is None else chars,
        mood="tense",
    )


def _character_response(name: str = "Maya Chen") -> CharacterResponse:
    return CharacterResponse(
        character=name,
        response=f"{name} looks at you carefully.",
    )


def _memory_diff(name: str = "Maya Chen") -> MemoryDiff:
    return MemoryDiff(
        character=name,
        old_summary="",
        new_summary="Met the player.",
        new_facts=["Player arrived"],
    )


def _game_state_result(
    beats: list[str] | None = None, completed: bool = False
) -> GameStateResult:
    return GameStateResult(
        beats_hit=beats or [],
        completed=completed,
    )


def _patch_all_agents(
    narrator_output=None,
    character_response=None,
    memory_diff=None,
    game_state_result=None,
):
    """Return a dict of patches for all agents and persistence functions."""
    return {
        "run_narrator": AsyncMock(return_value=narrator_output or _narrator_output()),
        "run_character": AsyncMock(
            return_value=character_response or _character_response()
        ),
        "run_memory_update": AsyncMock(return_value=memory_diff or _memory_diff()),
        "run_game_state": AsyncMock(
            return_value=game_state_result or _game_state_result()
        ),
        "append_conversation": MagicMock(),
        "save_state": MagicMock(),
        "save_memory": MagicMock(),
        "commit_turn": MagicMock(return_value="abc123"),
    }


class TestRunTurnBasic:
    """Basic turn flow: narrator -> characters -> post-turn -> persist."""

    @pytest.mark.asyncio
    async def test_basic_turn_flow(self, tmp_path: Path):
        """A simple turn with one character produces expected TurnResult."""
        mocks = _patch_all_agents()
        game = _make_game(
            tmp_path,
            memories={
                "maya": CharacterMemory(
                    character="Maya Chen", summary="", key_facts=[]
                ),
            },
        )
        config = _make_llm_config()

        with (
            patch(f"{_TURN}.run_narrator", mocks["run_narrator"]),
            patch(f"{_TURN}.run_character", mocks["run_character"]),
            patch(f"{_TURN}.run_memory_update", mocks["run_memory_update"]),
            patch(f"{_TURN}.run_game_state", mocks["run_game_state"]),
            patch(f"{_TURN}.append_conversation", mocks["append_conversation"]),
            patch(f"{_TURN}.save_state", mocks["save_state"]),
            patch(f"{_TURN}.save_memory", mocks["save_memory"]),
            patch(f"{_TURN}.commit_turn", mocks["commit_turn"]),
        ):
            result = await run_turn(game, "I look around", config)

        assert isinstance(result, TurnResult)
        assert result.turn == 1
        assert result.narrator.narration == "The jungle stirs around you."
        assert len(result.characters) == 1
        assert result.characters[0].character == "Maya Chen"
        assert game.state.turn == 1

        # Persistence was called
        mocks["save_state"].assert_called_once()
        mocks["commit_turn"].assert_called_once()
        # Conversation was appended (narrator + player + character = 3 entries)
        assert mocks["append_conversation"].call_count == 3

    @pytest.mark.asyncio
    async def test_no_responding_characters(self, tmp_path: Path):
        """When narrator returns no characters, only narrator + player entries."""
        mocks = _patch_all_agents(
            narrator_output=_narrator_output(chars=[]),
        )
        game = _make_game(tmp_path)
        config = _make_llm_config()

        with (
            patch(f"{_TURN}.run_narrator", mocks["run_narrator"]),
            patch(f"{_TURN}.run_character", mocks["run_character"]),
            patch(f"{_TURN}.run_memory_update", mocks["run_memory_update"]),
            patch(f"{_TURN}.run_game_state", mocks["run_game_state"]),
            patch(f"{_TURN}.append_conversation", mocks["append_conversation"]),
            patch(f"{_TURN}.save_state", mocks["save_state"]),
            patch(f"{_TURN}.save_memory", mocks["save_memory"]),
            patch(f"{_TURN}.commit_turn", mocks["commit_turn"]),
        ):
            result = await run_turn(game, "I look around", config)

        assert len(result.characters) == 0
        # No character agent was called
        mocks["run_character"].assert_not_awaited()
        # 2 entries: narrator + player
        assert mocks["append_conversation"].call_count == 2


class TestRunTurnCharacterResolution:
    """Cover lines 241-244: character ID resolution and dedup."""

    @pytest.mark.asyncio
    async def test_resolved_character_id_logged(self, tmp_path: Path):
        """When narrator returns a non-canonical ID that resolves, it still works
        (line 241-242: logs the resolution)."""
        mocks = _patch_all_agents(
            narrator_output=_narrator_output(chars=["Maya"]),  # uppercase
        )
        game = _make_game(
            tmp_path,
            memories={
                "maya": CharacterMemory(
                    character="Maya Chen", summary="", key_facts=[]
                ),
            },
        )
        config = _make_llm_config()

        with (
            patch(f"{_TURN}.run_narrator", mocks["run_narrator"]),
            patch(f"{_TURN}.run_character", mocks["run_character"]),
            patch(f"{_TURN}.run_memory_update", mocks["run_memory_update"]),
            patch(f"{_TURN}.run_game_state", mocks["run_game_state"]),
            patch(f"{_TURN}.append_conversation", mocks["append_conversation"]),
            patch(f"{_TURN}.save_state", mocks["save_state"]),
            patch(f"{_TURN}.save_memory", mocks["save_memory"]),
            patch(f"{_TURN}.commit_turn", mocks["commit_turn"]),
        ):
            result = await run_turn(game, "hello", config)

        assert len(result.characters) == 1
        mocks["run_character"].assert_awaited_once()

    @pytest.mark.asyncio
    async def test_duplicate_character_ids_only_run_once(self, tmp_path: Path):
        """When narrator returns same character twice, it only runs once
        (line 243-244: duplicate skip)."""
        mocks = _patch_all_agents(
            narrator_output=_narrator_output(chars=["maya", "maya"]),
        )
        game = _make_game(
            tmp_path,
            memories={
                "maya": CharacterMemory(
                    character="Maya Chen", summary="", key_facts=[]
                ),
            },
        )
        config = _make_llm_config()

        with (
            patch(f"{_TURN}.run_narrator", mocks["run_narrator"]),
            patch(f"{_TURN}.run_character", mocks["run_character"]),
            patch(f"{_TURN}.run_memory_update", mocks["run_memory_update"]),
            patch(f"{_TURN}.run_game_state", mocks["run_game_state"]),
            patch(f"{_TURN}.append_conversation", mocks["append_conversation"]),
            patch(f"{_TURN}.save_state", mocks["save_state"]),
            patch(f"{_TURN}.save_memory", mocks["save_memory"]),
            patch(f"{_TURN}.commit_turn", mocks["commit_turn"]),
        ):
            result = await run_turn(game, "hello", config)

        # Character agent should only be called once despite duplicate
        assert mocks["run_character"].await_count == 1
        assert len(result.characters) == 1

    @pytest.mark.asyncio
    async def test_unknown_character_skipped(self, tmp_path: Path):
        """When narrator returns an unknown character ID, it is skipped
        (line 236-239: warning + skip)."""
        mocks = _patch_all_agents(
            narrator_output=_narrator_output(chars=["nonexistent_npc"]),
        )
        game = _make_game(tmp_path)
        config = _make_llm_config()

        with (
            patch(f"{_TURN}.run_narrator", mocks["run_narrator"]),
            patch(f"{_TURN}.run_character", mocks["run_character"]),
            patch(f"{_TURN}.run_memory_update", mocks["run_memory_update"]),
            patch(f"{_TURN}.run_game_state", mocks["run_game_state"]),
            patch(f"{_TURN}.append_conversation", mocks["append_conversation"]),
            patch(f"{_TURN}.save_state", mocks["save_state"]),
            patch(f"{_TURN}.save_memory", mocks["save_memory"]),
            patch(f"{_TURN}.commit_turn", mocks["commit_turn"]),
        ):
            result = await run_turn(game, "hello", config)

        assert len(result.characters) == 0
        mocks["run_character"].assert_not_awaited()


class TestRunTurnExceptionHandling:
    """Cover lines 314, 330, 347-352, 358-363: exception handling in post-turn."""

    @pytest.mark.asyncio
    async def test_memory_update_exception_continues(self, tmp_path: Path):
        """When memory update raises, it is logged and turn continues
        (lines 347-352)."""
        mocks = _patch_all_agents()
        mocks["run_memory_update"] = AsyncMock(
            side_effect=RuntimeError("Memory agent failed")
        )
        game = _make_game(
            tmp_path,
            memories={
                "maya": CharacterMemory(
                    character="Maya Chen", summary="", key_facts=[]
                ),
            },
        )
        config = _make_llm_config()

        with (
            patch(f"{_TURN}.run_narrator", mocks["run_narrator"]),
            patch(f"{_TURN}.run_character", mocks["run_character"]),
            patch(f"{_TURN}.run_memory_update", mocks["run_memory_update"]),
            patch(f"{_TURN}.run_game_state", mocks["run_game_state"]),
            patch(f"{_TURN}.append_conversation", mocks["append_conversation"]),
            patch(f"{_TURN}.save_state", mocks["save_state"]),
            patch(f"{_TURN}.save_memory", mocks["save_memory"]),
            patch(f"{_TURN}.commit_turn", mocks["commit_turn"]),
        ):
            # Should not raise despite memory failure
            result = await run_turn(game, "hello", config)

        assert isinstance(result, TurnResult)
        # Memory diffs should be empty due to exception
        assert len(result.memory_diffs) == 0

    @pytest.mark.asyncio
    async def test_game_state_exception_uses_fallback(self, tmp_path: Path):
        """When game state agent raises, falls back to default GameStateResult
        (lines 358-363)."""
        mocks = _patch_all_agents()
        mocks["run_game_state"] = AsyncMock(
            side_effect=RuntimeError("Game state agent failed")
        )
        game = _make_game(
            tmp_path,
            memories={
                "maya": CharacterMemory(
                    character="Maya Chen", summary="", key_facts=[]
                ),
            },
        )
        config = _make_llm_config()

        with (
            patch(f"{_TURN}.run_narrator", mocks["run_narrator"]),
            patch(f"{_TURN}.run_character", mocks["run_character"]),
            patch(f"{_TURN}.run_memory_update", mocks["run_memory_update"]),
            patch(f"{_TURN}.run_game_state", mocks["run_game_state"]),
            patch(f"{_TURN}.append_conversation", mocks["append_conversation"]),
            patch(f"{_TURN}.save_state", mocks["save_state"]),
            patch(f"{_TURN}.save_memory", mocks["save_memory"]),
            patch(f"{_TURN}.commit_turn", mocks["commit_turn"]),
        ):
            result = await run_turn(game, "hello", config)

        # Fallback: no beats, not completed
        assert result.game_state is not None
        assert result.game_state.beats_hit == []
        assert result.game_state.completed is False


class TestRunTurnBeatRecording:
    """Cover lines 405-413: beat recording with resolve_beat."""

    @pytest.mark.asyncio
    async def test_beats_resolved_and_recorded(self, tmp_path: Path):
        """Beats from game state are resolved against chapter beats."""
        mocks = _patch_all_agents(
            game_state_result=_game_state_result(beats=["Player wakes on the beach"]),
        )
        game = _make_game(tmp_path)
        config = _make_llm_config()

        with (
            patch(f"{_TURN}.run_narrator", mocks["run_narrator"]),
            patch(f"{_TURN}.run_character", mocks["run_character"]),
            patch(f"{_TURN}.run_memory_update", mocks["run_memory_update"]),
            patch(f"{_TURN}.run_game_state", mocks["run_game_state"]),
            patch(f"{_TURN}.append_conversation", mocks["append_conversation"]),
            patch(f"{_TURN}.save_state", mocks["save_state"]),
            patch(f"{_TURN}.save_memory", mocks["save_memory"]),
            patch(f"{_TURN}.commit_turn", mocks["commit_turn"]),
        ):
            await run_turn(game, "I look around", config)

        assert "Player wakes on the beach" in game.state.beats_hit

    @pytest.mark.asyncio
    async def test_unrecognized_beat_ignored(self, tmp_path: Path):
        """Beats that don't match any canonical beat are ignored (line 407-409)."""
        mocks = _patch_all_agents(
            game_state_result=_game_state_result(
                beats=["Something completely unrelated to any beat"]
            ),
        )
        game = _make_game(tmp_path)
        config = _make_llm_config()

        with (
            patch(f"{_TURN}.run_narrator", mocks["run_narrator"]),
            patch(f"{_TURN}.run_character", mocks["run_character"]),
            patch(f"{_TURN}.run_memory_update", mocks["run_memory_update"]),
            patch(f"{_TURN}.run_game_state", mocks["run_game_state"]),
            patch(f"{_TURN}.append_conversation", mocks["append_conversation"]),
            patch(f"{_TURN}.save_state", mocks["save_state"]),
            patch(f"{_TURN}.save_memory", mocks["save_memory"]),
            patch(f"{_TURN}.commit_turn", mocks["commit_turn"]),
        ):
            await run_turn(game, "I look around", config)

        assert game.state.beats_hit == []

    @pytest.mark.asyncio
    async def test_duplicate_beat_not_added_twice(self, tmp_path: Path):
        """A beat already in beats_hit is not added again (line 412-413)."""
        mocks = _patch_all_agents(
            game_state_result=_game_state_result(beats=["Player wakes on the beach"]),
        )
        game = _make_game(tmp_path)
        game.state.beats_hit = ["Player wakes on the beach"]
        config = _make_llm_config()

        with (
            patch(f"{_TURN}.run_narrator", mocks["run_narrator"]),
            patch(f"{_TURN}.run_character", mocks["run_character"]),
            patch(f"{_TURN}.run_memory_update", mocks["run_memory_update"]),
            patch(f"{_TURN}.run_game_state", mocks["run_game_state"]),
            patch(f"{_TURN}.append_conversation", mocks["append_conversation"]),
            patch(f"{_TURN}.save_state", mocks["save_state"]),
            patch(f"{_TURN}.save_memory", mocks["save_memory"]),
            patch(f"{_TURN}.commit_turn", mocks["commit_turn"]),
        ):
            await run_turn(game, "I look around", config)

        # Should still be only one entry
        assert game.state.beats_hit.count("Player wakes on the beach") == 1

    @pytest.mark.asyncio
    async def test_fuzzy_beat_resolved_logged(self, tmp_path: Path):
        """A beat that fuzzy-matches is resolved to canonical (line 410-411)."""
        mocks = _patch_all_agents(
            game_state_result=_game_state_result(
                beats=["player wakes beach"]  # fuzzy match
            ),
        )
        game = _make_game(tmp_path)
        config = _make_llm_config()

        with (
            patch(f"{_TURN}.run_narrator", mocks["run_narrator"]),
            patch(f"{_TURN}.run_character", mocks["run_character"]),
            patch(f"{_TURN}.run_memory_update", mocks["run_memory_update"]),
            patch(f"{_TURN}.run_game_state", mocks["run_game_state"]),
            patch(f"{_TURN}.append_conversation", mocks["append_conversation"]),
            patch(f"{_TURN}.save_state", mocks["save_state"]),
            patch(f"{_TURN}.save_memory", mocks["save_memory"]),
            patch(f"{_TURN}.commit_turn", mocks["commit_turn"]),
        ):
            await run_turn(game, "I look around", config)

        # The canonical beat should be recorded, not the fuzzy one
        assert "Player wakes on the beach" in game.state.beats_hit


class TestRunTurnChapterAdvancement:
    """Cover lines 406-413, 425-428: chapter advancement when completed."""

    @pytest.mark.asyncio
    async def test_chapter_advances_when_completed(self, tmp_path: Path):
        """When game_state says completed, chapter advances."""
        mocks = _patch_all_agents(
            game_state_result=_game_state_result(completed=True),
        )
        game = _make_game(tmp_path)
        config = _make_llm_config()

        with (
            patch(f"{_TURN}.run_narrator", mocks["run_narrator"]),
            patch(f"{_TURN}.run_character", mocks["run_character"]),
            patch(f"{_TURN}.run_memory_update", mocks["run_memory_update"]),
            patch(f"{_TURN}.run_game_state", mocks["run_game_state"]),
            patch(f"{_TURN}.append_conversation", mocks["append_conversation"]),
            patch(f"{_TURN}.save_state", mocks["save_state"]),
            patch(f"{_TURN}.save_memory", mocks["save_memory"]),
            patch(f"{_TURN}.commit_turn", mocks["commit_turn"]),
            patch(
                f"{_TURN}.run_chapter_summary",
                new_callable=AsyncMock,
                return_value="Chapter summary.",
            ),
            patch(f"{_TURN}.save_summaries"),
        ):
            result = await run_turn(game, "I do it", config)

        assert result.chapter_advanced is True
        assert result.new_chapter == "ch2"
        assert game.state.current_chapter == "ch2"

    @pytest.mark.asyncio
    async def test_no_advancement_when_not_completed(self, tmp_path: Path):
        """When game_state says not completed, no advancement."""
        mocks = _patch_all_agents(
            game_state_result=_game_state_result(completed=False),
        )
        game = _make_game(tmp_path)
        config = _make_llm_config()

        with (
            patch(f"{_TURN}.run_narrator", mocks["run_narrator"]),
            patch(f"{_TURN}.run_character", mocks["run_character"]),
            patch(f"{_TURN}.run_memory_update", mocks["run_memory_update"]),
            patch(f"{_TURN}.run_game_state", mocks["run_game_state"]),
            patch(f"{_TURN}.append_conversation", mocks["append_conversation"]),
            patch(f"{_TURN}.save_state", mocks["save_state"]),
            patch(f"{_TURN}.save_memory", mocks["save_memory"]),
            patch(f"{_TURN}.commit_turn", mocks["commit_turn"]),
        ):
            result = await run_turn(game, "I look around", config)

        assert result.chapter_advanced is False
        assert result.new_chapter is None

    @pytest.mark.asyncio
    async def test_no_advancement_when_game_already_complete(self, tmp_path: Path):
        """When game is already complete, no advancement despite completed=True."""
        mocks = _patch_all_agents(
            game_state_result=_game_state_result(completed=True),
        )
        game = _make_game(tmp_path, game_complete=True)
        config = _make_llm_config()

        with (
            patch(f"{_TURN}.run_narrator", mocks["run_narrator"]),
            patch(f"{_TURN}.run_character", mocks["run_character"]),
            patch(f"{_TURN}.run_memory_update", mocks["run_memory_update"]),
            patch(f"{_TURN}.run_game_state", mocks["run_game_state"]),
            patch(f"{_TURN}.append_conversation", mocks["append_conversation"]),
            patch(f"{_TURN}.save_state", mocks["save_state"]),
            patch(f"{_TURN}.save_memory", mocks["save_memory"]),
            patch(f"{_TURN}.commit_turn", mocks["commit_turn"]),
        ):
            result = await run_turn(game, "hello", config)

        assert result.chapter_advanced is False


class TestRunTurnRollingSummary:
    """Cover lines 502-521: rolling summary trigger inside run_turn."""

    @pytest.mark.asyncio
    async def test_rolling_summary_triggered(self, tmp_path: Path):
        """When conversation is long enough, rolling summary runs."""
        mocks = _patch_all_agents()
        game = _make_game(tmp_path)
        # Pre-populate with long conversation
        long_text = "Detailed narration text about the island. " * 50
        for t in range(1, 12):
            game.conversation.append(
                ConversationEntry(turn=t, role="narrator", content=long_text)
            )
            game.conversation.append(
                ConversationEntry(turn=t, role="player", content="action")
            )
        config = _make_llm_config()

        with (
            patch(f"{_TURN}.run_narrator", mocks["run_narrator"]),
            patch(f"{_TURN}.run_character", mocks["run_character"]),
            patch(f"{_TURN}.run_memory_update", mocks["run_memory_update"]),
            patch(f"{_TURN}.run_game_state", mocks["run_game_state"]),
            patch(f"{_TURN}.append_conversation", mocks["append_conversation"]),
            patch(f"{_TURN}.save_state", mocks["save_state"]),
            patch(f"{_TURN}.save_memory", mocks["save_memory"]),
            patch(f"{_TURN}.commit_turn", mocks["commit_turn"]),
            patch(
                f"{_TURN}.run_rolling_summary",
                new_callable=AsyncMock,
                return_value="New rolling summary.",
            ) as mock_rolling,
        ):
            result = await run_turn(game, "hello", config)

        assert result.summary_updated is True
        mock_rolling.assert_awaited_once()


class TestRunTurnStreamCallbacks:
    """Cover lines 187-189, 263-265: streaming token callbacks."""

    @pytest.mark.asyncio
    async def test_on_token_callback_invoked(self, tmp_path: Path):
        """Token callback is invoked for narrator and character tokens."""
        tokens_received: list[tuple] = []

        async def mock_on_token(source, char_name, token, is_thinking):
            tokens_received.append((source, char_name, token, is_thinking))

        # We need run_narrator to invoke the callback
        async def fake_narrator(game, player_input, llm_config, on_token, **kw):
            if on_token:
                await on_token("narrator token", False)
            return _narrator_output()

        async def fake_character(
            game,
            character,
            memory,
            player_input,
            narrator_output,
            prior_responses,
            llm_config,
            on_token,
            **kw,
        ):
            if on_token:
                await on_token("char token", False)
            return _character_response()

        mocks = _patch_all_agents()
        game = _make_game(
            tmp_path,
            memories={
                "maya": CharacterMemory(
                    character="Maya Chen", summary="", key_facts=[]
                ),
            },
        )
        config = _make_llm_config()

        with (
            patch(f"{_TURN}.run_narrator", side_effect=fake_narrator),
            patch(f"{_TURN}.run_character", side_effect=fake_character),
            patch(f"{_TURN}.run_memory_update", mocks["run_memory_update"]),
            patch(f"{_TURN}.run_game_state", mocks["run_game_state"]),
            patch(f"{_TURN}.append_conversation", mocks["append_conversation"]),
            patch(f"{_TURN}.save_state", mocks["save_state"]),
            patch(f"{_TURN}.save_memory", mocks["save_memory"]),
            patch(f"{_TURN}.commit_turn", mocks["commit_turn"]),
        ):
            await run_turn(game, "hello", config, on_token=mock_on_token)

        # Verify callbacks were invoked
        narrator_tokens = [t for t in tokens_received if t[0] == "narrator"]
        char_tokens = [t for t in tokens_received if t[0] == "character"]
        assert len(narrator_tokens) >= 1
        assert len(char_tokens) >= 1


class TestRunTurnNarratorDoneCallback:
    """Cover line 225-226: on_narrator_done callback."""

    @pytest.mark.asyncio
    async def test_on_narrator_done_called(self, tmp_path: Path):
        """on_narrator_done callback is invoked with parsed NarratorOutput."""
        received = []

        async def on_done(output):
            received.append(output)

        mocks = _patch_all_agents()
        game = _make_game(tmp_path)
        config = _make_llm_config()

        with (
            patch(f"{_TURN}.run_narrator", mocks["run_narrator"]),
            patch(f"{_TURN}.run_character", mocks["run_character"]),
            patch(f"{_TURN}.run_memory_update", mocks["run_memory_update"]),
            patch(f"{_TURN}.run_game_state", mocks["run_game_state"]),
            patch(f"{_TURN}.append_conversation", mocks["append_conversation"]),
            patch(f"{_TURN}.save_state", mocks["save_state"]),
            patch(f"{_TURN}.save_memory", mocks["save_memory"]),
            patch(f"{_TURN}.commit_turn", mocks["commit_turn"]),
        ):
            await run_turn(game, "hello", config, on_narrator_done=on_done)

        assert len(received) == 1
        assert isinstance(received[0], NarratorOutput)


class TestRunTurnDiagnostics:
    """Cover lines 180-181, 200-213, 250-258, 280-288, 313-316, 329-330,
    366-390, 438-439: diagnostics writer path (debug=True)."""

    @pytest.mark.asyncio
    async def test_diagnostics_written_when_debug(self, tmp_path: Path):
        """When debug=True, DiagnosticsWriter is used."""
        mocks = _patch_all_agents()
        call_log = LLMCallLog()
        # Pre-populate a call record so diag logic fires
        LLMCallRecord(
            timestamp="2026-01-01T00:00:00",
            agent="narrator",
            turn=1,
            prompt_tokens=100,
            thinking_tokens=50,
            content_tokens=200,
            latency_ms=500,
            finish_reason="stop",
            parse_result="success",
            parse_attempts=1,
            retry_count=0,
            temperature=1.0,
            max_tokens=4096,
        )

        # Make run_narrator add a record to the log
        async def narrator_with_log(game, player_input, llm_config, on_token, **kw):
            cl = kw.get("call_log")
            if cl is not None:
                cl.log(
                    LLMCallRecord(
                        timestamp="2026-01-01T00:00:00",
                        agent="narrator",
                        turn=1,
                        prompt_tokens=100,
                        thinking_tokens=50,
                        content_tokens=200,
                        latency_ms=500,
                        finish_reason="stop",
                        parse_result="success",
                        parse_attempts=1,
                        retry_count=0,
                        temperature=1.0,
                        max_tokens=4096,
                    )
                )
            return _narrator_output()

        async def character_with_log(
            game,
            character,
            memory,
            player_input,
            narrator_output,
            prior_responses,
            llm_config,
            on_token,
            **kw,
        ):
            cl = kw.get("call_log")
            if cl is not None:
                cl.log(
                    LLMCallRecord(
                        timestamp="2026-01-01T00:00:01",
                        agent="character:maya",
                        turn=1,
                        prompt_tokens=80,
                        thinking_tokens=30,
                        content_tokens=150,
                        latency_ms=400,
                        finish_reason="stop",
                        parse_result="success",
                        parse_attempts=1,
                        retry_count=0,
                        temperature=1.0,
                        max_tokens=3000,
                    )
                )
            return _character_response()

        async def memory_with_log(character, memory, turn_entries, llm_config, **kw):
            cl = kw.get("call_log")
            if cl is not None:
                cl.log(
                    LLMCallRecord(
                        timestamp="2026-01-01T00:00:02",
                        agent="memory:maya",
                        turn=1,
                        prompt_tokens=60,
                        thinking_tokens=20,
                        content_tokens=100,
                        latency_ms=300,
                        finish_reason="stop",
                        parse_result="success",
                        parse_attempts=1,
                        retry_count=0,
                        temperature=0.2,
                        max_tokens=2500,
                    )
                )
            return _memory_diff()

        async def game_state_with_log(game, turn_entries, llm_config, **kw):
            cl = kw.get("call_log")
            if cl is not None:
                cl.log(
                    LLMCallRecord(
                        timestamp="2026-01-01T00:00:03",
                        agent="game_state",
                        turn=1,
                        prompt_tokens=70,
                        thinking_tokens=25,
                        content_tokens=80,
                        latency_ms=350,
                        finish_reason="stop",
                        parse_result="success",
                        parse_attempts=1,
                        retry_count=0,
                        temperature=0.2,
                        max_tokens=2000,
                    )
                )
            return _game_state_result()

        game = _make_game(
            tmp_path,
            memories={
                "maya": CharacterMemory(
                    character="Maya Chen", summary="", key_facts=[]
                ),
            },
        )
        config = _make_llm_config()

        with (
            patch(f"{_TURN}.run_narrator", side_effect=narrator_with_log),
            patch(f"{_TURN}.run_character", side_effect=character_with_log),
            patch(f"{_TURN}.run_memory_update", side_effect=memory_with_log),
            patch(f"{_TURN}.run_game_state", side_effect=game_state_with_log),
            patch(f"{_TURN}.append_conversation", mocks["append_conversation"]),
            patch(f"{_TURN}.save_state", mocks["save_state"]),
            patch(f"{_TURN}.save_memory", mocks["save_memory"]),
            patch(f"{_TURN}.commit_turn", mocks["commit_turn"]),
            patch(
                f"{_TURN}.build_narrator_messages",
                return_value=[
                    {"role": "system", "content": "You are a narrator."},
                    {"role": "user", "content": "Player input."},
                ],
            ),
            patch(
                f"{_TURN}.build_character_messages",
                return_value=[
                    {"role": "system", "content": "You are Maya."},
                    {"role": "user", "content": "Respond."},
                ],
            ),
            patch(
                f"{_TURN}.build_memory_messages",
                return_value=[
                    {"role": "system", "content": "Update memory."},
                ],
            ),
            patch(
                f"{_TURN}.build_game_state_messages",
                return_value=[
                    {"role": "system", "content": "Check state."},
                ],
            ),
        ):
            await run_turn(game, "hello", config, call_log=call_log, debug=True)

        # Verify diagnostics directory was created
        diag_dir = tmp_path / "diagnostics" / "turn-001"
        assert diag_dir.exists()
        # Check narrator diagnostics
        assert (diag_dir / "narrator" / "raw_response.txt").exists()
        # Check character diagnostics
        assert (diag_dir / "character-maya" / "raw_response.txt").exists()
        # Check memory diagnostics
        assert (diag_dir / "memory-maya" / "raw_response.txt").exists()
        # Check game_state diagnostics
        assert (diag_dir / "game_state" / "raw_response.txt").exists()
        # Check summary
        assert (diag_dir / "summary.yaml").exists()


class TestRunTurnPersistence:
    """Cover lines 551-579: persistence (save_state, save_memory, commit)."""

    @pytest.mark.asyncio
    async def test_memory_saved_for_responding_characters(self, tmp_path: Path):
        """save_memory is called for each responding character with memory."""
        mocks = _patch_all_agents()
        maya_mem = CharacterMemory(character="Maya Chen", summary="", key_facts=[])
        game = _make_game(tmp_path, memories={"maya": maya_mem})
        config = _make_llm_config()

        with (
            patch(f"{_TURN}.run_narrator", mocks["run_narrator"]),
            patch(f"{_TURN}.run_character", mocks["run_character"]),
            patch(f"{_TURN}.run_memory_update", mocks["run_memory_update"]),
            patch(f"{_TURN}.run_game_state", mocks["run_game_state"]),
            patch(f"{_TURN}.append_conversation", mocks["append_conversation"]),
            patch(f"{_TURN}.save_state", mocks["save_state"]),
            patch(f"{_TURN}.save_memory", mocks["save_memory"]),
            patch(f"{_TURN}.commit_turn", mocks["commit_turn"]),
        ):
            await run_turn(game, "hello", config)

        mocks["save_memory"].assert_called_once()
        # Called with save_path and the memory object
        call_args = mocks["save_memory"].call_args
        assert call_args[0][0] == tmp_path

    @pytest.mark.asyncio
    async def test_commit_turn_called_with_summary(self, tmp_path: Path):
        """commit_turn is called with truncated narration as summary."""
        mocks = _patch_all_agents(
            narrator_output=_narrator_output(
                narration="A very long narration that exceeds sixty characters and should be truncated for the commit message."
            ),
        )
        game = _make_game(tmp_path)
        config = _make_llm_config()

        with (
            patch(f"{_TURN}.run_narrator", mocks["run_narrator"]),
            patch(f"{_TURN}.run_character", mocks["run_character"]),
            patch(f"{_TURN}.run_memory_update", mocks["run_memory_update"]),
            patch(f"{_TURN}.run_game_state", mocks["run_game_state"]),
            patch(f"{_TURN}.append_conversation", mocks["append_conversation"]),
            patch(f"{_TURN}.save_state", mocks["save_state"]),
            patch(f"{_TURN}.save_memory", mocks["save_memory"]),
            patch(f"{_TURN}.commit_turn", mocks["commit_turn"]),
        ):
            await run_turn(game, "hello", config)

        call_args = mocks["commit_turn"].call_args
        assert call_args[0][0] == tmp_path  # save_path
        assert call_args[0][1] == 1  # turn number
        # Summary is truncated to 60 chars
        assert len(call_args[0][2]) <= 60

    @pytest.mark.asyncio
    async def test_conversation_entries_appended(self, tmp_path: Path):
        """All entries are appended to game.conversation."""
        mocks = _patch_all_agents()
        game = _make_game(
            tmp_path,
            memories={
                "maya": CharacterMemory(
                    character="Maya Chen", summary="", key_facts=[]
                ),
            },
        )
        config = _make_llm_config()

        with (
            patch(f"{_TURN}.run_narrator", mocks["run_narrator"]),
            patch(f"{_TURN}.run_character", mocks["run_character"]),
            patch(f"{_TURN}.run_memory_update", mocks["run_memory_update"]),
            patch(f"{_TURN}.run_game_state", mocks["run_game_state"]),
            patch(f"{_TURN}.append_conversation", mocks["append_conversation"]),
            patch(f"{_TURN}.save_state", mocks["save_state"]),
            patch(f"{_TURN}.save_memory", mocks["save_memory"]),
            patch(f"{_TURN}.commit_turn", mocks["commit_turn"]),
        ):
            await run_turn(game, "hello", config)

        # narrator + player + character = 3 entries
        assert len(game.conversation) == 3
        roles = [e.role for e in game.conversation]
        assert "narrator" in roles
        assert "player" in roles
        assert "character" in roles


class TestRunTurnChapterJustAdvancedCleared:
    """Cover line 185: chapter_just_advanced is cleared."""

    @pytest.mark.asyncio
    async def test_chapter_just_advanced_cleared(self, tmp_path: Path):
        """chapter_just_advanced flag is cleared before narrator runs."""
        mocks = _patch_all_agents()
        game = _make_game(tmp_path)
        game.state.chapter_just_advanced = True
        config = _make_llm_config()

        with (
            patch(f"{_TURN}.run_narrator", mocks["run_narrator"]),
            patch(f"{_TURN}.run_character", mocks["run_character"]),
            patch(f"{_TURN}.run_memory_update", mocks["run_memory_update"]),
            patch(f"{_TURN}.run_game_state", mocks["run_game_state"]),
            patch(f"{_TURN}.append_conversation", mocks["append_conversation"]),
            patch(f"{_TURN}.save_state", mocks["save_state"]),
            patch(f"{_TURN}.save_memory", mocks["save_memory"]),
            patch(f"{_TURN}.commit_turn", mocks["commit_turn"]),
        ):
            await run_turn(game, "hello", config)

        # After run_turn, the flag was cleared at line 185
        # (it may be set again if chapter advanced, but in this case completed=False)
        assert game.state.chapter_just_advanced is False


class TestRunTurnCallLog:
    """Cover call_log integration in run_turn."""

    @pytest.mark.asyncio
    async def test_call_log_tracks_records(self, tmp_path: Path):
        """When call_log is provided, log_before calculations work correctly."""
        mocks = _patch_all_agents()
        call_log = LLMCallLog()
        game = _make_game(tmp_path)
        config = _make_llm_config()

        with (
            patch(f"{_TURN}.run_narrator", mocks["run_narrator"]),
            patch(f"{_TURN}.run_character", mocks["run_character"]),
            patch(f"{_TURN}.run_memory_update", mocks["run_memory_update"]),
            patch(f"{_TURN}.run_game_state", mocks["run_game_state"]),
            patch(f"{_TURN}.append_conversation", mocks["append_conversation"]),
            patch(f"{_TURN}.save_state", mocks["save_state"]),
            patch(f"{_TURN}.save_memory", mocks["save_memory"]),
            patch(f"{_TURN}.commit_turn", mocks["commit_turn"]),
        ):
            result = await run_turn(game, "hello", config, call_log=call_log)

        assert isinstance(result, TurnResult)


class TestRunTurnMultipleCharacters:
    """Test with multiple characters responding."""

    @pytest.mark.asyncio
    async def test_multiple_characters_sequential(self, tmp_path: Path):
        """Multiple characters run sequentially, each seeing prior responses."""
        joaquin = Character(
            name="Father Joaquin",
            role="priest",
            personality="Calm, thoughtful.",
            secret="Lost his faith.",
            relationships={"player": "protective"},
        )
        maya = _make_character()

        char_responses = [
            CharacterResponse(character="Maya Chen", response="Maya speaks."),
            CharacterResponse(character="Father Joaquin", response="Joaquin speaks."),
        ]
        call_count = {"n": 0}

        async def fake_run_character(**kw):
            idx = call_count["n"]
            call_count["n"] += 1
            return char_responses[idx]

        mocks = _patch_all_agents(
            narrator_output=_narrator_output(chars=["maya", "joaquin"]),
        )
        mocks["run_character"] = AsyncMock(side_effect=fake_run_character)

        # Need both memory diffs returned for both characters
        memory_diffs = [_memory_diff("Maya Chen"), _memory_diff("Father Joaquin")]
        mem_count = {"n": 0}

        async def fake_memory_update(*a, **kw):
            idx = mem_count["n"]
            mem_count["n"] += 1
            return memory_diffs[idx]

        mocks["run_memory_update"] = AsyncMock(side_effect=fake_memory_update)

        game = _make_game(
            tmp_path,
            characters={"maya": maya, "joaquin": joaquin},
            memories={
                "maya": CharacterMemory(
                    character="Maya Chen", summary="", key_facts=[]
                ),
                "joaquin": CharacterMemory(
                    character="Father Joaquin", summary="", key_facts=[]
                ),
            },
        )
        config = _make_llm_config()

        with (
            patch(f"{_TURN}.run_narrator", mocks["run_narrator"]),
            patch(f"{_TURN}.run_character", mocks["run_character"]),
            patch(f"{_TURN}.run_memory_update", mocks["run_memory_update"]),
            patch(f"{_TURN}.run_game_state", mocks["run_game_state"]),
            patch(f"{_TURN}.append_conversation", mocks["append_conversation"]),
            patch(f"{_TURN}.save_state", mocks["save_state"]),
            patch(f"{_TURN}.save_memory", mocks["save_memory"]),
            patch(f"{_TURN}.commit_turn", mocks["commit_turn"]),
        ):
            result = await run_turn(game, "hello", config)

        assert len(result.characters) == 2
        assert result.characters[0].character == "Maya Chen"
        assert result.characters[1].character == "Father Joaquin"
        # save_memory called for each character
        assert mocks["save_memory"].call_count == 2

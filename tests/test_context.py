"""Tests for context assembly (message builders)."""

import shutil
from pathlib import Path

import pytest

from theact.engine.context import (
    build_character_messages,
    build_game_state_messages,
    build_memory_messages,
    build_narrator_messages,
    build_rolling_summary_messages,
    build_summary_messages,
    format_chapter_context,
    format_conversation,
    get_recent_conversation,
)
from theact.engine.types import CharacterResponse, NarratorOutput
from theact.io.save_manager import create_save, load_save
from theact.llm.config import LLMConfig
from theact.models.conversation import ConversationEntry
from theact.models.game import LoadedGame
from theact.models.memory import CharacterMemory

GAMES_DIR = Path(__file__).parent.parent / "games"


@pytest.fixture
def llm_config() -> LLMConfig:
    """A dummy LLM config (no real API key needed for context tests)."""
    return LLMConfig(api_key="test-key-not-real")


@pytest.fixture
def lost_island_game(tmp_path: Path) -> LoadedGame:
    """Load a fresh lost-island game from a temp save."""
    games_dir = tmp_path / "games"
    shutil.copytree(GAMES_DIR, games_dir)
    saves_dir = tmp_path / "saves"
    saves_dir.mkdir()
    create_save(
        "lost-island",
        "ctx-test",
        "Alex",
        games_dir=games_dir,
        saves_dir=saves_dir,
    )
    return load_save("ctx-test", saves_dir=saves_dir)


def _make_entries(num_turns: int = 3) -> list[ConversationEntry]:
    """Create a set of conversation entries spanning multiple turns."""
    entries: list[ConversationEntry] = []
    for t in range(1, num_turns + 1):
        entries.append(
            ConversationEntry(turn=t, role="narrator", content=f"Turn {t} narration.")
        )
        entries.append(
            ConversationEntry(turn=t, role="player", content=f"Turn {t} player action.")
        )
        entries.append(
            ConversationEntry(
                turn=t,
                role="character",
                character="Maya Chen",
                content=f"Turn {t} Maya speaks.",
            )
        )
    return entries


# ---------------------------------------------------------------------------
# get_recent_conversation
# ---------------------------------------------------------------------------


class TestGetRecentConversation:
    def test_returns_correct_entries(self):
        entries = _make_entries(5)
        recent = get_recent_conversation(entries, max_turns=2)
        # Should only include turns 4 and 5
        turns = {e.turn for e in recent}
        assert turns == {4, 5}

    def test_handles_empty(self):
        assert get_recent_conversation([], max_turns=4) == []

    def test_returns_all_when_fewer_than_max(self):
        entries = _make_entries(2)
        recent = get_recent_conversation(entries, max_turns=4)
        assert len(recent) == len(entries)

    def test_includes_all_entries_for_cutoff_turn(self):
        entries = _make_entries(3)
        recent = get_recent_conversation(entries, max_turns=2)
        # Should include all 3 entries for turn 2 and turn 3
        assert len(recent) == 6

    def test_single_turn(self):
        entries = _make_entries(1)
        recent = get_recent_conversation(entries, max_turns=1)
        assert len(recent) == 3  # narrator + player + character


# ---------------------------------------------------------------------------
# format_conversation
# ---------------------------------------------------------------------------


class TestFormatConversation:
    def test_narrator_format(self):
        entries = [ConversationEntry(turn=1, role="narrator", content="You wake up.")]
        result = format_conversation(entries)
        assert result == "[Narrator]: You wake up."

    def test_player_format(self):
        entries = [ConversationEntry(turn=1, role="player", content="I look around.")]
        result = format_conversation(entries)
        assert result == "[Player]: I look around."

    def test_character_format(self):
        entries = [
            ConversationEntry(
                turn=1, role="character", character="Maya Chen", content="She nods."
            )
        ]
        result = format_conversation(entries)
        assert result == "[Maya Chen]: She nods."

    def test_multiple_entries(self):
        entries = [
            ConversationEntry(turn=1, role="narrator", content="You wake up."),
            ConversationEntry(turn=1, role="player", content="I look around."),
            ConversationEntry(
                turn=1, role="character", character="Maya", content="Hello."
            ),
        ]
        result = format_conversation(entries)
        lines = result.split("\n")
        assert len(lines) == 3
        assert lines[0] == "[Narrator]: You wake up."
        assert lines[1] == "[Player]: I look around."
        assert lines[2] == "[Maya]: Hello."

    def test_empty_entries(self):
        assert format_conversation([]) == ""


# ---------------------------------------------------------------------------
# format_chapter_context
# ---------------------------------------------------------------------------


class TestFormatChapterContext:
    def test_includes_current_chapter(self, lost_island_game: LoadedGame):
        result = format_chapter_context(lost_island_game)
        assert "CURRENT CHAPTER: The Crash" in result
        assert "Complete when:" in result

    def test_includes_beats(self, lost_island_game: LoadedGame):
        result = format_chapter_context(lost_island_game)
        assert "Player wakes on the beach" in result

    def test_shows_beat_status(self, lost_island_game: LoadedGame):
        # Mark one beat as hit
        lost_island_game.state.beats_hit = ["Player wakes on the beach, disoriented"]
        result = format_chapter_context(lost_island_game)
        assert "[x] Player wakes on the beach" in result
        # Other beats should be unchecked
        assert "[ ] Explores wreckage, finds supplies" in result

    def test_includes_upcoming(self, lost_island_game: LoadedGame):
        result = format_chapter_context(lost_island_game)
        assert "UPCOMING:" in result
        assert "The Discovery" in result

    def test_includes_completed_summaries(self, lost_island_game: LoadedGame):
        from theact.models.chapter import ChapterSummary

        lost_island_game.chapter_summaries = [
            ChapterSummary(
                chapter_id="prev",
                title="Previous Chapter",
                summary="Things happened.",
            )
        ]
        result = format_chapter_context(lost_island_game)
        assert "COMPLETED CHAPTERS:" in result
        assert "Previous Chapter" in result


# ---------------------------------------------------------------------------
# build_narrator_messages
# ---------------------------------------------------------------------------


class TestBuildNarratorMessages:
    def test_produces_valid_messages(
        self, lost_island_game: LoadedGame, llm_config: LLMConfig
    ):
        messages = build_narrator_messages(
            lost_island_game, "I look around.", llm_config
        )
        assert len(messages) >= 2
        assert messages[0]["role"] == "system"
        assert messages[1]["role"] == "user"

    def test_system_prompt_contains_world(
        self, lost_island_game: LoadedGame, llm_config: LLMConfig
    ):
        messages = build_narrator_messages(
            lost_island_game, "I look around.", llm_config
        )
        system = messages[0]["content"]
        assert "South Pacific" in system or "island" in system.lower()

    def test_user_message_contains_player_input(
        self, lost_island_game: LoadedGame, llm_config: LLMConfig
    ):
        messages = build_narrator_messages(
            lost_island_game, "I look around.", llm_config
        )
        user = messages[1]["content"]
        assert "I look around." in user

    def test_opening_scene_guidance(
        self, lost_island_game: LoadedGame, llm_config: LLMConfig
    ):
        """On turn 0 with no conversation, narrator should get opening scene hint."""
        messages = build_narrator_messages(
            lost_island_game, "I open my eyes.", llm_config
        )
        user = messages[1]["content"]
        assert "opening scene" in user.lower()

    def test_includes_rolling_summary(
        self, lost_island_game: LoadedGame, llm_config: LLMConfig
    ):
        lost_island_game.state.rolling_summary = "Player woke on the beach."
        messages = build_narrator_messages(lost_island_game, "I stand up.", llm_config)
        user = messages[1]["content"]
        assert "Player woke on the beach." in user

    def test_chapter_transition_signal(
        self, lost_island_game: LoadedGame, llm_config: LLMConfig
    ):
        lost_island_game.state.chapter_just_advanced = True
        messages = build_narrator_messages(lost_island_game, "What now?", llm_config)
        user = messages[1]["content"]
        assert "new chapter" in user.lower()
        # Flag should be cleared after building messages
        assert not lost_island_game.state.chapter_just_advanced


# ---------------------------------------------------------------------------
# build_character_messages
# ---------------------------------------------------------------------------


class TestBuildCharacterMessages:
    def test_produces_valid_messages(
        self, lost_island_game: LoadedGame, llm_config: LLMConfig
    ):
        maya = lost_island_game.characters["maya"]
        narrator_output = NarratorOutput(
            narration="You see someone ahead.",
            responding_characters=["maya"],
            mood="tense",
        )
        messages = build_character_messages(
            lost_island_game,
            maya,
            None,
            "Hello?",
            narrator_output,
            [],
            llm_config,
        )
        assert len(messages) >= 2
        assert messages[0]["role"] == "system"

    def test_system_includes_character_info(
        self, lost_island_game: LoadedGame, llm_config: LLMConfig
    ):
        maya = lost_island_game.characters["maya"]
        narrator_output = NarratorOutput(
            narration="You see someone.",
            responding_characters=["maya"],
            mood="calm",
        )
        messages = build_character_messages(
            lost_island_game, maya, None, "Hi.", narrator_output, [], llm_config
        )
        system = messages[0]["content"]
        assert "Maya Chen" in system
        assert maya.secret in system

    def test_includes_memory(self, lost_island_game: LoadedGame, llm_config: LLMConfig):
        maya = lost_island_game.characters["maya"]
        memory = CharacterMemory(
            character="Maya Chen",
            summary="Met the player on the beach.",
            key_facts=["Player seems trustworthy"],
        )
        narrator_output = NarratorOutput(
            narration="Scene.",
            responding_characters=["maya"],
            mood="calm",
        )
        messages = build_character_messages(
            lost_island_game, maya, memory, "Hi.", narrator_output, [], llm_config
        )
        system = messages[0]["content"]
        assert "Met the player on the beach." in system
        assert "Player seems trustworthy" in system

    def test_includes_relationships(
        self, lost_island_game: LoadedGame, llm_config: LLMConfig
    ):
        maya = lost_island_game.characters["maya"]
        narrator_output = NarratorOutput(
            narration="Scene.",
            responding_characters=["maya"],
            mood="calm",
        )
        messages = build_character_messages(
            lost_island_game, maya, None, "Hi.", narrator_output, [], llm_config
        )
        system = messages[0]["content"]
        assert "joaquin" in system.lower()

    def test_includes_prior_responses(
        self, lost_island_game: LoadedGame, llm_config: LLMConfig
    ):
        joaquin = lost_island_game.characters["joaquin"]
        narrator_output = NarratorOutput(
            narration="Scene.",
            responding_characters=["maya", "joaquin"],
            mood="calm",
        )
        prior = [CharacterResponse(character="Maya Chen", response="I found water.")]
        messages = build_character_messages(
            lost_island_game,
            joaquin,
            None,
            "Any luck?",
            narrator_output,
            prior,
            llm_config,
        )
        # Prior response should appear in one of the user messages
        all_content = " ".join(m["content"] for m in messages if m["role"] == "user")
        assert "I found water." in all_content


# ---------------------------------------------------------------------------
# build_memory_messages
# ---------------------------------------------------------------------------


class TestBuildMemoryMessages:
    def test_produces_valid_messages(self, lost_island_game: LoadedGame):
        maya = lost_island_game.characters["maya"]
        entries = [
            ConversationEntry(turn=1, role="narrator", content="You wake up."),
            ConversationEntry(turn=1, role="player", content="I look around."),
        ]
        messages = build_memory_messages(maya, None, entries)
        assert len(messages) == 2
        assert messages[0]["role"] == "system"
        assert messages[1]["role"] == "user"

    def test_includes_current_memory(self, lost_island_game: LoadedGame):
        maya = lost_island_game.characters["maya"]
        memory = CharacterMemory(
            character="Maya Chen",
            summary="Met the player.",
            key_facts=["Player is disoriented"],
        )
        entries = [
            ConversationEntry(turn=1, role="narrator", content="Scene."),
        ]
        messages = build_memory_messages(maya, memory, entries)
        user = messages[1]["content"]
        assert "Met the player." in user
        assert "Player is disoriented" in user

    def test_includes_turn_entries(self, lost_island_game: LoadedGame):
        maya = lost_island_game.characters["maya"]
        entries = [
            ConversationEntry(turn=2, role="narrator", content="The sun sets."),
            ConversationEntry(turn=2, role="player", content="I gather wood."),
        ]
        messages = build_memory_messages(maya, None, entries)
        user = messages[1]["content"]
        assert "The sun sets." in user
        assert "I gather wood." in user

    def test_new_character_no_memory(self, lost_island_game: LoadedGame):
        maya = lost_island_game.characters["maya"]
        messages = build_memory_messages(maya, None, [])
        user = messages[1]["content"]
        assert "no memories" in user.lower() or "(none)" in user.lower()


# ---------------------------------------------------------------------------
# build_game_state_messages
# ---------------------------------------------------------------------------


class TestBuildGameStateMessages:
    def test_produces_valid_messages(self, lost_island_game: LoadedGame):
        entries = [
            ConversationEntry(turn=1, role="narrator", content="You wake up."),
        ]
        messages = build_game_state_messages(lost_island_game, entries)
        assert len(messages) == 2
        assert messages[0]["role"] == "system"
        assert messages[1]["role"] == "user"

    def test_includes_beats_with_status(self, lost_island_game: LoadedGame):
        lost_island_game.state.beats_hit = ["Player wakes on the beach, disoriented"]
        entries = [
            ConversationEntry(turn=2, role="narrator", content="You explore."),
        ]
        messages = build_game_state_messages(lost_island_game, entries)
        user = messages[1]["content"]
        assert "[x] Player wakes on the beach" in user
        assert "[ ]" in user  # at least one unchecked beat

    def test_includes_completion_condition(self, lost_island_game: LoadedGame):
        entries = [
            ConversationEntry(turn=1, role="narrator", content="Scene."),
        ]
        messages = build_game_state_messages(lost_island_game, entries)
        user = messages[1]["content"]
        assert "Complete when:" in user

    def test_includes_turn_text(self, lost_island_game: LoadedGame):
        entries = [
            ConversationEntry(
                turn=1, role="narrator", content="You hear drums in the jungle."
            ),
        ]
        messages = build_game_state_messages(lost_island_game, entries)
        user = messages[1]["content"]
        assert "drums in the jungle" in user

    def test_empty_when_no_chapter(self, lost_island_game: LoadedGame):
        lost_island_game.state.current_chapter = "nonexistent"
        entries = [ConversationEntry(turn=1, role="narrator", content="Scene.")]
        messages = build_game_state_messages(lost_island_game, entries)
        assert messages == []


# ---------------------------------------------------------------------------
# build_summary_messages and build_rolling_summary_messages
# ---------------------------------------------------------------------------


class TestBuildSummaryMessages:
    def test_chapter_summary_messages(self, lost_island_game: LoadedGame):
        # Add some conversation for the summarizer to work with
        lost_island_game.conversation = _make_entries(3)
        chapter = lost_island_game.chapters["01-the-crash"]
        messages = build_summary_messages(lost_island_game, chapter)
        assert len(messages) == 2
        assert messages[0]["role"] == "system"
        user = messages[1]["content"]
        assert "The Crash" in user

    def test_rolling_summary_messages(self):
        entries = _make_entries(2)
        messages = build_rolling_summary_messages("Player woke on the beach.", entries)
        assert len(messages) == 2
        user = messages[1]["content"]
        assert "Player woke on the beach." in user

    def test_rolling_summary_no_existing(self):
        entries = _make_entries(1)
        messages = build_rolling_summary_messages("", entries)
        user = messages[1]["content"]
        # Should not have "Previous summary" since it's empty
        assert "New events" in user or "Turn 1" in user


# ---------------------------------------------------------------------------
# Token budget overflow
# ---------------------------------------------------------------------------


class TestTokenBudgetOverflow:
    def test_narrator_trimming_with_long_conversation(
        self, lost_island_game: LoadedGame, llm_config: LLMConfig
    ):
        """When conversation is very long, narrator messages should trim."""
        # Add a lot of conversation to the game
        long_entries = _make_entries(20)
        lost_island_game.conversation = long_entries

        # Use a very small context limit to force trimming
        tiny_config = LLMConfig(
            api_key="test",
            context_limit=2000,
            default_max_tokens=600,
        )

        messages = build_narrator_messages(
            lost_island_game, "I look around.", tiny_config
        )

        # Should still produce valid messages
        assert len(messages) >= 2
        assert messages[0]["role"] == "system"
        assert messages[1]["role"] == "user"
        # Player input should always be present
        assert "I look around." in messages[1]["content"]

    def test_character_trimming_with_long_conversation(
        self, lost_island_game: LoadedGame, llm_config: LLMConfig
    ):
        """When conversation is very long, character messages should trim."""
        long_entries = _make_entries(20)
        lost_island_game.conversation = long_entries

        maya = lost_island_game.characters["maya"]
        narrator_output = NarratorOutput(
            narration="Scene." * 100,  # Long narration
            responding_characters=["maya"],
            mood="calm",
        )

        tiny_config = LLMConfig(
            api_key="test",
            context_limit=2000,
            default_max_tokens=400,
        )

        messages = build_character_messages(
            lost_island_game,
            maya,
            None,
            "Hello?",
            narrator_output,
            [],
            tiny_config,
        )

        # Should still produce valid messages
        assert len(messages) >= 2
        assert messages[0]["role"] == "system"

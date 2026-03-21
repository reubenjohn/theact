"""Tests for theact.commands.logic — pure command logic with no UI imports."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from theact.commands.logic import (
    cmd_conversation,
    cmd_help,
    cmd_history,
    cmd_memory,
    cmd_save_as,
    cmd_save_info,
    cmd_status,
    cmd_undo,
)
from theact.models.chapter import Chapter
from theact.models.character import Character
from theact.models.conversation import ConversationEntry
from theact.models.game import GameMeta, LoadedGame
from theact.models.memory import CharacterMemory
from theact.models.state import GameState
from theact.models.world import World

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_game(
    tmp_path: Path,
    conversation: list[ConversationEntry] | None = None,
    memories: dict[str, CharacterMemory] | None = None,
) -> LoadedGame:
    """Build a minimal LoadedGame for testing."""
    save_path = tmp_path / "saves" / "test-save"
    save_path.mkdir(parents=True, exist_ok=True)
    return LoadedGame(
        meta=GameMeta(
            id="test-game",
            title="Test Game",
            description="A test game",
            characters=["elena"],
            chapters=["ch1"],
        ),
        world=World(setting="Forest", tone="Grim", rules="No magic"),
        characters={
            "elena": Character(
                name="Elena",
                role="Healer",
                personality="Calm and steady.",
                secret="Knows the cure.",
                relationships={"player": "Curious"},
            ),
        },
        chapters={
            "ch1": Chapter(
                id="ch1",
                title="The Beginning",
                summary="The story begins.",
                beats=["Arrive", "Explore"],
                completion="Explored the area.",
                characters=["elena"],
                next=None,
            ),
        },
        state=GameState(
            player_name="Hero",
            current_chapter="ch1",
            turn=5,
            beats_hit=["Arrive"],
            flags={},
            chapter_history=[],
        ),
        conversation=conversation or [],
        memories=memories or {},
        chapter_summaries=[],
        save_path=save_path,
    )


def _entry(
    role: str, content: str, turn: int = 1, character: str | None = None
) -> ConversationEntry:
    """Shorthand for building a ConversationEntry."""
    return ConversationEntry(turn=turn, role=role, content=content, character=character)


# ===========================================================================
# cmd_help
# ===========================================================================


class TestCmdHelp:
    def test_cmd_help_returns_rows(self):
        result = cmd_help()
        assert result.success is True
        assert result.title == "Commands"
        assert len(result.rows) > 0
        # Each row has command, args, desc keys
        for row in result.rows:
            assert "command" in row
            assert "args" in row
            assert "desc" in row
        # All expected commands are present
        commands = [row["command"] for row in result.rows]
        assert "/help" in commands
        assert "/undo" in commands
        assert "/memory" in commands
        assert "/save-as" in commands


# ===========================================================================
# cmd_status
# ===========================================================================


class TestCmdStatus:
    def test_cmd_status_returns_chapter_info(self, tmp_path):
        game = _make_game(tmp_path)
        result = cmd_status(game)

        assert result.success is True
        assert "The Beginning" in result.message
        assert "ch1" in result.message
        assert "Turn: 5" in result.message
        # 1 beat hit out of 2 total
        assert "Beats: 1/2" in result.message

    def test_cmd_status_unknown_chapter(self, tmp_path):
        game = _make_game(tmp_path)
        game.state.current_chapter = "99-missing"
        result = cmd_status(game)

        assert result.success is True
        assert "99-missing" in result.message
        assert "(not found)" in result.message
        assert "Turn: 5" in result.message

    def test_cmd_status_with_flags(self, tmp_path):
        game = _make_game(tmp_path)
        game.state.flags = {"found_key": "yes"}
        result = cmd_status(game)

        assert "Flags:" in result.message
        assert "found_key" in result.message

    def test_cmd_status_without_flags(self, tmp_path):
        game = _make_game(tmp_path)
        result = cmd_status(game)
        assert "Flags" not in result.message


# ===========================================================================
# cmd_memory
# ===========================================================================


class TestCmdMemory:
    def test_cmd_memory_no_args_lists_characters(self, tmp_path):
        game = _make_game(tmp_path)
        result = cmd_memory(game, [])

        assert result.success is True
        assert "Elena" in result.message
        assert "Characters:" in result.message

    def test_cmd_memory_no_args_shows_memory_marker(self, tmp_path):
        memories = {
            "elena": CharacterMemory(
                character="Elena",
                summary="Met the player.",
                key_facts=["Is cautious"],
            ),
        }
        game = _make_game(tmp_path, memories=memories)
        result = cmd_memory(game, [])

        assert "(has memory)" in result.message

    def test_cmd_memory_with_name_returns_memory(self, tmp_path):
        memories = {
            "elena": CharacterMemory(
                character="Elena",
                summary="Met the player at dawn.",
                key_facts=["Trusts the player", "Knows about the cave"],
            ),
        }
        game = _make_game(tmp_path, memories=memories)
        result = cmd_memory(game, ["elena"])

        assert result.success is True
        assert "Elena -- Memory" in result.message
        assert "Met the player at dawn." in result.message
        assert "Trusts the player" in result.message
        assert "Knows about the cave" in result.message

    def test_cmd_memory_unknown_character(self, tmp_path):
        game = _make_game(tmp_path)
        result = cmd_memory(game, ["zephyr"])

        assert result.success is False
        assert "Unknown character" in result.message
        assert "Elena" in result.message

    def test_cmd_memory_no_memories_yet(self, tmp_path):
        game = _make_game(tmp_path)
        result = cmd_memory(game, ["elena"])

        assert result.success is True
        assert "no memories yet" in result.message

    def test_cmd_memory_fuzzy_match(self, tmp_path):
        memories = {
            "elena": CharacterMemory(
                character="Elena",
                summary="Healed a wound.",
                key_facts=["Is tired"],
            ),
        }
        game = _make_game(tmp_path, memories=memories)
        result = cmd_memory(game, ["ele"])

        assert result.success is True
        assert "Elena -- Memory" in result.message


# ===========================================================================
# cmd_conversation
# ===========================================================================


class TestCmdConversation:
    def test_cmd_conversation_default_count(self, tmp_path):
        entries = [_entry("player", f"Message {i}", turn=i) for i in range(1, 11)]
        game = _make_game(tmp_path, conversation=entries)

        result = cmd_conversation(game, [])

        assert result.success is True
        # Default is last 5 entries (messages 6-10)
        assert "Message 6" in result.message
        assert "Message 10" in result.message
        assert "Message 5" not in result.message

    def test_cmd_conversation_custom_count(self, tmp_path):
        entries = [_entry("player", f"Msg {i}", turn=i) for i in range(1, 11)]
        game = _make_game(tmp_path, conversation=entries)

        result = cmd_conversation(game, ["3"])

        assert "Msg 8" in result.message
        assert "Msg 10" in result.message
        assert "Msg 7" not in result.message

    def test_cmd_conversation_empty(self, tmp_path):
        game = _make_game(tmp_path)
        result = cmd_conversation(game, [])

        assert result.success is True
        assert "No conversation yet." in result.message

    def test_cmd_conversation_invalid_arg(self, tmp_path):
        game = _make_game(tmp_path)
        result = cmd_conversation(game, ["abc"])

        assert result.success is False
        assert "positive integer" in result.message

    def test_cmd_conversation_zero_arg(self, tmp_path):
        game = _make_game(tmp_path)
        result = cmd_conversation(game, ["0"])

        assert result.success is False
        assert "positive integer" in result.message

    def test_cmd_conversation_narrator_truncated(self, tmp_path):
        long_text = "A" * 300
        entries = [_entry("narrator", long_text)]
        game = _make_game(tmp_path, conversation=entries)

        result = cmd_conversation(game, [])

        assert "Narrator:" in result.message
        assert "..." in result.message
        assert "A" * 200 in result.message
        assert "A" * 201 not in result.message

    def test_cmd_conversation_player_not_truncated(self, tmp_path):
        long_input = "X" * 400
        entries = [_entry("player", long_input)]
        game = _make_game(tmp_path, conversation=entries)

        result = cmd_conversation(game, [])

        assert "X" * 400 in result.message
        assert "..." not in result.message

    def test_cmd_conversation_character_entry(self, tmp_path):
        entries = [_entry("character", "Hello traveler", character="Elena")]
        game = _make_game(tmp_path, conversation=entries)

        result = cmd_conversation(game, [])

        assert "Elena: Hello traveler" in result.message

    def test_cmd_conversation_uses_player_name(self, tmp_path):
        entries = [_entry("player", "I look around")]
        game = _make_game(tmp_path, conversation=entries)

        result = cmd_conversation(game, [])

        assert "Hero: I look around" in result.message


# ===========================================================================
# cmd_save_info
# ===========================================================================


class TestCmdSaveInfo:
    def test_cmd_save_info_returns_path(self, tmp_path):
        game = _make_game(tmp_path)
        result = cmd_save_info(game)

        assert result.success is True
        assert f"Save: {game.save_path.name}" in result.message
        assert "Game: Test Game" in result.message
        assert "Player: Hero" in result.message
        assert f"Path: {game.save_path}" in result.message


# ===========================================================================
# cmd_history
# ===========================================================================


class TestCmdHistory:
    @patch("theact.commands.logic.git_save.get_history")
    def test_cmd_history_empty(self, mock_get_history, tmp_path):
        mock_get_history.return_value = []
        game = _make_game(tmp_path)

        result = cmd_history(game)

        assert result.success is True
        assert "No turn history yet." in result.message
        assert result.rows == []

    @patch("theact.commands.logic.git_save.get_history")
    def test_cmd_history_with_entries(self, mock_get_history, tmp_path):
        from unittest.mock import MagicMock

        entry1 = MagicMock(turn=1, message="Turn 1: Arrived", timestamp="2026-01-01")
        entry2 = MagicMock(turn=2, message="Turn 2: Explored", timestamp="2026-01-02")
        mock_get_history.return_value = [entry1, entry2]

        game = _make_game(tmp_path)
        result = cmd_history(game)

        assert result.success is True
        assert result.title == "Turn History"
        assert len(result.rows) == 2
        assert result.rows[0]["turn"] == "1"
        assert "Arrived" in result.rows[0]["summary"]
        assert result.rows[1]["turn"] == "2"


# ===========================================================================
# cmd_undo
# ===========================================================================


class TestCmdUndo:
    @patch("theact.commands.logic.load_save")
    @patch("theact.commands.logic.git_save.undo")
    def test_cmd_undo_default_steps(self, mock_undo, mock_load_save, tmp_path):
        game = _make_game(tmp_path)
        reloaded = _make_game(tmp_path)
        mock_undo.return_value = 4
        mock_load_save.return_value = reloaded

        result = cmd_undo(game, [])

        assert result.success is True
        assert result.data is reloaded
        assert "1 turn(s)" in result.message
        assert "turn 4" in result.message
        mock_undo.assert_called_once_with(game.save_path, 1)

    def test_cmd_undo_invalid_arg(self, tmp_path):
        game = _make_game(tmp_path)
        result = cmd_undo(game, ["abc"])

        assert result.success is False
        assert "Usage:" in result.message
        assert result.data is None

    def test_cmd_undo_zero_arg(self, tmp_path):
        game = _make_game(tmp_path)
        result = cmd_undo(game, ["0"])

        assert result.success is False
        assert "Usage:" in result.message

    @patch(
        "theact.commands.logic.git_save.undo",
        side_effect=ValueError("Not enough history"),
    )
    def test_cmd_undo_git_error(self, mock_undo, tmp_path):
        game = _make_game(tmp_path)
        result = cmd_undo(game, [])

        assert result.success is False
        assert "Cannot undo:" in result.message
        assert "Not enough history" in result.message


# ===========================================================================
# cmd_save_as
# ===========================================================================


class TestCmdSaveAs:
    def test_cmd_save_as_no_args(self, tmp_path):
        game = _make_game(tmp_path)
        result = cmd_save_as(game, [])

        assert result.success is False
        assert "Usage:" in result.message

    @patch("theact.commands.logic.git_save.save_as")
    def test_cmd_save_as_success(self, mock_save_as, tmp_path):
        game = _make_game(tmp_path)
        new_path = tmp_path / "saves" / "my-fork"
        mock_save_as.return_value = new_path

        result = cmd_save_as(game, ["my-fork"])

        assert result.success is True
        assert "my-fork" in result.message
        mock_save_as.assert_called_once_with(game.save_path, "my-fork")

    @patch(
        "theact.commands.logic.git_save.save_as",
        side_effect=FileExistsError("already exists"),
    )
    def test_cmd_save_as_exists(self, mock_save_as, tmp_path):
        game = _make_game(tmp_path)
        result = cmd_save_as(game, ["taken"])

        assert result.success is False
        assert "already exists" in result.message

    @patch(
        "theact.commands.logic.git_save.save_as",
        side_effect=FileNotFoundError("source not found"),
    )
    def test_cmd_save_as_not_found(self, mock_save_as, tmp_path):
        game = _make_game(tmp_path)
        result = cmd_save_as(game, ["new-save"])

        assert result.success is False
        assert "Cannot fork" in result.message

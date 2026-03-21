"""Tests for theact.web.commands — thin web rendering wrappers.

The underlying logic is now tested in tests/test_command_logic.py.
These tests verify the web rendering layer (delegates to shared logic,
renders results correctly).
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from theact.models.chapter import Chapter
from theact.models.character import Character
from theact.models.conversation import ConversationEntry
from theact.models.game import GameMeta, LoadedGame
from theact.models.memory import CharacterMemory
from theact.models.state import GameState
from theact.models.world import World
from theact.web.commands import (
    cmd_conversation_web,
    cmd_help_web,
    cmd_history_web,
    cmd_memory_web,
    cmd_save_as_web,
    cmd_save_web,
    cmd_status_web,
    cmd_undo_web,
)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _make_game(
    tmp_path: Path, conversation: list[ConversationEntry] | None = None
) -> LoadedGame:
    save_path = tmp_path / "saves" / "test-save"
    save_path.mkdir(parents=True, exist_ok=True)
    return LoadedGame(
        meta=GameMeta(
            id="test-game",
            title="Test Game",
            description="A test",
            characters=["elena"],
            chapters=["01-arrival"],
        ),
        world=World(setting="Forest", tone="Grim", rules="No magic"),
        characters={
            "elena": Character(
                name="Elena",
                role="Healer",
                personality="Calm",
                secret="Immune",
                relationships={"brother": "Protective"},
            )
        },
        chapters={
            "01-arrival": Chapter(
                id="01-arrival",
                title="The Arrival",
                summary="Arrive at village",
                beats=["Approach", "Challenge", "Entry"],
                completion="Entered village",
                characters=["elena"],
                next=None,
            )
        },
        state=GameState(
            player_name="Alex",
            current_chapter="01-arrival",
            turn=3,
            beats_hit=["Approach"],
            flags={},
            chapter_history=[],
        ),
        conversation=conversation or [],
        memories={},
        chapter_summaries=[],
        save_path=save_path,
    )


def _entry(
    role: str, content: str, turn: int = 1, character: str | None = None
) -> ConversationEntry:
    """Shorthand for building a ConversationEntry."""
    return ConversationEntry(turn=turn, role=role, content=content, character=character)


# ===========================================================================
# cmd_undo_web — returns (LoadedGame | None, str) tuple
# ===========================================================================


class TestCmdUndoWeb:
    """Tests for cmd_undo_web(game, args)."""

    @patch("theact.commands.logic.load_save")
    @patch("theact.commands.logic.git_save.undo")
    def test_default_steps_is_one(self, mock_undo, mock_load_save, tmp_path):
        game = _make_game(tmp_path)
        reloaded = _make_game(tmp_path)
        mock_undo.return_value = 2
        mock_load_save.return_value = reloaded

        result_game, msg = cmd_undo_web(game, [])

        mock_undo.assert_called_once_with(game.save_path, 1)
        assert result_game is reloaded
        assert "1 turn(s)" in msg

    @patch("theact.commands.logic.load_save")
    @patch("theact.commands.logic.git_save.undo")
    def test_valid_integer_arg(self, mock_undo, mock_load_save, tmp_path):
        game = _make_game(tmp_path)
        reloaded = _make_game(tmp_path)
        mock_undo.return_value = 0
        mock_load_save.return_value = reloaded

        result_game, msg = cmd_undo_web(game, ["3"])

        mock_undo.assert_called_once_with(game.save_path, 3)
        assert result_game is reloaded
        assert "3 turn(s)" in msg

    def test_invalid_arg_non_integer(self, tmp_path):
        game = _make_game(tmp_path)
        result_game, msg = cmd_undo_web(game, ["abc"])

        assert result_game is None
        assert "positive integer" in msg

    def test_zero_arg_returns_error(self, tmp_path):
        game = _make_game(tmp_path)
        result_game, msg = cmd_undo_web(game, ["0"])

        assert result_game is None

    def test_negative_arg_returns_error(self, tmp_path):
        game = _make_game(tmp_path)
        result_game, msg = cmd_undo_web(game, ["-1"])

        assert result_game is None

    @patch(
        "theact.commands.logic.git_save.undo",
        side_effect=ValueError("Not enough history"),
    )
    def test_git_undo_raises_valueerror(self, mock_undo, tmp_path):
        game = _make_game(tmp_path)
        result_game, msg = cmd_undo_web(game, [])

        assert result_game is None
        assert "Cannot undo:" in msg
        assert "Not enough history" in msg

    @patch("theact.commands.logic.load_save")
    @patch("theact.commands.logic.git_save.undo")
    def test_success_returns_reloaded_game(self, mock_undo, mock_load_save, tmp_path):
        game = _make_game(tmp_path)
        reloaded = _make_game(tmp_path)
        mock_undo.return_value = 1
        mock_load_save.return_value = reloaded

        result_game, _msg = cmd_undo_web(game, [])

        assert result_game is reloaded
        assert result_game is not game

    def test_float_arg_returns_error(self, tmp_path):
        """A float like '1.5' is not a valid integer."""
        game = _make_game(tmp_path)
        result_game, msg = cmd_undo_web(game, ["1.5"])

        assert result_game is None


# ===========================================================================
# cmd_conversation_web — renders via shared logic
# ===========================================================================


class TestCmdConversationWeb:
    """Tests for cmd_conversation_web(chat_area, game, args)."""

    @patch("theact.web.commands.render_result")
    def test_default_count_renders_last_five(self, mock_render, tmp_path):
        entries = [_entry("player", f"Message {i}", turn=i) for i in range(1, 11)]
        game = _make_game(tmp_path, conversation=entries)
        chat_area = MagicMock()

        cmd_conversation_web(chat_area, game, [])

        mock_render.assert_called_once()
        result = mock_render.call_args[0][1]
        assert result.success
        # Should contain last 5 entries
        assert "Message 6" in result.message
        assert "Message 10" in result.message
        assert "Message 5" not in result.message

    @patch("theact.web.commands.render_result")
    def test_invalid_arg_renders_error(self, mock_render, tmp_path):
        game = _make_game(tmp_path)
        chat_area = MagicMock()

        cmd_conversation_web(chat_area, game, ["abc"])

        mock_render.assert_called_once()
        result = mock_render.call_args[0][1]
        assert not result.success

    @patch("theact.web.commands.render_result")
    def test_empty_conversation(self, mock_render, tmp_path):
        game = _make_game(tmp_path, conversation=[])
        chat_area = MagicMock()

        cmd_conversation_web(chat_area, game, [])

        result = mock_render.call_args[0][1]
        assert "No conversation yet." in result.message

    @patch("theact.web.commands.render_result")
    def test_narrator_entry_truncated_at_200(self, mock_render, tmp_path):
        long_text = "A" * 300
        entries = [_entry("narrator", long_text)]
        game = _make_game(tmp_path, conversation=entries)
        chat_area = MagicMock()

        cmd_conversation_web(chat_area, game, [])

        result = mock_render.call_args[0][1]
        assert "..." in result.message
        assert "A" * 200 in result.message
        assert "A" * 201 not in result.message

    @patch("theact.web.commands.render_result")
    def test_player_entry_uses_player_name(self, mock_render, tmp_path):
        entries = [_entry("player", "I look around")]
        game = _make_game(tmp_path, conversation=entries)
        chat_area = MagicMock()

        cmd_conversation_web(chat_area, game, [])

        result = mock_render.call_args[0][1]
        assert "Alex: I look around" in result.message


# ===========================================================================
# cmd_help_web
# ===========================================================================


class TestCmdHelpWeb:
    """Tests for cmd_help_web(chat_area)."""

    @patch("theact.web.commands.render_result")
    def test_help_renders_result(self, mock_render):
        chat_area = MagicMock()
        cmd_help_web(chat_area)

        mock_render.assert_called_once()
        result = mock_render.call_args[0][1]
        assert result.success
        assert result.rows  # Should have tabular data

    @patch("theact.web.commands.render_result")
    def test_help_mentions_all_commands(self, mock_render):
        chat_area = MagicMock()
        cmd_help_web(chat_area)

        result = mock_render.call_args[0][1]
        commands = [row.get("command", "") for row in result.rows]
        for cmd in [
            "/help",
            "/quit",
            "/undo",
            "/history",
            "/save",
            "/status",
            "/memory",
            "/think",
            "/retry",
            "/conversation",
            "/save-as",
        ]:
            assert cmd in commands, f"Missing {cmd}"


# ===========================================================================
# cmd_status_web
# ===========================================================================


class TestCmdStatusWeb:
    """Tests for cmd_status_web(chat_area, game)."""

    @patch("theact.web.commands.render_result")
    def test_status_shows_chapter_and_turn(self, mock_render, tmp_path):
        game = _make_game(tmp_path)
        chat_area = MagicMock()

        cmd_status_web(chat_area, game)

        result = mock_render.call_args[0][1]
        assert "The Arrival" in result.message
        assert "Turn: 3" in result.message

    @patch("theact.web.commands.render_result")
    def test_status_shows_beats_count(self, mock_render, tmp_path):
        game = _make_game(tmp_path)
        chat_area = MagicMock()

        cmd_status_web(chat_area, game)

        result = mock_render.call_args[0][1]
        assert "Beats: 1/3" in result.message


# ===========================================================================
# cmd_save_web
# ===========================================================================


class TestCmdSaveWeb:
    """Tests for cmd_save_web(chat_area, game)."""

    @patch("theact.web.commands.render_result")
    def test_save_shows_all_info(self, mock_render, tmp_path):
        game = _make_game(tmp_path)
        chat_area = MagicMock()

        cmd_save_web(chat_area, game)

        result = mock_render.call_args[0][1]
        assert f"Save: {game.save_path.name}" in result.message
        assert "Game: Test Game" in result.message
        assert "Player: Alex" in result.message


# ===========================================================================
# cmd_history_web
# ===========================================================================


class TestCmdHistoryWeb:
    """Tests for cmd_history_web(chat_area, game)."""

    @patch("theact.web.commands.render_result")
    @patch("theact.commands.logic.git_save.get_history")
    def test_history_empty(self, mock_get_history, mock_render, tmp_path):
        mock_get_history.return_value = []
        game = _make_game(tmp_path)
        chat_area = MagicMock()

        cmd_history_web(chat_area, game)

        result = mock_render.call_args[0][1]
        assert "No turn history yet." in result.message

    @patch("theact.web.commands.render_result")
    @patch("theact.commands.logic.git_save.get_history")
    def test_history_with_entries(self, mock_get_history, mock_render, tmp_path):
        entry1 = MagicMock(
            turn=1, message="Player arrived", timestamp="2026-01-01 10:00"
        )
        entry2 = MagicMock(
            turn=2, message="Player explored", timestamp="2026-01-01 10:05"
        )
        mock_get_history.return_value = [entry1, entry2]

        game = _make_game(tmp_path)
        chat_area = MagicMock()

        cmd_history_web(chat_area, game)

        result = mock_render.call_args[0][1]
        assert result.rows
        assert any("Player arrived" in str(r.values()) for r in result.rows)


# ===========================================================================
# cmd_memory_web
# ===========================================================================


def _make_game_with_memories(
    tmp_path: Path,
    memories: dict | None = None,
) -> LoadedGame:
    """Build a LoadedGame with multiple characters and optional memories."""
    save_path = tmp_path / "saves" / "test-save"
    save_path.mkdir(parents=True, exist_ok=True)
    return LoadedGame(
        meta=GameMeta(
            id="test-game",
            title="Test Game",
            description="A test",
            characters=["elena", "marcus"],
            chapters=["01-arrival"],
        ),
        world=World(setting="Forest", tone="Grim", rules="No magic"),
        characters={
            "elena": Character(
                name="Elena",
                role="Healer",
                personality="Calm",
                secret="Immune",
                relationships={"brother": "Protective"},
            ),
            "marcus": Character(
                name="Marcus",
                role="Guard",
                personality="Stern",
                secret="None",
                relationships={"elena": "Ally"},
            ),
        },
        chapters={
            "01-arrival": Chapter(
                id="01-arrival",
                title="The Arrival",
                summary="Arrive at village",
                beats=["Approach", "Challenge", "Entry"],
                completion="Entered village",
                characters=["elena", "marcus"],
                next=None,
            )
        },
        state=GameState(
            player_name="Alex",
            current_chapter="01-arrival",
            turn=3,
            beats_hit=["Approach"],
            flags={},
            chapter_history=[],
        ),
        conversation=[],
        memories=memories or {},
        chapter_summaries=[],
        save_path=save_path,
    )


class TestCmdMemoryWeb:
    """Tests for cmd_memory_web(chat_area, game, args)."""

    @patch("theact.web.commands.render_result")
    def test_memory_no_args_lists_characters(self, mock_render, tmp_path):
        game = _make_game_with_memories(tmp_path)
        chat_area = MagicMock()

        cmd_memory_web(chat_area, game, [])

        result = mock_render.call_args[0][1]
        assert "Elena" in result.message
        assert "Marcus" in result.message

    @patch("theact.web.commands.render_result")
    def test_memory_match_shows_summary(self, mock_render, tmp_path):
        memories = {
            "elena": CharacterMemory(
                character="Elena",
                summary="Met the player at dawn",
                key_facts=["Trusts the player", "Knows about the cave"],
            )
        }
        game = _make_game_with_memories(tmp_path, memories=memories)
        chat_area = MagicMock()

        cmd_memory_web(chat_area, game, ["elena"])

        result = mock_render.call_args[0][1]
        assert "Met the player at dawn" in result.message

    @patch("theact.web.commands.render_result")
    def test_memory_unknown_character(self, mock_render, tmp_path):
        game = _make_game_with_memories(tmp_path)
        chat_area = MagicMock()

        cmd_memory_web(chat_area, game, ["zephyr"])

        result = mock_render.call_args[0][1]
        assert "Unknown character" in result.message


# ===========================================================================
# cmd_save_as_web
# ===========================================================================


class TestCmdSaveAsWeb:
    """Tests for cmd_save_as_web(game, args)."""

    @patch("theact.web.commands.ui.notify")
    def test_save_as_no_args(self, mock_notify, tmp_path):
        game = _make_game(tmp_path)

        cmd_save_as_web(game, [])

        mock_notify.assert_called_once()
        assert mock_notify.call_args[1]["type"] == "warning"

    @patch("theact.web.commands.ui.notify")
    @patch("theact.commands.logic.git_save.save_as")
    def test_save_as_success(self, mock_save_as, mock_notify, tmp_path):
        game = _make_game(tmp_path)
        new_path = tmp_path / "saves" / "my-fork"
        mock_save_as.return_value = new_path

        cmd_save_as_web(game, ["my-fork"])

        mock_save_as.assert_called_once_with(game.save_path, "my-fork")
        mock_notify.assert_called_once()
        assert "my-fork" in mock_notify.call_args[0][0]
        assert mock_notify.call_args[1]["type"] == "positive"

    @patch("theact.web.commands.ui.notify")
    @patch("theact.commands.logic.git_save.save_as")
    def test_save_as_exists(self, mock_save_as, mock_notify, tmp_path):
        game = _make_game(tmp_path)
        mock_save_as.side_effect = FileExistsError("already exists")

        cmd_save_as_web(game, ["taken-name"])

        mock_notify.assert_called_once()
        assert mock_notify.call_args[1]["type"] == "warning"

    @patch("theact.web.commands.ui.notify")
    @patch("theact.commands.logic.git_save.save_as")
    def test_save_as_not_found(self, mock_save_as, mock_notify, tmp_path):
        game = _make_game(tmp_path)
        mock_save_as.side_effect = FileNotFoundError("source not found")

        cmd_save_as_web(game, ["new-save"])

        mock_notify.assert_called_once()
        assert mock_notify.call_args[1]["type"] == "warning"

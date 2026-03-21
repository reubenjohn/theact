"""Tests for theact.web.commands — slash command handlers."""

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
    COMMANDS_HELP,
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
# cmd_undo_web
# ===========================================================================


class TestCmdUndoWeb:
    """Tests for cmd_undo_web(game, args)."""

    @patch("theact.web.commands.load_save")
    @patch("theact.web.commands.git_save.undo")
    def test_default_steps_is_one(self, mock_undo, mock_load_save, tmp_path):
        game = _make_game(tmp_path)
        reloaded = _make_game(tmp_path)
        mock_undo.return_value = 2
        mock_load_save.return_value = reloaded

        result_game, msg = cmd_undo_web(game, [])

        mock_undo.assert_called_once_with(game.save_path, 1)
        assert result_game is reloaded
        assert "1 turn(s)" in msg
        assert "turn 2" in msg

    @patch("theact.web.commands.load_save")
    @patch("theact.web.commands.git_save.undo")
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
        assert "Usage:" in msg
        assert "positive integer" in msg

    def test_zero_arg_returns_error(self, tmp_path):
        game = _make_game(tmp_path)
        result_game, msg = cmd_undo_web(game, ["0"])

        assert result_game is None
        assert "Usage:" in msg

    def test_negative_arg_returns_error(self, tmp_path):
        game = _make_game(tmp_path)
        result_game, msg = cmd_undo_web(game, ["-1"])

        assert result_game is None
        assert "Usage:" in msg

    @patch(
        "theact.web.commands.git_save.undo",
        side_effect=ValueError("Not enough history"),
    )
    def test_git_undo_raises_valueerror(self, mock_undo, tmp_path):
        game = _make_game(tmp_path)
        result_game, msg = cmd_undo_web(game, [])

        assert result_game is None
        assert "Cannot undo:" in msg
        assert "Not enough history" in msg

    @patch("theact.web.commands.load_save")
    @patch("theact.web.commands.git_save.undo")
    def test_success_returns_reloaded_game(self, mock_undo, mock_load_save, tmp_path):
        game = _make_game(tmp_path)
        reloaded = _make_game(tmp_path)
        mock_undo.return_value = 1
        mock_load_save.return_value = reloaded

        result_game, _msg = cmd_undo_web(game, [])

        assert result_game is reloaded
        assert result_game is not game

    @patch("theact.web.commands.load_save")
    @patch("theact.web.commands.git_save.undo")
    def test_success_calls_load_save_correctly(
        self, mock_undo, mock_load_save, tmp_path
    ):
        game = _make_game(tmp_path)
        mock_undo.return_value = 1
        mock_load_save.return_value = _make_game(tmp_path)

        cmd_undo_web(game, [])

        mock_load_save.assert_called_once_with(
            game.save_path.name, game.save_path.parent
        )

    @patch("theact.web.commands.load_save")
    @patch("theact.web.commands.git_save.undo")
    def test_multiple_args_uses_first(self, mock_undo, mock_load_save, tmp_path):
        """Only the first argument is parsed; extras are ignored."""
        game = _make_game(tmp_path)
        mock_undo.return_value = 0
        mock_load_save.return_value = _make_game(tmp_path)

        cmd_undo_web(game, ["2", "ignored", "also-ignored"])

        mock_undo.assert_called_once_with(game.save_path, 2)

    @patch("theact.web.commands.load_save")
    @patch("theact.web.commands.git_save.undo")
    def test_large_step_value(self, mock_undo, mock_load_save, tmp_path):
        """Very large step values are passed through to git_save.undo."""
        game = _make_game(tmp_path)
        mock_undo.return_value = 0
        mock_load_save.return_value = _make_game(tmp_path)

        result_game, msg = cmd_undo_web(game, ["9999"])

        mock_undo.assert_called_once_with(game.save_path, 9999)
        assert "9999 turn(s)" in msg

    def test_float_arg_returns_error(self, tmp_path):
        """A float like '1.5' is not a valid integer."""
        game = _make_game(tmp_path)
        result_game, msg = cmd_undo_web(game, ["1.5"])

        assert result_game is None
        assert "Usage:" in msg


# ===========================================================================
# cmd_conversation_web
# ===========================================================================


class TestCmdConversationWeb:
    """Tests for cmd_conversation_web(chat_area, game, args)."""

    @patch("theact.web.commands.show_system_message")
    @patch("theact.web.commands.ui.notify")
    def test_default_count_is_five(self, mock_notify, mock_show, tmp_path):
        entries = [_entry("player", f"Message {i}", turn=i) for i in range(1, 11)]
        game = _make_game(tmp_path, conversation=entries)
        chat_area = MagicMock()

        cmd_conversation_web(chat_area, game, [])

        mock_show.assert_called_once()
        output = mock_show.call_args[0][1]
        # Should contain last 5 entries (messages 6-10)
        assert "Message 6" in output
        assert "Message 10" in output
        # Should NOT contain earlier entries
        assert "Message 5" not in output
        mock_notify.assert_not_called()

    @patch("theact.web.commands.show_system_message")
    @patch("theact.web.commands.ui.notify")
    def test_custom_count(self, mock_notify, mock_show, tmp_path):
        entries = [_entry("player", f"Msg {i}", turn=i) for i in range(1, 11)]
        game = _make_game(tmp_path, conversation=entries)
        chat_area = MagicMock()

        cmd_conversation_web(chat_area, game, ["3"])

        output = mock_show.call_args[0][1]
        # Last 3: Msg 8, Msg 9, Msg 10
        assert "Msg 8" in output
        assert "Msg 10" in output
        assert "Msg 7" not in output

    @patch("theact.web.commands.show_system_message")
    @patch("theact.web.commands.ui.notify")
    def test_invalid_arg_calls_notify(self, mock_notify, mock_show, tmp_path):
        game = _make_game(tmp_path)
        chat_area = MagicMock()

        cmd_conversation_web(chat_area, game, ["abc"])

        mock_notify.assert_called_once()
        call_args = mock_notify.call_args
        assert "positive integer" in call_args[0][0]
        assert call_args[1]["type"] == "warning"
        mock_show.assert_not_called()

    @patch("theact.web.commands.show_system_message")
    @patch("theact.web.commands.ui.notify")
    def test_zero_arg_calls_notify(self, mock_notify, mock_show, tmp_path):
        game = _make_game(tmp_path)
        chat_area = MagicMock()

        cmd_conversation_web(chat_area, game, ["0"])

        mock_notify.assert_called_once()
        assert "positive integer" in mock_notify.call_args[0][0]
        mock_show.assert_not_called()

    @patch("theact.web.commands.show_system_message")
    @patch("theact.web.commands.ui.notify")
    def test_negative_arg_calls_notify(self, mock_notify, mock_show, tmp_path):
        game = _make_game(tmp_path)
        chat_area = MagicMock()

        cmd_conversation_web(chat_area, game, ["-1"])

        mock_notify.assert_called_once()
        assert "positive integer" in mock_notify.call_args[0][0]
        mock_show.assert_not_called()

    @patch("theact.web.commands.show_system_message")
    @patch("theact.web.commands.ui.notify")
    def test_empty_conversation_shows_message(self, mock_notify, mock_show, tmp_path):
        game = _make_game(tmp_path, conversation=[])
        chat_area = MagicMock()

        cmd_conversation_web(chat_area, game, [])

        mock_show.assert_called_once()
        assert "No conversation yet." in mock_show.call_args[0][1]
        mock_notify.assert_not_called()

    @patch("theact.web.commands.show_system_message")
    @patch("theact.web.commands.ui.notify")
    def test_narrator_entry_truncated_at_200(self, mock_notify, mock_show, tmp_path):
        long_text = "A" * 300
        entries = [_entry("narrator", long_text)]
        game = _make_game(tmp_path, conversation=entries)
        chat_area = MagicMock()

        cmd_conversation_web(chat_area, game, [])

        output = mock_show.call_args[0][1]
        assert "Narrator:" in output
        assert "..." in output
        # The truncated content should be 200 chars of 'A' + '...'
        assert "A" * 200 in output
        # Full 300-char string should NOT appear
        assert "A" * 201 not in output

    @patch("theact.web.commands.show_system_message")
    @patch("theact.web.commands.ui.notify")
    def test_narrator_short_entry_not_truncated(self, mock_notify, mock_show, tmp_path):
        """Narrator entries at or under 200 chars should not have '...' appended."""
        short_text = "B" * 200
        entries = [_entry("narrator", short_text)]
        game = _make_game(tmp_path, conversation=entries)
        chat_area = MagicMock()

        cmd_conversation_web(chat_area, game, [])

        output = mock_show.call_args[0][1]
        assert "Narrator:" in output
        # Exactly 200 chars => no truncation
        assert "..." not in output

    @patch("theact.web.commands.show_system_message")
    @patch("theact.web.commands.ui.notify")
    def test_player_entry_uses_player_name(self, mock_notify, mock_show, tmp_path):
        entries = [_entry("player", "I look around")]
        game = _make_game(tmp_path, conversation=entries)
        chat_area = MagicMock()

        cmd_conversation_web(chat_area, game, [])

        output = mock_show.call_args[0][1]
        assert "Alex: I look around" in output

    @patch("theact.web.commands.show_system_message")
    @patch("theact.web.commands.ui.notify")
    def test_player_entry_not_truncated(self, mock_notify, mock_show, tmp_path):
        """Player entries are NOT truncated, even if over 200 chars."""
        long_input = "X" * 400
        entries = [_entry("player", long_input)]
        game = _make_game(tmp_path, conversation=entries)
        chat_area = MagicMock()

        cmd_conversation_web(chat_area, game, [])

        output = mock_show.call_args[0][1]
        assert "X" * 400 in output
        assert "..." not in output

    @patch("theact.web.commands.show_system_message")
    @patch("theact.web.commands.ui.notify")
    def test_character_entry_uses_name(self, mock_notify, mock_show, tmp_path):
        entries = [_entry("character", "Hello traveler", character="Elena")]
        game = _make_game(tmp_path, conversation=entries)
        chat_area = MagicMock()

        cmd_conversation_web(chat_area, game, [])

        output = mock_show.call_args[0][1]
        assert "Elena: Hello traveler" in output

    @patch("theact.web.commands.show_system_message")
    @patch("theact.web.commands.ui.notify")
    def test_character_entry_truncated_at_200(self, mock_notify, mock_show, tmp_path):
        """Character entries over 200 chars are truncated just like narrator."""
        long_text = "C" * 300
        entries = [_entry("character", long_text, character="Elena")]
        game = _make_game(tmp_path, conversation=entries)
        chat_area = MagicMock()

        cmd_conversation_web(chat_area, game, [])

        output = mock_show.call_args[0][1]
        assert "Elena:" in output
        assert "..." in output
        assert "C" * 200 in output
        assert "C" * 201 not in output

    @patch("theact.web.commands.show_system_message")
    @patch("theact.web.commands.ui.notify")
    def test_count_exceeding_entries_shows_all(self, mock_notify, mock_show, tmp_path):
        entries = [_entry("player", f"Turn {i}", turn=i) for i in range(1, 4)]
        game = _make_game(tmp_path, conversation=entries)
        chat_area = MagicMock()

        cmd_conversation_web(chat_area, game, ["100"])

        output = mock_show.call_args[0][1]
        assert "Turn 1" in output
        assert "Turn 2" in output
        assert "Turn 3" in output

    @patch("theact.web.commands.show_system_message")
    @patch("theact.web.commands.ui.notify")
    def test_character_with_none_name(self, mock_notify, mock_show, tmp_path):
        entries = [_entry("character", "Mystery voice", character=None)]
        game = _make_game(tmp_path, conversation=entries)
        chat_area = MagicMock()

        cmd_conversation_web(chat_area, game, [])

        output = mock_show.call_args[0][1]
        assert "?: Mystery voice" in output

    @patch("theact.web.commands.show_system_message")
    @patch("theact.web.commands.ui.notify")
    def test_mixed_roles_in_output(self, mock_notify, mock_show, tmp_path):
        """All three roles can appear together in a single output."""
        entries = [
            _entry("narrator", "The sun rises.", turn=1),
            _entry("player", "I step forward.", turn=1),
            _entry("character", "Watch your step!", turn=1, character="Elena"),
        ]
        game = _make_game(tmp_path, conversation=entries)
        chat_area = MagicMock()

        cmd_conversation_web(chat_area, game, [])

        output = mock_show.call_args[0][1]
        assert "Narrator: The sun rises." in output
        assert "Alex: I step forward." in output
        assert "Elena: Watch your step!" in output

    @patch("theact.web.commands.show_system_message")
    @patch("theact.web.commands.ui.notify")
    def test_output_is_html_escaped(self, mock_notify, mock_show, tmp_path):
        """Content with HTML special chars should be escaped."""
        entries = [_entry("player", "<script>alert('xss')</script>")]
        game = _make_game(tmp_path, conversation=entries)
        chat_area = MagicMock()

        cmd_conversation_web(chat_area, game, [])

        output = mock_show.call_args[0][1]
        assert "<script>" not in output
        assert "&lt;script&gt;" in output

    @patch("theact.web.commands.show_system_message")
    @patch("theact.web.commands.ui.notify")
    def test_multiple_args_uses_first(self, mock_notify, mock_show, tmp_path):
        """Only the first arg is used for count; extras are ignored."""
        entries = [_entry("player", f"Line {i}", turn=i) for i in range(1, 6)]
        game = _make_game(tmp_path, conversation=entries)
        chat_area = MagicMock()

        cmd_conversation_web(chat_area, game, ["2", "extra"])

        output = mock_show.call_args[0][1]
        assert "Line 4" in output
        assert "Line 5" in output
        assert "Line 3" not in output

    @patch("theact.web.commands.show_system_message")
    @patch("theact.web.commands.ui.notify")
    def test_float_arg_calls_notify(self, mock_notify, mock_show, tmp_path):
        """Float arguments like '2.5' are invalid."""
        game = _make_game(tmp_path)
        chat_area = MagicMock()

        cmd_conversation_web(chat_area, game, ["2.5"])

        mock_notify.assert_called_once()
        assert "positive integer" in mock_notify.call_args[0][0]
        mock_show.assert_not_called()


# ===========================================================================
# cmd_help_web
# ===========================================================================


class TestCmdHelpWeb:
    """Tests for cmd_help_web(chat_area)."""

    @patch("theact.web.commands.show_system_message")
    def test_help_calls_show_system_message(self, mock_show):
        chat_area = MagicMock()
        cmd_help_web(chat_area)

        mock_show.assert_called_once_with(chat_area, COMMANDS_HELP)

    def test_commands_help_mentions_all_commands(self):
        expected_commands = [
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
        ]
        for cmd in expected_commands:
            assert cmd in COMMANDS_HELP, f"COMMANDS_HELP is missing {cmd}"


# ===========================================================================
# cmd_status_web
# ===========================================================================


class TestCmdStatusWeb:
    """Tests for cmd_status_web(chat_area, game)."""

    @patch("theact.web.commands.show_system_message")
    def test_status_shows_chapter_and_turn(self, mock_show, tmp_path):
        game = _make_game(tmp_path)
        chat_area = MagicMock()

        cmd_status_web(chat_area, game)

        output = mock_show.call_args[0][1]
        assert "The Arrival" in output
        assert "01-arrival" in output
        assert "Turn: 3" in output

    @patch("theact.web.commands.show_system_message")
    def test_status_shows_beats_count(self, mock_show, tmp_path):
        game = _make_game(tmp_path)
        chat_area = MagicMock()

        cmd_status_web(chat_area, game)

        output = mock_show.call_args[0][1]
        # 1 beat hit out of 3 total
        assert "Beats: 1/3" in output

    @patch("theact.web.commands.show_system_message")
    def test_status_unknown_chapter_shows_not_found(self, mock_show, tmp_path):
        game = _make_game(tmp_path)
        game.state.current_chapter = "99-missing"
        chat_area = MagicMock()

        cmd_status_web(chat_area, game)

        output = mock_show.call_args[0][1]
        assert "99-missing" in output
        assert "(not found)" in output
        assert "Turn: 3" in output

    @patch("theact.web.commands.show_system_message")
    def test_status_with_flags(self, mock_show, tmp_path):
        game = _make_game(tmp_path)
        game.state.flags = {"found_key": True, "talked_to_guard": True}
        chat_area = MagicMock()

        cmd_status_web(chat_area, game)

        output = mock_show.call_args[0][1]
        assert "Flags:" in output
        assert "found_key" in output

    @patch("theact.web.commands.show_system_message")
    def test_status_without_flags(self, mock_show, tmp_path):
        game = _make_game(tmp_path)
        # flags is already {} from _make_game
        chat_area = MagicMock()

        cmd_status_web(chat_area, game)

        output = mock_show.call_args[0][1]
        assert "Flags" not in output


# ===========================================================================
# cmd_save_web
# ===========================================================================


class TestCmdSaveWeb:
    """Tests for cmd_save_web(chat_area, game)."""

    @patch("theact.web.commands.show_system_message")
    def test_save_shows_all_info(self, mock_show, tmp_path):
        game = _make_game(tmp_path)
        chat_area = MagicMock()

        cmd_save_web(chat_area, game)

        output = mock_show.call_args[0][1]
        assert f"Save: {game.save_path.name}" in output
        assert "Game: Test Game" in output
        assert "Player: Alex" in output
        assert f"Path: {game.save_path}" in output


# ===========================================================================
# cmd_history_web
# ===========================================================================


class TestCmdHistoryWeb:
    """Tests for cmd_history_web(chat_area, game)."""

    @patch("theact.web.commands.show_system_message")
    @patch("theact.web.commands.git_save.get_history")
    def test_history_empty(self, mock_get_history, mock_show, tmp_path):
        mock_get_history.return_value = []
        game = _make_game(tmp_path)
        chat_area = MagicMock()

        cmd_history_web(chat_area, game)

        output = mock_show.call_args[0][1]
        assert "No turn history yet." in output

    @patch("theact.web.commands.show_system_message")
    @patch("theact.web.commands.git_save.get_history")
    def test_history_with_entries(self, mock_get_history, mock_show, tmp_path):
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

        output = mock_show.call_args[0][1]
        assert "<table" in output
        assert "Player arrived" in output
        assert "Player explored" in output
        # Turn numbers should appear in table cells
        assert ">1<" in output
        assert ">2<" in output


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

    @patch("theact.web.commands.show_system_message")
    def test_memory_no_args_lists_characters(self, mock_show, tmp_path):
        game = _make_game_with_memories(tmp_path)
        chat_area = MagicMock()

        cmd_memory_web(chat_area, game, [])

        output = mock_show.call_args[0][1]
        assert "Elena" in output
        assert "Marcus" in output

    @patch("theact.web.commands.show_system_message")
    def test_memory_no_args_shows_memory_marker(self, mock_show, tmp_path):
        memories = {
            "elena": CharacterMemory(
                character="Elena", summary="Met the player", key_facts=["Fact 1"]
            )
        }
        game = _make_game_with_memories(tmp_path, memories=memories)
        chat_area = MagicMock()

        cmd_memory_web(chat_area, game, [])

        output = mock_show.call_args[0][1]
        assert "(has memory)" in output

    @patch("theact.web.commands.show_system_message")
    def test_memory_match_shows_summary(self, mock_show, tmp_path):
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

        output = mock_show.call_args[0][1]
        assert "Elena -- Memory" in output
        assert "Met the player at dawn" in output
        assert "Trusts the player" in output
        assert "Knows about the cave" in output

    @patch("theact.web.commands.show_system_message")
    def test_memory_match_no_memory(self, mock_show, tmp_path):
        game = _make_game_with_memories(tmp_path)
        chat_area = MagicMock()

        cmd_memory_web(chat_area, game, ["marcus"])

        output = mock_show.call_args[0][1]
        assert "Marcus has no memories yet" in output

    @patch("theact.web.commands.show_system_message")
    def test_memory_unknown_character(self, mock_show, tmp_path):
        game = _make_game_with_memories(tmp_path)
        chat_area = MagicMock()

        cmd_memory_web(chat_area, game, ["zephyr"])

        output = mock_show.call_args[0][1]
        assert "Unknown character" in output

    @patch("theact.web.commands.show_system_message")
    def test_memory_fuzzy_match_partial(self, mock_show, tmp_path):
        memories = {
            "elena": CharacterMemory(
                character="Elena",
                summary="Healed a wound",
                key_facts=["Is tired"],
            )
        }
        game = _make_game_with_memories(tmp_path, memories=memories)
        chat_area = MagicMock()

        cmd_memory_web(chat_area, game, ["ele"])

        output = mock_show.call_args[0][1]
        assert "Elena -- Memory" in output
        assert "Healed a wound" in output


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
        assert "Usage:" in mock_notify.call_args[0][0]
        assert mock_notify.call_args[1]["type"] == "warning"

    @patch("theact.web.commands.ui.notify")
    @patch("theact.web.commands.git_save.save_as")
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
    @patch("theact.web.commands.git_save.save_as")
    def test_save_as_exists(self, mock_save_as, mock_notify, tmp_path):
        game = _make_game(tmp_path)
        mock_save_as.side_effect = FileExistsError("already exists")

        cmd_save_as_web(game, ["taken-name"])

        mock_notify.assert_called_once()
        assert "already exists" in mock_notify.call_args[0][0]
        assert mock_notify.call_args[1]["type"] == "negative"

    @patch("theact.web.commands.ui.notify")
    @patch("theact.web.commands.git_save.save_as")
    def test_save_as_not_found(self, mock_save_as, mock_notify, tmp_path):
        game = _make_game(tmp_path)
        mock_save_as.side_effect = FileNotFoundError("source not found")

        cmd_save_as_web(game, ["new-save"])

        mock_notify.assert_called_once()
        assert "Cannot fork" in mock_notify.call_args[0][0]
        assert mock_notify.call_args[1]["type"] == "negative"

"""Tests for the save manager."""

from pathlib import Path

import pytest

from theact.io.save_manager import (
    append_conversation,
    create_save,
    list_games,
    list_saves,
    load_save,
    save_memory,
    save_state,
    save_summaries,
)
from theact.models import (
    ChapterSummary,
    CharacterMemory,
    ConversationEntry,
    GameState,
)


class TestListGames:
    def test_lists_available_games(self, games_dir: Path):
        games = list_games(games_dir)
        assert len(games) == 1
        assert games[0].id == "lost-island"

    def test_empty_dir(self, tmp_path: Path):
        empty = tmp_path / "empty_games"
        empty.mkdir()
        assert list_games(empty) == []

    def test_missing_dir(self, tmp_path: Path):
        assert list_games(tmp_path / "nonexistent") == []


class TestCreateSave:
    def test_creates_correct_structure(self, games_dir: Path, saves_dir: Path):
        save_path = create_save(
            "lost-island",
            "test-save-001",
            "Player1",
            games_dir=games_dir,
            saves_dir=saves_dir,
        )
        assert save_path.exists()
        assert (save_path / "game.yaml").exists()
        assert (save_path / "world.yaml").exists()
        assert (save_path / "state.yaml").exists()
        assert (save_path / "conversation.yaml").exists()
        assert (save_path / "summaries.yaml").exists()
        assert (save_path / "memory").is_dir()
        assert (save_path / "characters" / "maya.yaml").exists()
        assert (save_path / "characters" / "joaquin.yaml").exists()
        assert (save_path / "chapters" / "01-the-crash.yaml").exists()
        assert (save_path / ".git").is_dir()

    def test_initial_state(self, games_dir: Path, saves_dir: Path):
        save_path = create_save(
            "lost-island",
            "test-save-002",
            "TestPlayer",
            games_dir=games_dir,
            saves_dir=saves_dir,
        )
        from theact.io.yaml_io import load_yaml

        state = load_yaml(save_path / "state.yaml", GameState)
        assert state.player_name == "TestPlayer"
        assert state.turn == 0
        assert state.current_chapter == "01-the-crash"
        assert state.beats_hit == []
        assert state.flags == {}

    def test_rejects_duplicate_save(self, games_dir: Path, saves_dir: Path):
        create_save(
            "lost-island",
            "dup-save",
            "P1",
            games_dir=games_dir,
            saves_dir=saves_dir,
        )
        with pytest.raises(FileExistsError):
            create_save(
                "lost-island",
                "dup-save",
                "P2",
                games_dir=games_dir,
                saves_dir=saves_dir,
            )

    def test_rejects_missing_game(self, games_dir: Path, saves_dir: Path):
        with pytest.raises(FileNotFoundError):
            create_save(
                "nonexistent-game",
                "s1",
                "P",
                games_dir=games_dir,
                saves_dir=saves_dir,
            )


class TestLoadSave:
    def test_loads_complete_game(self, games_dir: Path, saves_dir: Path):
        create_save(
            "lost-island",
            "load-test",
            "Hero",
            games_dir=games_dir,
            saves_dir=saves_dir,
        )
        game = load_save("load-test", saves_dir=saves_dir)
        assert game.meta.id == "lost-island"
        assert game.world.setting is not None
        assert "maya" in game.characters
        assert "joaquin" in game.characters
        assert "01-the-crash" in game.chapters
        assert game.state.player_name == "Hero"
        assert game.conversation == []
        assert game.memories == {}
        assert game.chapter_summaries == []
        assert game.save_path.is_absolute()

    def test_missing_save_raises(self, saves_dir: Path):
        with pytest.raises(FileNotFoundError):
            load_save("no-such-save", saves_dir=saves_dir)


class TestListSaves:
    def test_lists_existing_saves(self, games_dir: Path, saves_dir: Path):
        create_save(
            "lost-island",
            "s1",
            "P1",
            games_dir=games_dir,
            saves_dir=saves_dir,
        )
        create_save(
            "lost-island",
            "s2",
            "P2",
            games_dir=games_dir,
            saves_dir=saves_dir,
        )
        saves = list_saves(saves_dir)
        assert len(saves) == 2
        ids = {s["id"] for s in saves}
        assert "s1" in ids
        assert "s2" in ids

    def test_empty_saves(self, saves_dir: Path):
        assert list_saves(saves_dir) == []


class TestSaveState:
    def test_updates_state(self, games_dir: Path, saves_dir: Path):
        save_path = create_save(
            "lost-island",
            "state-test",
            "P",
            games_dir=games_dir,
            saves_dir=saves_dir,
        )
        new_state = GameState(
            player_name="P",
            current_chapter="01-the-crash",
            turn=5,
            beats_hit=["Player wakes on the beach"],
            flags={"found_lighter": "true"},
            chapter_history=[],
            rolling_summary="Player woke up on a beach.",
        )
        save_state(save_path, new_state)
        game = load_save("state-test", saves_dir=saves_dir)
        assert game.state.turn == 5
        assert game.state.beats_hit == ["Player wakes on the beach"]
        assert game.state.flags == {"found_lighter": "true"}


class TestAppendConversation:
    def test_appends_entries(self, games_dir: Path, saves_dir: Path):
        save_path = create_save(
            "lost-island",
            "conv-test",
            "P",
            games_dir=games_dir,
            saves_dir=saves_dir,
        )
        e1 = ConversationEntry(turn=1, role="narrator", content="You wake up.")
        e2 = ConversationEntry(turn=1, role="player", content="I look around.")
        append_conversation(save_path, e1)
        append_conversation(save_path, e2)
        game = load_save("conv-test", saves_dir=saves_dir)
        assert len(game.conversation) == 2
        assert game.conversation[0].role == "narrator"
        assert game.conversation[1].role == "player"


class TestSaveMemory:
    def test_saves_and_loads_memory(self, games_dir: Path, saves_dir: Path):
        save_path = create_save(
            "lost-island",
            "mem-test",
            "P",
            games_dir=games_dir,
            saves_dir=saves_dir,
        )
        mem = CharacterMemory(
            character="Maya Chen",
            summary="Met the player on the beach.",
            key_facts=["Player found a lighter"],
        )
        save_memory(save_path, mem)
        game = load_save("mem-test", saves_dir=saves_dir)
        assert "maya" in game.memories
        assert game.memories["maya"].character == "Maya Chen"


class TestSaveSummaries:
    def test_saves_and_loads_summaries(self, games_dir: Path, saves_dir: Path):
        save_path = create_save(
            "lost-island",
            "sum-test",
            "P",
            games_dir=games_dir,
            saves_dir=saves_dir,
        )
        summaries = [
            ChapterSummary(
                chapter_id="01-the-crash",
                title="The Crash",
                summary="Player survived the crash and met Maya.",
            )
        ]
        save_summaries(save_path, summaries)
        game = load_save("sum-test", saves_dir=saves_dir)
        assert len(game.chapter_summaries) == 1
        assert game.chapter_summaries[0].chapter_id == "01-the-crash"


class TestRoundTrip:
    """Test create -> modify -> load sees modifications."""

    def test_full_round_trip(self, games_dir: Path, saves_dir: Path):
        save_path = create_save(
            "lost-island",
            "rt-test",
            "Hero",
            games_dir=games_dir,
            saves_dir=saves_dir,
        )

        # Append conversation
        append_conversation(
            save_path,
            ConversationEntry(turn=1, role="narrator", content="You wake up."),
        )
        append_conversation(
            save_path,
            ConversationEntry(turn=1, role="player", content="I stand."),
        )

        # Update state
        save_state(
            save_path,
            GameState(
                player_name="Hero",
                current_chapter="01-the-crash",
                turn=1,
                beats_hit=["Player wakes on the beach"],
                flags={},
                chapter_history=[],
            ),
        )

        # Save memory
        save_memory(
            save_path,
            CharacterMemory(
                character="Maya Chen",
                summary="Met the player.",
                key_facts=["Player seems disoriented"],
            ),
        )

        # Reload and verify
        game = load_save("rt-test", saves_dir=saves_dir)
        assert game.state.turn == 1
        assert len(game.conversation) == 2
        assert "maya" in game.memories
        assert game.memories["maya"].key_facts == ["Player seems disoriented"]

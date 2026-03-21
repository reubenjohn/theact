"""Tests for save versioning: save_as, peek_at_turn, diff_turns."""

import shutil
from pathlib import Path

import pytest
from git import Repo

from theact.io.save_manager import (
    append_conversation,
    create_save,
    list_saves,
    load_save,
    save_memory,
    save_state,
)
from theact.models import (
    CharacterMemory,
    ConversationEntry,
    GameState,
)
from theact.versioning.git_save import (
    commit_turn,
    diff_turns,
    get_history,
    get_turn_count,
    peek_at_turn,
    save_as,
    undo,
)

GAMES_DIR = Path(__file__).parent.parent / "games"


@pytest.fixture
def games_dir(tmp_path: Path) -> Path:
    dest = tmp_path / "games"
    shutil.copytree(GAMES_DIR, dest)
    return dest


@pytest.fixture
def saves_dir(tmp_path: Path) -> Path:
    d = tmp_path / "saves"
    d.mkdir()
    return d


@pytest.fixture
def save_path(games_dir: Path, saves_dir: Path) -> Path:
    """Create a save and return its path."""
    return create_save(
        "lost-island",
        "versioning-test",
        "Tester",
        games_dir=games_dir,
        saves_dir=saves_dir,
    )


def _make_turns(save_path: Path, n: int) -> None:
    """Helper to create n turns of fake data with state, conversation, and memory."""
    for i in range(1, n + 1):
        append_conversation(
            save_path,
            ConversationEntry(
                turn=i, role="narrator", content=f"Narration for turn {i}."
            ),
        )
        append_conversation(
            save_path,
            ConversationEntry(
                turn=i, role="player", content=f"Player action in turn {i}."
            ),
        )
        save_state(
            save_path,
            GameState(
                player_name="Tester",
                current_chapter="01-the-crash",
                turn=i,
                beats_hit=[f"beat-{j}" for j in range(1, i + 1)],
                flags={"last_turn": str(i)},
                chapter_history=[],
            ),
        )
        if i >= 2:
            save_memory(
                save_path,
                CharacterMemory(
                    character="Maya Chen",
                    summary=f"Memory after turn {i}.",
                    key_facts=[f"Fact from turn {i}"],
                ),
            )
        commit_turn(save_path, i, f"Turn {i}")


class TestSaveAs:
    def test_creates_copy(self, save_path: Path, saves_dir: Path):
        _make_turns(save_path, 3)
        forked = save_as(save_path, "forked-save", saves_dir=saves_dir)
        assert forked.exists()
        assert (forked / ".git").is_dir()
        assert (forked / "state.yaml").exists()
        assert (forked / "game.yaml").exists()

    def test_preserves_history(self, save_path: Path, saves_dir: Path):
        _make_turns(save_path, 3)
        forked = save_as(save_path, "forked-save", saves_dir=saves_dir)
        original_history = get_history(save_path)
        forked_history = get_history(forked)
        assert len(original_history) == len(forked_history)
        for orig, fork in zip(original_history, forked_history):
            assert orig.turn == fork.turn
            assert orig.commit_hash == fork.commit_hash

    def test_independent_after_fork(self, save_path: Path, saves_dir: Path):
        _make_turns(save_path, 3)
        forked = save_as(save_path, "forked-save", saves_dir=saves_dir)

        # Make a change to the fork
        append_conversation(
            forked,
            ConversationEntry(turn=4, role="narrator", content="Forked narration."),
        )
        save_state(
            forked,
            GameState(
                player_name="Tester",
                current_chapter="01-the-crash",
                turn=4,
                beats_hit=[],
                flags={"last_turn": "4"},
                chapter_history=[],
            ),
        )
        commit_turn(forked, 4, "Turn 4 on fork")

        # Original should still have only 3 turns
        assert get_turn_count(save_path) == 3
        assert get_turn_count(forked) == 4

    def test_undo_on_fork_preserves_original(self, save_path: Path, saves_dir: Path):
        _make_turns(save_path, 5)
        forked = save_as(save_path, "forked-save", saves_dir=saves_dir)

        # Undo on fork
        undo(forked, 3)

        # Original is intact
        assert get_turn_count(save_path) == 5
        assert get_turn_count(forked) == 2

    def test_duplicate_name_raises(self, save_path: Path, saves_dir: Path):
        _make_turns(save_path, 1)
        save_as(save_path, "first-fork", saves_dir=saves_dir)
        with pytest.raises(FileExistsError):
            save_as(save_path, "first-fork", saves_dir=saves_dir)

    def test_missing_source_raises(self, saves_dir: Path):
        fake_path = saves_dir / "nonexistent"
        with pytest.raises(FileNotFoundError):
            save_as(fake_path, "new-save", saves_dir=saves_dir)

    def test_list_saves_includes_fork(self, save_path: Path, saves_dir: Path):
        _make_turns(save_path, 2)
        save_as(save_path, "forked-save", saves_dir=saves_dir)
        saves = list_saves(saves_dir=saves_dir)
        save_ids = [s["id"] for s in saves]
        assert "versioning-test" in save_ids
        assert "forked-save" in save_ids


class TestPeekAtTurn:
    def test_peek_at_turn_zero(self, save_path: Path):
        _make_turns(save_path, 3)
        snapshot = peek_at_turn(save_path, 0)
        assert "state.yaml" in snapshot
        # Turn 0 state should have turn: 0
        assert "turn: 0" in snapshot["state.yaml"]

    def test_peek_at_specific_turn(self, save_path: Path):
        _make_turns(save_path, 5)
        snapshot = peek_at_turn(save_path, 3)
        assert "state.yaml" in snapshot
        assert "turn: 3" in snapshot["state.yaml"]
        assert "conversation.yaml" in snapshot

    def test_peek_does_not_modify_head(self, save_path: Path):
        _make_turns(save_path, 5)

        # Record current HEAD
        repo = Repo(save_path)
        head_before = repo.head.commit.hexsha

        # Peek at an earlier turn
        peek_at_turn(save_path, 2)

        # HEAD should not have moved
        head_after = repo.head.commit.hexsha
        assert head_before == head_after

        # Working directory should still reflect turn 5
        game = load_save("versioning-test", saves_dir=save_path.parent)
        assert game.state.turn == 5

    def test_peek_includes_memory_files(self, save_path: Path):
        _make_turns(save_path, 3)
        snapshot = peek_at_turn(save_path, 3)
        # Memory files should be present (created from turn 2 onwards)
        memory_keys = [k for k in snapshot if k.startswith("memory/")]
        assert len(memory_keys) > 0
        assert any("maya" in k for k in memory_keys)

    def test_peek_invalid_turn_raises(self, save_path: Path):
        _make_turns(save_path, 3)
        with pytest.raises(ValueError, match="Turn 10 not found"):
            peek_at_turn(save_path, 10)

    def test_peek_returns_conversation(self, save_path: Path):
        _make_turns(save_path, 3)
        snapshot = peek_at_turn(save_path, 2)
        assert "conversation.yaml" in snapshot
        assert "turn 2" in snapshot["conversation.yaml"].lower()


class TestDiffTurns:
    def test_diff_shows_state_changes(self, save_path: Path):
        _make_turns(save_path, 5)
        diff_output = diff_turns(save_path, 2, 4)
        # Should show changes in state.yaml (turn number changed)
        assert len(diff_output) > 0
        assert "state.yaml" in diff_output

    def test_diff_from_initial(self, save_path: Path):
        _make_turns(save_path, 3)
        diff_output = diff_turns(save_path, 0, 3)
        # From initial state (turn 0) to turn 3, there should be changes
        assert len(diff_output) > 0
        assert "state.yaml" in diff_output

    def test_diff_same_turn_empty(self, save_path: Path):
        _make_turns(save_path, 3)
        diff_output = diff_turns(save_path, 2, 2)
        assert diff_output == ""

    def test_diff_invalid_turn_raises(self, save_path: Path):
        _make_turns(save_path, 3)
        with pytest.raises(ValueError, match="Turn 99 not found"):
            diff_turns(save_path, 1, 99)

"""Tests for git-based save versioning."""

import shutil
from pathlib import Path

import pytest
from git import Repo

from theact.io.save_manager import (
    append_conversation,
    create_save,
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
    get_history,
    get_turn_count,
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
        "git-test",
        "Tester",
        games_dir=games_dir,
        saves_dir=saves_dir,
    )


class TestInitRepo:
    def test_creates_git_repo(self, save_path: Path):
        assert (save_path / ".git").is_dir()

    def test_initial_commit_message(self, save_path: Path):
        repo = Repo(save_path)
        commits = list(repo.iter_commits())
        assert len(commits) == 1
        assert "New game: The Lost Island" in commits[0].message

    def test_all_files_tracked(self, save_path: Path):
        repo = Repo(save_path)
        # No untracked files
        assert repo.untracked_files == []
        # No unstaged changes
        assert not repo.is_dirty()


class TestCommitTurn:
    def test_creates_commit(self, save_path: Path):
        # Simulate a turn
        append_conversation(
            save_path,
            ConversationEntry(turn=1, role="narrator", content="You wake up."),
        )
        save_state(
            save_path,
            GameState(
                player_name="Tester",
                current_chapter="01-the-crash",
                turn=1,
                beats_hit=[],
                flags={},
                chapter_history=[],
            ),
        )

        commit_hash = commit_turn(save_path, 1, "Player wakes on beach")
        assert len(commit_hash) == 40  # Full SHA

        repo = Repo(save_path)
        assert "Turn 1: Player wakes on beach" in repo.head.commit.message

    def test_multiple_turns(self, save_path: Path):
        for i in range(1, 4):
            append_conversation(
                save_path,
                ConversationEntry(
                    turn=i, role="narrator", content=f"Turn {i} narration."
                ),
            )
            save_state(
                save_path,
                GameState(
                    player_name="Tester",
                    current_chapter="01-the-crash",
                    turn=i,
                    beats_hit=[],
                    flags={},
                    chapter_history=[],
                ),
            )
            commit_turn(save_path, i, f"Turn {i} summary")

        repo = Repo(save_path)
        commits = list(repo.iter_commits())
        assert len(commits) == 4  # initial + 3 turns


class TestUndo:
    def _make_turns(self, save_path: Path, n: int) -> None:
        """Helper to create n turns of fake data."""
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
                    beats_hit=[],
                    flags={"last_turn": str(i)},
                    chapter_history=[],
                ),
            )
            commit_turn(save_path, i, f"Turn {i}")

    def test_undo_one(self, save_path: Path):
        self._make_turns(save_path, 3)
        result_turn = undo(save_path, 1)
        assert result_turn == 2

        # Verify state reverted
        game = load_save("git-test", saves_dir=save_path.parent)
        assert game.state.turn == 2
        assert game.state.flags["last_turn"] == "2"

    def test_undo_multiple(self, save_path: Path):
        self._make_turns(save_path, 5)
        result_turn = undo(save_path, 3)
        assert result_turn == 2

        game = load_save("git-test", saves_dir=save_path.parent)
        assert game.state.turn == 2
        # Should have 4 conversation entries (2 per turn * 2 turns)
        assert len(game.conversation) == 4

    def test_undo_all_turns(self, save_path: Path):
        self._make_turns(save_path, 3)
        result_turn = undo(save_path, 3)
        assert result_turn == 0

        game = load_save("git-test", saves_dir=save_path.parent)
        assert game.state.turn == 0
        assert game.conversation == []

    def test_undo_too_many_raises(self, save_path: Path):
        self._make_turns(save_path, 2)
        with pytest.raises(ValueError, match="Cannot undo 3 steps"):
            undo(save_path, 3)

    def test_undo_zero_raises(self, save_path: Path):
        self._make_turns(save_path, 1)
        with pytest.raises(ValueError, match="at least 1"):
            undo(save_path, 0)


class TestGetHistory:
    def test_empty_history(self, save_path: Path):
        history = get_history(save_path)
        assert history == []

    def test_returns_turn_info(self, save_path: Path):
        for i in range(1, 4):
            append_conversation(
                save_path,
                ConversationEntry(turn=i, role="narrator", content=f"Turn {i}."),
            )
            save_state(
                save_path,
                GameState(
                    player_name="Tester",
                    current_chapter="01-the-crash",
                    turn=i,
                    beats_hit=[],
                    flags={},
                    chapter_history=[],
                ),
            )
            commit_turn(save_path, i, f"Turn {i} summary")

        history = get_history(save_path)
        assert len(history) == 3
        # Most recent first
        assert history[0].turn == 3
        assert history[1].turn == 2
        assert history[2].turn == 1
        # Check fields
        assert len(history[0].commit_hash) == 40
        assert "Turn 3" in history[0].message
        assert history[0].timestamp  # Non-empty


class TestGetTurnCount:
    def test_zero_turns(self, save_path: Path):
        assert get_turn_count(save_path) == 0

    def test_counts_turns(self, save_path: Path):
        for i in range(1, 6):
            append_conversation(
                save_path,
                ConversationEntry(turn=i, role="narrator", content=f"Turn {i}."),
            )
            save_state(
                save_path,
                GameState(
                    player_name="Tester",
                    current_chapter="01-the-crash",
                    turn=i,
                    beats_hit=[],
                    flags={},
                    chapter_history=[],
                ),
            )
            commit_turn(save_path, i, f"Summary {i}")

        assert get_turn_count(save_path) == 5


class TestMultiTurnIntegration:
    """Integration test: create game -> 10 turns -> undo -> verify."""

    def test_ten_turns_undo_three(self, games_dir: Path, saves_dir: Path):
        save_path = create_save(
            "lost-island",
            "integration-test",
            "Hero",
            games_dir=games_dir,
            saves_dir=saves_dir,
        )

        # Simulate 10 turns
        for i in range(1, 11):
            append_conversation(
                save_path,
                ConversationEntry(turn=i, role="narrator", content=f"Narration {i}."),
            )
            append_conversation(
                save_path,
                ConversationEntry(turn=i, role="player", content=f"Action {i}."),
            )

            if i >= 3:
                save_memory(
                    save_path,
                    CharacterMemory(
                        character="Maya Chen",
                        summary=f"Memory after turn {i}.",
                        key_facts=[f"Fact from turn {i}"],
                    ),
                )

            save_state(
                save_path,
                GameState(
                    player_name="Hero",
                    current_chapter="01-the-crash",
                    turn=i,
                    beats_hit=[f"beat-{j}" for j in range(1, i + 1)],
                    flags={"turn": str(i)},
                    chapter_history=[],
                ),
            )
            commit_turn(save_path, i, f"Turn {i}")

        # Verify 10 turns
        assert get_turn_count(save_path) == 10

        # Undo 3 turns -> should be at turn 7
        result_turn = undo(save_path, 3)
        assert result_turn == 7

        # Verify state
        game = load_save("integration-test", saves_dir=saves_dir)
        assert game.state.turn == 7
        assert game.state.flags["turn"] == "7"
        assert len(game.state.beats_hit) == 7

        # Conversation should have 14 entries (2 per turn * 7 turns)
        assert len(game.conversation) == 14

        # Memory should reflect turn 7
        assert game.memories["maya"].summary == "Memory after turn 7."

        # History should show 7 turns
        assert get_turn_count(save_path) == 7

        # Git log should have 8 commits (1 initial + 7 turns)
        repo = Repo(save_path)
        assert len(list(repo.iter_commits())) == 8

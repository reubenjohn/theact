"""Git-based save versioning: init, commit, undo, history."""

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from git import Repo


@dataclass
class TurnInfo:
    """Summary of a single turn from git history.

    Uses dataclass (not BaseModel) since this is a transient data carrier,
    never serialized to YAML.
    """

    turn: int
    commit_hash: str
    message: str
    timestamp: str


def init_repo(save_path: Path, game_title: str) -> Repo:
    """Initialize a git repo in the save directory and make the initial commit.

    The initial commit contains the game definition files and empty state/conversation.
    Commit message: 'New game: <game title>'
    """
    repo = Repo.init(save_path)

    # Configure git user for this repo (required for commits)
    with repo.config_writer() as config:
        config.set_value("user", "name", "TheAct")
        config.set_value("user", "email", "theact@local")

    # Stage all files
    repo.git.add(A=True)

    # Initial commit
    repo.index.commit(f"New game: {game_title}")

    return repo


def commit_turn(save_path: Path, turn: int, summary: str) -> str:
    """Stage all changes and commit.

    Commit message format: 'Turn <N>: <one-line summary>'
    Returns the commit hash.
    """
    repo = Repo(save_path)

    # Stage all changes
    repo.git.add(A=True)

    # Commit
    message = f"Turn {turn}: {summary}"
    commit = repo.index.commit(message)

    return commit.hexsha


def undo(save_path: Path, steps: int = 1) -> int:
    """Undo the last N turns by resetting to HEAD~N.

    Returns the turn number we've rewound to.
    Raises ValueError if steps exceeds available history (excluding initial commit).
    """
    repo = Repo(save_path)

    # Count turn commits (all commits except the initial one)
    total_commits = len(list(repo.iter_commits()))
    turn_commits = total_commits - 1  # Exclude initial "New game" commit

    if steps > turn_commits:
        raise ValueError(
            f"Cannot undo {steps} steps: only {turn_commits} turn(s) in history"
        )

    if steps < 1:
        raise ValueError("Steps must be at least 1")

    # Reset to HEAD~N
    repo.git.reset("--hard", f"HEAD~{steps}")

    # Determine what turn we're now at
    # Parse from the current HEAD commit message
    head_msg = repo.head.commit.message.strip()
    turn_match = re.match(r"Turn (\d+):", head_msg)
    if turn_match:
        return int(turn_match.group(1))
    else:
        # We're at the initial commit (no turns)
        return 0


def get_history(save_path: Path) -> list[TurnInfo]:
    """Get the full turn history from git log.

    Returns most recent first. Excludes the initial 'New game' commit.
    Parses turn number from commit message.
    """
    repo = Repo(save_path)
    history = []

    for commit in repo.iter_commits():
        msg = commit.message.strip()
        turn_match = re.match(r"Turn (\d+):", msg)
        if not turn_match:
            continue  # Skip initial commit

        ts = datetime.fromtimestamp(commit.committed_date, tz=timezone.utc)
        history.append(
            TurnInfo(
                turn=int(turn_match.group(1)),
                commit_hash=commit.hexsha,
                message=msg,
                timestamp=ts.isoformat(),
            )
        )

    return history


def get_turn_count(save_path: Path) -> int:
    """Get the number of completed turns (number of turn commits)."""
    return len(get_history(save_path))

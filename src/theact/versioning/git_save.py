"""Git-based save versioning: init, commit, undo, history, fork, peek, diff."""

import re
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from git import GitCommandError, Repo

# Regex for parsing turn number from commit messages.
# All turn commits follow the format "Turn N: <summary>".
_TURN_RE = re.compile(r"Turn (\d+):")

# Mutable state files tracked by peek/diff operations.
_STATE_FILES = ["state.yaml", "conversation.yaml", "summaries.yaml"]


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
    if steps < 1:
        raise ValueError("Steps must be at least 1")

    repo = Repo(save_path)

    # Count turn commits (all commits except the initial one)
    total_commits = len(list(repo.iter_commits()))
    turn_commits = total_commits - 1  # Exclude initial "New game" commit

    if steps > turn_commits:
        raise ValueError(
            f"Cannot undo {steps} steps: only {turn_commits} turn(s) in history"
        )

    # Reset to HEAD~N
    repo.git.reset("--hard", f"HEAD~{steps}")

    # Determine what turn we're now at from the current HEAD commit message
    head_msg = repo.head.commit.message.strip()
    turn_match = _TURN_RE.match(head_msg)
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
        turn_match = _TURN_RE.match(msg)
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


def save_as(save_path: Path, new_save_id: str, saves_dir: Path | None = None) -> Path:
    """Copy an entire save directory (including .git/ history) to a new location.

    Enables non-destructive forking: copy first, then undo on the copy.

    Args:
        save_path: Existing save directory
        new_save_id: Name for the new save directory
        saves_dir: Parent directory for saves (defaults to save_path.parent)

    Returns:
        Path to the new save directory

    Raises:
        FileExistsError: If target already exists
        FileNotFoundError: If source doesn't exist
    """
    if not save_path.exists():
        raise FileNotFoundError(f"Source save not found: {save_path}")

    parent = saves_dir or save_path.parent
    target_dir = parent / new_save_id

    if target_dir.exists():
        raise FileExistsError(f"Save already exists: {target_dir}")

    shutil.copytree(save_path, target_dir)
    return target_dir


def _resolve_turn_ref(repo: Repo, history: list[TurnInfo], turn_number: int) -> str:
    """Resolve a turn number to a git commit ref (hex SHA).

    Turn 0 = the initial commit (before any turns).
    Turn N = the commit for turn N.

    Raises ValueError if the turn number is out of range.
    """
    if turn_number == 0:
        # Find the initial commit (the oldest one, which has no Turn prefix)
        all_commits = list(repo.iter_commits())
        if not all_commits:
            raise ValueError("Repository has no commits")
        return all_commits[-1].hexsha

    # Find the matching turn in history
    for info in history:
        if info.turn == turn_number:
            return info.commit_hash

    max_turn = history[0].turn if history else 0
    raise ValueError(f"Turn {turn_number} not found. Valid range: 0-{max_turn}")


def peek_at_turn(save_path: Path, turn_number: int) -> dict[str, str]:
    """Read-only access to any historical turn's state WITHOUT modifying HEAD.

    Uses ``git show <ref>:<path>`` to read file contents at specific commits.

    Args:
        save_path: Save directory (must be git repo)
        turn_number: Turn to peek at (0 = initial state before any turns)

    Returns:
        Dict mapping filename to content for key game state files.
        Keys include: ``state.yaml``, ``conversation.yaml``, ``summaries.yaml``,
        plus ``memory/<name>.yaml`` entries.

    Raises:
        ValueError: If turn_number is out of range
    """
    repo = Repo(save_path)
    history = get_history(save_path)
    ref = _resolve_turn_ref(repo, history, turn_number)

    result: dict[str, str] = {}

    # Core state files
    for filepath in _STATE_FILES:
        try:
            content = repo.git.show(f"{ref}:{filepath}")
            result[filepath] = content
        except GitCommandError:
            pass  # File may not exist at that commit

    # Memory files: discover via ls-tree
    try:
        tree_output = repo.git.ls_tree("-r", "--name-only", ref)
        for line in tree_output.splitlines():
            if line.startswith("memory/") and line.endswith(".yaml"):
                try:
                    content = repo.git.show(f"{ref}:{line}")
                    result[line] = content
                except GitCommandError:
                    pass
    except GitCommandError:
        pass

    return result


def diff_turns(save_path: Path, turn_a: int, turn_b: int) -> str:
    """Show what changed between two turns using git diff.

    Only diffs mutable state files (state.yaml, conversation.yaml,
    summaries.yaml, memory/).

    Returns:
        Unified diff text (empty string if no differences)

    Raises:
        ValueError: If either turn is out of range
    """
    repo = Repo(save_path)
    history = get_history(save_path)
    ref_a = _resolve_turn_ref(repo, history, turn_a)
    ref_b = _resolve_turn_ref(repo, history, turn_b)

    return repo.git.diff(ref_a, ref_b, "--", *_STATE_FILES, "memory/")

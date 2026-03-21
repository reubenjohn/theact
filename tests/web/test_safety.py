"""Unit tests for save file locking (no browser needed).

Tests the SaveLock class from theact.web.safety.
Uses tmp_path fixture for isolated file system operations.

Requires the ``web`` optional dependency group (filelock).
Run with:  uv run --extra web pytest tests/web/test_safety.py -v
"""

from pathlib import Path

import pytest

from theact.web.safety import SaveLock, _HAS_FILELOCK

pytestmark = pytest.mark.skipif(
    not _HAS_FILELOCK,
    reason="filelock not installed (install with: uv sync --extra web)",
)


def test_lock_acquired(tmp_path: Path):
    """Lock acquisition succeeds on an unlocked directory."""
    lock = SaveLock(tmp_path)
    assert lock.acquire() is True
    assert lock.is_locked is True
    lock.release()


def test_lock_conflict(tmp_path: Path):
    """Second lock on the same directory fails while first is held."""
    lock1 = SaveLock(tmp_path)
    lock2 = SaveLock(tmp_path)

    assert lock1.acquire() is True
    assert lock2.acquire() is False  # Already locked by lock1

    lock1.release()

    # After release, lock2 can acquire
    assert lock2.acquire() is True
    lock2.release()


def test_lock_release(tmp_path: Path):
    """Releasing the lock clears the is_locked flag."""
    lock = SaveLock(tmp_path)
    lock.acquire()
    assert lock.is_locked is True

    lock.release()
    assert lock.is_locked is False


def test_lock_release_allows_reacquire(tmp_path: Path):
    """After release, a new lock can be acquired on the same path."""
    lock1 = SaveLock(tmp_path)
    lock1.acquire()
    lock1.release()

    lock2 = SaveLock(tmp_path)
    assert lock2.acquire() is True
    lock2.release()


def test_lock_release_without_acquire(tmp_path: Path):
    """Releasing a lock that was never acquired is a no-op."""
    lock = SaveLock(tmp_path)
    lock.release()  # Should not raise
    assert lock.is_locked is False


def test_double_release(tmp_path: Path):
    """Releasing a lock twice does not raise."""
    lock = SaveLock(tmp_path)
    lock.acquire()
    lock.release()
    lock.release()  # Should not raise
    assert lock.is_locked is False


def test_force_acquire(tmp_path: Path):
    """force_acquire breaks an existing lock and acquires."""
    lock1 = SaveLock(tmp_path)
    lock2 = SaveLock(tmp_path)

    assert lock1.acquire() is True
    assert lock2.acquire() is False

    # Force-acquire should succeed
    assert lock2.force_acquire() is True
    assert lock2.is_locked is True
    lock2.release()


def test_gitignore_created(tmp_path: Path):
    """Acquiring a lock creates/updates .gitignore to exclude .lock."""
    lock = SaveLock(tmp_path)
    lock.acquire()

    gitignore = tmp_path / ".gitignore"
    assert gitignore.exists()
    assert ".lock" in gitignore.read_text()

    lock.release()


def test_gitignore_not_duplicated(tmp_path: Path):
    """Acquiring multiple times does not duplicate .lock in .gitignore."""
    lock1 = SaveLock(tmp_path)
    lock1.acquire()
    lock1.release()

    lock2 = SaveLock(tmp_path)
    lock2.acquire()
    lock2.release()

    gitignore = tmp_path / ".gitignore"
    content = gitignore.read_text()
    # Count occurrences of ".lock" (should be exactly 1)
    assert content.count(".lock") == 1


def test_lock_file_location(tmp_path: Path):
    """Lock file is created inside the save directory."""
    lock = SaveLock(tmp_path)
    lock.acquire()

    lock_file = tmp_path / ".lock"
    assert lock_file.exists()

    lock.release()

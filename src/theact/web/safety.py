"""Multi-tab file locking for save directories.

Prevents two browser tabs from writing to the same save
simultaneously, which would corrupt the git history.

Uses the ``filelock`` package (optional web dependency).
Falls back to a no-op lock if ``filelock`` is not installed.
"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

try:
    from filelock import FileLock, Timeout

    _HAS_FILELOCK = True
except ImportError:
    _HAS_FILELOCK = False


def _ensure_gitignore_has_lock(save_path: Path) -> None:
    """Ensure the save directory's .gitignore excludes .lock files."""
    gitignore = save_path / ".gitignore"
    if gitignore.exists():
        content = gitignore.read_text()
        if ".lock" in content:
            return
    with open(gitignore, "a") as f:
        f.write("\n.lock\n")


class SaveLock:
    """Manages exclusive access to a save directory.

    Uses ``filelock.FileLock`` for OS-level locking. If filelock
    is not installed, all operations are no-ops (lock always succeeds).
    """

    def __init__(self, save_path: Path) -> None:
        self._save_path = save_path
        self._acquired = False

        if _HAS_FILELOCK:
            self._lock_path = save_path / ".lock"
            self._lock = FileLock(self._lock_path, timeout=0)
        else:
            self._lock_path = None
            self._lock = None

    def acquire(self) -> bool:
        """Try to acquire the lock. Returns True if successful."""
        if not _HAS_FILELOCK or self._lock is None:
            self._acquired = True
            return True

        try:
            self._lock.acquire(timeout=0)
            self._acquired = True
            _ensure_gitignore_has_lock(self._save_path)
            return True
        except Timeout:
            return False

    def release(self) -> None:
        """Release the lock if held."""
        if self._acquired and self._lock is not None:
            try:
                self._lock.release()
            except Exception:
                logger.debug("Lock release failed (already released?)")
            self._acquired = False
        elif self._acquired:
            self._acquired = False

    def force_acquire(self) -> bool:
        """Force-acquire the lock by releasing any existing hold first.

        This is used when the user chooses "Force Unlock" in the
        conflict dialog. Returns True if the lock was acquired.
        """
        if not _HAS_FILELOCK or self._lock is None:
            self._acquired = True
            return True

        # Break the existing lock by removing the lock file
        try:
            if self._lock_path and self._lock_path.exists():
                self._lock_path.unlink()
        except OSError:
            pass

        # Re-create the FileLock and acquire
        self._lock = FileLock(self._lock_path, timeout=0)
        return self.acquire()

    @property
    def is_locked(self) -> bool:
        """Whether this instance currently holds the lock."""
        return self._acquired

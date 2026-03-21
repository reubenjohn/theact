"""Fixtures for web UI browser tests.

These tests run against a live NiceGUI server using pytest-playwright.
Run separately from unit tests:  uv run pytest tests/web/
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
import urllib.request

import pytest


def _remove_lock_file(save_path) -> None:
    """Remove any stale .lock file from a save directory.

    The save lock is held per-tab and may not be released between
    tests running in the same browser session, causing a lock conflict
    dialog to block all UI interactions.
    """
    lock_file = save_path / ".lock"
    if lock_file.exists():
        lock_file.unlink(missing_ok=True)


def _dismiss_lock_dialog(page) -> None:
    """Dismiss the save lock conflict dialog if it appears.

    The SaveLock feature can show a modal dialog that blocks all
    interactions. This helper checks for it and clicks Force Unlock.
    """
    try:
        force_btn = page.get_by_role("button", name="Force Unlock")
        if force_btn.is_visible(timeout=1500):
            force_btn.click()
            page.wait_for_timeout(500)
    except Exception:
        pass  # Dialog not present, continue


def _load_save_into_gameplay(page, web_server, save_id, save_path=None) -> None:
    """Navigate to the menu, load a save, and enter gameplay.

    Handles lock file cleanup and dialog dismissal.
    """
    if save_path:
        _remove_lock_file(save_path)

    page.goto(web_server)
    page.wait_for_load_state("networkidle")

    # Click the Load button on the save card
    save_card = page.locator(f'[data-testid="save-card-{save_id}"]')
    save_card.locator("button").first.click()

    # Dismiss lock dialog if it appears (before waiting for gameplay)
    _dismiss_lock_dialog(page)

    # Wait for gameplay view to appear
    page.locator('input[placeholder="What do you do?"]').wait_for(
        state="visible", timeout=10000
    )

    # Dismiss lock dialog again (it might appear after gameplay loads)
    _dismiss_lock_dialog(page)


@pytest.fixture(scope="session")
def web_server():
    """Launch the web UI server for the test session.

    Yields the base URL (e.g. http://127.0.0.1:8090).
    The server runs as a subprocess and is torn down after tests.

    Uses subprocess.Popen instead of multiprocessing.Process because
    NiceGUI's ui.run() does not work reliably when forked.
    Strips PYTEST_CURRENT_TEST from the env so NiceGUI doesn't activate
    its internal test mode (which expects NICEGUI_SCREEN_TEST_PORT).
    """
    host = "127.0.0.1"
    port = 8090

    # Strip pytest env vars so NiceGUI runs in normal (non-test) mode.
    env = {k: v for k, v in os.environ.items() if k != "PYTEST_CURRENT_TEST"}

    proc = subprocess.Popen(
        [sys.executable, "-m", "theact.web", "--port", str(port), "--host", host],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    )

    # Wait for server to be ready
    base_url = f"http://{host}:{port}"
    for _ in range(30):
        if proc.poll() is not None:
            stdout = proc.stdout.read().decode()[-500:]
            stderr = proc.stderr.read().decode()[-500:]
            pytest.fail(
                f"Web server exited with code {proc.returncode} before becoming ready.\n"
                f"STDOUT: {stdout}\nSTDERR: {stderr}"
            )
        try:
            urllib.request.urlopen(base_url, timeout=1)
            break
        except Exception:
            time.sleep(1)
    else:
        proc.kill()
        proc.wait(timeout=5)
        pytest.fail("Web server did not start in time")

    yield base_url

    proc.kill()
    proc.wait(timeout=5)

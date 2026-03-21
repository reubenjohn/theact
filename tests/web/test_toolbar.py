"""Browser tests for the gameplay toolbar.

Tests toolbar buttons, confirmation dialogs, and turn info display.
Uses the same web server and test save fixtures as test_gameplay.py.

Run with:  uv run pytest tests/web/test_toolbar.py -v
"""

import shutil

import pytest
from playwright.sync_api import expect

from theact.io.save_manager import SAVES_DIR, create_save
from tests.web.conftest import _remove_lock_file

_TEST_SAVE_ID = "pw-test-toolbar"


@pytest.fixture(scope="module", autouse=True)
def ensure_test_save():
    """Create a test save for toolbar tests."""
    save_path = SAVES_DIR / _TEST_SAVE_ID
    if not save_path.exists():
        create_save("lost-island", _TEST_SAVE_ID, "TestPlayer")
    yield
    if save_path.exists():
        shutil.rmtree(save_path)


@pytest.fixture
def gameplay_page(page, web_server, ensure_test_save):
    """Navigate to the gameplay view by loading the test save."""
    # Remove any stale lock file before loading
    _remove_lock_file(SAVES_DIR / _TEST_SAVE_ID)

    page.goto(web_server)
    page.wait_for_load_state("networkidle")
    # Find the save card and click its first button (Load)
    save_card = page.locator(f'[data-testid="save-card-{_TEST_SAVE_ID}"]')
    save_card.locator("button").first.click()
    page.locator('input[placeholder="What do you do?"]').wait_for(
        state="visible", timeout=10000
    )

    # Dismiss any save lock conflict dialog that may have appeared
    dialog_btn = page.get_by_role("button", name="Force Unlock")
    if dialog_btn.is_visible(timeout=1000):
        dialog_btn.click()
        page.wait_for_timeout(500)

    return page


class TestToolbarButtons:
    """Test that toolbar buttons are visible and interactive."""

    def test_toolbar_buttons_visible(self, gameplay_page):
        """All four toolbar buttons should be visible."""
        page = gameplay_page
        expect(page.locator('[data-testid="toolbar-undo"]')).to_be_visible()
        expect(page.locator('[data-testid="toolbar-retry"]')).to_be_visible()
        expect(page.locator('[data-testid="toolbar-save-as"]')).to_be_visible()
        expect(page.locator('[data-testid="toolbar-history"]')).to_be_visible()

    def test_undo_button_opens_dialog(self, gameplay_page):
        """Clicking the undo button should open a confirmation dialog."""
        page = gameplay_page
        page.locator('[data-testid="toolbar-undo"]').click()
        # Dialog should contain "Undo Turns" text and a Cancel button
        expect(page.get_by_text("Undo Turns")).to_be_visible()
        expect(page.get_by_role("button", name="Cancel")).to_be_visible()
        # Close the dialog
        page.get_by_role("button", name="Cancel").click()

    def test_save_as_button_opens_dialog(self, gameplay_page):
        """Clicking the save-as button should open a name input dialog."""
        page = gameplay_page
        page.locator('[data-testid="toolbar-save-as"]').click()
        expect(page.get_by_text("Fork Save", exact=True)).to_be_visible()
        expect(page.get_by_role("button", name="Cancel")).to_be_visible()
        page.get_by_role("button", name="Cancel").click()


class TestToolbarHistory:
    """Test the history button functionality."""

    def test_history_button_opens_browser(self, gameplay_page):
        """Clicking history should open the history browser panel."""
        page = gameplay_page
        page.locator('[data-testid="toolbar-history"]').click()
        page.wait_for_timeout(500)
        # The history browser dialog should be visible with its title
        expect(page.get_by_text("Turn History")).to_be_visible()
        expect(page.locator('[data-testid="history-browser"]')).to_be_visible()

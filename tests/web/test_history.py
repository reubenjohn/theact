"""Browser integration tests for turn history and enhanced save management.

Uses pytest-playwright's ``page`` fixture and the session-scoped
``web_server`` fixture from conftest.py.

Run with:  uv run pytest tests/web/test_history.py -v
"""

import shutil

import pytest
from playwright.sync_api import expect

from theact.io.save_manager import SAVES_DIR, create_save
from tests.web.conftest import _remove_lock_file

_TEST_SAVE_ID = "pw-test-history"


@pytest.fixture(scope="module", autouse=True)
def ensure_test_save():
    """Create a test save for history tests."""
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


class TestSavesTable:
    """Tests for the enhanced saves table on the menu page."""

    def test_continue_game_label_visible(self, page, web_server):
        page.goto(web_server)
        expect(page.get_by_text("Continue Game")).to_be_visible()

    def test_save_card_layout(self, page, web_server, ensure_test_save):
        """Saves are displayed as cards with expected info."""
        page.goto(web_server)
        page.wait_for_load_state("networkidle")
        # The test save card should exist
        save_card = page.locator(f'[data-testid="save-card-{_TEST_SAVE_ID}"]')
        expect(save_card).to_be_visible()
        # Card should show the save ID text
        expect(save_card.get_by_text(_TEST_SAVE_ID)).to_be_visible()
        # Card should show turn info
        expect(save_card.get_by_text("Turn", exact=False)).to_be_visible()

    def test_saves_have_fork_button(self, page, web_server, ensure_test_save):
        """Each save in the menu has a fork button (call_split icon)."""
        page.goto(web_server)
        page.wait_for_load_state("networkidle")
        save_card = page.locator(f'[data-testid="save-card-{_TEST_SAVE_ID}"]')
        # The card should have at least 3 buttons (Load, Fork, Delete)
        buttons = save_card.locator("button")
        assert buttons.count() >= 3

    def test_empty_state_when_no_saves_section_present(self, page, web_server):
        """The Continue Game section always renders without error."""
        page.goto(web_server)
        page.wait_for_load_state("networkidle")
        # Continue Game section heading should always be present
        expect(page.get_by_text("Continue Game")).to_be_visible()


class TestHistoryBrowser:
    """Tests for the turn history browser during gameplay."""

    def test_history_button_toggles_panel(self, gameplay_page):
        """Clicking history toolbar button opens/closes the panel."""
        page = gameplay_page

        # Open history
        page.locator('[data-testid="toolbar-history"]').click()
        page.wait_for_timeout(500)
        expect(page.locator('[data-testid="history-browser"]')).to_be_visible()
        expect(page.get_by_text("Turn History")).to_be_visible()

        # Close history via close button
        page.locator('[data-testid="history-browser"]').locator("button").last.click()
        page.wait_for_timeout(500)
        expect(page.locator('[data-testid="history-browser"]')).not_to_be_visible()

    def test_history_shows_no_turns_message(self, gameplay_page):
        """A fresh save with no turns shows 'No turns yet.'"""
        page = gameplay_page
        page.locator('[data-testid="toolbar-history"]').click()
        page.wait_for_timeout(500)
        # Fresh test save has no turns, should show empty message
        expect(page.get_by_text("No turns yet.")).to_be_visible()

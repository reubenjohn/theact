"""Browser integration tests for the game state sidebar.

Tests that the sidebar renders correctly with character cards,
chapter progress, and game info. Uses the same test save approach
as test_gameplay.py -- loads an existing save (no LLM calls).

Run with:  uv run pytest tests/web/test_sidebar.py -v
"""

import shutil
from pathlib import Path

import pytest
from playwright.sync_api import expect

from theact.io.save_manager import SAVES_DIR, create_save, load_save
from tests.web.conftest import _remove_lock_file

GAMES_DIR = Path(__file__).parent.parent.parent / "games"

# Unique save name for this test module (avoid collisions).
_TEST_SAVE_ID = "pw-test-sidebar"


@pytest.fixture(scope="module", autouse=True)
def ensure_test_save():
    """Create a test save on disk if it doesn't exist."""
    save_path = SAVES_DIR / _TEST_SAVE_ID
    if not save_path.exists():
        create_save("lost-island", _TEST_SAVE_ID, "SidebarTester")
    yield
    # Clean up after all tests in this module
    if save_path.exists():
        shutil.rmtree(save_path)


@pytest.fixture(scope="module")
def loaded_game(ensure_test_save):
    """Load the test save for assertion data."""
    return load_save(_TEST_SAVE_ID)


@pytest.fixture
def gameplay_page(page, web_server, ensure_test_save):
    """Navigate to gameplay view by loading the test save.

    Clicks the "Load" button next to the test save in the Continue
    section. No LLM call is triggered.
    """
    # Remove any stale lock file before loading
    _remove_lock_file(SAVES_DIR / _TEST_SAVE_ID)

    page.goto(web_server)
    page.wait_for_load_state("networkidle")

    # Find the save card and click its first button (Load)
    save_card = page.locator(f'[data-testid="save-card-{_TEST_SAVE_ID}"]')
    save_card.locator("button").first.click()

    # Wait for gameplay view to appear
    page.locator('input[placeholder="What do you do?"]').wait_for(
        state="visible", timeout=10000
    )

    # Dismiss any save lock conflict dialog that may have appeared
    dialog_btn = page.get_by_role("button", name="Force Unlock")
    if dialog_btn.is_visible(timeout=1000):
        dialog_btn.click()
        page.wait_for_timeout(500)

    return page


class TestSidebarVisibility:
    """Tests for sidebar presence and toggle behavior."""

    def test_sidebar_visible_in_gameplay(self, gameplay_page):
        """Sidebar container is present and visible in the gameplay view."""
        sidebar = gameplay_page.locator('[data-testid="game-sidebar"]')
        expect(sidebar).to_be_visible()

    def test_sidebar_toggle(self, gameplay_page):
        """Clicking toggle button hides and re-shows the sidebar."""
        sidebar = gameplay_page.locator('[data-testid="game-sidebar"]')
        # Find the toggle button by its tooltip text
        toggle = gameplay_page.get_by_role("button", name="Toggle game state sidebar")

        expect(sidebar).to_be_visible()
        toggle.click()
        expect(sidebar).to_be_hidden()
        toggle.click()
        expect(sidebar).to_be_visible()


class TestCharacterCards:
    """Tests for character cards in the sidebar."""

    def test_character_cards_rendered(self, gameplay_page, loaded_game):
        """Each active character in the current chapter has a card."""
        chapter = loaded_game.chapters[loaded_game.state.current_chapter]
        for char_id in chapter.characters:
            char = loaded_game.characters[char_id]
            card = gameplay_page.locator(f"text={char.name}")
            expect(card.first).to_be_visible()

    def test_characters_section_label(self, gameplay_page):
        """The Characters section header is visible."""
        sidebar = gameplay_page.locator('[data-testid="game-sidebar"]')
        expect(sidebar.get_by_text("Characters", exact=True)).to_be_visible()


class TestChapterProgress:
    """Tests for chapter progress display in the sidebar."""

    def test_chapter_progress_displayed(self, gameplay_page, loaded_game):
        """Chapter beats are shown in the sidebar."""
        chapter = loaded_game.chapters[loaded_game.state.current_chapter]
        sidebar = gameplay_page.locator('[data-testid="game-sidebar"]')
        for beat in chapter.beats:
            expect(sidebar.get_by_text(beat, exact=False).first).to_be_visible()

    def test_chapter_title_displayed(self, gameplay_page, loaded_game):
        """Current chapter title is shown in the sidebar."""
        chapter = loaded_game.chapters[loaded_game.state.current_chapter]
        sidebar = gameplay_page.locator('[data-testid="game-sidebar"]')
        expect(sidebar.get_by_text(chapter.title, exact=False).first).to_be_visible()

    def test_beats_progress_counter(self, gameplay_page, loaded_game):
        """Beat progress counter (e.g. '0/6 beats completed') is visible."""
        chapter = loaded_game.chapters[loaded_game.state.current_chapter]
        total = len(chapter.beats)
        sidebar = gameplay_page.locator('[data-testid="game-sidebar"]')
        expect(
            sidebar.get_by_text(f"/{total} beats completed", exact=False)
        ).to_be_visible()


class TestGameInfo:
    """Tests for game info section in the sidebar."""

    def test_turn_counter_displayed(self, gameplay_page):
        """Turn counter is visible in the sidebar."""
        sidebar = gameplay_page.locator('[data-testid="game-sidebar"]')
        # Match "Turn N" pattern (the bold label in the game info section)
        expect(sidebar.get_by_text("Turn 0", exact=False)).to_be_visible()

    def test_player_name_displayed(self, gameplay_page):
        """Player name is visible in the sidebar."""
        sidebar = gameplay_page.locator('[data-testid="game-sidebar"]')
        expect(
            sidebar.get_by_text("Player: SidebarTester", exact=False)
        ).to_be_visible()

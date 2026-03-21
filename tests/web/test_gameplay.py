"""Browser integration tests for the web UI gameplay view.

Loads an existing save via the UI (no LLM calls) and tests gameplay
elements and slash commands. Uses pytest-playwright's ``page`` fixture
and the session-scoped ``web_server`` fixture from conftest.py.

Run with:  uv run pytest tests/web/test_gameplay.py -v
"""

import shutil
from pathlib import Path

import pytest
from playwright.sync_api import expect

from theact.io.save_manager import SAVES_DIR, create_save

GAMES_DIR = Path(__file__).parent.parent.parent / "games"

# Unique save name for this test module (avoid collisions with real saves).
_TEST_SAVE_ID = "pw-test-gameplay"


@pytest.fixture(scope="module", autouse=True)
def ensure_test_save():
    """Create a test save on disk if it doesn't exist.

    Loading an existing save does NOT trigger auto_start (LLM call),
    making tests fast and deterministic.
    """
    save_path = SAVES_DIR / _TEST_SAVE_ID
    if not save_path.exists():
        create_save("lost-island", _TEST_SAVE_ID, "TestPlayer")
    yield
    # Clean up after all tests in this module
    if save_path.exists():
        shutil.rmtree(save_path)


@pytest.fixture
def gameplay_page(page, web_server, ensure_test_save):
    """Navigate to gameplay view by loading the test save.

    Clicks the "Load" button next to the test save in the Continue
    section. No LLM call is triggered.
    """
    page.goto(web_server)
    page.wait_for_load_state("networkidle")

    # Find and click the Load button for our test save
    # The save ID appears in a label in the same row as the Load button
    save_row = page.locator(f"text={_TEST_SAVE_ID}").first
    # The Load button is a sibling in the same row
    load_btn = save_row.locator("..").get_by_role("button", name="Load")
    load_btn.click()

    # Wait for gameplay view to appear
    page.locator('input[placeholder="What do you do?"]').wait_for(
        state="visible", timeout=10000
    )

    return page


class TestGameplayView:
    """Tests for gameplay view UI elements."""

    def test_header_shows_game_info(self, gameplay_page):
        # Header format: "The Lost Island -- Turn N -- ChapterTitle"
        header = gameplay_page.get_by_text("The Lost Island -- Turn", exact=False)
        expect(header).to_be_visible()

    def test_input_field_present(self, gameplay_page):
        input_field = gameplay_page.locator('input[placeholder="What do you do?"]')
        expect(input_field).to_be_visible()

    def test_send_button_present(self, gameplay_page):
        expect(gameplay_page.get_by_role("button", name="Send")).to_be_visible()

    def test_menu_button_present(self, gameplay_page):
        expect(gameplay_page.get_by_role("button", name="Menu")).to_be_visible()

    def test_thinking_toggle_present(self, gameplay_page):
        expect(gameplay_page.get_by_text("Thinking", exact=True)).to_be_visible()


class TestSlashCommands:
    """Tests for slash commands rendered in the gameplay view."""

    def _send_command(self, page, command):
        """Type a slash command and press Send."""
        input_field = page.locator('input[placeholder="What do you do?"]')
        input_field.fill(command)
        page.get_by_role("button", name="Send").click()
        page.wait_for_timeout(1000)

    def test_help_command_renders_table(self, gameplay_page):
        self._send_command(gameplay_page, "/help")
        expect(gameplay_page.get_by_text("Show this help message")).to_be_visible()

    def test_status_command_shows_chapter(self, gameplay_page):
        self._send_command(gameplay_page, "/status")
        expect(gameplay_page.get_by_text("Chapter:", exact=False)).to_be_visible()
        expect(gameplay_page.get_by_text("Beats:", exact=False)).to_be_visible()

    def test_save_command_shows_info(self, gameplay_page):
        self._send_command(gameplay_page, "/save")
        # /save output includes "Save: <name>\nGame: ...\nPlayer: ..."
        # Use "Game:" to avoid clash with the "Loaded save: ..." notification toast
        expect(
            gameplay_page.get_by_text("Game: The Lost Island", exact=False)
        ).to_be_visible()


class TestMenuNavigation:
    """Tests for navigating back to the menu from gameplay."""

    def test_menu_button_returns_to_menu(self, gameplay_page):
        gameplay_page.get_by_role("button", name="Menu").click()
        # Menu page reloads via navigate.to("/")
        gameplay_page.wait_for_load_state("networkidle")
        expect(gameplay_page.get_by_text("T H E A C T")).to_be_visible()
        expect(gameplay_page.get_by_text("New Game")).to_be_visible()

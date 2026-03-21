"""Browser integration tests for the web UI menu page.

Uses pytest-playwright's ``page`` fixture and the session-scoped
``web_server`` fixture from conftest.py.

Run with:  uv run pytest tests/web/test_menu.py -v
"""

from playwright.sync_api import expect


class TestMenuBanner:
    """Tests for the banner section of the menu page."""

    def test_banner_visible(self, page, web_server):
        page.goto(web_server)
        expect(page.get_by_text("T H E A C T")).to_be_visible()

    def test_subtitle_visible(self, page, web_server):
        page.goto(web_server)
        expect(page.get_by_text("an AI text-based RPG")).to_be_visible()

    def test_page_title(self, page, web_server):
        page.goto(web_server)
        expect(page).to_have_title("TheAct")


class TestMenuNewGameSection:
    """Tests for the 'New Game' section."""

    def test_new_game_label_visible(self, page, web_server):
        page.goto(web_server)
        expect(page.get_by_text("New Game")).to_be_visible()

    def test_game_selector_present(self, page, web_server):
        page.goto(web_server)
        expect(page.get_by_label("Game")).to_be_visible()

    def test_save_name_input_present(self, page, web_server):
        page.goto(web_server)
        expect(page.get_by_label("Save Name")).to_be_visible()

    def test_player_name_input_present(self, page, web_server):
        page.goto(web_server)
        expect(page.get_by_label("Player Name")).to_be_visible()

    def test_start_game_button_present(self, page, web_server):
        page.goto(web_server)
        expect(page.get_by_role("button", name="Start Game")).to_be_visible()

    def test_player_name_defaults_to_player(self, page, web_server):
        page.goto(web_server)
        player_input = page.get_by_label("Player Name")
        expect(player_input).to_have_value("Player")


class TestMenuContinueSection:
    """Tests for the 'Continue Game' section."""

    def test_continue_game_label_visible(self, page, web_server):
        page.goto(web_server)
        expect(page.get_by_text("Continue Game")).to_be_visible()


class TestMenuDeleteSection:
    """Tests for the 'Delete Save' section."""

    def test_delete_save_label_visible(self, page, web_server):
        page.goto(web_server)
        expect(page.get_by_text("Delete Save")).to_be_visible()

    def test_delete_button_present(self, page, web_server):
        page.goto(web_server)
        # The delete section has a delete button
        delete_buttons = page.get_by_role("button", name="Delete")
        expect(delete_buttons.first).to_be_visible()

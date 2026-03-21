"""Browser integration tests for the playtest dashboard.

Uses pytest-playwright's ``page`` fixture and the session-scoped
``web_server`` fixture from conftest.py.

Run with:  uv run pytest tests/web/test_playtest_dashboard.py -v
"""

from playwright.sync_api import expect


class TestPlaytestPageAccess:
    """Tests that the playtest page is accessible."""

    def test_playtest_page_loads(self, page, web_server):
        """Playtest page is accessible at /playtest."""
        page.goto(f"{web_server}/playtest")
        expect(page.get_by_text("Playtest Dashboard")).to_be_visible()

    def test_back_button_present(self, page, web_server):
        """Back button is present on the playtest page."""
        page.goto(f"{web_server}/playtest")
        back_btn = page.locator("button").filter(has_text="arrow_back").first
        expect(back_btn).to_be_visible()


class TestPlaytestConfigForm:
    """Tests for the configuration panel."""

    def test_game_selector_present(self, page, web_server):
        """Game selector dropdown is present."""
        page.goto(f"{web_server}/playtest")
        expect(page.get_by_label("Game")).to_be_visible()

    def test_max_turns_input_present(self, page, web_server):
        """Max turns number input is present."""
        page.goto(f"{web_server}/playtest")
        expect(page.get_by_label("Max Turns")).to_be_visible()

    def test_player_name_input_present(self, page, web_server):
        """Player name text input is present."""
        page.goto(f"{web_server}/playtest")
        expect(page.get_by_label("Player Name")).to_be_visible()

    def test_edge_case_slider_present(self, page, web_server):
        """Edge case frequency slider label is present."""
        page.goto(f"{web_server}/playtest")
        expect(page.get_by_text("Edge Case Frequency")).to_be_visible()

    def test_stop_on_error_checkbox_present(self, page, web_server):
        """Stop on error checkbox is present."""
        page.goto(f"{web_server}/playtest")
        expect(page.get_by_text("Stop on error")).to_be_visible()

    def test_start_button_present(self, page, web_server):
        """Start Playtest button is present."""
        page.goto(f"{web_server}/playtest")
        expect(page.get_by_role("button", name="Start Playtest")).to_be_visible()


class TestPlaytestPastReports:
    """Tests for the past reports browser section."""

    def test_past_reports_section_exists(self, page, web_server):
        """Past Reports section header is visible."""
        page.goto(f"{web_server}/playtest")
        expect(page.get_by_text("Past Reports")).to_be_visible()

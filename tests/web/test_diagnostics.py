"""Browser tests for the diagnostics & observability viewer.

Uses pytest-playwright's ``page`` fixture and the session-scoped
``web_server`` fixture from conftest.py.

Run with:  uv run pytest tests/web/test_diagnostics.py -v
"""

from playwright.sync_api import expect


class TestDiagnosticsPage:
    """Tests for the diagnostics page at /diagnostics."""

    def test_diagnostics_page_loads(self, page, web_server):
        """Diagnostics page loads at /diagnostics."""
        page.goto(f"{web_server}/diagnostics")
        heading = page.locator("text=Diagnostics & Observability")
        expect(heading).to_be_visible()

    def test_back_button_present(self, page, web_server):
        """Back button navigates to the menu."""
        page.goto(f"{web_server}/diagnostics")
        back_btn = page.get_by_role("button", name="arrow_back")
        expect(back_btn).to_be_visible()
        back_btn.click()
        page.wait_for_url(f"{web_server}/")
        expect(page).to_have_url(f"{web_server}/")

    def test_empty_state_message(self, page, web_server):
        """With no call data, shows an appropriate message."""
        page.goto(f"{web_server}/diagnostics")
        empty_msg = page.locator("text=No LLM call data available")
        expect(empty_msg).to_be_visible()

    def test_diagnostics_link_in_menu(self, page, web_server):
        """Menu page has a link/button to diagnostics."""
        page.goto(web_server)
        diag_button = page.locator("text=Diagnostics")
        expect(diag_button).to_be_visible()


class TestDiagnosticsWithSave:
    """Tests that require a save with call log data.

    NOTE: These tests navigate to /diagnostics without a save_id,
    so they verify the empty/selector state. Testing with actual
    call log data requires a save directory with call_log.yaml,
    which is not created by the test server fixture.
    """

    def test_tabs_present_without_save(self, page, web_server):
        """Without a save, tabs are not shown (empty state instead)."""
        page.goto(f"{web_server}/diagnostics")
        # Without a save_id, we get the empty state message
        empty_msg = page.locator("text=No LLM call data available")
        expect(empty_msg).to_be_visible()

"""Browser tests for the settings page.

Uses pytest-playwright's ``page`` fixture and the session-scoped
``web_server`` fixture from conftest.py.

Run with:  uv run pytest tests/web/test_settings.py -v
"""

from playwright.sync_api import expect


class TestSettingsPage:
    """Tests for the settings page at /settings."""

    def test_settings_page_accessible(self, page, web_server):
        """Settings page loads at /settings."""
        page.goto(f"{web_server}/settings")
        expect(page.get_by_text("Settings")).to_be_visible()

    def test_settings_back_button(self, page, web_server):
        """Back button navigates to the menu."""
        page.goto(f"{web_server}/settings")
        page.wait_for_load_state("networkidle")
        # NiceGUI renders icon buttons with a <i class="material-icons">
        # element inside; match by filtering for the icon text content.
        back_btn = page.locator("button").filter(has_text="arrow_back").first
        back_btn.click()
        page.wait_for_url(f"{web_server}/")
        expect(page).to_have_url(f"{web_server}/")

    def test_save_button_exists(self, page, web_server):
        """Save button is present in the header bar."""
        page.goto(f"{web_server}/settings")
        expect(page.get_by_role("button", name="Save")).to_be_visible()


class TestLLMConfigSection:
    """Tests for the LLM configuration section."""

    def test_llm_config_fields_present(self, page, web_server):
        """LLM configuration section has all expected fields."""
        page.goto(f"{web_server}/settings")
        page.wait_for_load_state("networkidle")
        expect(page.get_by_text("LLM Configuration")).to_be_visible()
        # NiceGUI/Quasar inputs render labels as floating text inside the
        # input wrapper, not as HTML <label> elements. Use get_by_text()
        # to match the label text rendered by Quasar.
        expect(page.get_by_text("API Key", exact=True).first).to_be_visible()
        expect(page.get_by_text("Base URL", exact=True).first).to_be_visible()
        expect(page.get_by_text("Model", exact=True).first).to_be_visible()
        expect(page.get_by_text("Temperature").first).to_be_visible()
        expect(page.get_by_text("Default Max Tokens").first).to_be_visible()
        expect(page.get_by_text("Context Limit").first).to_be_visible()

    def test_api_key_masked(self, page, web_server):
        """API key input is a password field (masked by default)."""
        page.goto(f"{web_server}/settings")
        api_key_input = page.locator("input[type='password']").first
        expect(api_key_input).to_be_visible()

    def test_test_connection_button_exists(self, page, web_server):
        """Test Connection button is present."""
        page.goto(f"{web_server}/settings")
        expect(page.get_by_role("button", name="Test Connection")).to_be_visible()


class TestCreatorConfigSection:
    """Tests for the creator configuration section."""

    def test_creator_config_section_present(self, page, web_server):
        """Creator configuration section has separate fields."""
        page.goto(f"{web_server}/settings")
        expect(page.get_by_text("Creator Configuration")).to_be_visible()
        expect(page.get_by_text("Use same config as gameplay")).to_be_visible()


class TestDisplayPreferences:
    """Tests for the display preferences section."""

    def test_display_preferences_present(self, page, web_server):
        """Display preferences section has expected controls."""
        page.goto(f"{web_server}/settings")
        expect(page.get_by_text("Display Preferences")).to_be_visible()
        expect(page.get_by_text("Show model thinking by default")).to_be_visible()
        expect(page.get_by_text("Chat Font Size")).to_be_visible()
        expect(page.get_by_text("Message Density")).to_be_visible()


class TestMenuSettingsLink:
    """Tests for the settings link on the menu page."""

    def test_menu_has_settings_link(self, page, web_server):
        """Menu page has a settings navigation button."""
        page.goto(f"{web_server}/")
        settings_btn = page.locator("[aria-label='Settings']")
        expect(settings_btn).to_be_visible()
        settings_btn.click()
        page.wait_for_url(f"{web_server}/settings")
        expect(page).to_have_url(f"{web_server}/settings")

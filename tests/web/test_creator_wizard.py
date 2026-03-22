"""Browser tests for the game creation wizard.

Run with:  uv run pytest tests/web/test_creator_wizard.py -v
"""

from playwright.sync_api import expect


class TestCreatePageAccess:
    """Tests for the /create route and navigation."""

    def test_create_page_accessible(self, page, web_server):
        """The /create page loads without error."""
        page.goto(f"{web_server}/create")
        expect(page.get_by_text("Create a New Game")).to_be_visible()

    def test_create_button_on_menu(self, page, web_server):
        """The menu has a 'Create Game' button."""
        page.goto(web_server)
        expect(page.get_by_role("button", name="Create Game")).to_be_visible()

    def test_create_button_navigates(self, page, web_server):
        """Clicking 'Create Game' navigates to /create."""
        page.goto(web_server)
        page.get_by_role("button", name="Create Game").click()
        page.wait_for_url(f"{web_server}/create")
        expect(page.get_by_text("Create a New Game")).to_be_visible()


class TestWizardSteps:
    """Tests for the wizard step structure."""

    def test_stepper_visible(self, page, web_server):
        """The step indicator is visible on the create page."""
        page.goto(f"{web_server}/create")
        expect(page.get_by_text("Concept")).to_be_visible()

    def test_concept_textarea_present(self, page, web_server):
        """Step 1 has a textarea for concept input."""
        page.goto(f"{web_server}/create")
        textarea = page.locator("textarea")
        expect(textarea).to_be_visible()

    def test_generate_button_present(self, page, web_server):
        """Step 1 has a 'Generate Proposal' button."""
        page.goto(f"{web_server}/create")
        expect(page.get_by_role("button", name="Generate Proposal")).to_be_visible()

    def test_back_button_returns_to_menu(self, page, web_server):
        """The back arrow button navigates to the menu."""
        page.goto(f"{web_server}/create")
        page.get_by_role("button", name="").first.click()
        page.wait_for_url(web_server + "/")


class TestBrainstormChatPanel:
    """Tests for the brainstorm chat side panel."""

    def test_brainstorm_button_visible(self, page, web_server):
        """The Brainstorm toggle button is visible on the create page."""
        page.goto(f"{web_server}/create")
        expect(page.get_by_role("button", name="Brainstorm")).to_be_visible()

    def test_brainstorm_drawer_opens(self, page, web_server):
        """Clicking Brainstorm opens the chat drawer."""
        page.goto(f"{web_server}/create")
        page.get_by_role("button", name="Brainstorm").click()
        drawer = page.locator('[data-testid="creator-chat-drawer"]')
        expect(drawer).to_be_visible()

    def test_brainstorm_drawer_has_input(self, page, web_server):
        """The chat drawer has a message input field."""
        page.goto(f"{web_server}/create")
        page.get_by_role("button", name="Brainstorm").click()
        drawer = page.locator('[data-testid="creator-chat-drawer"]')
        input_field = drawer.locator('input[placeholder="Type a message..."]')
        expect(input_field).to_be_visible()

    def test_brainstorm_drawer_closes(self, page, web_server):
        """Clicking close hides the chat drawer."""
        page.goto(f"{web_server}/create")
        page.get_by_role("button", name="Brainstorm").click()
        drawer = page.locator('[data-testid="creator-chat-drawer"]')
        expect(drawer).to_be_visible()
        # Close it
        drawer.locator("button", has=page.locator("text=close")).click()
        expect(drawer).to_be_hidden()

    def test_brainstorm_has_paste_button(self, page, web_server):
        """The chat drawer has a paste/use-as-concept button."""
        page.goto(f"{web_server}/create")
        page.get_by_role("button", name="Brainstorm").click()
        drawer = page.locator('[data-testid="creator-chat-drawer"]')
        paste_btn = drawer.locator("button", has=page.locator("text=content_paste"))
        expect(paste_btn).to_be_visible()


class TestConfigError:
    """Tests for missing creator config handling.

    These tests require a test environment where CREATOR_API_KEY
    and LLM_API_KEY are both unset, which is difficult to arrange
    in the standard test fixture. Mark as manual or conditional.
    """

    pass  # Conditional tests based on env availability

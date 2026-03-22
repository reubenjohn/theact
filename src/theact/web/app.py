"""Web application setup -- page routing only.

Delegates menu construction to MenuBuilder and gameplay to
GameplaySession. Manages transitions between menu and gameplay views.
"""

from __future__ import annotations

import logging

from dotenv import load_dotenv
from nicegui import ui

from theact.io.settings_store import load_settings
from theact.llm.config import load_llm_config
from theact.web.menu import MenuBuilder
from theact.web.session import GameplaySession
from theact.web.state import GameSessionState

logger = logging.getLogger(__name__)


def setup_app() -> None:
    """Configure the NiceGUI application and register page routes."""
    load_dotenv()

    @ui.page("/")
    async def index():
        """Main page: shows menu or gameplay depending on state."""
        try:
            llm_config = load_llm_config()
        except ValueError as e:
            ui.label(str(e)).style("color: #ff5252; padding: 20px;")
            ui.label("Create a .env file with LLM_API_KEY=your_key_here").style(
                "color: #999; padding: 0 20px;"
            )
            return

        # Page-level state
        page_state = {
            "session": None,
            "menu_container": None,
            "gameplay_container": None,
        }

        # --- Layout wrapper ---
        with ui.column().classes("w-full items-center"):
            page_state["menu_container"] = ui.column().classes(
                "w-full max-w-3xl mx-auto p-4"
            )
            page_state["gameplay_container"] = ui.column().classes(
                "w-full max-w-6xl mx-auto"
            )
            page_state["gameplay_container"].set_visibility(False)

        def enter_gameplay(game, auto_start: bool = False):
            """Transition from menu to gameplay view."""
            page_state["menu_container"].set_visibility(False)
            page_state["gameplay_container"].set_visibility(True)
            page_state["gameplay_container"].clear()

            settings = load_settings()
            state = GameSessionState(
                game=game,
                llm_config=llm_config,
                debug_mode=settings.debug_mode,
            )
            session = GameplaySession(
                state=state,
                on_quit=return_to_menu,
            )
            page_state["session"] = session
            session.build(page_state["gameplay_container"])

            if auto_start:
                ui.timer(0.1, lambda: _auto_start(session), once=True)

        async def _auto_start(session: GameplaySession):
            """Run the opening narration for a fresh game."""
            await session.auto_start()

        def return_to_menu():
            """Transition from gameplay back to menu."""
            ui.navigate.to("/")

        # --- Build menu ---
        menu = MenuBuilder(
            on_start_game=lambda game: enter_gameplay(game, auto_start=True),
            on_load_game=lambda game: enter_gameplay(game, auto_start=False),
        )
        menu.build(page_state["menu_container"])

    @ui.page("/create")
    async def create_page():
        """Game creation wizard page."""
        from theact.web.creator_wizard import CreatorWizard

        wizard = CreatorWizard(on_complete=lambda: ui.navigate.to("/"))
        wizard.build()

    @ui.page("/settings")
    async def settings_page():
        """Settings page for LLM and display configuration."""
        from theact.web.settings import build_settings_page

        build_settings_page(on_back=lambda: ui.navigate.to("/"))

    @ui.page("/diagnostics")
    async def diagnostics_page(save: str = ""):
        """Diagnostics and observability viewer."""
        from theact.web.diagnostics_viewer import build_diagnostics_page

        build_diagnostics_page(save_id=save)

    @ui.page("/playtest")
    async def playtest():
        """Playtest dashboard page."""
        from theact.web.playtest_dashboard import playtest_page

        await playtest_page()

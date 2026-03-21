"""Main NiceGUI application: page routing, menu, and session dispatch.

This is the central module that sets up the NiceGUI app with a single
page route. It manages transitions between the menu view and the
gameplay view using container visibility toggling.
"""

from __future__ import annotations

import logging
import shutil
from datetime import datetime, timezone

from dotenv import load_dotenv
from nicegui import ui

from theact.io.save_manager import (
    SAVES_DIR,
    create_save,
    list_games,
    list_saves,
    load_save,
    slugify,
)
from theact.llm.config import load_llm_config
from theact.web.session import GameplaySession

logger = logging.getLogger(__name__)


def setup_app() -> None:
    """Configure the NiceGUI application and register page routes."""
    load_dotenv()

    @ui.page("/")
    async def index():
        """Main page: shows menu or gameplay depending on state."""
        # Load LLM config
        try:
            llm_config = load_llm_config()
        except ValueError as e:
            ui.label(str(e)).style("color: #ff5252; padding: 20px;")
            ui.label("Create a .env file with VENICE_API_KEY=your_key_here").style(
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
            # Menu container
            page_state["menu_container"] = ui.column().classes(
                "w-full max-w-3xl mx-auto p-4"
            )

            # Gameplay container (hidden initially)
            page_state["gameplay_container"] = ui.column().classes(
                "w-full max-w-3xl mx-auto"
            )
            page_state["gameplay_container"].set_visibility(False)

        def enter_gameplay(game, auto_start: bool = False):
            """Transition from menu to gameplay view."""
            page_state["menu_container"].set_visibility(False)
            page_state["gameplay_container"].set_visibility(True)
            page_state["gameplay_container"].clear()

            session = GameplaySession(
                game=game,
                llm_config=llm_config,
                on_quit=return_to_menu,
            )
            page_state["session"] = session
            session.build(page_state["gameplay_container"])

            if auto_start:
                # Use ui.timer to trigger auto-start after the UI is built
                ui.timer(0.1, lambda: _auto_start(session), once=True)

        async def _auto_start(session: GameplaySession):
            """Run the opening narration for a fresh game."""
            await session.auto_start()

        def return_to_menu():
            """Transition from gameplay back to menu.

            Navigates to "/" to rebuild the page with fresh save data.
            """
            ui.navigate.to("/")

        # --- Build menu ---
        _build_menu(
            page_state["menu_container"],
            enter_gameplay,
        )


def _build_menu(
    container: ui.element,
    enter_gameplay: callable,
) -> None:
    """Build the menu view with game management sections."""
    with container:
        # --- Banner ---
        with ui.column().classes("w-full items-center py-6"):
            ui.label("T H E   A C T").style(
                "color: #ffffff; font-size: 1.8em; font-weight: bold; "
                "letter-spacing: 0.3em;"
            )
            ui.label("an AI text-based RPG").style(
                "color: #888; font-size: 0.9em; font-style: italic;"
            )

        ui.separator()

        # --- New Game section ---
        _build_new_game_section(container, enter_gameplay)

        ui.separator()

        # --- Continue Game section ---
        saves_container = ui.column().classes("w-full")
        _build_saves_table(saves_container, enter_gameplay)

        ui.separator()

        # --- Delete Save section ---
        _build_delete_section(container)


def _build_new_game_section(
    container: ui.element,
    enter_gameplay: callable,
) -> None:
    """Build the 'New Game' form."""
    games = list_games()

    with container:
        ui.label("New Game").style(
            "font-size: 1.2em; font-weight: bold; color: #ccc; margin-top: 12px;"
        )

        if not games:
            ui.label("No games found in games/ directory.").style("color: #999;")
            return

        game_options = {g.id: f"{g.title} -- {g.description}" for g in games}
        game_select = ui.select(
            options=game_options,
            label="Game",
            value=games[0].id,
        ).classes("w-full")

        save_name_input = (
            ui.input(
                label="Save Name",
                value=games[0].id if games else "my-save",
            )
            .classes("w-full")
            .props("outlined dense dark")
        )

        player_name_input = (
            ui.input(
                label="Player Name",
                value="Player",
            )
            .classes("w-full")
            .props("outlined dense dark")
        )

        async def on_start():
            game_id = game_select.value
            save_name = slugify(save_name_input.value or "save")
            player_name = (player_name_input.value or "").strip() or "Player"

            try:
                create_save(game_id, save_name, player_name)
                game = load_save(save_name)
                ui.notify(f"Created save: {save_name}", type="positive")
                enter_gameplay(game, auto_start=True)
            except FileExistsError:
                ui.notify(
                    f"A save named '{save_name}' already exists. "
                    f"Choose a different name.",
                    type="negative",
                )
            except FileNotFoundError as e:
                ui.notify(f"Error: {e}", type="negative")
            except Exception as e:
                ui.notify(f"Error creating save: {e}", type="negative")

        ui.button("Start Game", on_click=on_start, icon="play_arrow").props("dense")


def _build_saves_table(
    container: ui.element,
    enter_gameplay: callable,
) -> None:
    """Build the 'Continue Game' table with load buttons."""
    saves = list_saves()

    with container:
        ui.label("Continue Game").style(
            "font-size: 1.2em; font-weight: bold; color: #ccc; margin-top: 12px;"
        )

        if not saves:
            ui.label("No saves found.").style("color: #999;")
            return

        # Build a row-based layout with load buttons
        for save_info in saves:
            modified = save_info.get("last_modified", 0)
            if isinstance(modified, (int, float)) and modified > 0:
                ts = datetime.fromtimestamp(modified, tz=timezone.utc)
                time_str = ts.strftime("%Y-%m-%d %H:%M")
            else:
                time_str = "unknown"

            with (
                ui.row()
                .classes("w-full items-center py-1")
                .style("border-bottom: 1px solid #333;")
            ):
                ui.label(save_info["id"]).style("color: #ccc; min-width: 120px;")
                ui.label(save_info["game_title"]).style(
                    "color: #aaa; min-width: 150px;"
                )
                ui.label(f"Turn {save_info['turn']}").style(
                    "color: #888; min-width: 70px;"
                )
                ui.label(time_str).style("color: #888; min-width: 120px;")

                save_id = save_info["id"]

                def make_load_handler(sid: str):
                    async def handler():
                        try:
                            game = load_save(sid)
                            ui.notify(f"Loaded save: {sid}", type="positive")
                            enter_gameplay(game, auto_start=False)
                        except Exception as e:
                            ui.notify(f"Error loading save: {e}", type="negative")

                    return handler

                ui.button(
                    "Load", on_click=make_load_handler(save_id), icon="folder_open"
                ).props("flat dense").style("color: #69f0ae;")


def _build_delete_section(
    parent_container: ui.element,
) -> None:
    """Build the 'Delete Save' section."""
    with parent_container:
        ui.label("Delete Save").style(
            "font-size: 1.2em; font-weight: bold; color: #ccc; margin-top: 12px;"
        )

        saves = list_saves()
        if not saves:
            ui.label("No saves to delete.").style("color: #999;")
            return

        save_options = {
            s["id"]: f"{s['id']} ({s['game_title']}, turn {s['turn']})" for s in saves
        }
        delete_select = ui.select(
            options=save_options,
            label="Select save to delete",
        ).classes("w-full")

        async def on_delete():
            save_id = delete_select.value
            if not save_id:
                ui.notify("Please select a save to delete.", type="warning")
                return

            # Show confirmation dialog
            with ui.dialog() as dialog, ui.card():
                ui.label(f'Delete save "{save_id}"? This cannot be undone.').style(
                    "color: #ccc;"
                )
                with ui.row().classes("justify-end gap-2"):
                    ui.button("Cancel", on_click=dialog.close).props("flat")

                    async def confirm():
                        save_path = SAVES_DIR / save_id
                        if save_path.exists():
                            shutil.rmtree(save_path)
                            ui.notify(f"Deleted save: {save_id}", type="positive")
                        else:
                            ui.notify("Save not found.", type="warning")
                        dialog.close()
                        # Refresh the page to update all save lists
                        ui.navigate.to("/")

                    ui.button("Delete", on_click=confirm, color="red").props("flat")
            dialog.open()

        ui.button("Delete", on_click=on_delete, icon="delete").props("dense").style(
            "color: #ff5252;"
        )

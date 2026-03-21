"""Menu UI builder.

Extracted from app.py. Builds the main menu with new game, continue
game, and delete save sections. app.py delegates to this class.
"""

from __future__ import annotations

import logging
import shutil
from datetime import datetime, timezone

from nicegui import ui

from theact.io.save_manager import (
    SAVES_DIR,
    create_save,
    list_games,
    list_saves,
    load_save,
    slugify,
)

logger = logging.getLogger(__name__)


class MenuBuilder:
    """Builds the main menu UI."""

    def __init__(self, on_start_game: callable, on_load_game: callable) -> None:
        self._on_start_game = on_start_game
        self._on_load_game = on_load_game

    def build(self, container: ui.element) -> None:
        """Build the complete menu inside the container."""
        with container:
            self._build_banner()
            ui.separator()
            self._build_new_game_section()
            ui.separator()
            self._build_saves_table()
            ui.separator()
            self._build_delete_section()

    def _build_banner(self) -> None:
        """Render the title banner."""
        with ui.column().classes("w-full items-center py-6"):
            ui.label("T H E   A C T").style(
                "color: #ffffff; font-size: 1.8em; font-weight: bold; "
                "letter-spacing: 0.3em;"
            )
            ui.label("an AI text-based RPG").style(
                "color: #888; font-size: 0.9em; font-style: italic;"
            )

    def _build_new_game_section(self) -> None:
        """Build the 'New Game' form."""
        games = list_games()

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
                self._on_start_game(game)
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

    def _build_saves_table(self) -> None:
        """Build the 'Continue Game' table with load buttons."""
        saves = list_saves()

        ui.label("Continue Game").style(
            "font-size: 1.2em; font-weight: bold; color: #ccc; margin-top: 12px;"
        )

        if not saves:
            ui.label("No saves found.").style("color: #999;")
            return

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
                            self._on_load_game(game)
                        except Exception as e:
                            ui.notify(f"Error loading save: {e}", type="negative")

                    return handler

                ui.button(
                    "Load", on_click=make_load_handler(save_id), icon="folder_open"
                ).props("flat dense").style("color: #69f0ae;")

    def _build_delete_section(self) -> None:
        """Build the 'Delete Save' section."""
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
                        ui.navigate.to("/")

                    ui.button("Delete", on_click=confirm, color="red").props("flat")
            dialog.open()

        ui.button("Delete", on_click=on_delete, icon="delete").props("dense").style(
            "color: #ff5252;"
        )

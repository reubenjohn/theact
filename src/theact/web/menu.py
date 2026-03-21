"""Menu UI builder.

Extracted from app.py. Builds the main menu with new game, continue
game sections. app.py delegates to this class.

Save cards show title, game name, turn count, relative time, and
action buttons (Load, Fork, Delete). The standalone delete section
has been replaced by per-card delete buttons.
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

from nicegui import ui

from theact.io.save_manager import (
    SAVES_DIR,
    create_save,
    list_games,
    list_saves,
    load_save,
    slugify,
)
from theact.versioning import git_save
from theact.web.components.html_utils import relative_time

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
            ui.button(
                "Create Game",
                on_click=lambda: ui.navigate.to("/create"),
                icon="auto_fix_high",
            ).props("outline").classes("w-full")
            ui.separator()
            self._build_new_game_section()
            ui.separator()
            self._build_saves_table()
            ui.separator()
            with ui.row().classes("w-full items-center gap-2"):
                ui.label("Tools").style(
                    "font-size: 1.2em; font-weight: bold; color: #ccc; margin-top: 12px;"
                )
            with ui.row().classes("w-full gap-2"):
                ui.button(
                    "Playtest Dashboard",
                    on_click=lambda: ui.navigate.to("/playtest"),
                    icon="science",
                ).props("dense")
                ui.button(
                    "Diagnostics",
                    on_click=lambda: ui.navigate.to("/diagnostics"),
                    icon="analytics",
                ).props("dense")

    def _build_banner(self) -> None:
        """Render the title banner with settings link."""
        with ui.column().classes("w-full items-center py-6"):
            # Settings button in top-right corner
            with ui.row().classes("w-full justify-end"):
                ui.button(
                    icon="settings",
                    on_click=lambda: ui.navigate.to("/settings"),
                ).props("flat dense").tooltip("Settings").props('aria-label="Settings"')
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
        """Build the 'Continue Game' section with card-based save layout."""
        saves = list_saves()

        ui.label("Continue Game").style(
            "font-size: 1.2em; font-weight: bold; color: #ccc; margin-top: 12px;"
        )

        if not saves:
            with ui.row().classes("w-full items-center justify-center py-8"):
                ui.icon("save", size="2em").style("color: #555;")
                ui.label("No saves yet. Start a new game above!").style(
                    "color: #888; font-size: 1em;"
                )
            return

        # Sort by last modified (most recent first)
        saves.sort(key=lambda s: s.get("last_modified", 0), reverse=True)

        for save_info in saves:
            self._build_save_card(save_info)

    def _build_save_card(self, save_info: dict) -> None:
        """Build a single save card with info and action buttons."""
        save_id = save_info["id"]
        modified = save_info.get("last_modified", 0)
        time_str = (
            relative_time(modified)
            if isinstance(modified, (int, float)) and modified > 0
            else "unknown"
        )

        with (
            ui.card()
            .classes("w-full")
            .style("background: #2a2a2a; border: 1px solid #444; padding: 12px;")
            .props(f'data-testid="save-card-{save_id}"')
        ):
            with ui.row().classes("w-full items-center"):
                # Left side: save info
                with ui.column().classes("flex-grow gap-0"):
                    ui.label(save_id).style(
                        "color: #eee; font-weight: bold; font-size: 1.05em;"
                    )
                    ui.label(
                        f"{save_info['game_title']}  --  "
                        f"Turn {save_info['turn']}  --  {time_str}"
                    ).style("color: #999; font-size: 0.85em;")

                # Right side: action buttons
                with ui.row().classes("gap-1"):

                    def make_load_handler(sid: str):
                        async def handler():
                            loading = ui.row().classes("items-center gap-2")
                            with loading:
                                ui.spinner("dots", size="sm")
                                ui.label("Loading...").style(
                                    "color: #888; font-size: 0.8em;"
                                )
                            try:
                                game = load_save(sid)
                                ui.notify(f"Loaded save: {sid}", type="positive")
                                self._on_load_game(game)
                            except Exception as e:
                                ui.notify(f"Error loading save: {e}", type="negative")
                            finally:
                                loading.delete()

                        return handler

                    def make_fork_handler(sid: str, save_path: Path):
                        def handler():
                            _show_fork_dialog(sid, save_path)

                        return handler

                    def make_delete_handler(sid: str):
                        def handler():
                            _show_delete_dialog(sid)

                        return handler

                    ui.button(
                        icon="folder_open",
                        on_click=make_load_handler(save_id),
                    ).props("flat dense").style("color: #69f0ae;").tooltip("Load")

                    save_path = SAVES_DIR / save_id
                    ui.button(
                        icon="call_split",
                        on_click=make_fork_handler(save_id, save_path),
                    ).props("flat dense").style("color: #42a5f5;").tooltip("Fork")

                    ui.button(
                        icon="delete",
                        on_click=make_delete_handler(save_id),
                    ).props("flat dense").style("color: #ff5252;").tooltip("Delete")


def _show_fork_dialog(save_id: str, save_path: Path) -> None:
    """Show a dialog to fork (save-as) an existing save."""
    with ui.dialog() as dialog, ui.card().style("min-width: 300px;"):
        ui.label(f'Fork save "{save_id}"').style("color: #ccc; font-weight: bold;")
        ui.label(
            "Create a copy with a new name. The original save is unchanged."
        ).style("color: #999; font-size: 0.85em;")
        name_input = (
            ui.input(label="New save name", value=f"{save_id}-fork")
            .classes("w-full")
            .props("outlined dense dark")
        )

        with ui.row().classes("justify-end gap-2"):
            ui.button("Cancel", on_click=dialog.close).props("flat")

            async def confirm_fork():
                new_name = slugify(name_input.value or "fork")
                try:
                    git_save.save_as(save_path, new_name)
                    ui.notify(f"Forked to '{new_name}'", type="positive")
                    dialog.close()
                    ui.navigate.to("/")  # Refresh to show new save
                except FileExistsError:
                    ui.notify(f"'{new_name}' already exists.", type="negative")
                except Exception as e:
                    ui.notify(f"Fork failed: {e}", type="negative")

            ui.button("Fork", on_click=confirm_fork, icon="call_split").props(
                "flat"
            ).style("color: #42a5f5;")
    dialog.open()


def _show_delete_dialog(save_id: str) -> None:
    """Show a confirmation dialog to delete a save."""
    with ui.dialog() as dialog, ui.card():
        ui.label(f'Delete save "{save_id}"?').style("color: #ccc; font-weight: bold;")
        ui.label("This cannot be undone.").style("color: #ff5252; font-size: 0.85em;")

        with ui.row().classes("justify-end gap-2"):
            ui.button("Cancel", on_click=dialog.close).props("flat")

            async def confirm_delete():
                path = SAVES_DIR / save_id
                if path.exists():
                    shutil.rmtree(path)
                    ui.notify(f"Deleted: {save_id}", type="positive")
                else:
                    ui.notify("Save not found.", type="warning")
                dialog.close()
                ui.navigate.to("/")

            ui.button("Delete", on_click=confirm_delete, color="red").props("flat")
    dialog.open()

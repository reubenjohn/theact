"""Game state sidebar -- collapsible right panel.

Shows live game state: active characters, chapter progress, and game info.
Reads all data from GameSessionState and registers as a listener for
automatic updates after each turn.
"""

from __future__ import annotations

from nicegui import ui

from theact.models.character import Character
from theact.models.memory import CharacterMemory
from theact.web.state import GameSessionState
from theact.web.styles import ERROR_COLOR, SUCCESS_COLOR, get_character_color


def _truncate(text: str, max_len: int = 80) -> str:
    """Truncate text with ellipsis if too long."""
    if len(text) <= max_len:
        return text
    return text[: max_len - 3].rstrip() + "..."


class GameStateSidebar:
    """Collapsible right sidebar showing live game state.

    Reads all data from GameSessionState (shared observable state from Step 00).
    Registers as a state listener so it refreshes automatically after each turn
    or game reload -- no manual update calls needed from the session.
    """

    def __init__(self, state: GameSessionState) -> None:
        self._state = state
        self._visible = True
        self._container: ui.column | None = None

    @property
    def character_list(self) -> list[str]:
        return self._state.character_list

    @property
    def game(self):
        return self._state.game

    def build(self, parent: ui.element) -> None:
        """Create the sidebar DOM within ``parent``.

        Registers as a state listener and calls each @ui.refreshable
        method once for initial render.
        """
        with parent:
            self._container = (
                ui.column()
                .classes(
                    "w-[300px] min-w-[300px] h-full border-l border-gray-700 "
                    "overflow-y-auto p-3 game-sidebar"
                )
                .style("background-color: #111827; max-height: 100vh;")
                .props('data-testid="game-sidebar"')
            )

            with self._container:
                ui.label("Game State").classes("text-lg font-bold mb-2").style(
                    "color: #ccc;"
                )

                # Characters section
                ui.label("Characters").classes("font-bold text-sm mt-2").style(
                    "color: #aaa;"
                )
                self._refresh_characters()

                # Chapter progress section
                ui.separator().classes("my-2")
                ui.label("Chapter Progress").classes("font-bold text-sm").style(
                    "color: #aaa;"
                )
                self._refresh_chapter()

                # Game info section
                ui.separator().classes("my-2")
                ui.label("Game Info").classes("font-bold text-sm").style("color: #aaa;")
                self._refresh_info()

        # Register for automatic updates when state changes
        self._state.add_listener(self.refresh)

    def toggle(self) -> None:
        """Show/hide the sidebar. Called from toolbar button."""
        self._visible = not self._visible
        if self._container:
            self._container.set_visibility(self._visible)

    def refresh(self) -> None:
        """Re-render all sections. Called after each turn.

        NiceGUI's @ui.refreshable requires calling the .refresh()
        attribute on the decorated method, not re-invoking the method.
        """
        self._refresh_characters.refresh()
        self._refresh_chapter.refresh()
        self._refresh_info.refresh()

    # ----- Refreshable sections -----

    @ui.refreshable
    def _refresh_characters(self) -> None:
        """Render character cards for active characters in current chapter."""
        current_chapter_id = self.game.state.current_chapter
        chapter = self.game.chapters.get(current_chapter_id)
        if not chapter:
            ui.label("No chapter loaded").classes("text-sm italic text-gray-500")
            return

        for char_id in chapter.characters:
            char = self.game.characters.get(char_id)
            if not char:
                continue
            memory = self.game.memories.get(char_id)
            self._render_character_card(char, char_id, memory)

    @ui.refreshable
    def _refresh_chapter(self) -> None:
        """Render chapter progress with beat checklist."""
        current_chapter_id = self.game.state.current_chapter
        chapter = self.game.chapters.get(current_chapter_id)
        if not chapter:
            ui.label("No chapter loaded").classes("text-sm italic text-gray-500")
            return

        beats_hit = self.game.state.beats_hit or []

        ui.label(chapter.title).classes("font-bold").style("color: #e0e0e0;")
        ui.label(chapter.summary).classes("text-sm text-gray-400")

        # Completion criteria
        ui.label(f"Goal: {chapter.completion}").classes("text-xs italic mt-1").style(
            "color: #888;"
        )

        # Beats checklist
        ui.separator().classes("my-1")
        total = len(chapter.beats)
        done = len([b for b in chapter.beats if b in beats_hit])
        ui.label(f"{done}/{total} beats completed").classes("text-sm").style(
            "color: #aaa;"
        )
        ui.linear_progress(value=done / total if total else 0).classes("mt-1")

        for beat in chapter.beats:
            hit = beat in beats_hit
            icon = "check_box" if hit else "check_box_outline_blank"
            with ui.row().classes("items-center gap-1"):
                ui.icon(icon, size="xs").style(
                    f"color: {SUCCESS_COLOR if hit else '#666'};"
                )
                ui.label(beat).classes(
                    f"text-sm {'line-through text-gray-500' if hit else ''}"
                ).style(f"color: {'#888' if hit else '#ccc'};")

    @ui.refreshable
    def _refresh_info(self) -> None:
        """Render game metadata: turn, player, flags, summary, history."""
        state = self.game.state

        ui.label(f"Turn {state.turn}").classes("font-bold").style("color: #e0e0e0;")
        ui.label(f"Player: {state.player_name}").classes("text-sm").style(
            "color: #aaa;"
        )

        # Flags as badges
        if state.flags:
            with ui.row().classes("flex-wrap gap-1 mt-1"):
                for key, val in state.flags.items():
                    ui.badge(f"{key}: {val}", color="blue").classes("text-xs")

        # Rolling summary (collapsible)
        if state.rolling_summary:
            with ui.expansion("Rolling Summary").classes("mt-2 w-full"):
                ui.label(state.rolling_summary).classes("text-sm").style("color: #aaa;")

        # Completed chapters
        completed = [
            ch
            for ch_id, ch in self.game.chapters.items()
            if ch_id != state.current_chapter and ch_id in (state.chapter_history or [])
        ]
        if completed:
            ui.label("Completed Chapters").classes("font-bold text-sm mt-2").style(
                "color: #aaa;"
            )
            for ch in completed:
                ui.label(f"  - {ch.title}").classes("text-sm text-gray-500")

    # ----- Character card -----

    def _render_character_card(
        self,
        char: Character,
        char_id: str,
        memory: CharacterMemory | None,
    ) -> None:
        """Render a single character card as an expandable section."""
        color = get_character_color(char_id, self.character_list)

        with (
            ui.expansion(char.name)
            .classes("w-full")
            .props(f'header-style="color: {color};"')
        ):
            # Always-visible summary (shown inside expanded content)
            ui.label(char.role).classes("text-sm").style("color: #999;")
            ui.label(_truncate(char.personality, 80)).classes("text-xs italic").style(
                "color: #888;"
            )

            # Full details
            ui.separator()
            ui.label("Personality").classes("font-bold text-sm").style("color: #ccc;")
            ui.label(char.personality).classes("text-sm").style("color: #aaa;")

            if char.relationships:
                ui.label("Relationships").classes("font-bold text-sm mt-2").style(
                    "color: #ccc;"
                )
                for target, desc in char.relationships.items():
                    ui.label(f"{target}: {desc}").classes("text-sm ml-2").style(
                        "color: #aaa;"
                    )

            if memory:
                ui.label("Memory Summary").classes("font-bold text-sm mt-2").style(
                    "color: #ccc;"
                )
                ui.label(memory.summary).classes("text-sm").style("color: #aaa;")
                if memory.key_facts:
                    ui.label("Key Facts").classes("font-bold text-sm mt-2").style(
                        "color: #ccc;"
                    )
                    for fact in memory.key_facts:
                        ui.label(f"  - {fact}").classes("text-sm").style("color: #aaa;")
            else:
                ui.label("No memories yet").classes("text-sm italic text-gray-400 mt-2")

            # Secret behind spoiler
            if char.secret:
                with ui.expansion("Reveal Secret").classes("mt-2"):
                    ui.label("Spoiler warning!").classes("text-xs").style(
                        f"color: {ERROR_COLOR};"
                    )
                    ui.label(char.secret).classes("text-sm").style("color: #ffab91;")

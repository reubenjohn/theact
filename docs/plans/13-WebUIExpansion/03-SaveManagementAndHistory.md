# Step 03: Save Management & History Browser

> **Implementation note:** Step 00 must be complete. This step depends on Step 01 (Gameplay Toolbar) for the History button in the toolbar. After Step 00, the save table lives in `menu.py` (`MenuBuilder` class), not `app.py` — `app.py` is now slim routing only. The `relative_time()` helper is already available in `components/html_utils.py`. This step modifies `src/theact/web/menu.py` (enhanced saves table), creates `src/theact/web/history.py` (turn history browser), and adds tests in `tests/web/test_history.py`. All git operations use existing APIs in `src/theact/versioning/git_save.py` -- no engine changes required.

---

## 1. Overview

The current web UI has basic save management in the menu: a new game form, a flat table of saves with load buttons, and a delete section with a confirmation dialog. For history, the `/history` slash command renders a text table of git commits, `/undo N` rewinds turns, and `/save-as name` forks saves. But there is no visual browser for turn history, no way to peek at past turns without slash commands, and no diff viewer.

This step:
- **Enhances the menu's save management** with richer card-based layout, fork (save-as) support, and better empty states.
- **Adds a turn history browser** accessible from the gameplay toolbar (Step 01), showing a timeline of all past turns with peek, diff, and restore capabilities.
- **Replaces slash-command-only access** to history/peek/diff with a visual interface, while keeping the slash commands functional for keyboard-oriented users.

---

## 2. Enhanced Saves Table

**File:** `src/theact/web/menu.py` (modify `_build_saves_table` in `MenuBuilder`)

> **Note:** After Step 00, the save table is in `menu.py` (`MenuBuilder` class), not `app.py`. The `relative_time()` helper already exists in `components/html_utils.py` — import it from there instead of defining a new one.

Replace the current row-based saves table with a card-based layout. Each save gets a card with richer information and multiple action buttons.

### 2.1 Save Card Layout

Each save card displays:
- **Title** (bold): the save ID
- **Game name**: from `save_info["game_title"]`
- **Turn count**: `Turn N`
- **Last played**: relative time (e.g., "2 hours ago", "3 days ago") instead of absolute timestamp
- **Chapter name**: requires loading chapter info from the save's `state.yaml`

Action buttons per card:
- **Load** (green, `folder_open` icon) -- loads the save into gameplay
- **Fork** (blue, `call_split` icon) -- opens a dialog to create a copy via `git_save.save_as()`
- **Delete** (red, `delete` icon) -- confirmation dialog, then removes save directory

### 2.2 Relative Time Helper

Step 00 already provides `relative_time()` in `components/html_utils.py`. Import it instead of defining a new helper:

```python
from theact.web.components.html_utils import relative_time
```

The function signature is `relative_time(timestamp: float) -> str` and returns human-readable strings like "just now", "2 hours ago", "3 days ago".

### 2.3 Card-Based Save Layout

```python
def _build_saves_table(
    container: ui.element,
    enter_gameplay: callable,
) -> None:
    """Build the 'Continue Game' section with card-based save layout."""
    saves = list_saves()

    with container:
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
            _build_save_card(save_info, enter_gameplay, container)
```

### 2.4 Individual Save Card

```python
def _build_save_card(
    save_info: dict,
    enter_gameplay: callable,
    parent_container: ui.element,
) -> None:
    """Build a single save card with info and action buttons."""
    save_id = save_info["id"]
    modified = save_info.get("last_modified", 0)
    time_str = relative_time(modified) if modified > 0 else "unknown"

    with ui.card().classes("w-full").style(
        "background: #2a2a2a; border: 1px solid #444; padding: 12px;"
    ):
        with ui.row().classes("w-full items-center"):
            # Left side: save info
            with ui.column().classes("flex-grow gap-0"):
                ui.label(save_id).style(
                    "color: #eee; font-weight: bold; font-size: 1.05em;"
                )
                ui.label(
                    f"{save_info['game_title']}  --  Turn {save_info['turn']}  --  {time_str}"
                ).style("color: #999; font-size: 0.85em;")

            # Right side: action buttons
            with ui.row().classes("gap-1"):
                def make_load_handler(sid: str):
                    async def handler():
                        try:
                            game = load_save(sid)
                            ui.notify(f"Loaded save: {sid}", type="positive")
                            enter_gameplay(game, auto_start=False)
                        except Exception as e:
                            ui.notify(f"Error loading save: {e}", type="negative")
                    return handler

                def make_fork_handler(sid: str, save_path):
                    def handler():
                        _show_fork_dialog(sid, save_path)
                    return handler

                def make_delete_handler(sid: str):
                    def handler():
                        _show_delete_dialog(sid)
                    return handler

                ui.button(icon="folder_open", on_click=make_load_handler(save_id)).props(
                    "flat dense"
                ).style("color: #69f0ae;").tooltip("Load")

                save_path = SAVES_DIR / save_id
                ui.button(icon="call_split", on_click=make_fork_handler(save_id, save_path)).props(
                    "flat dense"
                ).style("color: #42a5f5;").tooltip("Fork")

                ui.button(icon="delete", on_click=make_delete_handler(save_id)).props(
                    "flat dense"
                ).style("color: #ff5252;").tooltip("Delete")
```

### 2.5 Fork Dialog

> **Note:** Step 00 provides `text_input_dialog()` in `components/dialogs.py` for text input dialogs. The fork name input should use this shared builder instead of building a custom dialog. The example below shows the inline approach for reference. Import `from pathlib import Path` and `from theact.versioning import git_save` as needed in `menu.py`.

```python
def _show_fork_dialog(save_id: str, save_path: Path) -> None:
    """Show a dialog to fork (save-as) an existing save."""
    with ui.dialog() as dialog, ui.card().style("min-width: 300px;"):
        ui.label(f'Fork save "{save_id}"').style("color: #ccc; font-weight: bold;")
        ui.label("Create a copy with a new name. The original save is unchanged.").style(
            "color: #999; font-size: 0.85em;"
        )
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

            ui.button("Fork", on_click=confirm_fork, icon="call_split").props("flat").style(
                "color: #42a5f5;"
            )
    dialog.open()
```

### 2.6 Delete Dialog (Inline Per Card)

Move the delete confirmation into a per-card dialog instead of the current separate "Delete Save" section. Remove the standalone `_build_delete_section` from the menu. Each card's delete button opens its own confirmation:

```python
def _show_delete_dialog(save_id: str) -> None:
    """Show a confirmation dialog to delete a save."""
    with ui.dialog() as dialog, ui.card():
        ui.label(f'Delete save "{save_id}"?').style("color: #ccc; font-weight: bold;")
        ui.label("This cannot be undone.").style("color: #ff5252; font-size: 0.85em;")

        with ui.row().classes("justify-end gap-2"):
            ui.button("Cancel", on_click=dialog.close).props("flat")

            async def confirm_delete():
                save_path = SAVES_DIR / save_id
                if save_path.exists():
                    shutil.rmtree(save_path)
                    ui.notify(f"Deleted: {save_id}", type="positive")
                else:
                    ui.notify("Save not found.", type="warning")
                dialog.close()
                ui.navigate.to("/")

            ui.button("Delete", on_click=confirm_delete, color="red").props("flat")
    dialog.open()
```

### 2.7 Updated `MenuBuilder._build_saves_table()`

Remove the standalone delete section. In `src/theact/web/menu.py`, `MenuBuilder._build_saves_table()` replaces the old saves + delete sections with the card-based layout above. The menu's `build()` method calls `_build_saves_table()` after the "New Game" section:

```python
# In MenuBuilder.build(), after the new game section:
ui.separator()
# Enhanced saves table (replaces old saves + delete sections)
saves_container = ui.column().classes("w-full")
self._build_saves_table(saves_container)
```

---

## 3. Turn History Browser

> **NiceGUI constraint:** `ui.right_drawer` must be a direct child of the page content, NOT nested inside other containers. Create the drawer in `app.py`'s `index()` function BEFORE any container elements, then pass it to the session for content management. Alternatively, use `ui.dialog` instead of `ui.right_drawer` -- dialogs can be created from any nesting level and avoid the parent-hierarchy restriction entirely.

**File:** `src/theact/web/history.py` (new)

A visual browser for turn history, accessible from the gameplay toolbar's History button (Step 01). Shows a vertical timeline of all past turns with peek, diff, and restore-to-here capabilities.

### 3.1 Module Structure

```python
"""Turn history browser: timeline, peek viewer, diff viewer, restore.

Opened from the gameplay toolbar. Reads git history from the
current save via git_save APIs.
"""

from __future__ import annotations

import html as html_lib
import logging
from datetime import datetime, timezone

import yaml
from nicegui import ui

from theact.versioning import git_save
from theact.versioning.git_save import TurnInfo

logger = logging.getLogger(__name__)
```

### 3.2 `TurnHistoryBrowser` Class

The browser opens as a right-side drawer (NiceGUI `ui.right_drawer`). It holds three panels: the timeline, the peek viewer, and the diff viewer.

```python
class TurnHistoryBrowser:
    """Visual turn history browser with timeline, peek, and diff."""

    def __init__(
        self,
        save_path: Path,
        current_turn: int,
        on_restore: callable,  # callback(steps: int) -> None
    ) -> None:
        self.save_path = save_path
        self.current_turn = current_turn
        self.on_restore = on_restore  # Called after restore to reload game

        # UI references
        self._drawer: ui.right_drawer | None = None
        self._timeline_container: ui.column | None = None
        self._detail_container: ui.column | None = None

        # State
        self._history: list[TurnInfo] = []
        self._selected_turns: list[int] = []  # For diff mode (max 2)
        self._diff_mode: bool = False

    def build(self, parent: ui.element) -> ui.right_drawer:
        """Build the history browser as a right-side drawer."""
        self._drawer = ui.right_drawer(
            value=False, fixed=False, bordered=True
        ).style("width: 400px; background: #1e1e1e;").classes("q-pa-md")

        with self._drawer:
            self._build_header()
            self._timeline_container = ui.column().classes("w-full gap-1")
            ui.separator()
            self._detail_container = ui.column().classes("w-full")

        return self._drawer

    def open(self) -> None:
        """Open the drawer and refresh the timeline."""
        self._refresh_timeline()
        if self._drawer:
            self._drawer.value = True

    def close(self) -> None:
        """Close the drawer."""
        if self._drawer:
            self._drawer.value = False
```

### 3.3 Header and Mode Toggle

```python
    def _build_header(self) -> None:
        """Build the header with title and mode toggle."""
        with ui.row().classes("w-full items-center justify-between"):
            ui.label("Turn History").style(
                "color: #ccc; font-weight: bold; font-size: 1.1em;"
            )
            with ui.row().classes("gap-1"):
                ui.button(icon="compare_arrows", on_click=self._toggle_diff_mode).props(
                    "flat dense"
                ).style("color: #999;").tooltip("Compare two turns")
                ui.button(icon="close", on_click=self.close).props(
                    "flat dense"
                ).style("color: #999;")
```

### 3.4 Timeline Rendering

```python
    def _refresh_timeline(self) -> None:
        """Reload git history and render the timeline."""
        self._history = git_save.get_history(self.save_path)
        self._selected_turns.clear()

        if self._timeline_container:
            self._timeline_container.clear()

        if not self._history:
            with self._timeline_container:
                ui.label("No turns yet.").style("color: #888;")
            return

        with self._timeline_container:
            for entry in self._history:  # Most recent first (git log order)
                self._build_turn_entry(entry)

    def _build_turn_entry(self, entry: TurnInfo) -> None:
        """Build a single turn entry in the timeline."""
        # Parse timestamp for display
        try:
            ts = datetime.fromisoformat(entry.timestamp)
            time_str = ts.strftime("%H:%M")
        except (ValueError, TypeError):
            time_str = "?"

        # Truncate commit message to summary
        summary = entry.message.replace(f"Turn {entry.turn}: ", "", 1)
        if len(summary) > 60:
            summary = summary[:57] + "..."

        is_current = entry.turn == self.current_turn

        with ui.card().classes("w-full").style(
            f"background: {'#2d3748' if is_current else '#252525'}; "
            f"border-left: 3px solid {'#69f0ae' if is_current else '#555'}; "
            f"padding: 8px; cursor: pointer;"
        ):
            with ui.row().classes("w-full items-center"):
                # Turn number badge
                ui.badge(str(entry.turn)).style(
                    f"background: {'#69f0ae' if is_current else '#555'}; "
                    f"color: {'#000' if is_current else '#ccc'};"
                )
                # Summary and time
                with ui.column().classes("flex-grow gap-0"):
                    ui.label(summary).style("color: #ccc; font-size: 0.85em;")
                    ui.label(time_str).style("color: #666; font-size: 0.75em;")

                # Action buttons
                if self._diff_mode:
                    self._build_diff_select_button(entry)
                else:
                    self._build_turn_actions(entry)

    def _build_turn_actions(self, entry: TurnInfo) -> None:
        """Build View and Restore buttons for a turn entry."""
        turn_num = entry.turn

        def make_view_handler(t: int):
            def handler():
                self._show_peek(t)
            return handler

        def make_restore_handler(t: int):
            def handler():
                self._confirm_restore(t)
            return handler

        with ui.row().classes("gap-0"):
            ui.button(icon="visibility", on_click=make_view_handler(turn_num)).props(
                "flat dense round"
            ).style("color: #42a5f5;").tooltip("View snapshot")

            if turn_num < self.current_turn:
                ui.button(icon="restore", on_click=make_restore_handler(turn_num)).props(
                    "flat dense round"
                ).style("color: #ffa726;").tooltip("Restore to here")
```

---

## 4. Turn Peek Viewer

When the user clicks "View" on a historical turn, call `git_save.peek_at_turn(save_path, turn_number)` and display the results in the detail panel below the timeline.

### 4.1 Peek Display

```python
    def _show_peek(self, turn_number: int) -> None:
        """Display a read-only snapshot of a historical turn."""
        if self._detail_container:
            self._detail_container.clear()

        try:
            files = git_save.peek_at_turn(self.save_path, turn_number)
        except ValueError as e:
            with self._detail_container:
                ui.label(f"Error: {e}").style("color: #ff5252;")
            return

        with self._detail_container:
            ui.label(f"Turn {turn_number} -- Historical Snapshot (read-only)").style(
                "color: #ffa726; font-weight: bold; font-size: 0.95em; margin-bottom: 8px;"
            )

            # Game State (state.yaml)
            if "state.yaml" in files:
                self._render_state_panel(files["state.yaml"])

            # Conversation (conversation.yaml) -- entries for this turn only
            if "conversation.yaml" in files:
                self._render_conversation_panel(files["conversation.yaml"], turn_number)

            # Character Memories (memory/*.yaml)
            memory_files = {k: v for k, v in files.items() if k.startswith("memory/")}
            if memory_files:
                self._render_memories_panel(memory_files)
```

### 4.2 State Panel

```python
    def _render_state_panel(self, state_yaml: str) -> None:
        """Render game state from state.yaml content."""
        with ui.expansion("Game State", icon="flag").classes("w-full"):
            try:
                state = yaml.safe_load(state_yaml)
                if isinstance(state, dict):
                    items = [
                        f"Turn: {state.get('turn', '?')}",
                        f"Chapter: {state.get('current_chapter', '?')}",
                        f"Player: {state.get('player_name', '?')}",
                    ]
                    beats = state.get("beats_hit", [])
                    if beats:
                        items.append(f"Beats: {', '.join(beats)}")
                    flags = state.get("flags", {})
                    if flags:
                        items.append(f"Flags: {flags}")
                    for item in items:
                        ui.label(item).style("color: #ccc; font-size: 0.85em;")
                else:
                    ui.code(state_yaml, language="yaml").classes("w-full")
            except yaml.YAMLError:
                ui.code(state_yaml, language="yaml").classes("w-full")
```

### 4.3 Conversation Panel

```python
    def _render_conversation_panel(self, conv_yaml: str, turn_number: int) -> None:
        """Render conversation entries for the specified turn."""
        with ui.expansion("Conversation", icon="chat").classes("w-full"):
            try:
                entries = yaml.safe_load(conv_yaml)
                if isinstance(entries, list):
                    turn_entries = [e for e in entries if e.get("turn") == turn_number]
                    if not turn_entries:
                        ui.label("No entries for this turn.").style("color: #888;")
                        return
                    for entry in turn_entries:
                        role = entry.get("role", "?")
                        character = entry.get("character", "")
                        content = entry.get("content", "")
                        # Truncate long content
                        if len(content) > 300:
                            content = content[:297] + "..."
                        label = character if role == "character" else role.capitalize()
                        ui.label(f"{label}: {content}").style(
                            "color: #ccc; font-size: 0.85em; margin-bottom: 4px;"
                        )
                else:
                    ui.code(conv_yaml, language="yaml").classes("w-full")
            except yaml.YAMLError:
                ui.code(conv_yaml, language="yaml").classes("w-full")
```

### 4.4 Memories Panel

```python
    def _render_memories_panel(self, memory_files: dict[str, str]) -> None:
        """Render character memory snapshots."""
        with ui.expansion("Character Memories", icon="psychology").classes("w-full"):
            for filepath, content in sorted(memory_files.items()):
                char_name = filepath.replace("memory/", "").replace(".yaml", "")
                try:
                    mem = yaml.safe_load(content)
                    if isinstance(mem, dict):
                        summary = mem.get("summary", "No summary")
                        facts = mem.get("key_facts", [])
                        ui.label(f"{mem.get('character', char_name)}").style(
                            "color: #69f0ae; font-weight: bold; font-size: 0.85em;"
                        )
                        ui.label(f"  {summary}").style("color: #ccc; font-size: 0.8em;")
                        for fact in facts[:5]:
                            ui.label(f"  - {fact}").style(
                                "color: #999; font-size: 0.8em;"
                            )
                    else:
                        ui.code(content, language="yaml").classes("w-full")
                except yaml.YAMLError:
                    ui.code(content, language="yaml").classes("w-full")
```

---

## 5. Turn Diff Viewer

"Compare" mode lets the user select two turns from the timeline and view a unified diff of what changed between them.

### 5.1 Diff Mode Toggle

```python
    def _toggle_diff_mode(self) -> None:
        """Toggle between normal mode and diff comparison mode."""
        self._diff_mode = not self._diff_mode
        self._selected_turns.clear()

        if self._detail_container:
            self._detail_container.clear()

        if self._diff_mode:
            with self._detail_container:
                ui.label("Select two turns to compare.").style(
                    "color: #999; font-size: 0.85em;"
                )

        # Re-render timeline with appropriate buttons
        self._refresh_timeline()
```

### 5.2 Diff Turn Selection

```python
    def _build_diff_select_button(self, entry: TurnInfo) -> None:
        """Build a select/deselect button for diff mode."""
        is_selected = entry.turn in self._selected_turns

        def make_toggle_handler(t: int):
            def handler():
                if t in self._selected_turns:
                    self._selected_turns.remove(t)
                elif len(self._selected_turns) < 2:
                    self._selected_turns.append(t)
                    if len(self._selected_turns) == 2:
                        self._show_diff()
                # Re-render timeline to update selection state
                self._refresh_timeline()
            return handler

        ui.button(
            icon="check_circle" if is_selected else "radio_button_unchecked",
            on_click=make_toggle_handler(entry.turn),
        ).props("flat dense round").style(
            f"color: {'#42a5f5' if is_selected else '#666'};"
        )
```

### 5.3 Diff Display

```python
    def _show_diff(self) -> None:
        """Show the unified diff between two selected turns."""
        if len(self._selected_turns) != 2:
            return

        turn_a, turn_b = sorted(self._selected_turns)

        if self._detail_container:
            self._detail_container.clear()

        try:
            diff_text = git_save.diff_turns(self.save_path, turn_a, turn_b)
        except ValueError as e:
            with self._detail_container:
                ui.label(f"Error: {e}").style("color: #ff5252;")
            return

        with self._detail_container:
            ui.label(f"Diff: Turn {turn_a} vs Turn {turn_b}").style(
                "color: #42a5f5; font-weight: bold; font-size: 0.95em; margin-bottom: 8px;"
            )

            if not diff_text.strip():
                ui.label("No differences found.").style("color: #888;")
                return

            # Parse diff to identify changed files
            changed_files = set()
            for line in diff_text.splitlines():
                if line.startswith("diff --git"):
                    # Extract filename from "diff --git a/file b/file"
                    parts = line.split()
                    if len(parts) >= 4:
                        changed_files.add(parts[3].removeprefix("b/"))

            if changed_files:
                ui.label(f"Changed files: {', '.join(sorted(changed_files))}").style(
                    "color: #999; font-size: 0.8em; margin-bottom: 8px;"
                )

            # Render diff with syntax highlighting
            # Use ui.html with color-coded lines for +/- highlighting
            html_lines = []
            for line in diff_text.splitlines():
                escaped = html_lib.escape(line)
                if line.startswith("+") and not line.startswith("+++"):
                    html_lines.append(
                        f'<div style="color: #69f0ae; font-family: monospace; '
                        f'font-size: 0.8em; background: #1a3a1a; padding: 1px 4px;">'
                        f'{escaped}</div>'
                    )
                elif line.startswith("-") and not line.startswith("---"):
                    html_lines.append(
                        f'<div style="color: #ff5252; font-family: monospace; '
                        f'font-size: 0.8em; background: #3a1a1a; padding: 1px 4px;">'
                        f'{escaped}</div>'
                    )
                elif line.startswith("@@"):
                    html_lines.append(
                        f'<div style="color: #42a5f5; font-family: monospace; '
                        f'font-size: 0.8em; padding: 1px 4px;">{escaped}</div>'
                    )
                else:
                    html_lines.append(
                        f'<div style="color: #999; font-family: monospace; '
                        f'font-size: 0.8em; padding: 1px 4px;">{escaped}</div>'
                    )

            ui.html("\n".join(html_lines)).style(
                "max-height: 400px; overflow-y: auto; "
                "background: #1a1a1a; border: 1px solid #333; border-radius: 4px; "
                "padding: 8px;"
            )
```

---

## 6. History-Based Undo (Restore to Here)

Each past turn in the timeline has a "Restore to here" button. This provides a visual alternative to the `/undo N` slash command.

### 6.1 Restore Confirmation

```python
    def _confirm_restore(self, target_turn: int) -> None:
        """Show a confirmation dialog before restoring to a past turn."""
        steps = self.current_turn - target_turn
        if steps <= 0:
            ui.notify("Cannot restore to the current or a future turn.", type="warning")
            return

        with ui.dialog() as dialog, ui.card():
            ui.label(f"Restore to Turn {target_turn}?").style(
                "color: #ccc; font-weight: bold;"
            )
            ui.label(
                f"This will undo {steps} turn{'s' if steps != 1 else ''}. "
                f"This cannot be reversed."
            ).style("color: #ffa726; font-size: 0.9em;")
            ui.label(
                "Tip: Use Fork first to keep a copy of the current state."
            ).style("color: #888; font-size: 0.8em;")

            with ui.row().classes("justify-end gap-2"):
                ui.button("Cancel", on_click=dialog.close).props("flat")

                async def confirm():
                    dialog.close()
                    try:
                        new_turn = git_save.undo(self.save_path, steps)
                        self.current_turn = new_turn
                        ui.notify(
                            f"Restored to turn {new_turn}.",
                            type="positive",
                        )
                        # Notify the session to reload
                        if self.on_restore:
                            self.on_restore(steps)
                        # Close the drawer after restore
                        self.close()
                    except ValueError as e:
                        ui.notify(f"Restore failed: {e}", type="negative")

                ui.button("Restore", on_click=confirm, icon="restore").props(
                    "flat"
                ).style("color: #ffa726;")
        dialog.open()
```

---

## 7. Integration with Gameplay Session

### 7.1 Session Additions

**File:** `src/theact/web/session.py`

Add the history browser to `GameplaySession`:

```python
from theact.web.history import TurnHistoryBrowser

class GameplaySession:
    def __init__(self, ...):
        ...
        self._history_browser: TurnHistoryBrowser | None = None

    def build(self, container: ui.element) -> None:
        with container:
            ...
            # Build history browser (drawer, initially closed)
            self._history_browser = TurnHistoryBrowser(
                save_path=self._state.game.save_path,
                current_turn=self._state.game.state.turn,
                on_restore=self._on_history_restore,
            )
            self._history_browser.build(container)

    def open_history(self) -> None:
        """Open the turn history browser. Called from toolbar button."""
        if self._history_browser:
            self._history_browser.current_turn = self._state.game.state.turn
            self._history_browser.open()

    def _on_history_restore(self, steps: int) -> None:
        """Callback after history-based restore. Reloads game and re-renders."""
        self._state.reload_game()
        self._chat_area.clear()
        self._render_history()
        self._update_header()

        # Update the history browser's current turn reference
        if self._history_browser:
            self._history_browser.current_turn = self._state.game.state.turn
```

### 7.2 Toolbar Integration

The toolbar's History button (from Step 01) calls `session.open_history()`. If Step 01 is not yet implemented, the history browser can also be triggered by the existing `/history` command as a progressive enhancement -- the text table continues to work, but a new `/history-browser` command or a button in the chat header can open the visual browser.

### 7.3 Post-Turn Update

After each turn completes (`_play_turn` in `session.py`), update the history browser's current turn so the timeline stays in sync:

```python
    async def _play_turn(self, player_input: str) -> None:
        ...
        # After successful turn
        if self._history_browser:
            self._history_browser.current_turn = self._state.game.state.turn
```

---

## 8. Tests

**File:** `tests/web/test_history.py`

Browser tests using Playwright, following the pattern in `tests/web/test_menu.py`.

### 8.1 Test Plan

```python
"""Browser integration tests for turn history and enhanced save management.

Uses pytest-playwright's ``page`` fixture and the session-scoped
``web_server`` fixture from conftest.py.

Run with:  uv run pytest tests/web/test_history.py -v
"""

from playwright.sync_api import expect


class TestSavesTable:
    """Tests for the enhanced saves table on the menu page."""

    def test_continue_game_label_visible(self, page, web_server):
        page.goto(web_server)
        expect(page.get_by_text("Continue Game")).to_be_visible()

    def test_empty_state_when_no_saves(self, page, web_server):
        """With no saves, the empty state message should be visible."""
        page.goto(web_server)
        # This test may need a clean saves directory
        # If saves exist, they should appear as cards instead
        saves = page.locator("[role='button']", has_text="Load")
        # At minimum, the section should render without error

    def test_save_cards_have_action_buttons(self, page, web_server):
        """Each save card should have Load, Fork, and Delete buttons."""
        page.goto(web_server)
        # Create a save first (via the new game form), then verify buttons
        # This requires a game to exist in games/
        pass  # Implementation depends on test fixtures

    def test_fork_button_opens_dialog(self, page, web_server):
        """Clicking Fork should open a dialog with a name input."""
        page.goto(web_server)
        # Requires an existing save
        fork_buttons = page.locator("button", has=page.locator("[data-icon='call_split']"))
        if fork_buttons.count() > 0:
            fork_buttons.first.click()
            expect(page.get_by_text("Fork save")).to_be_visible()


class TestHistoryBrowser:
    """Tests for the turn history browser during gameplay."""

    def test_history_button_exists_in_gameplay(self, page, web_server):
        """After loading a game, a History button should be accessible."""
        # This test depends on Step 01 toolbar; skip if toolbar not yet built
        pass

    def test_history_timeline_entries(self, page, web_server):
        """The history timeline should show one entry per completed turn."""
        # Requires a save with multiple turns
        pass

    def test_peek_shows_snapshot(self, page, web_server):
        """Clicking View on a turn should show a read-only snapshot."""
        # Requires a save with completed turns
        pass
```

### 8.2 Test Notes

- Tests that require existing saves will need either a pre-created test save directory or a fixture that creates one via `create_save()` + multiple `run_turn()` calls.
- History browser tests depend on Step 01 (toolbar). If the toolbar is not yet built, these tests should be marked `@pytest.mark.skip` or use an alternative entry point.
- The peek and diff tests require saves with at least 2-3 completed turns, which means the test fixture needs an LLM API key. Consider marking these as integration tests that only run when `LLM_API_KEY` is set.
- **Breaking change:** `tests/web/test_menu.py::TestMenuDeleteSection` must be updated or removed since the standalone "Delete Save" section is being replaced by per-card delete buttons. Replace those assertions with tests that verify the per-card delete button opens a confirmation dialog (covered by `TestSavesTable` above).

---

## 9. What This Step Does NOT Do

- **No engine changes.** All features use existing `git_save` and `save_manager` APIs as-is.
- **No new LLM calls.** The history browser is purely a UI over git data. No model inference.
- **No changes to git versioning.** The commit format, undo mechanism, and diff logic are unchanged.
- **No multi-user or locking.** If multiple tabs modify the same save, behavior is undefined (Step 08 addresses this).
- **No search or filtering.** The timeline shows all turns. Filtering by content or date range is out of scope.
- **No auto-save or periodic snapshots.** Saves remain one-commit-per-turn.
- **No changes to slash commands.** `/history`, `/undo`, `/save-as` continue to work as text commands alongside the visual UI.

---

## 10. Verification

After implementation, confirm the following:

1. **Saves table** shows all saves as cards with title, game, turn, relative time, and Load/Fork/Delete buttons.
2. **Empty state** displays a helpful message when no saves exist (no blank screen or error).
3. **Sort order** is most-recently-modified first.
4. **Fork** opens a dialog, creates a new save via `git_save.save_as()`, and refreshes the menu to show both the original and the fork.
5. **Delete** per card opens a confirmation dialog and removes the save directory. The menu refreshes to reflect the deletion.
6. **Standalone delete section** is removed from the menu (superseded by per-card delete buttons).
7. **History browser** opens as a right-side drawer when triggered from the toolbar or session.
8. **Timeline** shows all past turns with turn number, commit summary, and timestamp, most recent first.
9. **Current turn** is visually highlighted in the timeline (green border and badge).
10. **Peek viewer** displays game state, conversation entries (filtered to the selected turn), and character memories as expansion panels.
11. **Peek is read-only** -- clearly labeled, and no modifications to the save are made.
12. **Diff mode** allows selecting two turns and displays a color-coded unified diff.
13. **Changed files summary** appears above the diff output.
14. **Restore to here** calculates correct step count, shows a confirmation with the step count, calls `git_save.undo()`, reloads the game, re-renders conversation, updates the header, and closes the history browser.
15. **Post-turn sync** -- after playing a new turn, the history browser's current turn reference updates so the timeline stays accurate on next open.
16. **All existing tests pass** (`uv run pytest tests/`) -- no regressions in menu or gameplay tests.

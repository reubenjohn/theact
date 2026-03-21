# Step 01: Gameplay Toolbar & Quick Actions

> **Implementation note:** This step has no prerequisites beyond the existing web UI (Phase 07). All commands already exist in `src/theact/web/commands.py` — this step wraps them in clickable buttons and adds a turn info display. No engine changes are needed. The existing `TurnResult` data model already contains all fields used by the turn info bar (mood, beats_hit, chapter_advanced). NiceGUI patterns used here (icon buttons, dialogs, expansion panels) are already established in `src/theact/web/app.py` and `src/theact/web/components.py`.

## 1. Overview

The web UI gameplay view currently requires all actions to be typed as slash commands (`/undo`, `/retry`, `/save-as <name>`, `/history`, etc.). There are no clickable buttons for common actions, no visual display of turn result metadata (mood, beats hit, chapter advancement), and no input enhancements beyond a plain text field.

This step adds three things:

1. **Gameplay toolbar** — a row of icon buttons below the header bar for the most common actions (Undo, Retry, Save As, History). Each button triggers the same logic as the corresponding slash command but with a better UX (confirmation dialogs, name input dialogs).

2. **Turn info bar** — after each turn completes, a subtle info line inside the turn card showing mood, new beats hit, and chapter advancement. The session already renders a basic version of this (lines 266-285 of `session.py`); this step replaces it with a structured, color-coded component.

3. **Input improvements** — a command hint dropdown when the user types `/`, and contextual placeholder text.

### What This Step Does NOT Do

- No sidebar or game state panel — that is Step 02.
- No turn history timeline or peek/diff viewer — that is Step 03.
- No changes to the turn engine, agents, or data models.
- No changes to `src/theact/web/commands.py` function signatures — the toolbar calls existing functions.
- No new slash commands — existing slash commands continue to work unchanged.
- No mobile-specific layout — that is Step 08.

---

## 2. Toolbar Component

**New file:** `src/theact/web/toolbar.py`

### 2.1 Class Signature

```python
"""Gameplay toolbar with quick-action buttons.

Provides clickable icon buttons for common actions that currently
require slash commands. Each button calls existing command functions
from commands.py or versioning/git_save.py.
"""

from __future__ import annotations

from typing import Callable, Awaitable

from nicegui import ui


class GameplayToolbar:
    """Row of icon buttons for common gameplay actions.

    Args:
        on_undo: Async callback for undo action. Receives number of steps.
        on_retry: Async callback for retry action.
        on_save_as: Async callback for save-as action. Receives new save name.
        on_history: Callback to open the history panel.
        is_processing: Callable that returns True when a turn is in progress.
    """

    def __init__(
        self,
        on_undo: Callable[[int], Awaitable[None]],
        on_retry: Callable[[], Awaitable[None]],
        on_save_as: Callable[[str], Awaitable[None]],
        on_history: Callable[[], None],
        is_processing: Callable[[], bool],
    ) -> None:
        self._on_undo = on_undo
        self._on_retry = on_retry
        self._on_save_as = on_save_as
        self._on_history = on_history
        self._is_processing = is_processing

        # UI references (set during build)
        self._undo_btn: ui.button | None = None
        self._retry_btn: ui.button | None = None
        self._save_as_btn: ui.button | None = None
        self._history_btn: ui.button | None = None

    def build(self, container: ui.element) -> None:
        """Build the toolbar row inside the given container."""
        ...

    def set_enabled(self, enabled: bool) -> None:
        """Enable or disable all toolbar buttons."""
        ...
```

### 2.2 Button Layout

The toolbar is a `ui.row` rendered between the header bar and the chat scroll area. Buttons use NiceGUI's `ui.button` with the `icon` parameter and `flat dense` props for a compact appearance. Each button has a tooltip.

```python
def build(self, container: ui.element) -> None:
    with container:
        with ui.row().classes("w-full items-center px-2 py-1 gap-1").style(
            "border-bottom: 1px solid #333;"
        ):
            self._undo_btn = (
                ui.button(icon="undo", on_click=self._show_undo_dialog)
                .props('flat dense data-testid="toolbar-undo"')
                .tooltip("Undo last turn")
                .style("color: #999;")
            )
            self._retry_btn = (
                ui.button(icon="refresh", on_click=self._handle_retry)
                .props('flat dense data-testid="toolbar-retry"')
                .tooltip("Retry last turn")
                .style("color: #999;")
            )
            self._save_as_btn = (
                ui.button(icon="fork_right", on_click=self._show_save_as_dialog)
                .props('flat dense data-testid="toolbar-save-as"')
                .tooltip("Fork save")
                .style("color: #999;")
            )
            self._history_btn = (
                ui.button(icon="history", on_click=self._handle_history)
                .props('flat dense data-testid="toolbar-history"')
                .tooltip("Turn history")
                .style("color: #999;")
            )
```

### 2.3 Enable/Disable During Processing

All buttons must be disabled while a turn is processing (the `_processing` flag on `GameplaySession`). The `set_enabled` method toggles all buttons:

```python
def set_enabled(self, enabled: bool) -> None:
    for btn in [self._undo_btn, self._retry_btn, self._save_as_btn, self._history_btn]:
        if btn is not None:
            if enabled:
                btn.enable()
            else:
                btn.disable()
```

The session calls `self._toolbar.set_enabled(False)` in `_lock_input()` and `self._toolbar.set_enabled(True)` in `_unlock_input()`.

### 2.4 Button Click Handlers

Each handler checks `self._is_processing()` as a guard, then either opens a dialog or directly invokes the callback:

```python
def _show_undo_dialog(self) -> None:
    """Show undo confirmation dialog with step count input."""
    if self._is_processing():
        return
    # See Section 6 for dialog implementation
    ...

async def _handle_retry(self) -> None:
    """Invoke the retry callback directly (no confirmation needed)."""
    if self._is_processing():
        return
    await self._on_retry()

def _show_save_as_dialog(self) -> None:
    """Show save-as dialog with name input."""
    if self._is_processing():
        return
    # See Section 6 for dialog implementation
    ...

def _handle_history(self) -> None:
    """Invoke the history callback."""
    if self._is_processing():
        return
    self._on_history()
```

---

## 3. Turn Info Bar

### 3.1 Purpose

After each turn completes, display a color-coded info line inside the turn card showing:
- **Mood** — from `TurnResult.narrator.mood` (e.g., "tense", "peaceful"). Displayed as a subtle gray label.
- **Beats hit** — from `TurnResult.game_state.beats_hit` (list of beat strings). Each beat shown in green.
- **Chapter advancement** — if `TurnResult.chapter_advanced` is `True`, show the new chapter name in gold.

### 3.2 Component Function

Add a new function to `src/theact/web/components.py`:

```python
def create_turn_info_bar(
    container: ui.element,
    mood: str | None,
    beats_hit: list[str],
    chapter_advanced: bool,
    new_chapter: str | None,
) -> None:
    """Render a color-coded turn info line inside a turn card.

    Args:
        container: The turn card element to append into.
        mood: Narrator mood string, or None.
        beats_hit: List of beat descriptions hit this turn.
        chapter_advanced: Whether the chapter advanced.
        new_chapter: New chapter ID if chapter_advanced is True.
    """
    ...
```

### 3.3 Implementation

```python
from theact.web.styles import MOOD_COLOR, BEAT_COLOR, CHAPTER_ADVANCE_COLOR

def create_turn_info_bar(
    container: ui.element,
    mood: str | None,
    beats_hit: list[str],
    chapter_advanced: bool,
    new_chapter: str | None,
) -> None:
    has_content = mood or beats_hit or chapter_advanced
    if not has_content:
        return

    with container:
        with ui.row().classes("w-full items-center gap-3 mt-2").style(
            "border-top: 1px solid #333; padding-top: 6px;"
        ):
            if mood:
                ui.label(f"Mood: {mood}").style(
                    f"color: {MOOD_COLOR}; font-size: 0.75em; font-style: italic;"
                )

            if beats_hit:
                for beat in beats_hit:
                    ui.badge(beat, color="green").props("outline").style(
                        "font-size: 0.7em;"
                    )

            if chapter_advanced and new_chapter:
                ui.badge(
                    f"Chapter: {new_chapter}", color="amber"
                ).props("outline").style("font-size: 0.7em;")
```

### 3.4 Style Constants

Add to `src/theact/web/styles.py`:

```python
# --- Turn info bar ---
BEAT_COLOR = "#69f0ae"          # green, matches character palette
CHAPTER_ADVANCE_COLOR = "#ffd740"  # gold/amber
MOOD_COLOR = "#888888"          # subtle gray
```

### 3.5 Data Flow

```
run_turn() returns TurnResult
    |
    v
session._play_turn() receives result
    |
    v
create_turn_info_bar(
    turn_card,
    mood=result.narrator.mood,
    beats_hit=result.game_state.beats_hit if result.game_state else [],
    chapter_advanced=result.chapter_advanced,
    new_chapter=result.new_chapter,
)
    |
    v
Color-coded badges/labels rendered inside the turn card
```

This replaces the existing inline info rendering in `session.py` lines 266-285 (the `info_parts` list joined with `" | "`). Remove that block and replace with a call to `create_turn_info_bar`.

---

## 4. Input Improvements

### 4.1 Command Hint Dropdown

When the user types `/` as the first character in the input field, show a dropdown of available commands. Use NiceGUI's `ui.menu` anchored to the input field.

**Implementation approach:**

Add an `on_value_change` handler to the input field that checks if the current value starts with `/`:

```python
def _build_input_bar(self) -> None:
    with ui.row().classes("w-full items-center p-2 gap-2").style(
        "border-top: 1px solid #444;"
    ):
        # Command hint menu (hidden by default)
        self._cmd_menu = ui.menu().props("auto-close")
        with self._cmd_menu:
            for cmd, desc in COMMAND_HINTS:
                ui.menu_item(
                    f"/{cmd} — {desc}",
                    on_click=lambda c=cmd: self._insert_command(c),
                )

        self._input_field = (
            ui.input(placeholder="What do you do?")
            .classes("flex-grow")
            .props("outlined dense dark")
            .on("keydown.enter", self._on_submit)
        )
        self._input_field.on_value_change(self._on_input_change)

        self._send_button = ui.button(
            "Send", on_click=self._on_submit, icon="send"
        ).props("dense")
```

**Command hints list** — define in `session.py` or import from `commands.py`:

```python
COMMAND_HINTS: list[tuple[str, str]] = [
    ("undo", "Undo last N turns"),
    ("retry", "Retry last turn"),
    ("save-as", "Fork save"),
    ("history", "Turn history"),
    ("status", "Game status"),
    ("memory", "Character memory"),
    ("conversation", "Recent entries"),
    ("think", "Toggle thinking"),
    ("save", "Save info"),
    ("help", "All commands"),
    ("quit", "Return to menu"),
]
```

**Input change handler:**

```python
def _on_input_change(self, e) -> None:
    """Show command hints when input starts with '/'."""
    value = e.value or ""
    if value == "/":
        self._cmd_menu.open()
    else:
        self._cmd_menu.close()

def _insert_command(self, cmd: str) -> None:
    """Insert a command into the input field."""
    self._input_field.value = f"/{cmd} "
    self._input_field.run_method("focus")
```

### 4.2 Contextual Placeholder

The input field currently shows a static "What do you do?" placeholder. Enhance it to cycle through contextual hints based on game state. This is optional polish — implement only if time allows.

```python
def _get_placeholder(self) -> str:
    """Return a contextual placeholder for the input field."""
    if self.game.state.turn == 0:
        return "The story begins..."
    if self._last_player_input:
        return "What do you do next?"
    return "What do you do?"
```

### 4.3 Multiline Input (Shift+Enter)

NiceGUI's `ui.input` is single-line. For multiline support, replace with `ui.textarea` and handle Enter vs Shift+Enter:

```python
self._input_field = (
    ui.textarea(placeholder="What do you do?")
    .classes("flex-grow")
    .props("outlined dense dark rows=1 auto-grow")
)
```

Use a JavaScript handler to distinguish Enter (submit) from Shift+Enter (newline):

```python
self._input_field.on(
    "keydown.enter",
    handler=self._on_submit,
    # Prevent submission on Shift+Enter
    js_handler="(e) => { if (e.shiftKey) e.stopPropagation(); }",
)
```

**Note:** Test whether `ui.textarea` with `rows=1 auto-grow` produces an acceptable single-line appearance that expands. If it looks too different from the current `ui.input`, keep `ui.input` and skip multiline support in this step.

---

## 5. Integration with GameplaySession

### 5.1 Modifications to `src/theact/web/session.py`

**Import the toolbar:**

```python
from theact.web.toolbar import GameplayToolbar
from theact.web.components import create_turn_info_bar
```

**Add toolbar to `__init__`:**

```python
def __init__(self, game, llm_config, on_quit) -> None:
    ...
    self._toolbar: GameplayToolbar | None = None
```

**Instantiate toolbar in `build()`:**

Insert the toolbar between the header and the chat scroll area:

```python
def build(self, container: ui.element) -> None:
    with container:
        self._gameplay_container = (
            ui.column()
            .classes("w-full max-w-3xl mx-auto")
            .style("min-height: 100vh;")
        )

        with self._gameplay_container:
            # --- Header bar ---
            self._build_header()

            # --- Toolbar (NEW) ---
            self._toolbar = GameplayToolbar(
                on_undo=self._toolbar_undo,
                on_retry=self._toolbar_retry,
                on_save_as=self._toolbar_save_as,
                on_history=self._toolbar_history,
                is_processing=lambda: self._processing,
            )
            self._toolbar.build(self._gameplay_container)

            # --- Chat area ---
            self._chat_scroll = (
                ui.scroll_area()
                .classes("w-full flex-grow")
                .style("height: calc(100vh - 180px);")  # Adjusted for toolbar
            )
            ...
```

**Note:** The chat scroll height changes from `calc(100vh - 140px)` to approximately `calc(100vh - 180px)` to account for the toolbar row. Adjust the exact value during implementation.

### 5.2 Toolbar Callback Methods

Add these methods to `GameplaySession`:

```python
async def _toolbar_undo(self, steps: int = 1) -> None:
    """Toolbar undo callback: undo N turns and re-render."""
    reloaded, message = cmd_undo_web(self.game, [str(steps)])
    if reloaded is None:
        ui.notify(message, type="warning")
        return
    self.game = reloaded
    ui.notify(message, type="info")
    self._chat_area.clear()
    self._render_history()
    self._update_header()

async def _toolbar_retry(self) -> None:
    """Toolbar retry callback: undo last turn and replay."""
    await self._cmd_retry()

async def _toolbar_save_as(self, name: str) -> None:
    """Toolbar save-as callback: fork save to new name."""
    cmd_save_as_web(self.game, [name])

def _toolbar_history(self) -> None:
    """Toolbar history callback: show history in chat area.

    In Step 03, this will open the history panel instead.
    """
    cmd_history_web(self._chat_area, self.game)
    if self._chat_scroll:
        self._chat_scroll.scroll_to(percent=1.0)
```

### 5.3 Lock/Unlock Integration

Modify `_lock_input` and `_unlock_input` to also toggle the toolbar:

```python
def _lock_input(self) -> None:
    self._processing = True
    if self._input_field:
        self._input_field.disable()
    if self._send_button:
        self._send_button.disable()
    if self._toolbar:
        self._toolbar.set_enabled(False)

def _unlock_input(self) -> None:
    self._processing = False
    if self._input_field:
        self._input_field.enable()
        self._input_field.run_method("focus")
    if self._send_button:
        self._send_button.enable()
    if self._toolbar:
        self._toolbar.set_enabled(True)
```

### 5.4 Replace Inline Turn Info with `create_turn_info_bar`

In `_play_turn()`, replace lines 266-285 (the `info_parts` block) with:

```python
# Show turn info bar (replaces inline info_parts)
create_turn_info_bar(
    turn_card,
    mood=result.narrator.mood,
    beats_hit=result.game_state.beats_hit if result.game_state else [],
    chapter_advanced=result.chapter_advanced,
    new_chapter=result.new_chapter,
)
```

Remove the old `info_parts` list assembly and the `ui.label(" | ".join(info_parts))` call entirely. Also remove the `char_names` resolution block (lines 271-276) since `create_turn_info_bar` does not display responding characters — that information is already visible from the character response blocks above.

---

## 6. Confirmation Dialogs

### 6.1 Undo Confirmation Dialog

The undo button opens a dialog that asks how many turns to undo (defaulting to 1) and requires confirmation. This prevents accidental undo clicks.

```python
def _show_undo_dialog(self) -> None:
    """Show undo confirmation dialog with step count input."""
    if self._is_processing():
        return

    with ui.dialog() as dialog, ui.card():
        ui.label("Undo Turns").style("font-weight: bold; color: #ccc;")
        ui.label("How many turns to undo?").style("color: #999;")

        steps_input = (
            ui.number(label="Steps", value=1, min=1, max=100)
            .props("outlined dense dark")
            .style("width: 100px;")
        )

        with ui.row().classes("justify-end gap-2 mt-2"):
            ui.button("Cancel", on_click=dialog.close).props("flat")

            async def confirm():
                steps = int(steps_input.value or 1)
                dialog.close()
                await self._on_undo(steps)

            ui.button("Undo", on_click=confirm).props("flat").style(
                "color: #ff9800;"
            )

    dialog.open()
```

### 6.2 Save-As Name Input Dialog

The save-as button opens a dialog with a text field for the new save name.

```python
def _show_save_as_dialog(self) -> None:
    """Show save-as dialog with name input."""
    if self._is_processing():
        return

    with ui.dialog() as dialog, ui.card():
        ui.label("Fork Save").style("font-weight: bold; color: #ccc;")
        ui.label("Enter a name for the new save:").style("color: #999;")

        name_input = (
            ui.input(label="Save name", placeholder="my-save-fork")
            .props("outlined dense dark")
            .classes("w-full")
        )

        with ui.row().classes("justify-end gap-2 mt-2"):
            ui.button("Cancel", on_click=dialog.close).props("flat")

            async def confirm():
                name = (name_input.value or "").strip()
                if not name:
                    ui.notify("Please enter a save name.", type="warning")
                    return
                dialog.close()
                await self._on_save_as(name)

            ui.button("Create", on_click=confirm).props("flat").style(
                "color: #69f0ae;"
            )

    dialog.open()
```

### 6.3 Dialog Pattern

Both dialogs follow the same pattern already used for delete confirmation in `app.py` (lines 288-306):
- Create dialog with `ui.dialog() as dialog, ui.card()`
- Add content and inputs inside the card
- Add Cancel (calls `dialog.close()`) and Confirm buttons in a `ui.row`
- Call `dialog.open()` to show it

---

## 7. Tests

**New file:** `tests/web/test_toolbar.py`

Tests use the same Playwright-based pattern as `tests/web/test_gameplay.py`: a session-scoped web server fixture, a module-scoped test save, and a `gameplay_page` fixture that navigates to the gameplay view.

### 7.1 Test Cases

```python
"""Browser tests for the gameplay toolbar.

Tests toolbar buttons, confirmation dialogs, and turn info display.
Uses the same web server and test save fixtures as test_gameplay.py.

Run with:  uv run pytest tests/web/test_toolbar.py -v
"""

import shutil
from pathlib import Path

import pytest
from playwright.sync_api import expect

from theact.io.save_manager import SAVES_DIR, create_save

_TEST_SAVE_ID = "pw-test-toolbar"


@pytest.fixture(scope="module", autouse=True)
def ensure_test_save():
    """Create a test save for toolbar tests."""
    save_path = SAVES_DIR / _TEST_SAVE_ID
    if not save_path.exists():
        create_save("lost-island", _TEST_SAVE_ID, "TestPlayer")
    yield
    if save_path.exists():
        shutil.rmtree(save_path)


@pytest.fixture
def gameplay_page(page, web_server, ensure_test_save):
    """Navigate to the gameplay view by loading the test save."""
    page.goto(web_server)
    page.wait_for_load_state("networkidle")
    save_row = page.locator(f"text={_TEST_SAVE_ID}").first
    load_btn = save_row.locator("..").get_by_role("button", name="Load")
    load_btn.click()
    page.locator('input[placeholder="What do you do?"]').wait_for(
        state="visible", timeout=10000
    )
    return page


class TestToolbarButtons:
    """Test that toolbar buttons are visible and interactive."""

    def test_toolbar_buttons_visible(self, gameplay_page):
        """All four toolbar buttons should be visible."""
        page = gameplay_page
        expect(page.locator('[data-testid="toolbar-undo"]')).to_be_visible()
        expect(page.locator('[data-testid="toolbar-retry"]')).to_be_visible()
        expect(page.locator('[data-testid="toolbar-save-as"]')).to_be_visible()
        expect(page.locator('[data-testid="toolbar-history"]')).to_be_visible()

    def test_undo_button_opens_dialog(self, gameplay_page):
        """Clicking the undo button should open a confirmation dialog."""
        page = gameplay_page
        page.locator('[data-testid="toolbar-undo"]').click()
        # Dialog should contain "Undo Turns" text and a Cancel button
        expect(page.get_by_text("Undo Turns")).to_be_visible()
        expect(page.get_by_role("button", name="Cancel")).to_be_visible()
        # Close the dialog
        page.get_by_role("button", name="Cancel").click()

    def test_save_as_button_opens_dialog(self, gameplay_page):
        """Clicking the save-as button should open a name input dialog."""
        page = gameplay_page
        page.locator('[data-testid="toolbar-save-as"]').click()
        expect(page.get_by_text("Fork Save")).to_be_visible()
        expect(page.get_by_role("button", name="Cancel")).to_be_visible()
        page.get_by_role("button", name="Cancel").click()


class TestToolbarHistory:
    """Test the history button functionality."""

    def test_history_button_shows_output(self, gameplay_page):
        """Clicking history should render history content in chat area."""
        page = gameplay_page
        page.locator('[data-testid="toolbar-history"]').click()
        # Should show either history content or "No turn history yet."
        # (depends on whether the test save has any turns)
        page.wait_for_timeout(500)
        # Verify no error occurred (no red error labels)
        expect(page.locator("text=Error")).not_to_be_visible()
```

### 7.2 Locator Strategy

NiceGUI renders Quasar components. The toolbar buttons use `icon` parameter which renders as a `<q-icon>` or `<i>` element inside the button. The exact DOM structure depends on the NiceGUI/Quasar version. During implementation, inspect the rendered DOM to determine the correct Playwright locator strategy. Alternatives:

- Use `.tooltip()` text: `page.get_by_role("button", name="Undo last turn")`
- Use `aria-label` if NiceGUI sets it from the tooltip
- Use a test ID: add `.props('data-testid="undo-btn"')` to each button for reliable selection

**Recommendation:** Add `data-testid` props to toolbar buttons for test reliability:

```python
self._undo_btn = (
    ui.button(icon="undo", on_click=self._show_undo_dialog)
    .props('flat dense data-testid="toolbar-undo"')
    .tooltip("Undo last turn")
    .style("color: #999;")
)
```

Then in tests:
```python
page.locator('[data-testid="toolbar-undo"]').click()
```

---

## 8. Verification Criteria

All of the following must be true after implementation:

1. **Toolbar visible.** The gameplay view shows a row of four icon buttons (Undo, Retry, Save As, History) between the header and the chat area.

2. **Undo dialog.** Clicking the Undo button opens a confirmation dialog with a numeric step input (default 1) and Cancel/Undo buttons. Confirming executes the undo, re-renders conversation, and updates the header.

3. **Retry works.** Clicking the Retry button undoes the last turn and replays the previous player input (same behavior as `/retry`).

4. **Save-as dialog.** Clicking the Save As button opens a dialog with a text input for the new save name. Confirming creates the fork and shows a notification.

5. **History works.** Clicking the History button renders turn history in the chat area (same behavior as `/history`). In Step 03 this will be replaced with a history panel.

6. **Buttons disabled during processing.** While a turn is streaming, all toolbar buttons are disabled. They re-enable when the turn completes.

7. **Turn info bar.** After each turn completes, the turn card shows a color-coded info line: mood in gray italic, beats as green badges, chapter advancement as a gold badge. Turns with no metadata show no info bar.

8. **Command hints.** Typing `/` in the input field shows a dropdown of available commands. Clicking a command inserts it into the input field.

9. **No regression.** All existing slash commands (`/undo`, `/retry`, `/save-as`, `/history`, `/status`, `/memory`, `/think`, `/conversation`, `/save`, `/help`, `/quit`) continue to work when typed in the input field. Existing browser tests in `tests/web/test_gameplay.py` still pass.

10. **New tests pass.** All tests in `tests/web/test_toolbar.py` pass.

---

## 9. File Change Summary

| File | Action | Description |
|------|--------|-------------|
| `src/theact/web/toolbar.py` | **NEW** | `GameplayToolbar` class with icon buttons and dialog methods |
| `src/theact/web/session.py` | MODIFY | Import toolbar, instantiate in `build()`, add callback methods, integrate with lock/unlock, replace inline turn info with `create_turn_info_bar` |
| `src/theact/web/components.py` | MODIFY | Add `create_turn_info_bar()` function |
| `src/theact/web/styles.py` | MODIFY | Add `BEAT_COLOR`, `CHAPTER_ADVANCE_COLOR`, `MOOD_COLOR` constants |
| `tests/web/test_toolbar.py` | **NEW** | Playwright browser tests for toolbar buttons and dialogs |

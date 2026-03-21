# Step 02: Game State Sidebar

> **Implementation note:** Step 00 must be complete. The sidebar reads from `GameSessionState` (shared observable state) and registers as a listener for automatic updates. This step adds a collapsible right sidebar to the gameplay view that persistently displays character info, chapter progress, and game metadata. It replaces the need for `/memory`, `/status`, and `/conversation` slash commands during web gameplay. All sidebar sections update reactively after each turn via the state listener pattern.

## 1. Overview

The current web UI gameplay view is a single-column chat interface. To inspect game state — characters, memories, chapter beats, flags — the player must type slash commands (`/memory`, `/status`, `/conversation`). The web UI has ample screen real estate to show this information persistently.

This step adds a **collapsible right sidebar** with three sections:

- **Characters** — cards for each active character with expandable memory/personality details
- **Chapter Progress** — current chapter title, beat checklist, completion criteria
- **Game Info** — turn counter, player name, flags, rolling summary, chapter history

The sidebar:

- Defaults to **open** on viewports >= 1024px, **closed** on narrower screens
- Can be toggled open/closed via a toolbar button (from Step 01)
- Updates reactively after each turn completes
- Does not interfere with the chat column's scroll position or input focus

## 2. Sidebar Component

**New file:** `src/theact/web/sidebar.py`

Create a `GameStateSidebar` class that owns all sidebar rendering and refresh logic.

```python
from theact.web.state import GameSessionState

class GameStateSidebar:
    """Collapsible right sidebar showing live game state.

    Reads all data from GameSessionState (shared observable state from Step 00).
    Registers as a state listener so it refreshes automatically after each turn
    or game reload — no manual update calls needed from the session.
    """

    def __init__(self, state: GameSessionState) -> None:
        self._state = state        # access game via self._state.game
        self._visible = True       # toggled by toolbar button
        self._container = None     # reference to the outer ui.column

    @property
    def character_list(self) -> list[str]:
        return self._state.character_list

    @property
    def game(self):
        return self._state.game

    def build(self, parent: ui.element) -> None:
        """Create the sidebar DOM within `parent`.

        Registers as a state listener and calls each @ui.refreshable
        method once for initial render.
        """
        ...
        # Register for automatic updates when state changes
        self._state.add_listener(self.refresh)
        # Initial render of refreshable sections
        self._refresh_characters()
        self._refresh_chapter()
        self._refresh_info()

    def toggle(self) -> None:
        """Show/hide the sidebar. Called from toolbar button."""
        self._visible = not self._visible
        self._container.set_visibility(self._visible)

    def refresh(self) -> None:
        """Re-render all sections. Called after each turn.

        NiceGUI's @ui.refreshable requires calling the .refresh()
        attribute on the decorated method, not re-invoking the method.
        """
        self._refresh_characters.refresh()
        self._refresh_chapter.refresh()
        self._refresh_info.refresh()

    @ui.refreshable
    def _refresh_characters(self) -> None: ...

    @ui.refreshable
    def _refresh_chapter(self) -> None: ...

    @ui.refreshable
    def _refresh_info(self) -> None: ...
```

**Width:** ~300px fixed when open. When closed, the sidebar collapses entirely (no icon strip in this iteration — the toolbar toggle re-opens it).

**Styling:** Use a right-side `ui.column` with `classes('w-[300px] min-w-[300px] border-l overflow-y-auto')` and a max-height tied to the viewport.

## 3. Characters Section

Renders one expandable card per **active character** in the current chapter (i.e., characters listed in the current `Chapter.characters`).

```python
@ui.refreshable
def _refresh_characters(self) -> None:
    current_chapter = self.game.chapters[self.game.state.current_chapter]
    for char_id in current_chapter.characters:
        char = self.game.characters[char_id]
        memory = self.game.memories.get(char_id)
        self._render_character_card(char, memory)
```

Each card is a `ui.expansion`:

```python
def _render_character_card(self, char: Character, memory: CharacterMemory | None) -> None:
    color = get_character_color(char.name, self.character_list)  # from styles.py
    with ui.expansion(char.name).classes('w-full'):
        # Header (always visible)
        ui.label(char.role).classes('text-sm text-gray-500')
        ui.label(_truncate(char.personality, 80)).classes('text-xs italic')

        # Expanded content
        ui.separator()
        ui.label('Personality').classes('font-bold text-sm')
        ui.label(char.personality).classes('text-sm')

        if char.relationships:
            ui.label('Relationships').classes('font-bold text-sm mt-2')
            for target, desc in char.relationships.items():
                ui.label(f'{target}: {desc}').classes('text-sm ml-2')

        if memory:
            ui.label('Memory Summary').classes('font-bold text-sm mt-2')
            ui.label(memory.summary).classes('text-sm')
            if memory.key_facts:
                ui.label('Key Facts').classes('font-bold text-sm mt-2')
                for fact in memory.key_facts:
                    ui.label(f'  - {fact}').classes('text-sm')
        else:
            ui.label('No memories yet').classes('text-sm italic text-gray-400 mt-2')

        # Secret — hidden behind spoiler
        if char.secret:
            with ui.expansion('Reveal Secret').classes('mt-2 text-red-400'):
                ui.label('Spoiler warning!').classes('text-xs text-red-300')
                ui.label(char.secret).classes('text-sm')
```

The character name label in the expansion header should use the character's assigned color from `src/theact/web/styles.py` (the same palette used for chat message headers).

## 4. Chapter Progress Section

Shows the current chapter and beat completion status.

```python
@ui.refreshable
def _refresh_chapter(self) -> None:
    chapter = self.game.chapters[self.game.state.current_chapter]
    beats_hit = self.game.state.beats_hit or []

    ui.label(f'Chapter: {chapter.title}').classes('font-bold')
    ui.label(chapter.summary).classes('text-sm text-gray-400')

    # Completion criteria
    ui.label(f'Goal: {chapter.completion}').classes('text-xs italic mt-1')

    # Beats checklist
    ui.separator()
    total = len(chapter.beats)
    done = len([b for b in chapter.beats if b in beats_hit])
    ui.label(f'{done}/{total} beats completed').classes('text-sm')
    ui.linear_progress(value=done / total if total else 0).classes('mt-1')

    for beat in chapter.beats:
        hit = beat in beats_hit
        icon = 'check_box' if hit else 'check_box_outline_blank'
        with ui.row().classes('items-center gap-1'):
            ui.icon(icon, size='xs')
            ui.label(beat).classes(f'text-sm {"line-through text-gray-500" if hit else ""}')
```

When the chapter advances (detected via `TurnResult.chapter_advanced`), briefly apply a highlight class to the chapter title (e.g., a 2-second CSS animation via `ui.notify` or a temporary class).

## 5. Game Info Section

Displays metadata and the rolling summary.

```python
@ui.refreshable
def _refresh_info(self) -> None:
    state = self.game.state

    ui.label(f'Turn {state.turn}').classes('font-bold')
    ui.label(f'Player: {state.player_name}').classes('text-sm')

    # Flags as chips (state.flags is a dict)
    if state.flags:
        with ui.row().classes('flex-wrap gap-1 mt-1'):
            for key, val in state.flags.items():
                ui.badge(f"{key}: {val}", color='blue').classes('text-xs')

    # Rolling summary (collapsible — can be long)
    if state.rolling_summary:
        with ui.expansion('Rolling Summary').classes('mt-2'):
            ui.label(state.rolling_summary).classes('text-sm')

    # Chapter history
    completed = [
        ch for ch_id, ch in self.game.chapters.items()
        if ch_id != state.current_chapter
        and ch_id in (state.chapter_history or [])
    ]
    if completed:
        ui.label('Completed Chapters').classes('font-bold text-sm mt-2')
        for ch in completed:
            ui.label(f'  - {ch.title}').classes('text-sm text-gray-500')
```

## 6. Layout Integration

**Modified file:** `src/theact/web/session.py` (the slim orchestrator from Step 00)

After Step 00, `session.py` (`GameplaySession`) is a thin orchestrator (~120 lines) that delegates to `GameSessionState`, `TurnRunner`, `StreamRenderer`, and `CommandRouter`. The sidebar integrates into this pattern by receiving the shared `GameSessionState` and registering as a listener.

The gameplay view currently renders a single chat column. Change it to a two-column flexbox layout.

**Note:** The existing `max-w-3xl` (768px) constraint on both `app.py` and `session.py` containers must be widened to `max-w-6xl` or removed when the sidebar is present. The sidebar adds 300px and the chat column needs room to remain usable.

```python
# In the gameplay page builder (session.py orchestrator):
with ui.row().classes('w-full h-full'):
    # Main chat area — takes remaining space
    with ui.column().classes('flex-grow h-full overflow-hidden'):
        # existing chat log + input
        ...

    # Sidebar — reads from shared GameSessionState
    sidebar = GameStateSidebar(state=self._state)
    with ui.column().classes('w-[300px] min-w-[300px] h-full border-l border-gray-700 overflow-y-auto bg-gray-900 p-3'):
        sidebar.build(parent=ui.element.default_slot.parent)
```

The toolbar (from Step 01) gets a toggle button:

```python
ui.button(icon='info', on_click=sidebar.toggle).tooltip('Toggle game state sidebar')
```

**Session state:** Store `sidebar` reference on the session object so the turn-completion callback can call `sidebar.refresh()`. The `_visible` flag survives across turns because the `GameStateSidebar` instance persists for the session lifetime.

## 7. Reactive Updates

After each turn completes, the turn-completion callback in the session must refresh the sidebar:

```python
async def on_turn_complete(result: TurnResult) -> None:
    # ... existing chat append logic ...

    # Refresh sidebar with latest game state
    sidebar.refresh()
```

Specific update triggers:

| Data changed | Sidebar section affected | Source |
|---|---|---|
| `MemoryDiff` returned | Characters (memory summary + key facts) | `TurnResult.memory_diffs` |
| `GameStateResult.beats_hit` changed | Chapter Progress (checklist + bar) | `TurnResult.game_state_result` |
| `TurnResult.chapter_advanced` is True | Chapter Progress (new chapter) | `TurnResult` |
| Turn counter incremented | Game Info (turn number) | `LoadedGame.state.turn` |
| New flags set | Game Info (flag chips) | `LoadedGame.state.flags` |

Because all three `@ui.refreshable` methods re-read from `self.game` (which is a reference to the live `LoadedGame`), calling `sidebar.refresh()` after the game state is persisted is sufficient — no explicit data passing needed.

**Note:** After Step 00, the sidebar reads from `GameSessionState` and registers as a listener via `self._state.add_listener(self.refresh)`. When the game is reloaded (e.g., undo or retry), updating `self._state.game` automatically triggers all listeners — no manual reference update or explicit `sidebar.refresh()` call is needed from the session.

## 8. Responsive Behavior

On narrow viewports (below 1024px), the sidebar should not consume layout space.

**Strategy:** Use NiceGUI's `ui.drawer` (right-side) as the sidebar container on narrow screens, and a fixed `ui.column` on wide screens. Detect viewport width with a small JavaScript snippet on page load:

```python
async def _setup_responsive(self) -> None:
    width = await ui.run_javascript('window.innerWidth')
    if width < 1024:
        self._visible = False
        self._container.set_visibility(False)
```

Alternatively, use a single `ui.drawer` with `value=True` (open by default) and `elevated=True`, which NiceGUI renders as an overlay on small screens and inline on large screens. The toggle button always works regardless of viewport size.

A resize listener can be added later, but for this step, the initial viewport check on page load is sufficient.

## 9. Tests

**New file:** `tests/web/test_sidebar.py`

All tests use the Playwright-based browser testing pattern established in `tests/web/test_gameplay.py`: sync `def` functions with the `web_server` fixture (not `async def` with `running_app`).

```python
def test_sidebar_visible_in_gameplay(page, web_server, gameplay_page):
    """Sidebar is present in the gameplay view."""
    sidebar = gameplay_page.locator('[data-testid="game-sidebar"]')
    expect(sidebar).to_be_visible()

def test_character_cards_rendered(page, web_server, gameplay_page, loaded_game):
    """Each active character in the current chapter has a card."""
    chapter = loaded_game.chapters[loaded_game.state.current_chapter]
    for char_id in chapter.characters:
        card = gameplay_page.locator(f'text={loaded_game.characters[char_id].name}')
        expect(card).to_be_visible()

def test_chapter_beats_displayed(page, web_server, gameplay_page, loaded_game):
    """Chapter progress section shows beat items."""
    chapter = loaded_game.chapters[loaded_game.state.current_chapter]
    for beat in chapter.beats:
        expect(gameplay_page.locator(f'text={beat}')).to_be_visible()

def test_sidebar_toggle(page, web_server, gameplay_page):
    """Toggle button hides and re-shows the sidebar."""
    sidebar = gameplay_page.locator('[data-testid="game-sidebar"]')
    toggle = gameplay_page.locator('[aria-label="Toggle game state sidebar"]')

    expect(sidebar).to_be_visible()
    toggle.click()
    expect(sidebar).to_be_hidden()
    toggle.click()
    expect(sidebar).to_be_visible()
```

Tests should add `data-testid="game-sidebar"` to the sidebar container to make assertions stable.

## 10. What This Step Does NOT Do

- **Edit character data from the sidebar.** The sidebar is read-only. Editing character files or memories is out of scope.
- **Real-time streaming updates.** The sidebar refreshes once per turn after all agents complete, not mid-turn while agents are running.
- **Drag-to-resize sidebar.** Width is fixed at ~300px. A resizable splitter could be added later.
- **Sidebar on the CLI.** This is web-only. The terminal CLI continues to use slash commands.
- **Multiple sidebar tabs or panels.** All three sections stack vertically in a single scrollable column. Tabbed navigation is a future refinement.
- **Map or visual chapter graph.** Chapter progress is a checklist, not a visual flowchart.
- **Persist sidebar open/closed state across sessions.** State lives on the in-memory session object and resets on page reload.

## 11. Verification

After implementation, confirm:

1. **Characters section** — All active characters in the current chapter appear with correct names and colors from `styles.py`. Clicking a card expands to show personality, relationships, memory summary, and key facts. Characters with no memory show "No memories yet". Secret is hidden behind a spoiler expansion.
2. **Chapter progress section** — Current chapter title and summary are correct. Beat checklist accurately reflects `state.beats_hit` (checked vs. unchecked). Progress bar fraction matches. When the chapter advances, the new chapter title appears.
3. **Game info section** — Turn counter increments after each turn. Player name is correct. Flags render as chips. Rolling summary is collapsible and shows current text. Completed chapters are listed.
4. **Reactive updates** — After a turn completes, all three sections reflect the new game state without a page reload.
5. **Toggle** — Toolbar button hides and re-shows the sidebar. Chat column expands to fill the freed space when sidebar is hidden.
6. **Responsive** — On viewports below 1024px, the sidebar starts collapsed. The toggle button opens it as an overlay or drawer that does not push the chat column.
7. **No regressions** — Existing web UI tests (`tests/web/`) continue to pass. Chat input focus and scroll behavior are unaffected by the sidebar.

# Step 08: Polish, Responsiveness & Safety

> **Implementation note:** This is the final polish pass for the Web UI expansion. It addresses robustness gaps (multi-tab safety, refresh recovery), responsiveness (mobile/tablet layout), and UX improvements (keyboard shortcuts, error retry, loading states). These changes cut across many existing files rather than introducing major new features. The `filelock` package is added as an optional web dependency.
>
> **Step 00 refactoring:** After Step 00, the web architecture has changed significantly. `GameplaySession` is now a thin orchestrator delegating to `GameSessionState` (observable state with listener pattern), `TurnRunner` (turn execution), `StreamRenderer` (streaming display), and `CommandRouter` (command dispatch). `app.py` is slim routing only. `commands/logic.py` contains shared command logic as pure functions returning `CommandResult`. The `components/` package provides reusable UI building blocks. These separations affect how each polish item integrates — see per-section notes below.

---

## 1. Overview

The web UI is functional but has several gaps in robustness and polish:

- **No multi-tab safety** — Two browser tabs can load the same save and cause git corruption.
- **No refresh recovery** — Browser refresh drops back to menu, losing session state.
- **No mobile layout** — UI is desktop-only with fixed widths.
- **No keyboard shortcuts** — Everything requires mouse clicks.
- **No error retry** — If a turn fails mid-stream, user must type input again.
- **No loading states** — Some operations (save loading, game creation) lack feedback.

This step addresses all of the above in a single pass. The changes are mostly additive — new modules for safety, CSS for responsiveness, and small tweaks to existing UI code.

---

## 2. Multi-Tab File Locking

**New file:** `src/theact/web/safety.py`

This module prevents two tabs from writing to the same save simultaneously, which would corrupt the git history.

### Approach

Use the `filelock` Python package to acquire an exclusive lock file inside the save directory.

```python
# src/theact/web/safety.py
from filelock import FileLock, Timeout
from pathlib import Path


class SaveLock:
    """Manages exclusive access to a save directory."""

    def __init__(self, save_path: Path):
        self._lock_path = save_path / ".lock"
        self._lock = FileLock(self._lock_path, timeout=0)  # non-blocking
        self._acquired = False

    def acquire(self) -> bool:
        """Try to acquire the lock. Returns True if successful."""
        try:
            self._lock.acquire(timeout=0)
            self._acquired = True
            return True
        except Timeout:
            return False

    def release(self):
        """Release the lock if held."""
        if self._acquired:
            self._lock.release()
            self._acquired = False

    @property
    def is_locked(self) -> bool:
        return self._acquired
```

### Preventing lock file from being committed to git

The `.lock` file lives inside the save directory, which is a git repo. The engine's `repo.git.add(A=True)` call would stage the lock file. To prevent this, ensure that the save directory's `.gitignore` excludes the lock file. When initializing a new save's git repo (or on first lock creation), add a `.gitignore` entry:

```python
gitignore_path = save_path / ".gitignore"
if not gitignore_path.exists() or ".lock" not in gitignore_path.read_text():
    with open(gitignore_path, "a") as f:
        f.write("\n.lock\n")
```

Alternatively, place lock files in a temp directory outside the save (e.g., `/tmp/theact-locks/{save_id}.lock`). This avoids any git interaction but loses the filesystem locality. The `.gitignore` approach is simpler.

### Integration with gameplay page

When a save is loaded in the gameplay page:

1. Create a `SaveLock` for `saves/{save-id}/`.
2. Call `lock.acquire()`.
3. If lock acquisition fails, show a warning dialog:

```python
async def _check_save_lock(self):
    self._save_lock = SaveLock(self._state.game.save_path)
    if not self._save_lock.acquire():
        with ui.dialog() as dlg, ui.card():
            ui.label("This save is open in another tab.")
            ui.label("Opening it here may cause data corruption.")
            with ui.row():
                ui.button("Open Read-Only", on_click=lambda: self._enter_readonly(dlg))
                ui.button("Force Unlock", on_click=lambda: self._force_unlock(dlg))
                ui.button("Back to Menu", on_click=lambda: self._back_to_menu(dlg))
        dlg.open()
```

### Lock release

The lock must be released when the user leaves the gameplay page:

- **Quit to menu** — release in the quit handler.
- **Tab close / navigate away** — use NiceGUI's `ui.context.client.on_delete` handler. Unlike `app.on_disconnect` (which fires on every transient disconnect, including brief network blips), `on_delete` fires only after the reconnect timeout expires, meaning the tab is truly gone:

```python
ui.context.client.on_delete(lambda: self._save_lock.release() if self._save_lock else None)
```

- **Ungraceful shutdown** — `filelock` uses `fcntl.flock()` under the hood on Linux/macOS, which automatically releases the lock when the process dies. No stale-lock timer is needed.

### Dependencies

Add `filelock` to the optional `[web]` dependency group in `pyproject.toml`:

```toml
[project.optional-dependencies]
web = ["nicegui>=3.9.0", "filelock>=3.12"]
```

---

## 3. Browser Refresh Recovery

Use NiceGUI's `app.storage.tab` to persist session state across browser refreshes. This storage is backed by a server-side dict keyed by a tab-specific cookie, so it survives page reloads.

> **Note:** After Step 00, session state is centralized in `GameSessionState` (in `state.py`) with an observable listener pattern. This makes it cleaner to serialize/restore — the state to persist is well-defined in one place rather than scattered across the session object. Write the relevant `GameSessionState` fields to `app.storage.tab` and restore them on refresh.

### Stored state

On entering gameplay, write to `app.storage.tab`:

```python
app.storage.tab["save_id"] = save_id
app.storage.tab["in_gameplay"] = True
app.storage.tab["show_thinking"] = self._show_thinking
```

### Recovery on page load

In the main page handler, check for an active session before showing the menu:

```python
@ui.page("/")
async def index():
    # Must wait for WebSocket connection before accessing tab storage
    await ui.context.client.connected()
    tab = app.storage.tab
    if tab.get("in_gameplay") and tab.get("save_id"):
        save_id = tab["save_id"]
        save_path = Path(f"saves/{save_id}")
        if save_path.exists():
            # Restore session — skip menu, go directly to gameplay
            game = load_save(save_id)
            await enter_gameplay(game, show_thinking=tab.get("show_thinking", False))
            return
        else:
            # Save no longer exists — clear stale state, fall through to menu
            tab.clear()
    show_menu()
```

### Clearing state

Clear `app.storage.tab` when the user explicitly quits to menu:

```python
def _quit_to_menu(self):
    self._save_lock.release()
    app.storage.tab.clear()
    ui.navigate.to("/")
```

Recovery is best-effort. If the save directory has been deleted or moved, the UI falls back to the menu gracefully.

> **Note:** `app.storage.tab` is stored in server memory and does not persist across server restarts. Refresh recovery only works within the same server lifetime. There is no Redis or persistent backing store — if the server process restarts, all tab storage is lost and the user will see the menu on next load.

---

## 4. Responsive Layout

Use CSS media queries injected via `ui.add_css()` or NiceGUI's `ui.query` to adapt the layout at three breakpoints.

### Breakpoints

| Range | Target | Layout |
|-------|--------|--------|
| >1024px | Desktop | Full layout with sidebar visible |
| 768–1024px | Tablet | Sidebar collapsed by default, toolbar compressed |
| <768px | Mobile | Sidebar hidden (drawer), toolbar as dropdown, full-width chat |

### Implementation

Add a shared CSS file or inject styles in the page setup:

```python
ui.add_css("""
/* Mobile: <768px */
@media (max-width: 767px) {
    .sidebar { display: none !important; }
    .turn-card { padding: 0.5rem !important; }
    .input-bar { flex-direction: column; }
    .input-bar .q-input { width: 100% !important; }
    .input-bar .q-btn { width: 100% !important; margin-top: 0.25rem; }
    .menu-columns { flex-direction: column !important; }
}

/* Tablet: 768–1024px */
@media (min-width: 768px) and (max-width: 1024px) {
    .sidebar { width: 250px !important; }
    .toolbar-extras { display: none !important; }
}
""")
```

### Sidebar as drawer on mobile

> **Note:** Pure CSS media queries are strongly preferred over Python-side viewport detection (`ui.run_javascript("window.innerWidth")`). JS-based detection requires a round-trip, causes a flash of wrong layout, and does not respond to window resizes. Instead, build **both** the drawer and the sidebar, and use CSS to show the appropriate one at each breakpoint.

```python
# Build both layouts; CSS controls which is visible
with ui.left_drawer() as drawer:
    self._build_sidebar()
drawer.classes("mobile-sidebar")  # visible only on mobile via CSS

with ui.column().classes("sidebar desktop-sidebar"):
    self._build_sidebar()

ui.button(icon="menu", on_click=drawer.toggle).classes("mobile-menu-btn")
```

```css
/* Desktop: show sidebar, hide drawer toggle */
@media (min-width: 768px) {
    .mobile-sidebar { display: none !important; }
    .mobile-menu-btn { display: none !important; }
}
/* Mobile: show drawer, hide sidebar */
@media (max-width: 767px) {
    .desktop-sidebar { display: none !important; }
}
```

### Input bar on mobile

The input field and send button stack vertically on mobile, each taking full width. This is handled by the CSS above (`.input-bar { flex-direction: column; }`).

### Menu layout

The menu page currently uses side-by-side columns for "Load Game" and "New Game." On mobile these stack vertically via the `.menu-columns` rule.

---

## 5. Keyboard Shortcuts

> **Note:** After Step 00, `GameplaySession` is a thin orchestrator. Keyboard handlers should call methods on the session, which delegates to the appropriate component: `CommandRouter` for commands like undo and save-as, `TurnRunner` for turn-related actions, and `GameSessionState` for state toggles like sidebar visibility. Do not put business logic directly in keyboard handlers.

### Implementation

Use NiceGUI's `ui.keyboard` component to listen for key events:

```python
def _setup_keyboard_shortcuts(self):
    # Set ignore=[] so events fire even when an input/textarea is focused.
    # The handler only acts on modifier key combos (Ctrl+key) and Escape,
    # so normal typing in input fields is unaffected.
    keyboard = ui.keyboard(on_key=self._handle_key, ignore=[])

async def _handle_key(self, e):
    if not e.action.keydown:
        return
    if e.key == "z" and e.modifiers.ctrl:
        await self._confirm_undo()
    elif e.key == "s" and e.modifiers.ctrl:
        await self._show_save_as_dialog()
    elif e.key == "h" and e.modifiers.ctrl:
        self._toggle_history_browser()
    elif e.key == "b" and e.modifiers.ctrl:
        self._toggle_sidebar()
    elif e.key.escape:
        self._close_open_dialogs()
```

### Shortcut reference

| Shortcut | Action |
|----------|--------|
| `Enter` | Submit input (default textarea behavior) |
| `Ctrl+Z` | Undo last turn (with confirmation dialog via `components/dialogs.py`'s `confirm_dialog()`, then delegates to `self._command_router.execute("undo", ...)`) |
| `Ctrl+S` | Open save-as dialog |
| `Ctrl+H` | Toggle history browser |
| `Ctrl+B` | Toggle sidebar |
| `Escape` | Close open dialogs/drawers |

### Preventing browser defaults

For shortcuts like `Ctrl+S` that have browser-default behavior (save page), use JavaScript to prevent the default:

```python
ui.run_javascript("""
document.addEventListener('keydown', function(e) {
    if ((e.ctrlKey || e.metaKey) && ['s', 'h', 'b'].includes(e.key)) {
        e.preventDefault();
    }
});
""")
```

### Discoverability

- Add tooltip text to toolbar buttons showing the shortcut (e.g., "Undo (Ctrl+Z)").
- Include shortcut reference in the `/help` command output if a help system exists.

---

## 6. Error Retry Mechanism

When `run_turn()` throws an exception during streaming, the user should be able to retry without retyping their input.

> **Note:** After Step 00, `TurnRunner` handles turn execution and `GameSessionState` holds the game state. Retry logic calls `state.reload_game()` to discard partial mutations, then calls `TurnRunner.run()` again with the same player input.

### Current behavior

The gameplay page already stores `_last_player_input`. Errors during streaming are caught and displayed in the turn card.

### Enhanced behavior

In the turn execution flow, after catching an error:

```python
async def _play_turn(self, player_input: str):
    self._last_player_input = player_input
    renderer = StreamRenderer(self._turn_card)
    try:
        await self._turn_runner.run(player_input, on_token=renderer.route_token)
    except Exception as e:
        self._show_turn_error(str(e), player_input)

def _show_turn_error(self, error_msg: str, player_input: str):
    with self._turn_card:
        ui.label(f"Turn failed: {error_msg}").classes("text-negative")
        ui.button(
            "Retry",
            icon="refresh",
            on_click=lambda: self._retry_turn(player_input),
        ).classes("retry-btn")

async def _retry_turn(self, player_input: str):
    # Reload game state from disk to discard partial mutations
    # After Step 00: use state.reload_game() then TurnRunner.run()
    self._state.reload_game()
    # Remove the error turn card
    self._remove_last_turn_card()
    # Replay the turn via TurnRunner with a fresh StreamRenderer
    renderer = StreamRenderer(self._turn_card)
    await self._turn_runner.run(player_input, on_token=renderer.route_token)
```

Key detail: **reload game state from disk before retry.** A failed turn may have partially mutated in-memory state (e.g., narrator output written but character agents not yet run). Calling `state.reload_game()` ensures a clean slate since the engine only persists state after a fully successful turn. Then `TurnRunner.run()` re-executes the turn.

---

## 7. Loading States & Transitions

Add visual feedback for operations that take noticeable time.

### Save loading

When the user clicks a save to load it:

```python
async def _load_save(self, save_id: str):
    with ui.column().classes("loading-container"):
        ui.spinner("dots", size="lg")
        ui.label("Loading save...")
    session = await load_save(save_id)
    # Loading container is replaced by gameplay UI
```

### Game creation

Game creation (Step 04 of this phase) already has a progress stepper. Ensure it uses consistent spinner styling.

### Playtest start

Show a spinner while the playtest save is being created and the first turn is running.

### Navigation transitions

Keep transitions minimal — a brief spinner during page changes is sufficient. Avoid elaborate animations that add complexity.

### Consistent spinner usage

Use `ui.spinner("dots", size="sm")` for inline indicators and `ui.spinner("dots", size="lg")` for full-page loading states. Standardize across all loading points.

---

## 8. Post-Turn Processing Indicator

After streaming completes, the engine runs memory updates and game state checks in parallel via `asyncio.gather`. This can take a few seconds. Currently the UI shows nothing during this phase.

> **Note:** After Step 00, `StreamRenderer` is a separate component from the session. It handles rendering streamed tokens into the UI. `TurnRunner` handles turn execution. The "Updating world state..." indicator should be shown between `StreamRenderer.finish()` (when streaming display is complete) and `TurnRunner.run()` returning (when memory updates and game state checks are done). The session orchestrates the handoff between these two components.

### Implementation

Add a subtle indicator below the turn card after streaming finishes but before `run_turn()` returns:

> **Note:** `run_turn()` is a single function — there is no separate `run_turn_stream` / `run_turn_post` split. The recommended approach is to use the streaming callback (`on_token`) to detect when the last narrative token has been received, then show the "Updating world state..." indicator between the last token arriving and `run_turn()` returning (which signals that memory updates and game state checks are complete). In the Step 00 architecture, `StreamRenderer.finish()` marks the end of streaming display, and `TurnRunner.run()` returning marks the completion of all post-turn processing.

```python
async def _play_turn(self, player_input: str):
    self._last_player_input = player_input
    spinner_row = None
    try:
        def on_token(chunk: str, *, agent: str, done: bool = False):
            self._append_to_turn_card(chunk)
            if done and spinner_row is None:
                # Streaming finished — show post-turn processing indicator
                nonlocal spinner_row
                with self._turn_card:
                    spinner_row = ui.row().classes("post-turn-indicator")
                    with spinner_row:
                        ui.spinner("dots", size="sm")
                        ui.label("Updating world state...").classes(
                            "text-caption text-grey"
                        )

        await run_turn(
            self._session, player_input, on_token=on_token,
        )

        # Remove indicator after run_turn returns
        if spinner_row is not None:
            spinner_row.delete()
    except Exception as e:
        if spinner_row is not None:
            spinner_row.delete()
        self._show_turn_error(str(e), player_input)
```

The indicator is small and unobtrusive — a small spinner with grey caption text. It disappears as soon as post-turn processing completes.

---

## 9. Graceful Degradation

All error states should suggest corrective actions, not just report the problem.

### LLM API unreachable

```python
def _show_api_error(self):
    with ui.card().classes("error-card"):
        ui.label("Cannot reach LLM API").classes("text-h6 text-negative")
        ui.label("Check your API key and endpoint in settings.")
        ui.button("Open Settings", on_click=lambda: ui.navigate.to("/settings"))
```

### Save directory missing

If the save directory referenced in `app.storage.tab` no longer exists:

```python
if not save_path.exists():
    ui.notify("Save not found. It may have been deleted.", type="warning")
    app.storage.tab.clear()
    ui.navigate.to("/")
```

### Git operations fail

If git operations fail (e.g., corrupted repo):

```python
def _show_git_error(self, save_path: Path, error: str):
    with ui.card().classes("error-card"):
        ui.label("Save history error").classes("text-h6 text-negative")
        ui.label(f"Git error: {error}")
        ui.label("This usually means the save's history is corrupted.")
        with ui.row():
            ui.button("Recreate History", on_click=lambda: self._recreate_git(save_path))
            ui.button("Back to Menu", on_click=lambda: ui.navigate.to("/"))
```

The "Recreate History" button re-initializes the git repo in the save directory, preserving current files but losing history. This is a last resort but better than a dead save.

### General principle

Every error message follows the pattern:
1. **What happened** — clear, non-technical description.
2. **Why it might have happened** — one-line hint.
3. **What to do next** — actionable button(s).

---

## 10. Tests

**New file:** `tests/web/test_safety.py`

### File lock tests

```python
import pytest
from pathlib import Path
from theact.web.safety import SaveLock

def test_lock_acquired(tmp_path):
    lock = SaveLock(tmp_path)
    assert lock.acquire() is True
    assert lock.is_locked
    lock.release()

def test_lock_conflict(tmp_path):
    lock1 = SaveLock(tmp_path)
    lock2 = SaveLock(tmp_path)
    assert lock1.acquire() is True
    assert lock2.acquire() is False  # Already locked
    lock1.release()
    assert lock2.acquire() is True  # Now available
    lock2.release()

def test_lock_release_on_context(tmp_path):
    lock = SaveLock(tmp_path)
    lock.acquire()
    lock.release()
    assert not lock.is_locked
```

### Refresh recovery tests (browser tests)

These require the Playwright-based browser test setup used by existing web tests in `tests/web/`:

```python
async def test_refresh_recovery(page, running_app):
    """After loading a save and refreshing, user returns to gameplay."""
    # Navigate to app, load a save
    await page.goto(running_app.url)
    await page.click("[data-testid='save-item-test']")
    await page.wait_for_selector("[data-testid='gameplay-input']")

    # Refresh the page
    await page.reload()

    # Should return to gameplay, not menu
    await page.wait_for_selector("[data-testid='gameplay-input']")

async def test_refresh_recovery_missing_save(page, running_app):
    """If save is deleted after refresh, falls back to menu."""
    # Load save, delete directory, refresh
    # Should show menu (not crash)
    await page.wait_for_selector("[data-testid='menu']")
```

### Keyboard shortcut tests

```python
async def test_ctrl_b_toggles_sidebar(page, running_app):
    """Ctrl+B toggles the sidebar visibility."""
    await page.goto(running_app.url)
    # Load a save to enter gameplay
    await page.click("[data-testid='save-item-test']")
    await page.wait_for_selector(".sidebar")

    # Press Ctrl+B
    await page.keyboard.press("Control+b")
    # Sidebar should be hidden
    assert not await page.is_visible(".sidebar")

    # Press Ctrl+B again
    await page.keyboard.press("Control+b")
    # Sidebar should be visible
    assert await page.is_visible(".sidebar")
```

---

## 11. Verification

After implementation, verify the following manually and via tests:

- [ ] Opening the same save in two browser tabs shows a lock warning dialog.
- [ ] Choosing "Open Read-Only" in the lock dialog prevents turn submission.
- [ ] Choosing "Force Unlock" acquires the lock and enables normal gameplay.
- [ ] Lock is released when quitting to menu.
- [ ] Lock is released when closing the browser tab.
- [ ] Browser refresh returns to the active game (not the menu).
- [ ] Browser refresh with a deleted save falls back to menu gracefully.
- [ ] Layout adapts correctly at mobile (<768px) breakpoint — sidebar hidden, input full-width.
- [ ] Layout adapts correctly at tablet (768–1024px) breakpoint — sidebar collapsed.
- [ ] `Ctrl+Z` triggers undo confirmation dialog.
- [ ] `Ctrl+S` opens save-as dialog.
- [ ] `Ctrl+B` toggles sidebar.
- [ ] `Ctrl+H` toggles history browser.
- [ ] `Escape` closes open dialogs.
- [ ] Failed turn shows a "Retry" button.
- [ ] Retry button replays the same input and produces a successful turn.
- [ ] Post-turn processing shows "Updating world state..." indicator.
- [ ] Save loading shows a spinner.
- [ ] API errors suggest opening settings.
- [ ] Git errors offer to recreate history.
- [ ] All existing web tests still pass.

---

## What This Step Does NOT Do

- **Offline support** — No service worker or local caching. The app requires a live server.
- **PWA manifest** — No installable web app. This could be a future enhancement.
- **Accessibility audit** — Basic keyboard navigation is added, but a full WCAG audit is out of scope.
- **Internationalization** — All strings remain English. No i18n framework.
- **Performance optimization** — No lazy loading, code splitting, or asset minification. NiceGUI handles bundling.
- **Dark mode toggle** — The UI uses NiceGUI's default theme. A dark/light toggle is a separate feature.
- **WebSocket reconnection** — If the server restarts, the client does not auto-reconnect. NiceGUI handles basic reconnection, but long outages require a page refresh.

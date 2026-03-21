# Step 00: Web UI Refactoring

> **Implementation note:** This step MUST be completed before any other Phase 13 step. It restructures the existing web UI code into a modular architecture that the remaining steps can build on cleanly. No new features are added — the web UI should behave identically before and after this step. All existing web tests (`tests/web/`) must continue to pass.

## 1. Overview

The current web UI (`src/theact/web/`) has several structural problems:

- **God class.** `GameplaySession` (453 lines) handles UI construction, turn execution, streaming, command dispatch, input management, and state persistence.
- **Duplicated command logic.** `web/commands.py` and `cli/commands.py` share ~90% identical logic with only rendering differences.
- **Flat component file.** `components.py` mixes streaming infrastructure, turn card rendering, static message rendering, and system messages in a single 179-line file.
- **Monolithic app.py.** Menu construction, save management, page routing, and event handlers are interleaved in one file with a closure-based state dict.
- **Duplicate render paths.** The streaming callback in `session.py` and `render_static_turn()` in `components.py` both handle narrator/character/player roles independently.
- **No shared utilities.** HTML escaping, relative time formatting, and other common operations are reimplemented inline.

This step restructures the code into focused modules with clear responsibilities, making Steps 01-08 straightforward to implement.

### What This Step Does NOT Do

- No new features. The web UI behaves identically before and after.
- No new pages, routes, or UI components.
- No changes to the engine, agents, models, or CLI.
- No NiceGUI version changes.

---

## 2. Target Architecture

### Before (current)

```
src/theact/web/
    __init__.py          # start_web()
    __main__.py          # CLI args
    app.py               # 312 lines — page routing, menu, save management, state dict
    session.py           # 453 lines — god class: UI + turns + streaming + commands
    commands.py          # 239 lines — web command implementations (90% duplicated from CLI)
    components.py        # 179 lines — flat file: streaming, turn cards, messages, system
    styles.py            # 50 lines — colors (clean, keep as-is)
```

### After (target)

```
src/theact/web/
    __init__.py              # start_web() — unchanged
    __main__.py              # CLI args — unchanged
    styles.py                # Colors — unchanged

    app.py                   # Slim: page routing only, delegates to menu + session
    menu.py                  # NEW: MenuBuilder class — all menu UI construction
    session.py               # Slim: GameplaySession as thin orchestrator

    state.py                 # NEW: GameSessionState — shared observable state
    turn_runner.py           # NEW: TurnRunner — wraps run_turn(), handles result
    streaming.py             # NEW: StreamRenderer — routes tokens to UI blocks
    command_router.py        # NEW: CommandRouter — dispatches commands, returns results

    components/              # FOLDER replacing components.py
        __init__.py          # Re-exports for backward compat
        turn_card.py         # Turn card creation and turn info rendering
        message_blocks.py    # StreamingTextBlock, static message blocks
        thinking_panel.py    # Thinking panel component
        system_message.py    # System message card
        dialogs.py           # Reusable confirmation/input dialogs
        html_utils.py        # HTML escaping, text-to-html, table builder

src/theact/commands/         # NEW shared package
    __init__.py
    logic.py                 # Shared command logic (no rendering)
    types.py                 # CommandResult dataclass

src/theact/cli/
    commands.py              # Slim: CLI rendering over shared logic
```

### Dependency Flow

```
app.py
  ├─ menu.py ──────────────────────→ save_manager, components/dialogs
  └─ session.py (orchestrator)
       ├─ state.py ────────────────→ LoadedGame, LLMConfig
       ├─ turn_runner.py ──────────→ engine.turn.run_turn
       ├─ streaming.py ────────────→ components/message_blocks
       ├─ command_router.py ───────→ commands/logic
       └─ components/ ─────────────→ styles.py
```

Key principle: **dependencies flow downward.** `session.py` orchestrates, but never imports `app.py`. Components never import session. The `commands/logic.py` module is pure Python with no UI imports.

---

## 3. Shared Command Logic

**New package:** `src/theact/commands/`

### 3.1 `commands/types.py`

```python
"""Shared types for command results."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class CommandResult:
    """Uniform result from any slash command.

    Both CLI and web command handlers return this. The renderer
    (CLI console or web UI) decides how to display it.
    """

    success: bool
    message: str = ""
    data: Any = None  # e.g., reloaded LoadedGame for /undo
    rows: list[dict[str, str]] = field(default_factory=list)  # tabular data
    title: str = ""  # optional heading
```

### 3.2 `commands/logic.py`

Extract all shared logic from `cli/commands.py` and `web/commands.py`. These are pure functions with no UI imports — they operate on game data and return `CommandResult`.

```python
"""Shared command logic — no UI imports, no rendering.

Both CLI and web command modules call these functions and
render the CommandResult using their respective UI frameworks.
"""

from __future__ import annotations

from theact.commands.types import CommandResult
from theact.models.game import LoadedGame
from theact.versioning import git_save
from theact.io.save_manager import load_save


def cmd_help() -> CommandResult:
    """Return help text as structured data."""
    rows = [
        {"command": "/help", "args": "none", "description": "Show this help message"},
        {"command": "/undo [N]", "args": "optional integer", "description": "Undo last N turns"},
        {"command": "/retry", "args": "none", "description": "Retry last turn"},
        {"command": "/history", "args": "none", "description": "Show turn history"},
        {"command": "/status", "args": "none", "description": "Game status"},
        {"command": "/memory [name]", "args": "optional name", "description": "Character memory"},
        {"command": "/conversation [N]", "args": "optional integer", "description": "Recent entries"},
        {"command": "/save", "args": "none", "description": "Save info"},
        {"command": "/save-as <name>", "args": "save name", "description": "Fork save"},
        {"command": "/think [on|off]", "args": "optional", "description": "Toggle thinking"},
        {"command": "/quit", "args": "none", "description": "Return to menu"},
    ]
    return CommandResult(success=True, title="Commands", rows=rows)


def cmd_status(game: LoadedGame) -> CommandResult:
    """Return game status as structured data."""
    chapter = game.chapters.get(game.state.current_chapter)
    total_beats = len(chapter.beats) if chapter else 0
    hit_beats = len(game.state.beats_hit) if game.state.beats_hit else 0
    lines = [
        f"Chapter: {chapter.title if chapter else 'unknown'} ({game.state.current_chapter})",
        f"Turn: {game.state.turn}",
        f"Beats: {hit_beats}/{total_beats}",
    ]
    if game.state.flags:
        lines.append(f"Flags: {game.state.flags}")
    return CommandResult(success=True, message="\n".join(lines))


def cmd_save_info(game: LoadedGame) -> CommandResult:
    """Return save metadata."""
    lines = [
        f"Save: {game.save_path.name}",
        f"Game: {game.meta.title}",
        f"Player: {game.state.player_name}",
        f"Path: {game.save_path}",
    ]
    return CommandResult(success=True, message="\n".join(lines))


def cmd_history(game: LoadedGame) -> CommandResult:
    """Return turn history as tabular data."""
    history = git_save.get_history(game.save_path)
    if not history:
        return CommandResult(success=True, message="No turn history yet.")
    rows = [
        {"turn": str(t.turn), "summary": t.message, "timestamp": t.timestamp}
        for t in history
    ]
    return CommandResult(success=True, title="Turn History", rows=rows)


def cmd_memory(game: LoadedGame, args: list[str]) -> CommandResult:
    """Return character memory. If no args, list characters."""
    if not args:
        lines = []
        for char_id, char in game.characters.items():
            has_mem = "has memory" if char_id in game.memories else "no memory"
            lines.append(f"  {char.name} ({has_mem})")
        return CommandResult(success=True, title="Characters", message="\n".join(lines))

    # Fuzzy match character name
    query = " ".join(args).lower()
    match = None
    for char_id, char in game.characters.items():
        if query in char.name.lower() or query in char_id.lower():
            match = char_id
            break
    if not match:
        return CommandResult(success=False, message=f"Unknown character: {query}")

    char = game.characters[match]
    memory = game.memories.get(match)
    if not memory:
        return CommandResult(success=True, message=f"{char.name} has no memories yet.")

    lines = [
        f"Memory: {char.name}",
        f"Summary: {memory.summary}",
    ]
    if memory.key_facts:
        lines.append("Key facts:")
        for fact in memory.key_facts:
            lines.append(f"  - {fact}")
    return CommandResult(success=True, message="\n".join(lines))


def cmd_conversation(game: LoadedGame, args: list[str]) -> CommandResult:
    """Return last N conversation entries."""
    count = 5
    if args:
        try:
            count = int(args[0])
        except ValueError:
            return CommandResult(success=False, message=f"Invalid number: {args[0]}")

    entries = game.conversation[-count:]
    if not entries:
        return CommandResult(success=True, message="No conversation yet.")

    lines = []
    for entry in entries:
        if entry.role == "player":
            speaker = game.state.player_name
        else:
            speaker = entry.character or entry.role
        content = entry.content
        if entry.role == "narrator" and len(content) > 200:
            content = content[:200] + "..."
        lines.append(f"{speaker}: {content}")
    return CommandResult(success=True, title="Recent Conversation", message="\n".join(lines))


def cmd_undo(game: LoadedGame, args: list[str]) -> CommandResult:
    """Undo N turns. Returns reloaded game in data field."""
    steps = 1
    if args:
        try:
            steps = int(args[0])
        except ValueError:
            return CommandResult(success=False, message=f"Invalid number: {args[0]}")

    try:
        git_save.undo(game.save_path, steps)
        reloaded = load_save(game.save_path.name, game.save_path.parent)
        return CommandResult(
            success=True,
            message=f"Undid {steps} turn(s). Now at turn {reloaded.state.turn}.",
            data=reloaded,
        )
    except Exception as e:
        return CommandResult(success=False, message=f"Undo failed: {e}")


def cmd_save_as(game: LoadedGame, args: list[str]) -> CommandResult:
    """Fork the current save to a new name."""
    if not args:
        return CommandResult(success=False, message="Usage: /save-as <name>")
    new_name = args[0].strip()
    try:
        git_save.save_as(game.save_path, new_name)
        return CommandResult(success=True, message=f"Save forked as '{new_name}'.")
    except Exception as e:
        return CommandResult(success=False, message=f"Save-as failed: {e}")
```

### 3.3 Updating CLI Commands

After extracting shared logic, `src/theact/cli/commands.py` becomes a thin rendering layer:

```python
# Simplified pattern for each CLI command:
from theact.commands.logic import cmd_status as _cmd_status

def cmd_status(console: Console, game: LoadedGame) -> None:
    result = _cmd_status(game)
    console.print(result.message)
```

The `parse_command()` function stays in `cli/commands.py` since it's already imported by the web layer.

### 3.4 Updating Web Commands

`src/theact/web/commands.py` also becomes a thin rendering layer, but renders `CommandResult` into NiceGUI elements:

```python
from theact.commands.logic import cmd_status as _cmd_status
from theact.web.components import show_system_message

def cmd_status_web(chat_area, game: LoadedGame) -> None:
    result = _cmd_status(game)
    show_system_message(chat_area, result.message)
```

For tabular results (help, history), the web renderer converts `result.rows` into an HTML table using `html_utils.render_table()`.

---

## 4. GameplaySession Decomposition

### 4.1 `state.py` — Shared Observable State

A single state object that all components read from. Updated in one place after each turn or command.

```python
"""Shared game session state.

All web UI components (session, sidebar, toolbar, history) read from
this object. It is updated by the session orchestrator after turns
and commands. Components should NEVER mutate state directly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from theact.models.game import LoadedGame
from theact.llm.config import LLMConfig


@dataclass
class GameSessionState:
    """Observable state for a gameplay session."""

    game: LoadedGame
    llm_config: LLMConfig
    show_thinking: bool = True
    processing: bool = False
    last_player_input: str = ""
    debug_mode: bool = False

    # Listeners called when state changes
    _listeners: list[Callable[[], None]] = field(default_factory=list, repr=False)

    def add_listener(self, callback: Callable[[], None]) -> None:
        """Register a callback to be notified on state changes."""
        self._listeners.append(callback)

    def notify(self) -> None:
        """Notify all listeners that state has changed."""
        for cb in self._listeners:
            cb()

    def reload_game(self) -> None:
        """Reload game from disk and notify listeners."""
        from theact.io.save_manager import load_save

        self.game = load_save(self.game.save_path.name, self.game.save_path.parent)
        self.notify()

    @property
    def character_list(self) -> list[str]:
        """Ordered list of character stems."""
        return list(self.game.characters.keys())
```

### 4.2 `turn_runner.py` — Turn Execution

Wraps `run_turn()` and handles result processing. No UI code.

```python
"""Turn execution wrapper.

Calls engine.turn.run_turn() and processes the result. Does NOT
handle UI updates — returns the TurnResult for the caller to render.
"""

from __future__ import annotations

from theact.engine.turn import run_turn, StreamCallback
from theact.engine.types import TurnResult
from theact.llm.call_log import LLMCallLog
from theact.web.state import GameSessionState


class TurnRunner:
    """Executes turns via the engine and returns results."""

    def __init__(self, state: GameSessionState) -> None:
        self._state = state
        self.call_log: LLMCallLog | None = None

    async def run(
        self,
        player_input: str,
        on_token: StreamCallback | None = None,
    ) -> TurnResult:
        """Run a turn and return the result.

        The caller is responsible for UI updates (streaming is handled
        via the on_token callback). After this returns, the caller
        should call state.reload_game() to get the persisted state.
        """
        return await run_turn(
            game=self._state.game,
            player_input=player_input,
            llm_config=self._state.llm_config,
            on_token=on_token,
            call_log=self.call_log,
            debug=self._state.debug_mode,
        )
```

### 4.3 `streaming.py` — Stream Renderer

Routes streaming tokens to UI components. Replaces the nested closure in `_play_turn()`.

```python
"""Routes streaming tokens to UI components.

Replaces the nested on_token callback closure in the old
GameplaySession._play_turn(). Tracks current section (narrator vs
character) and manages StreamingTextBlock instances.
"""

from __future__ import annotations

from nicegui import ui

from theact.web.components.message_blocks import (
    StreamingTextBlock,
    create_narrator_block,
    create_character_block,
)
from theact.web.components.thinking_panel import create_thinking_panel


class StreamRenderer:
    """Routes streaming tokens to the correct UI blocks."""

    def __init__(
        self,
        turn_card: ui.card,
        character_list: list[str],
        show_thinking: bool = True,
    ) -> None:
        self._turn_card = turn_card
        self._character_list = character_list
        self._show_thinking = show_thinking

        self._current_block: StreamingTextBlock | None = None
        self._current_section: str = ""
        self._thinking_block: StreamingTextBlock | None = None
        self._scroll_target: ui.scroll_area | None = None

    def set_scroll_target(self, scroll_area: ui.scroll_area) -> None:
        """Set the scroll area for auto-scrolling."""
        self._scroll_target = scroll_area

    def create_thinking_panel(self) -> None:
        """Create the thinking panel inside the turn card."""
        self._thinking_block = create_thinking_panel(self._turn_card)

    async def route_token(
        self,
        source: str,
        character: str | None,
        token: str,
        is_thinking: bool,
    ) -> None:
        """Route a single token to the correct UI block.

        This is the on_token callback passed to run_turn().
        """
        if is_thinking:
            if self._show_thinking and self._thinking_block:
                self._thinking_block.append_text(token)
        elif source == "narrator":
            if self._current_section != "narrator":
                self._finish_current()
                self._current_block = create_narrator_block(self._turn_card)
                self._current_section = "narrator"
            if self._current_block:
                self._current_block.append_text(token)
        elif source == "character":
            char_name = character or "?"
            section_key = f"character:{char_name}"
            if self._current_section != section_key:
                self._finish_current()
                self._current_block = create_character_block(
                    self._turn_card, char_name, self._character_list
                )
                self._current_section = section_key
            if self._current_block:
                self._current_block.append_text(token)

        if self._scroll_target:
            self._scroll_target.scroll_to(percent=1.0)

    def finish(self) -> None:
        """Finish any active streaming block."""
        self._finish_current()

    def _finish_current(self) -> None:
        if self._current_block:
            self._current_block.finish()
            self._current_block = None
```

### 4.4 `command_router.py` — Command Dispatch

Replaces the if-elif chain in `GameplaySession._execute_command()`.

```python
"""Command dispatch for the web UI.

Routes slash commands to shared logic and renders results.
Handles web-specific commands (think, quit) locally.
"""

from __future__ import annotations

from nicegui import ui

from theact.commands import logic
from theact.commands.types import CommandResult
from theact.web.state import GameSessionState
from theact.web.components.system_message import show_system_message
from theact.web.components.html_utils import render_result


class CommandRouter:
    """Dispatches slash commands and renders results to the chat area."""

    def __init__(self, state: GameSessionState, chat_area: ui.element) -> None:
        self._state = state
        self._chat_area = chat_area

    def execute(self, cmd: str, args: list[str]) -> CommandResult | None:
        """Execute a command. Returns result, or None for quit/special commands.

        The session handles quit and think separately since they
        affect session-level state, not just chat output.
        """
        handler = self._COMMANDS.get(cmd)
        if handler is None:
            show_system_message(self._chat_area, f"Unknown command: /{cmd}")
            return CommandResult(success=False, message=f"Unknown command: /{cmd}")
        return handler(self, args)

    def _cmd_help(self, args: list[str]) -> CommandResult:
        result = logic.cmd_help()
        render_result(self._chat_area, result)
        return result

    def _cmd_status(self, args: list[str]) -> CommandResult:
        result = logic.cmd_status(self._state.game)
        render_result(self._chat_area, result)
        return result

    def _cmd_save(self, args: list[str]) -> CommandResult:
        result = logic.cmd_save_info(self._state.game)
        render_result(self._chat_area, result)
        return result

    def _cmd_history(self, args: list[str]) -> CommandResult:
        result = logic.cmd_history(self._state.game)
        render_result(self._chat_area, result)
        return result

    def _cmd_memory(self, args: list[str]) -> CommandResult:
        result = logic.cmd_memory(self._state.game, args)
        render_result(self._chat_area, result)
        return result

    def _cmd_conversation(self, args: list[str]) -> CommandResult:
        result = logic.cmd_conversation(self._state.game, args)
        render_result(self._chat_area, result)
        return result

    def _cmd_undo(self, args: list[str]) -> CommandResult:
        result = logic.cmd_undo(self._state.game, args)
        if result.success and result.data:
            self._state.game = result.data
            self._state.notify()
        render_result(self._chat_area, result)
        return result

    def _cmd_save_as(self, args: list[str]) -> CommandResult:
        result = logic.cmd_save_as(self._state.game, args)
        if result.success:
            ui.notify(result.message, type="positive")
        else:
            ui.notify(result.message, type="warning")
        return result

    # NOTE: _COMMANDS is defined at class level with unbound methods intentionally.
    # This avoids creating bound method objects per instance. It works because
    # execute() calls handler(self, args), passing self explicitly. Alternatively,
    # you could populate this dict in __init__ with bound methods (self._cmd_help, etc.)
    # if you prefer the more conventional pattern.
    _COMMANDS = {
        "help": _cmd_help,
        "status": _cmd_status,
        "save": _cmd_save,
        "history": _cmd_history,
        "memory": _cmd_memory,
        "conversation": _cmd_conversation,
        "undo": _cmd_undo,
        "save-as": _cmd_save_as,
        # "think" and "quit" are handled by the session directly
    }
```

### 4.5 Refactored `session.py` — Thin Orchestrator

The session becomes ~120 lines. It delegates to `TurnRunner`, `StreamRenderer`, and `CommandRouter`.

```python
"""Gameplay session — thin orchestrator.

Delegates to:
  - TurnRunner for turn execution
  - StreamRenderer for token routing
  - CommandRouter for slash commands
  - GameSessionState for shared state

Owns the UI layout (header, chat area, input bar) and the main
input loop (_on_submit). Everything else is delegated.
"""

from __future__ import annotations

from nicegui import ui

from theact.cli.commands import parse_command
from theact.web.state import GameSessionState
from theact.web.turn_runner import TurnRunner
from theact.web.streaming import StreamRenderer
from theact.web.command_router import CommandRouter
from theact.web.components.turn_card import create_turn_card
from theact.web.components.message_blocks import create_player_block


class GameplaySession:
    """Thin orchestrator for the gameplay view."""

    def __init__(self, state: GameSessionState, on_quit: callable) -> None:
        self._state = state
        self._on_quit = on_quit
        self._turn_runner = TurnRunner(state)
        self._command_router: CommandRouter | None = None

        # UI references (set during build)
        self._chat_scroll: ui.scroll_area | None = None
        self._chat_area: ui.column | None = None
        self._input_field: ui.input | None = None
        self._send_button: ui.button | None = None
        self._header_label: ui.label | None = None
        self._think_switch: ui.switch | None = None

    def build(self, container: ui.element) -> None:
        """Build the gameplay UI layout."""
        # ... header, chat area, input bar (same structure as current)
        # After building chat_area:
        self._command_router = CommandRouter(self._state, self._chat_area)
        self._render_history()

    async def _on_submit(self) -> None:
        """Handle input submission — route to command or turn."""
        text = self._input_field.value.strip()
        if not text:
            return
        self._input_field.value = ""

        command = parse_command(text)
        if command:
            cmd, args = command
            if cmd == "quit":
                self._on_quit()
                return
            if cmd == "think":
                self._handle_think(args)
                return
            if cmd == "retry":
                await self._handle_retry()
                return
            self._command_router.execute(cmd, args)
            if cmd == "undo":
                self._chat_area.clear()
                self._render_history()
                self._update_header()
        else:
            await self._play_turn(text)

    async def _play_turn(self, player_input: str) -> None:
        """Execute a turn with streaming."""
        self._state.last_player_input = player_input
        self._lock_input()

        turn_card = create_turn_card(
            self._chat_area,
            self._state.game.state.turn + 1,
            self._current_chapter_title(),
        )

        renderer = StreamRenderer(
            turn_card=turn_card,
            character_list=self._state.character_list,
            show_thinking=self._state.show_thinking,
        )
        renderer.set_scroll_target(self._chat_scroll)
        renderer.create_thinking_panel()

        try:
            result = await self._turn_runner.run(
                player_input=player_input,
                on_token=renderer.route_token,
            )
            renderer.finish()
            create_player_block(
                turn_card, self._state.game.state.player_name, player_input
            )
            # TurnResult post-processing (info bar, etc.) added in Step 01
        except Exception:
            renderer.finish()
            # ... error handling
        finally:
            self._state.reload_game()
            self._update_header()
            self._unlock_input()

    # ... _lock_input, _unlock_input, _update_header, _render_history,
    #     _handle_think, _handle_retry, _current_chapter_title, auto_start
    #     (same as current but much shorter since logic is delegated)
```

---

## 5. Components Package

**Replace** `src/theact/web/components.py` with `src/theact/web/components/`.

### 5.1 Package Structure

```
src/theact/web/components/
    __init__.py          # Re-exports for backward compat during transition
    turn_card.py         # create_turn_card(), create_turn_info_bar() (Step 01)
    message_blocks.py    # StreamingTextBlock, create_narrator/character/player_block
    thinking_panel.py    # create_thinking_panel()
    system_message.py    # show_system_message()
    static_turn.py       # render_static_turn() — renders past turns from conversation
    dialogs.py           # Reusable dialog builders (used by Step 01+)
    html_utils.py        # HTML escaping, text-to-html, table rendering
```

### 5.2 `components/__init__.py`

Re-export everything so existing imports (`from theact.web.components import ...`) continue to work:

```python
"""Web UI components package.

Re-exports all public components for backward compatibility.
New code should import from specific submodules.
"""

from theact.web.components.turn_card import create_turn_card
from theact.web.components.message_blocks import (
    StreamingTextBlock,
    create_narrator_block,
    create_character_block,
    create_player_block,
)
from theact.web.components.thinking_panel import create_thinking_panel
from theact.web.components.system_message import show_system_message
from theact.web.components.static_turn import render_static_turn

__all__ = [
    "StreamingTextBlock",
    "create_turn_card",
    "create_narrator_block",
    "create_character_block",
    "create_player_block",
    "create_thinking_panel",
    "show_system_message",
    "render_static_turn",
]
```

### 5.3 `components/html_utils.py`

Centralizes HTML operations that are currently scattered across commands.py and components.py.

```python
"""HTML utilities for the web UI.

Centralizes HTML escaping, text-to-HTML conversion, and table
rendering. Used by components, commands, and the command router.
"""

from __future__ import annotations

import html as html_lib

from theact.commands.types import CommandResult


def escape(text: str) -> str:
    """HTML-escape a string."""
    return html_lib.escape(text)


def text_to_html(text: str, color: str = "#e0e0e0") -> str:
    """Convert plain text to styled HTML with line breaks."""
    escaped = escape(text)
    with_breaks = escaped.replace("\n", "<br>")
    return f'<div style="color: {color}; white-space: pre-wrap;">{with_breaks}</div>'


def render_table(rows: list[dict[str, str]], headers: list[str] | None = None) -> str:
    """Render a list of dicts as an HTML table.

    If headers is None, uses the keys from the first row.
    """
    if not rows:
        return "<p>No data.</p>"
    if headers is None:
        headers = list(rows[0].keys())

    header_cells = "".join(
        f'<th style="text-align: left; padding: 4px 12px; '
        f'border-bottom: 1px solid #555; color: #aaa;">{escape(h)}</th>'
        for h in headers
    )
    body_rows = []
    for row in rows:
        cells = "".join(
            f'<td style="padding: 4px 12px; color: #ccc;">'
            f'{escape(str(row.get(h, "")))}</td>'
            for h in headers
        )
        body_rows.append(f"<tr>{cells}</tr>")

    return (
        f'<table style="border-collapse: collapse; width: 100%;">'
        f"<thead><tr>{header_cells}</tr></thead>"
        f'<tbody>{"".join(body_rows)}</tbody>'
        f"</table>"
    )


def render_result(chat_area, result: CommandResult) -> None:
    """Render a CommandResult into the chat area.

    Uses show_system_message for text results, and render_table for
    tabular results.
    """
    from theact.web.components.system_message import show_system_message

    if result.rows:
        table_html = render_table(result.rows)
        content = f"<b>{escape(result.title)}</b><br>{table_html}" if result.title else table_html
        show_system_message(chat_area, content)
    elif result.message:
        text = escape(result.message).replace("\n", "<br>")
        content = f"<b>{escape(result.title)}</b><br>{text}" if result.title else text
        show_system_message(chat_area, content)


def relative_time(timestamp: float) -> str:
    """Convert a Unix timestamp to a human-readable relative time string.

    Used by save management and history displays.
    """
    from datetime import datetime, timezone

    now = datetime.now(tz=timezone.utc)
    dt = datetime.fromtimestamp(timestamp, tz=timezone.utc)
    delta = now - dt
    seconds = int(delta.total_seconds())

    if seconds < 60:
        return "just now"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes} minute{'s' if minutes != 1 else ''} ago"
    hours = minutes // 60
    if hours < 24:
        return f"{hours} hour{'s' if hours != 1 else ''} ago"
    days = hours // 24
    if days < 30:
        return f"{days} day{'s' if days != 1 else ''} ago"
    return dt.strftime("%Y-%m-%d")
```

### 5.4 `components/dialogs.py`

Reusable dialog builders for confirmation and input dialogs.

```python
"""Reusable dialog builders.

Provides factory functions for common dialog patterns used across
the web UI: confirmation dialogs, text input dialogs, and number
input dialogs.
"""

from __future__ import annotations

from typing import Callable, Awaitable

from nicegui import ui


async def confirm_dialog(
    title: str,
    message: str,
    confirm_label: str = "Confirm",
    confirm_color: str = "#ff9800",
) -> bool:
    """Show a confirmation dialog and return True if confirmed."""
    result = False

    with ui.dialog() as dialog, ui.card():
        ui.label(title).style("font-weight: bold; color: #ccc;")
        ui.label(message).style("color: #999;")
        with ui.row().classes("justify-end gap-2 mt-2"):
            ui.button("Cancel", on_click=dialog.close).props("flat")

            def on_confirm():
                nonlocal result
                result = True
                dialog.close()

            ui.button(confirm_label, on_click=on_confirm).props("flat").style(
                f"color: {confirm_color};"
            )

    await dialog
    return result


async def text_input_dialog(
    title: str,
    message: str,
    label: str = "Name",
    placeholder: str = "",
    confirm_label: str = "Create",
    confirm_color: str = "#69f0ae",
) -> str | None:
    """Show a text input dialog. Returns the entered text, or None if cancelled."""
    result = None

    with ui.dialog() as dialog, ui.card():
        ui.label(title).style("font-weight: bold; color: #ccc;")
        ui.label(message).style("color: #999;")
        text_input = (
            ui.input(label=label, placeholder=placeholder)
            .props("outlined dense dark")
            .classes("w-full")
        )
        with ui.row().classes("justify-end gap-2 mt-2"):
            ui.button("Cancel", on_click=dialog.close).props("flat")

            def on_confirm():
                nonlocal result
                val = (text_input.value or "").strip()
                if val:
                    result = val
                    dialog.close()
                else:
                    ui.notify("Please enter a value.", type="warning")

            ui.button(confirm_label, on_click=on_confirm).props("flat").style(
                f"color: {confirm_color};"
            )

    await dialog
    return result


async def number_input_dialog(
    title: str,
    message: str,
    label: str = "Steps",
    default: int = 1,
    min_val: int = 1,
    max_val: int = 100,
    confirm_label: str = "Confirm",
    confirm_color: str = "#ff9800",
) -> int | None:
    """Show a number input dialog. Returns the number, or None if cancelled."""
    result = None

    with ui.dialog() as dialog, ui.card():
        ui.label(title).style("font-weight: bold; color: #ccc;")
        ui.label(message).style("color: #999;")
        num_input = (
            ui.number(label=label, value=default, min=min_val, max=max_val)
            .props("outlined dense dark")
            .style("width: 100px;")
        )
        with ui.row().classes("justify-end gap-2 mt-2"):
            ui.button("Cancel", on_click=dialog.close).props("flat")

            def on_confirm():
                nonlocal result
                result = int(num_input.value or default)
                dialog.close()

            ui.button(confirm_label, on_click=on_confirm).props("flat").style(
                f"color: {confirm_color};"
            )

    await dialog
    return result
```

### 5.5 Moving Existing Components

Each existing component function moves to its own module:

| Current location | New location | Contents |
|---|---|---|
| `components.py:23-57` | `components/message_blocks.py` | `StreamingTextBlock` class |
| `components.py:60-70` | `components/turn_card.py` | `create_turn_card()` |
| `components.py:73-102` | `components/message_blocks.py` | `create_narrator/character/player_block()` |
| `components.py:104-114` | `components/thinking_panel.py` | `create_thinking_panel()` |
| `components.py:116-124` | `components/system_message.py` | `show_system_message()` |
| `components.py:126-179` | `components/static_turn.py` | `render_static_turn()` |

The `_text_to_html()` method inside `StreamingTextBlock` should call `html_utils.text_to_html()` instead of having its own implementation.

---

## 6. Menu Extraction

**New file:** `src/theact/web/menu.py`

Extract all menu construction from `app.py` into a `MenuBuilder` class. The `app.py` becomes a slim routing file.

```python
"""Menu UI builder.

Extracted from app.py. Builds the main menu with new game, continue
game, and delete save sections. app.py delegates to this class.
"""

from __future__ import annotations

from nicegui import ui

from theact.io.save_manager import list_games, list_saves, create_save, slugify, SAVES_DIR
from theact.web.components.html_utils import relative_time


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

    def _build_banner(self) -> None: ...
    def _build_new_game_section(self) -> None: ...
    def _build_saves_table(self) -> None: ...
    def _build_delete_section(self) -> None: ...
```

### Refactored `app.py`

```python
"""Web application setup — page routing only.

Delegates menu construction to MenuBuilder and gameplay to
GameplaySession. Manages transitions between menu and gameplay views.
"""

from nicegui import ui

from theact.llm.config import load_llm_config
from theact.io.save_manager import load_save, create_save
from theact.web.menu import MenuBuilder
from theact.web.session import GameplaySession
from theact.web.state import GameSessionState


def setup_app() -> None:
    """Register all page routes."""

    @ui.page("/")
    async def index():
        llm_config = load_llm_config()

        # Containers
        menu_container = ui.column().classes("w-full max-w-3xl mx-auto p-4")
        gameplay_container = ui.column().classes("w-full").style("display: none;")

        session: GameplaySession | None = None

        def enter_gameplay(game, auto_start=False):
            nonlocal session
            state = GameSessionState(game=game, llm_config=llm_config)
            session = GameplaySession(state=state, on_quit=return_to_menu)
            menu_container.style("display: none;")
            gameplay_container.style(replace="display: flex;")
            gameplay_container.clear()
            session.build(gameplay_container)
            if auto_start and state.game.state.turn == 0:
                ui.timer(0.1, lambda: session.auto_start(), once=True)

        def return_to_menu():
            nonlocal session
            session = None
            gameplay_container.style(replace="display: none;")
            menu_container.style(replace="display: flex;")
            ui.navigate.to("/")

        menu = MenuBuilder(
            on_start_game=lambda game: enter_gameplay(game, auto_start=True),
            on_load_game=lambda game: enter_gameplay(game, auto_start=False),
        )
        menu.build(menu_container)
```

---

## 7. Implementation Steps

Execute in this exact order. Run tests after each step.

### Step 0a: Create `commands/` package with shared logic
1. Create `src/theact/commands/__init__.py` and `types.py`
2. Create `src/theact/commands/logic.py` with all shared command functions
3. Write unit tests: `tests/test_command_logic.py` — test each command function with mock game data
4. Update `tests/test_web_commands.py`: patch targets change from `theact.web.commands.*` to `theact.commands.logic.*`, and many tests should migrate to `tests/test_command_logic.py` (since the logic is now shared, not web-specific)
5. Verify: `uv run pytest tests/test_command_logic.py -v`

### Step 0b: Slim down CLI commands
1. Rewrite `src/theact/cli/commands.py` to delegate to `commands/logic.py`
2. Keep `parse_command()` in `cli/commands.py` (it's imported by the web layer)
3. Verify: `uv run pytest tests/ -v` (all existing tests pass)

### Step 0c: Create `components/` package
1. Create `src/theact/web/components/` directory
2. Move each component to its own module (see Section 5.5)
3. Create `__init__.py` with re-exports (Section 5.2)
4. Create `html_utils.py` (Section 5.3) and `dialogs.py` (Section 5.4)
5. Delete old `src/theact/web/components.py`
6. Verify: `uv run pytest tests/web/ -v` (all existing web tests pass)

### Step 0d: Create `state.py` and `turn_runner.py`
1. Create `src/theact/web/state.py` (Section 4.1)
2. Create `src/theact/web/turn_runner.py` (Section 4.2)
3. Write unit tests for `GameSessionState` (listener notification, reload)
4. Verify: `uv run pytest tests/ -v`

### Step 0e: Create `streaming.py`
1. Create `src/theact/web/streaming.py` (Section 4.3)
2. Verify: existing web tests still pass

### Step 0f: Create `command_router.py` and slim web commands
1. Create `src/theact/web/command_router.py` (Section 4.4)
2. Rewrite `src/theact/web/commands.py` to thin rendering layer over `commands/logic.py`
3. Verify: `uv run pytest tests/web/ -v` (slash command tests still pass)

### Step 0g: Refactor `session.py` and create `menu.py`
1. Create `src/theact/web/menu.py` (Section 6)
2. Rewrite `src/theact/web/session.py` as thin orchestrator (Section 4.5)
3. Slim down `src/theact/web/app.py` to routing only (Section 6)
4. Verify: `uv run pytest tests/web/ -v` (ALL existing web tests pass)

### Step 0h: Manual Playwright validation
1. Start dev server: `uv run scripts/dev_server.py start --port 8111`
2. Use Playwright MCP to navigate, screenshot, and interact
3. Verify: menu works (new game, load save, delete save)
4. Verify: gameplay works (submit input, streaming, slash commands)
5. Convert any issues found into regression tests
6. Run: `uv run prek run --all-files` for lint/format

---

## 8. Verification Criteria

All of the following must be true after this step:

1. **All existing web tests pass.** `uv run pytest tests/web/ -v` — zero failures.
2. **All existing non-web tests pass.** `uv run pytest tests/ -v` — zero failures.
3. **Web UI behaves identically.** Menu, gameplay, streaming, all slash commands work as before.
4. **No feature regressions.** Manually verify with Playwright: new game, load save, play a turn, use /undo, /history, /memory, /status, /help, /think, /retry, /save-as, /quit.
5. **GameplaySession is < 150 lines.** The god class is split into focused modules.
6. **Command duplication is eliminated.** `commands/logic.py` contains shared logic; both CLI and web commands are thin rendering layers.
7. **Components are modular.** Each component type has its own file in `components/`.
8. **New unit tests for shared commands.** `tests/test_command_logic.py` covers all command functions.
9. **Lint passes.** `uv run prek run --all-files` — zero failures.

---

## 9. File Change Summary

| File | Action | Lines (approx) |
|---|---|---|
| `src/theact/commands/__init__.py` | **NEW** | 5 |
| `src/theact/commands/types.py` | **NEW** | 20 |
| `src/theact/commands/logic.py` | **NEW** | 150 |
| `src/theact/cli/commands.py` | REWRITE | 100 (was 257) |
| `src/theact/web/components/__init__.py` | **NEW** | 25 |
| `src/theact/web/components/turn_card.py` | **NEW** | 20 |
| `src/theact/web/components/message_blocks.py` | **NEW** | 80 |
| `src/theact/web/components/thinking_panel.py` | **NEW** | 20 |
| `src/theact/web/components/system_message.py` | **NEW** | 15 |
| `src/theact/web/components/static_turn.py` | **NEW** | 60 |
| `src/theact/web/components/dialogs.py` | **NEW** | 100 |
| `src/theact/web/components/html_utils.py` | **NEW** | 80 |
| `src/theact/web/state.py` | **NEW** | 50 |
| `src/theact/web/turn_runner.py` | **NEW** | 40 |
| `src/theact/web/streaming.py` | **NEW** | 80 |
| `src/theact/web/command_router.py` | **NEW** | 80 |
| `src/theact/web/menu.py` | **NEW** | 120 |
| `src/theact/web/app.py` | REWRITE | 60 (was 312) |
| `src/theact/web/session.py` | REWRITE | 120 (was 453) |
| `src/theact/web/commands.py` | REWRITE | 40 (was 239) |
| `src/theact/web/components.py` | DELETE | 0 (was 179) |
| `tests/test_command_logic.py` | **NEW** | 100 |
| `tests/test_web_commands.py` | REWRITE | — |
| `tests/test_web_session.py` | REWRITE | — |

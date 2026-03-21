# Phase 04: Rich Terminal CLI

> **Implementation note:** The CLI is a thin presentation layer. If you find yourself putting game logic here, stop — it belongs in the engine (Phase 03). The CLI should only: render output, collect input, and dispatch commands.

## 1. Overview

This phase builds the primary user interface for TheAct — a terminal CLI powered by the Rich library. The CLI is a thin presentation layer over the turn engine (Phase 03). No game logic lives here. Its responsibilities are:

- Present game management menus (list games, create/load/delete saves)
- Capture player input and forward it to the turn engine
- Render streaming tokens in real time with visual distinction between narrator, characters, and thinking
- Process slash commands (/undo, /history, /status, etc.)
- Run an asyncio event loop that drives the async turn engine

The CLI deliberately uses Rich's Console and markup primitives — not Textual. This is a scrolling terminal experience, not a TUI with panels and widgets. The player types, hits enter, and text streams in.

### File Layout

All code from this phase lives under `src/theact/cli/`:

```
src/theact/cli/
    __init__.py          # Public API: main() entry point
    app.py               # Top-level application loop (menu → game session)
    menu.py              # Game management: list, create, load, delete
    session.py           # Gameplay loop: input → turn engine → display
    commands.py          # Slash command parser and handlers
    renderer.py          # Rich-based rendering: streaming, styling, layout
    styles.py            # Color/style constants
```

Additionally, the entry point:

```
main.py                  # asyncio.run(main()) — the script the player runs
```

---

## 2. Architecture

```
+-----------------------------------------------------------+
|  main.py                                                  |
|  asyncio.run(cli.main())                                  |
+-----------------------------------------------------------+
        |
        v
+-----------------------------------------------------------+
|  app.py — Application                                     |
|  Main menu loop: games/saves management                   |
|  Transitions to Session when player loads a save           |
+-----------------------------------------------------------+
        |                           |
        v                           v
+-------------------+   +---------------------------+
|  menu.py          |   |  session.py — GameSession  |
|  list_games()     |   |  Gameplay loop:            |
|  create_save()    |   |  input → turn engine →     |
|  list_saves()     |   |  stream display → repeat   |
|  delete_save()    |   +---------------------------+
+-------------------+          |            |
                               v            v
                    +---------------+  +----------------+
                    | commands.py   |  | renderer.py    |
                    | parse /cmd    |  | stream tokens  |
                    | dispatch      |  | style text     |
                    +---------------+  +----------------+
                                            |
                                            v
                                    +---------------+
                                    | styles.py     |
                                    | color consts  |
                                    +---------------+
```

### Dependency Direction

The CLI depends on:
- `theact.io.save_manager` — list_games, create_save, load_save, list_saves, delete_save
- `theact.versioning.git_save` — undo, get_history
- `theact.engine` (Phase 03) — TurnEngine, its async streaming interface
- `theact.models` — LoadedGame, GameState, CharacterMemory, ConversationEntry
- `theact.llm.streaming` — StreamChunk (for type checking during rendering)
- `rich` — Console, markup, Live, Spinner, Panel, Table, Rule, Text

The CLI never imports anything from the agents or prompt templates. It only talks to the turn engine's public interface.

### The Turn Engine Interface (from Phase 03)

Phase 03 defines `run_turn()` as a standalone async function with a `StreamCallback`:

```python
# Phase 03's actual interface:
StreamCallback = Callable[[str, str, str], Awaitable[None]]
# (source: "narrator"|"character", character_name: str, token: str)

async def run_turn(
    game: LoadedGame,
    player_input: str,
    llm_config: LLMConfig,
    on_token: StreamCallback | None = None,
) -> TurnResult
```

**This CLI wraps that into a TurnEvent-based async iterator** to decouple rendering from the callback signature. The `TurnEngine` class below is a thin adapter defined in `cli/session.py` (or `engine/__init__.py`) — it does NOT add game logic:

```python
class TurnEngine:
    """Thin adapter: wraps run_turn's StreamCallback into an AsyncIterator[TurnEvent]."""

    def __init__(self, game: LoadedGame, llm_config: LLMConfig):
        self.game = game
        self.llm_config = llm_config

    async def play_turn(self, player_input: str) -> AsyncIterator[TurnEvent]:
        """
        Yields TurnEvent objects as the turn progresses:
        - NarratorThinking(chunk: str)
        - NarratorContent(chunk: str)
        - NarratorDone(full_text: str, metadata: dict)
        - CharacterThinking(character: str, chunk: str)
        - CharacterContent(character: str, chunk: str)
        - CharacterDone(character: str, full_text: str)
        - PostProcessingStart()
        - PostProcessingDone(state: GameState)
        - TurnComplete(turn: int)

        Internally calls engine.run_turn() with an on_token callback that
        pushes TurnEvent objects into an asyncio.Queue, which this method
        yields from.
        """
        ...
```

The CLI iterates over `TurnEvent` objects and dispatches each to the renderer. This is the only coupling point between the engine and the CLI. The adapter pattern keeps all game logic in Phase 03 while giving the CLI a clean iteration interface.

---

## 3. Game Flow

### 3.1 Launch

The player runs:

```
uv run python main.py
```

This calls `asyncio.run(cli.main())`, which:

1. Loads `.env` (dotenv)
2. Validates that `LLM_API_KEY` is set
3. Prints the title banner
4. Enters the main menu

### 3.2 Main Menu

```
╭─────────────────────────────────╮
│         T H E   A C T           │
│     an AI text-based RPG        │
╰─────────────────────────────────╯

  1. New Game
  2. Continue Game
  3. Delete Save
  4. Quit

>
```

Each option:

**1. New Game:**
- Lists available game definitions from `games/`
- Player picks a game
- Player enters a save name (auto-slugified, e.g., "my playthrough" → "my-playthrough")
- Player enters their character name
- `save_manager.create_save()` is called
- Immediately enters gameplay with the new save

**2. Continue Game:**
- Lists existing saves with metadata (game title, turn number, last modified)
- Player picks one
- `save_manager.load_save()` is called
- Shows a brief recap: the last 3-5 conversation entries from `game.conversation`, styled with narrator/character colors, so the player has context for where they left off. Prefixed with a "Previously..." header.
- Enters gameplay

**3. Delete Save:**
- Lists existing saves
- Player picks one (or cancels)
- Confirms deletion
- `save_manager.delete_save()` removes the save directory
- Returns to main menu

**4. Quit:**
- Exit cleanly

### 3.3 Gameplay Loop

Once a save is loaded, the player enters the gameplay session. The loop:

```
1. Display turn header (Turn N, Chapter title)
2. If turn 0: run an initial narrator turn with no player input (opening narration)
3. Show prompt: player name >
4. Read input
5. If input starts with "/": parse and execute slash command
6. Otherwise: pass input to turn_engine.play_turn()
7. Iterate over TurnEvents, rendering each via renderer
8. After TurnComplete: loop back to step 1
```

### 3.4 First Turn (Turn 0 → Turn 1)

When a brand new save is loaded (turn == 0), the CLI automatically triggers the first turn with an empty player input (or a sentinel like `"[game start]"`). This produces the opening narration — the narrator sets the scene without the player having typed anything. The turn counter advances to 1 and the player sees their first prompt.

### 3.5 Exiting

The player can exit via:
- `/quit` command
- Ctrl+C (caught by signal handler, prints farewell)
- Ctrl+D (EOF on input, same as `/quit`)

On any exit, the game state is already persisted (git commit happens at the end of every turn in Phase 03). No explicit "save on exit" is needed. The CLI prints a brief confirmation:

```
Game saved at turn 7. See you next time.
```

---

## 4. Commands

All commands are prefixed with `/` during gameplay. The `commands.py` module parses the input and dispatches to the appropriate handler.

### 4.1 Command Parser

```python
def parse_command(raw_input: str) -> tuple[str, list[str]] | None:
    """
    If input starts with '/', parse it as a command.
    Returns (command_name, args) or None if not a command.

    Examples:
        "/undo"       → ("undo", [])
        "/undo 3"     → ("undo", ["3"])
        "/memory maya" → ("memory", ["maya"])
        "hello"       → None
    """
```

### 4.2 Command Reference

| Command | Args | Behavior |
|---|---|---|
| `/help` | none | Print the command reference table |
| `/quit` | none | Exit the game session, return to main menu |
| `/undo [N]` | optional int, default 1 | Undo last N turns. Calls `git_save.undo()`. Reloads game state. Prints confirmation with new turn number. |
| `/history` | none | Show turn history from `git_save.get_history()`. Displays as a numbered list with turn number, commit message, and timestamp. |
| `/save` | none | Show current save info: save ID, game title, player name, save path. |
| `/status` | none | Show game state: current chapter (title + ID), turn number, beats hit vs. total beats, active flags. |
| `/memory [character]` | optional character name | With no args: list all characters. With a name: show that character's memory (summary + key_facts). Uses fuzzy matching on character name (case-insensitive, partial match). |
| `/think [on\|off]` | optional toggle | Toggle thinking token visibility. With no args: show current state. Default is on. |
| `/retry` | none | Undo the last turn and replay the same player input. Equivalent to `/undo` followed by re-submitting the previous input. Useful when the LLM produces a bad response. |
| `/conversation [N]` | optional int, default 5 | Show the last N conversation entries (narrator, player, character text). Useful for reviewing context after loading a save or after an undo. |

### 4.3 Edge Cases

- **Unknown command**: Print "Unknown command: /foo. Type /help for available commands."
- **Invalid args**: Print usage hint for that specific command. E.g., `/undo abc` → "Usage: /undo [N] where N is a positive integer."
- **Undo past beginning**: `git_save.undo()` raises `ValueError`. CLI catches it and prints "Cannot undo: only N turns in history."
- **Memory for unknown character**: Print "Unknown character. Available: Maya Chen, Father Joaquin Reyes."
- **Empty input** (just pressing enter): Ignore, re-show the prompt. Do not send an empty string to the turn engine.

---

## 5. Rendering

### 5.1 Style Constants (`styles.py`)

```python
from rich.style import Style

# --- Narrative styles ---
NARRATOR_STYLE = Style(color="white", italic=True)
NARRATOR_LABEL_STYLE = Style(color="bright_white", bold=True, italic=True)

# --- Character styles ---
# Characters get assigned colors from this palette in order of appearance.
CHARACTER_COLORS = [
    "bright_cyan",
    "bright_magenta",
    "bright_yellow",
    "bright_green",
    "bright_red",
    "bright_blue",
]
CHARACTER_NAME_STYLE = Style(bold=True)  # combined with character color

# --- Player styles ---
PLAYER_STYLE = Style(color="bright_white", bold=True)
PLAYER_PROMPT_STYLE = Style(color="bright_white", bold=True)

# --- Thinking styles ---
THINKING_STYLE = Style(color="bright_black", dim=True)  # gray, dimmed
THINKING_LABEL_STYLE = Style(color="bright_black", bold=True, dim=True)

# --- UI styles ---
STATUS_STYLE = Style(color="bright_black")
ERROR_STYLE = Style(color="red", bold=True)
TURN_HEADER_STYLE = Style(color="bright_black", bold=True)
COMMAND_OUTPUT_STYLE = Style(color="bright_black")

# --- Separators ---
TURN_SEPARATOR = "dim"  # Rich Rule style
```

### 5.2 Character Color Assignment

Each character in the game is assigned a color from `CHARACTER_COLORS` based on their index in the game's character list. This is deterministic — the same character always gets the same color within a game.

```python
def get_character_color(character_name: str, character_list: list[str]) -> str:
    """Return the color for a character based on their position in the roster."""
    try:
        idx = character_list.index(character_name)
    except ValueError:
        idx = hash(character_name)  # fallback for unknown characters
    return CHARACTER_COLORS[idx % len(CHARACTER_COLORS)]
```

### 5.3 Turn Layout

A complete turn looks like this in the terminal:

```
─── Turn 3 · The Crash ────────────────────────────────────────

  ⠿ thinking...
  The model is reasoning about the player's action and the
  current state of the story...

  The tide has pulled back, exposing the reef like broken teeth.
  You can see the tail section now — half-submerged, tilted at
  an unnatural angle. Something moves in the tree line beyond
  the beach. Not wind. Something deliberate.

  Maya Chen
  She drops the piece of fuselage she was examining and looks
  where you're pointing. "I saw it too. About ten minutes ago."
  She pauses. "We should move camp inland before dark."

  ⠿ updating world state...

─────────────────────────────────────────────────────────────

you >
```

Breakdown:
1. **Turn separator**: Rich `Rule` with turn number and chapter title, dimmed
2. **Thinking section**: Gray/dimmed text, preceded by a small label. Streams in real-time. Can be toggled off.
3. **Narrator text**: White italic. Streams token by token.
4. **Character block**: Character name in bold+color on its own line, followed by their dialogue/action text in that color. Streams token by token.
5. **Post-processing indicator**: Brief spinner ("updating world state..."), not streamed text — just a status indicator.
6. **Bottom separator**: Simple rule.
7. **Player prompt**: Player name in bold white, `>` cursor.

### 5.4 Thinking Section

The thinking section displays the model's reasoning tokens. It renders as:

```
  ⠿ thinking...
  i need to consider what the player is doing. they want to
  explore the wreckage. the chapter beat says they should
  discover a body. i should narrate them approaching the
  tail section and finding something disturbing...
```

- The `⠿ thinking...` label appears when the first thinking token arrives
- Subsequent thinking tokens append to the section, streaming in
- The entire section is styled with `THINKING_STYLE` (gray, dimmed)
- When content tokens start arriving, a blank line separates thinking from content
- If thinking is toggled off (`/think off`), thinking tokens are silently consumed but not printed

### 5.5 Streaming Display

Tokens are printed character by character as they arrive from the async iterator. The key requirement is that there is no flickering or jarring redraws. We use `Console.print()` with `end=""` for inline streaming (not `rich.live.Live`, which would redraw the whole block).

**Important: Streaming tokens must not be parsed as Rich markup.** LLM output frequently contains bracket characters (e.g., `[she paused]`, `[sound of waves]`) which Rich would interpret as markup tags, causing garbled output or exceptions. All streaming `console.print()` calls must use `Text` objects (which are pre-escaped) or pass `markup=False, highlight=False`.

```python
# Simplified rendering pseudocode
from rich.text import Text

console = Console()

async for event in turn_engine.play_turn(player_input):
    match event:
        case NarratorThinking(chunk=text):
            if show_thinking:
                console.print(Text(text, style=THINKING_STYLE), end="")
        case NarratorContent(chunk=text):
            console.print(Text(text, style=NARRATOR_STYLE), end="")
        case CharacterContent(character=name, chunk=text):
            color = get_character_color(name, characters)
            console.print(Text(text, style=Style(color=color)), end="")
        ...
```

This works because:
- Rich's `Console.print()` with `end=""` writes inline without a newline
- Using `Text()` objects prevents Rich from interpreting brackets in LLM output as markup
- Each token is a small string fragment (often a single word or word piece)
- The terminal handles the scrolling naturally
- No redraws needed — we only append

---

## 6. Streaming Display — Detailed Behavior

### 6.1 Token Flow

The turn engine yields events in this order for a typical turn:

```
NarratorThinking("i need to")     ← 0+ thinking chunks
NarratorThinking(" consider...")
NarratorContent("The tide has")   ← narrator prose chunks
NarratorContent(" pulled back,")
NarratorContent(" exposing...")
NarratorDone(full_text, metadata) ← signals end of narrator
CharacterThinking("maya would")   ← 0+ per-character thinking
CharacterContent("maya", "She")   ← character prose chunks
CharacterContent("maya", " drops")
CharacterDone("maya", full_text)  ← signals end of character
PostProcessingStart()             ← spinner begins
PostProcessingDone(state)         ← spinner ends
TurnComplete(turn=3)              ← turn fully committed
```

### 6.2 Transition Handling

The renderer must handle transitions between sections cleanly:

- **Thinking → Content**: Print a blank line to separate the thinking block from the narrative.
- **Narrator → Character**: Print a blank line, then the character name label on its own line, then begin streaming character text.
- **Character → Character** (sequential characters): Same — blank line, new character name label, stream text.
- **Character → Post-processing**: Print a blank line, show spinner.

The renderer tracks a `current_section` state to know when transitions occur:

```python
class RenderState:
    IDLE = "idle"
    THINKING = "thinking"
    NARRATOR = "narrator"
    CHARACTER = "character"
    POST_PROCESSING = "post_processing"
```

When the incoming event type differs from `current_section`, the renderer emits appropriate spacing and labels before printing the token.

### 6.3 Post-Processing Display

Post-turn processing (memory updates + game state check) runs in the background. The CLI shows a brief spinner:

```
  ⠿ updating world state...
```

This uses `rich.console.Console.status()` — a context manager that shows an animated spinner. It appears after the last character finishes and disappears when the turn is fully committed.

### 6.4 Error During Streaming

If the LLM call fails mid-stream (connection error, timeout):
- The partial text that was already rendered stays on screen (it has been printed)
- An error message is shown in `ERROR_STYLE`: "Error: Lost connection to AI. Your turn was not saved. Try again."
- The player returns to the input prompt
- No git commit happens (the turn engine handles this — `run_turn` only commits on success)
- **State rollback**: The turn engine may have mutated `game.state` or appended to `game.conversation` in memory before the error. The CLI must reload the game from disk after an error to discard any partial in-memory mutations: `self.game = save_manager.load_save(self.game.save_path)`. Since no git commit was made, the on-disk state is still the last committed turn.
- If the spinner is active when the error occurs, the renderer must stop it (see `show_error` below)

### 6.5 Console Width

The renderer does not manually wrap text. Rich and the terminal handle wrapping based on terminal width. Long narration flows naturally. If the terminal is very narrow (< 40 columns), the experience degrades gracefully — Rich handles this.

---

## 7. Module Details

### 7.1 `app.py` — Application

```python
from rich.console import Console

class Application:
    """Top-level CLI application."""

    def __init__(self):
        self.console = Console()
        self.llm_config = None  # loaded on start

    async def run(self):
        """Main entry point. Shows banner, then main menu loop."""
        self._print_banner()
        self.llm_config = self._load_config()

        while True:
            choice = await self._main_menu()
            if choice == "new":
                await self._new_game()
            elif choice == "continue":
                await self._continue_game()
            elif choice == "delete":
                await self._delete_save()
            elif choice == "quit":
                self._farewell()
                break

    def _print_banner(self):
        """Print the title card."""
        ...

    def _load_config(self) -> LLMConfig:
        """Load LLM config from env. Print error and exit if missing."""
        ...

    async def _main_menu(self) -> str:
        """Display menu, return choice string."""
        ...

    async def _new_game(self):
        """Game selection → save creation → enter session."""
        ...

    async def _continue_game(self):
        """Save selection → load → enter session."""
        ...

    async def _delete_save(self):
        """Save selection → confirm → delete."""
        ...

    async def _enter_session(self, game: LoadedGame):
        """Create TurnEngine and GameSession, run session loop."""
        engine = TurnEngine(game, self.llm_config)
        session = GameSession(self.console, engine, game)
        await session.run()

    def _farewell(self):
        self.console.print("\nUntil next time.\n", style=STATUS_STYLE)
```

### 7.2 `menu.py` — Game Management

```python
from rich.console import Console
from rich.table import Table

def show_game_list(console: Console) -> list[GameMeta]:
    """Display available games as a numbered table. Returns the list."""
    games = save_manager.list_games()
    if not games:
        console.print("No games found in games/.", style=ERROR_STYLE)
        return []
    table = Table(title="Available Games")
    table.add_column("#", style="bold")
    table.add_column("Title")
    table.add_column("Description")
    for i, game in enumerate(games, 1):
        table.add_row(str(i), game.title, game.description)
    console.print(table)
    return games

def show_save_list(console: Console) -> list[dict]:
    """Display existing saves as a numbered table. Returns the list."""
    saves = save_manager.list_saves()
    if not saves:
        console.print("No saves found.", style=STATUS_STYLE)
        return []
    table = Table(title="Saved Games")
    table.add_column("#", style="bold")
    table.add_column("Save ID")
    table.add_column("Game")
    table.add_column("Turn")
    table.add_column("Last Played")
    for i, save in enumerate(saves, 1):
        table.add_row(str(i), save["id"], save["game"], str(save["turn"]), save["modified"])
    console.print(table)
    return saves

def prompt_choice(console: Console, items: list, prompt: str = "Select") -> int | None:
    """Prompt user to pick a numbered item. Returns 0-based index or None on cancel."""
    ...

def prompt_text(console: Console, prompt: str, default: str = "") -> str:
    """Prompt for free-form text input. Returns stripped string."""
    ...

def confirm(console: Console, message: str) -> bool:
    """Yes/no confirmation. Returns True if yes."""
    ...

def slugify(text: str) -> str:
    """Convert a free-form name to a URL-safe slug."""
    # lowercase, replace spaces/special chars with hyphens, strip leading/trailing hyphens
    ...
```

### 7.3 `session.py` — GameSession

```python
class GameSession:
    """Manages a single gameplay session from load to quit."""

    def __init__(self, console: Console, engine: TurnEngine, game: LoadedGame):
        self.console = console
        self.engine = engine
        self.game = game
        self.renderer = Renderer(console, game)
        self.show_thinking = True

    async def run(self):
        """Main gameplay loop."""
        if self.game.state.turn == 0:
            # Fresh game — run the opening narration automatically
            await self._play_turn("[game start]")
        else:
            # Resuming a saved game — show recent context so the player
            # knows where they left off
            self._show_recap()

        while True:
            player_input = self._get_input()

            if player_input is None:
                # EOF (Ctrl+D) — treat as quit
                break

            if not player_input.strip():
                continue

            command = parse_command(player_input)
            if command:
                cmd_name, args = command
                should_quit = await self._handle_command(cmd_name, args)
                if should_quit:
                    break
                continue

            await self._play_turn(player_input)

        self._print_exit_message()

    async def _play_turn(self, player_input: str):
        """Run a turn through the engine, streaming results to the renderer."""
        self.renderer.begin_turn(self.game.state.turn + 1, self._current_chapter_title())

        try:
            async for event in self.engine.play_turn(player_input):
                self.renderer.handle_event(event, show_thinking=self.show_thinking)
        except Exception as e:
            self.renderer.show_error(f"Error during turn: {e}")
            # Reload from disk to discard any partial in-memory state mutations
            self.game = save_manager.load_save(self.game.save_path)
            return

        self.renderer.end_turn()
        # Reload game state after turn (the engine has committed changes)
        self.game = save_manager.load_save(self.game.save_path)

    def _get_input(self) -> str | None:
        """Prompt for player input. Returns None on EOF."""
        try:
            return self.console.input(
                f"[bold bright_white]{self.game.state.player_name} > [/]"
            )
        except EOFError:
            return None

    async def _handle_command(self, cmd: str, args: list[str]) -> bool:
        """Execute a slash command. Returns True if session should end."""
        ...  # delegates to commands.py functions

    def _show_recap(self):
        """Show the last few conversation entries so the player has context."""
        entries = self.game.conversation[-5:]  # last 5 entries
        if not entries:
            return
        self.console.print()
        self.console.print("  Previously...", style=Style(dim=True, italic=True))
        self.console.print()
        for entry in entries:
            if entry.role == "narrator":
                # Show truncated narrator text
                text = entry.content[:200] + ("..." if len(entry.content) > 200 else "")
                self.console.print(Text(f"  {text}", style=NARRATOR_STYLE))
            elif entry.role == "player":
                line = Text(f"  {self.game.state.player_name}: ", style=PLAYER_STYLE)
                line.append(entry.content)
                self.console.print(line)
            elif entry.role == "character":
                name = entry.character or "?"
                color = get_character_color(name, list(self.game.characters.keys()))
                self.console.print(Text(f"  {name}: ", style=Style(color=color, bold=True)), end="")
                text = entry.content[:200] + ("..." if len(entry.content) > 200 else "")
                self.console.print(Text(text, style=Style(color=color)))
        self.console.print()

    def _current_chapter_title(self) -> str:
        chapter_id = self.game.state.current_chapter
        return self.game.chapters[chapter_id].title

    def _print_exit_message(self):
        turn = self.game.state.turn
        self.console.print(
            f"\nGame saved at turn {turn}. See you next time.\n",
            style=STATUS_STYLE,
        )
```

### 7.4 `commands.py` — Command Handling

```python
from rich.console import Console
from rich.table import Table

COMMANDS = {
    "help":    {"args": "",               "desc": "Show this help message"},
    "quit":    {"args": "",               "desc": "Exit to main menu"},
    "undo":    {"args": "[N]",            "desc": "Undo last N turns (default: 1)"},
    "history": {"args": "",               "desc": "Show turn history"},
    "save":    {"args": "",               "desc": "Show current save info"},
    "status":  {"args": "",               "desc": "Show game status"},
    "memory":  {"args": "[character]",    "desc": "Show character memory"},
    "think":   {"args": "[on|off]",       "desc": "Toggle thinking display"},
    "retry":   {"args": "",               "desc": "Undo last turn and replay same input"},
    "conversation": {"args": "[N]",       "desc": "Show last N conversation entries"},
}

def parse_command(raw_input: str) -> tuple[str, list[str]] | None:
    """Parse a slash command. Returns (name, args) or None."""
    stripped = raw_input.strip()
    if not stripped.startswith("/"):
        return None
    parts = stripped[1:].split()
    if not parts:
        return None
    return parts[0].lower(), parts[1:]

def cmd_help(console: Console):
    """Display command reference."""
    table = Table(title="Commands", show_header=True)
    table.add_column("Command", style="bold")
    table.add_column("Args")
    table.add_column("Description")
    for name, info in COMMANDS.items():
        table.add_row(f"/{name}", info["args"], info["desc"])
    console.print(table)

def cmd_undo(console: Console, game: LoadedGame, args: list[str]) -> LoadedGame:
    """
    Undo N turns. Returns the reloaded game.
    Raises ValueError for invalid args or over-undo.
    """
    steps = 1
    if args:
        try:
            steps = int(args[0])
            if steps < 1:
                raise ValueError
        except ValueError:
            console.print("Usage: /undo [N] where N is a positive integer.", style=ERROR_STYLE)
            return game

    try:
        new_turn = git_save.undo(Path(game.save_path), steps)
        game = save_manager.load_save(game.save_path)
        console.print(f"Undone {steps} turn(s). Now at turn {new_turn}.", style=STATUS_STYLE)
        return game
    except ValueError as e:
        console.print(f"Cannot undo: {e}", style=ERROR_STYLE)
        return game

def cmd_history(console: Console, game: LoadedGame):
    """Display turn history."""
    history = git_save.get_history(Path(game.save_path))
    if not history:
        console.print("No turn history yet.", style=STATUS_STYLE)
        return
    table = Table(title="Turn History")
    table.add_column("Turn", style="bold")
    table.add_column("Summary")
    table.add_column("Time")
    for entry in history:
        table.add_row(str(entry.turn), entry.message, entry.timestamp)
    console.print(table)

def cmd_save(console: Console, game: LoadedGame):
    """Display save info."""
    console.print(f"  Save:    {game.meta.id}", style=COMMAND_OUTPUT_STYLE)
    console.print(f"  Game:    {game.meta.title}", style=COMMAND_OUTPUT_STYLE)
    console.print(f"  Player:  {game.state.player_name}", style=COMMAND_OUTPUT_STYLE)
    console.print(f"  Path:    {game.save_path}", style=COMMAND_OUTPUT_STYLE)

def cmd_status(console: Console, game: LoadedGame):
    """Display game status."""
    chapter = game.chapters[game.state.current_chapter]
    beats_total = len(chapter.beats)
    beats_done = len(game.state.beats_hit)

    console.print(f"  Chapter: {chapter.title} ({chapter.id})", style=COMMAND_OUTPUT_STYLE)
    console.print(f"  Turn:    {game.state.turn}", style=COMMAND_OUTPUT_STYLE)
    console.print(f"  Beats:   {beats_done}/{beats_total}", style=COMMAND_OUTPUT_STYLE)
    if game.state.flags:
        console.print(f"  Flags:   {game.state.flags}", style=COMMAND_OUTPUT_STYLE)

def cmd_memory(console: Console, game: LoadedGame, args: list[str]):
    """Display character memory."""
    if not args:
        # List characters
        console.print("Characters:", style=COMMAND_OUTPUT_STYLE)
        for name in game.characters:
            char = game.characters[name]
            has_memory = name in game.memories
            marker = " (has memory)" if has_memory else ""
            console.print(f"  - {char.name}{marker}", style=COMMAND_OUTPUT_STYLE)
        return

    # Find character by fuzzy match
    query = " ".join(args).lower()
    match = None
    for key, char in game.characters.items():
        if query in char.name.lower() or query in key.lower():
            match = key
            break

    if match is None:
        names = [game.characters[k].name for k in game.characters]
        console.print(f"Unknown character. Available: {', '.join(names)}", style=ERROR_STYLE)
        return

    if match not in game.memories:
        console.print(f"{game.characters[match].name} has no memories yet.", style=STATUS_STYLE)
        return

    memory = game.memories[match]
    console.print(f"\n  {memory.character} — Memory", style=Style(bold=True))
    console.print(f"\n  Summary: {memory.summary}", style=COMMAND_OUTPUT_STYLE)
    if memory.key_facts:
        console.print("  Key facts:", style=COMMAND_OUTPUT_STYLE)
        for fact in memory.key_facts:
            console.print(f"    - {fact}", style=COMMAND_OUTPUT_STYLE)
    console.print()

def cmd_think(console: Console, args: list[str], current: bool) -> bool:
    """Toggle or set thinking display. Returns new state."""
    if not args:
        state = "on" if current else "off"
        console.print(f"Thinking display is {state}.", style=STATUS_STYLE)
        return current

    arg = args[0].lower()
    if arg == "on":
        console.print("Thinking display enabled.", style=STATUS_STYLE)
        return True
    elif arg == "off":
        console.print("Thinking display disabled.", style=STATUS_STYLE)
        return False
    else:
        console.print("Usage: /think [on|off]", style=ERROR_STYLE)
        return current
```

### 7.5 `renderer.py` — Rendering Engine

```python
from rich.console import Console
from rich.rule import Rule
from rich.text import Text

class Renderer:
    """Handles all visual output during gameplay."""

    def __init__(self, console: Console, game: LoadedGame):
        self.console = console
        self.game = game
        self.character_list = list(game.characters.keys())
        self._section = RenderState.IDLE
        self._current_character = None

    def begin_turn(self, turn_number: int, chapter_title: str):
        """Print the turn header."""
        self.console.print()
        self.console.print(
            Rule(f" Turn {turn_number} · {chapter_title} ", style=TURN_SEPARATOR)
        )
        self.console.print()
        self._section = RenderState.IDLE

    def end_turn(self):
        """Print the turn footer."""
        self.console.print()
        self.console.print(Rule(style=TURN_SEPARATOR))
        self.console.print()
        self._section = RenderState.IDLE

    def handle_event(self, event, show_thinking: bool = True):
        """Route a TurnEvent to the appropriate rendering method."""
        match event:
            case NarratorThinking(chunk=text):
                self._render_thinking(text, show_thinking, label="thinking")
            case NarratorContent(chunk=text):
                self._transition_to(RenderState.NARRATOR)
                self.console.print(Text(text, style=NARRATOR_STYLE), end="")
            case NarratorDone():
                self.console.print()  # newline after narrator block
            case CharacterThinking(character=name, chunk=text):
                self._render_thinking(text, show_thinking, label=f"{name} thinking")
            case CharacterContent(character=name, chunk=text):
                self._transition_to_character(name)
                color = get_character_color(name, self.character_list)
                self.console.print(Text(text, style=Style(color=color)), end="")
            case CharacterDone():
                self.console.print()  # newline after character block
            case PostProcessingStart():
                self._transition_to(RenderState.POST_PROCESSING)
                self._start_spinner()
            case PostProcessingDone():
                self._stop_spinner()
            case TurnComplete():
                pass  # end_turn handles footer

    def _render_thinking(self, text: str, show: bool, label: str):
        """Render thinking tokens if enabled."""
        if not show:
            return
        if self._section != RenderState.THINKING:
            self._transition_to(RenderState.THINKING)
            self.console.print(f"  ⠿ {label}...", style=THINKING_LABEL_STYLE)
        self.console.print(Text(text, style=THINKING_STYLE), end="")

    def _transition_to(self, new_section: str):
        """Handle section transitions with appropriate spacing."""
        if self._section == new_section:
            return
        if self._section != RenderState.IDLE:
            self.console.print()  # end current inline stream
            self.console.print()  # blank line between sections
        self._section = new_section

    def _transition_to_character(self, name: str):
        """Handle transition into a character section, printing name label."""
        if self._section == RenderState.CHARACTER and self._current_character == name:
            return  # still same character, keep streaming
        self._transition_to(RenderState.CHARACTER)
        self._current_character = name
        color = get_character_color(name, self.character_list)
        display_name = self.game.characters.get(name, None)
        label = display_name.name if display_name else name
        self.console.print(f"  {label}", style=Style(color=color, bold=True))

    def _start_spinner(self):
        """Show a post-processing spinner. Uses console.status()."""
        # Note: console.status() is a context manager. We store it so _stop_spinner can exit.
        self._status_ctx = self.console.status(
            "  updating world state...", spinner="dots", style=STATUS_STYLE
        )
        self._status_ctx.__enter__()

    def _stop_spinner(self):
        """Stop the post-processing spinner."""
        if hasattr(self, "_status_ctx"):
            self._status_ctx.__exit__(None, None, None)
            del self._status_ctx
        self._section = RenderState.IDLE

    def show_error(self, message: str):
        """Display an error message. Also stops the spinner if it's running."""
        self._stop_spinner()  # safe to call even if spinner isn't active
        self.console.print()
        self.console.print(f"  Error: {message}", style=ERROR_STYLE)
        self.console.print()
```

---

## 8. Implementation Steps

Build in this order. Each step should produce working, runnable code before moving to the next.

### Step 1: Package scaffolding

- Create `src/theact/cli/` with `__init__.py`
- Create `styles.py` with all style constants
- Create `main.py` at the project root with a stub: `asyncio.run(main())` → prints banner and exits
- Add `rich` to `pyproject.toml` dependencies
- Verify `uv run python main.py` prints the banner

### Step 2: Menu system

- Implement `menu.py` with all menu display and prompt functions
- Implement the main menu in `app.py` (new game, continue, delete, quit)
- Wire up save_manager calls: list_games, list_saves, create_save, load_save
- At this point, "New Game" creates a save and prints "Session would start here" — no gameplay yet
- Verify: can create and list saves through the menu

### Step 3: Command parser

- Implement `commands.py` with `parse_command()` and all `cmd_*` functions
- Unit test: `parse_command("/undo 3")` → `("undo", ["3"])`
- Unit test: `parse_command("hello")` → `None`
- Wire up each command handler (most can work with just a LoadedGame, no engine needed)
- Verify: `/help`, `/save`, `/status`, `/memory`, `/history` all work on a loaded save

### Step 4: Renderer skeleton

- Implement `renderer.py` with the `Renderer` class
- Implement `begin_turn`, `end_turn`, `show_error`
- Test with mock events: create fake TurnEvent objects and feed them to `handle_event`
- Verify visual output looks correct in the terminal

### Step 5: Streaming display

- Implement `handle_event` for all event types: thinking, narrator, character, post-processing
- Implement section transitions and character labels
- Test with a script that simulates streaming events with `asyncio.sleep` delays
- Verify: tokens appear smoothly, transitions have correct spacing, no flickering

### Step 6: Game session

- Implement `session.py` with `GameSession`
- Wire up the gameplay loop: input → command check → turn engine → renderer
- Handle the turn 0 (opening narration) case
- Integrate command handlers so `/undo` reloads the game, `/quit` exits
- Handle Ctrl+C and Ctrl+D gracefully

### Step 7: Integration and polish

- Wire `app.py` → `session.py`: main menu "New Game" and "Continue" enter the session
- Test the full flow: launch → new game → play a turn → /undo → /quit → main menu
- Handle edge cases: no games available, no saves, invalid input
- Add the `/think` toggle
- Polish: adjust spacing, colors, ensure the experience feels clean

### Step 8: Entry point and delete save

- Finalize `main.py` as the canonical entry point
- Implement save deletion (menu option 3) with confirmation
- Consider adding `[project.scripts]` to `pyproject.toml` for a `theact` CLI command
- Final pass on error messages and edge cases

---

## 9. Verification

Phase 04 is complete when all of the following work:

### Manual Tests

1. **Launch and menu**: `uv run python main.py` shows the banner and main menu
2. **New game flow**: Select "New Game" → pick a game → enter save name → enter player name → see opening narration stream in
3. **Continue game flow**: Select "Continue" → pick a save → see "Previously..." recap with last few conversation entries → resume at correct turn → type input → see narrator and character responses stream in
4. **Streaming quality**: Tokens appear smoothly without flickering. Thinking is gray/dimmed. Narrator is white/italic. Characters have distinct colors and bold names.
5. **All slash commands**:
   - `/help` — shows command table
   - `/quit` — returns to main menu with save confirmation
   - `/undo` — undoes last turn, shows new turn number
   - `/undo 3` — undoes 3 turns
   - `/undo 999` — shows error about insufficient history
   - `/history` — shows turn history table
   - `/save` — shows save info
   - `/status` — shows chapter, turn, beats
   - `/memory` — lists characters
   - `/memory maya` — shows Maya's memory
   - `/memory unknown` — shows error with available names
   - `/think off` — hides thinking on next turn
   - `/think on` — shows thinking again
   - `/retry` — undoes last turn and replays same input
   - `/conversation` — shows last 5 conversation entries
   - `/conversation 10` — shows last 10 entries
6. **Empty input**: Pressing enter without text re-shows the prompt
7. **Ctrl+C**: Catches interrupt, prints farewell, exits cleanly
8. **Ctrl+D**: Treats as quit
9. **Delete save**: Select delete → pick save → confirm → save is removed
10. **No games**: If `games/` is empty, shows appropriate message
11. **Error resilience**: If LLM connection fails mid-stream, shows error message and returns to prompt without crashing

### Automated Tests

The CLI is primarily a presentation layer, so automated testing is focused on the non-visual components:

- `test_commands.py`:
  - `parse_command` correctly parses all command formats
  - `parse_command` returns None for non-commands
  - `slugify` produces valid slugs
- `test_styles.py`:
  - `get_character_color` returns deterministic colors
  - `get_character_color` handles unknown characters via fallback

### Live Testing & Regression Capture

The CLI is hard to test automatically since it's a presentation layer, but live testing reveals UX issues that matter.

**Step 1 — Play a real session (5+ turns):**
- Launch the CLI, create a new game, and play naturally for 5+ turns. Pay attention to:
  - Does streaming feel smooth, or are there pauses/jumps between narrator and character output?
  - Is the visual distinction between narrator and characters clear at a glance?
  - Does thinking text feel intrusive or useful? Adjust dimming/collapse behavior.
  - Does `/undo` feel responsive? After undoing, is the state clearly communicated?
  - What happens if you type a very long input (200+ words)? Does it wrap correctly?
  - What happens if the model produces a very long response (500+ words)? Is it readable?
  - Does the post-processing spinner feel appropriate, or does it hang too long?

**Step 2 — Fix and capture:**
- For any command-parsing edge cases found (e.g., `/undo  3` with extra spaces, `/UNDO` uppercase), fix `parse_command` and add a test case.
- For any rendering issues, fix the renderer and document the fix in a test where possible (e.g., test that character names with special characters render correctly).

**Step 3 — Verify:**
- Run `uv run pytest tests/ -v` — all tests pass.
- Play another 3-turn session to confirm fixes didn't introduce new UX issues.

---

## 10. Dependencies

Add to `pyproject.toml`:

```toml
dependencies = [
    "openai>=2.29.0",
    "python-dotenv>=1.2.2",
    "pydantic>=2.10.0",
    "pyyaml>=6.0",
    "gitpython>=3.1.0",
    "rich>=13.0.0",
]
```

### Rich Library — What We Use

| Rich Feature | Where Used |
|---|---|
| `Console` | All output — `print()`, `input()`, `status()` |
| `Console.print(Text(...), end="")` | Streaming token display (use `Text` objects, never raw strings — LLM output contains brackets that Rich would misinterpret as markup) |
| `Console.status()` | Post-processing spinner |
| `Console.input()` | Player input with styled prompt |
| `Rule` | Turn separators with labels |
| `Table` | Menu lists, command help, history |
| `Style` | All styling constants |
| `Panel` | Title banner (optional, for the main menu card) |
| `Text` | Composing styled text segments when needed |
| Markup (`[bold]...[/]`) | Inline styling in prompts |

What we do NOT use from Rich:
- `Live` — not needed; we append-only, never redraw
- `Layout` / `Columns` — not a panel-based UI
- `Progress` — no progress bars
- `Prompt` / `Confirm` — we use `Console.input()` directly for simpler control
- `Textual` — entirely separate library; we want a CLI, not a TUI

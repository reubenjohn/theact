# Phase 07: Web UI

> **Implementation note:** NiceGUI should be an optional dependency under `[project.optional-dependencies]` so CLI-only users aren't affected. The web UI uses the same turn engine interface as the CLI — no engine changes should be needed.

## 1. Overview

This phase builds a browser-based frontend as an alternative to the Rich CLI (Phase 04). The web UI connects to the same turn engine and uses the same `TurnEvent` async iterator pattern. No changes to the engine, data models, or any prior phase are required.

The web UI provides:
- A chat-like interface where narrator text, character dialogue, and player input appear as styled messages
- Real-time streaming of tokens as they arrive from the LLM
- Collapsible thinking token sections for transparency into model reasoning
- Game management (list games, create saves, load saves, delete saves)
- All slash commands available through the UI
- Visual distinction between characters using colors and name labels
- Input locking during turn processing to prevent double-submission

All code lives under `src/theact/web/`. A separate entry point (`web.py` or a console script) launches the web server. The Rich CLI remains fully functional and unmodified.

---

## 2. Framework Evaluation

Four Python-first web frameworks are evaluated against the specific requirements of this project: streaming token display, collapsible thinking sections, chat interface, minimal frontend code, and input locking during processing.

### 2.1 NiceGUI

**What it is:** A Python-first web framework that builds on FastAPI + Vue.js + Quasar. UI elements are declared in Python. All state lives server-side. Communication happens over WebSockets with automatic reactivity.

**Pros for TheAct:**
- **WebSocket-native.** UI updates are pushed from server to client in real time. No polling. This is the correct architecture for streaming tokens.
- **`ui.chat_message` component.** Built-in chat message widget with avatar, name, color support. Directly maps to our narrator/character/player message pattern.
- **`ui.expansion` component.** Collapsible panels -- ideal for thinking token sections. Can start collapsed and expand on click.
- **Async-native.** Event handlers can be `async def`. The turn engine's `async for event in engine.play_turn()` works directly inside a NiceGUI handler without threading hacks.
- **`ui.run_javascript` escape hatch.** If we need custom behavior (auto-scroll, focus management), we can inject small JS snippets without leaving Python.
- **Input state control.** Elements have `.disable()` and `.enable()` methods. Locking the input during a turn is trivial.
- **Tailwind CSS built in.** Fine-grained styling without writing CSS files.
- **Single-process, single-port.** No separate frontend build step. `python web.py` and open a browser.
- **Multiple concurrent users.** Each browser tab gets its own session state. Not needed now, but free.

**Cons for TheAct:**
- Less well-known than Gradio/Streamlit. Smaller community, fewer Stack Overflow answers.
- Documentation is comprehensive but organized as a reference, not tutorials.
- Slightly larger dependency footprint (FastAPI, uvicorn, Quasar).

**Streaming token verdict:** Excellent. We can append text to a `ui.html` or `ui.markdown` element on every token, and the WebSocket pushes the update to the browser immediately.

### 2.2 Gradio

**What it is:** A framework built for ML demos. Has a `ChatInterface` component with built-in streaming support.

**Pros for TheAct:**
- `ChatInterface` handles the chat loop pattern out of the box.
- Streaming is a first-class concept -- generator functions yield partial responses.
- Very popular, large community, well-documented.
- Built-in theming.

**Cons for TheAct:**
- **Opinionated chat model.** `ChatInterface` assumes a simple user/assistant turn structure. Our turns have a narrator response, then 0-N character responses, then post-processing -- this does not map cleanly to Gradio's "one assistant response per user message" model.
- **Thinking tokens.** No built-in collapsible section for thinking. We would need to inject custom HTML inside chat messages, fighting the framework rather than working with it.
- **Multi-character display.** All "assistant" messages look the same. Differentiating narrator from Maya from Joaquin requires custom CSS and HTML injection.
- **Input locking.** Gradio does lock the input during processing by default, which is good. But customizing what happens during that locked state (showing a spinner, streaming multiple sequential outputs) is awkward.
- **Game management screens.** Gradio is designed for single-page demos. Building a multi-view application (menu screen, game selection, gameplay) requires `gr.Tabs` or `gr.Blocks` with visibility toggling -- workable but unnatural.
- **Heavy dependencies.** Pulls in numpy, pandas, matplotlib as transitive dependencies even if unused.

**Streaming token verdict:** Good for simple cases. Our multi-source, multi-character streaming pattern would require significant workarounds.

### 2.3 Streamlit

**What it is:** The original framework used in the predecessor project (`token_world/xplore`). Reruns the entire script on every interaction.

**Pros for TheAct:**
- The user has prior experience with it.
- `st.chat_message` and `st.chat_input` provide a clean chat interface.
- `st.write_stream` handles streaming display.
- **Input locking.** Streamlit naturally locks the UI during script execution. The user mentioned this worked well in the predecessor.
- `st.expander` for collapsible thinking sections.
- Mature, huge community.

**Cons for TheAct:**
- **Rerun model.** Every user interaction reruns the entire script from top to bottom. State must be stored in `st.session_state`. This is a fundamental architectural mismatch with our async turn engine. The engine yields `TurnEvent` objects from an async iterator -- but Streamlit's rerun model means we cannot simply `async for event in engine.play_turn()` across multiple reruns. We would need to buffer events into session state and replay them, adding a complex state machine layer.
- **No true async.** Streamlit runs in a synchronous execution model. Our turn engine is fully async. We would need `asyncio.run()` wrappers or threading bridges.
- **Multi-character streaming.** `st.write_stream` works for a single stream. Our turn produces narrator tokens, then character A tokens, then character B tokens. Each transition requires creating a new `st.chat_message` container. This is doable but requires careful container management mid-stream.
- **WebSocket overhead.** Streamlit sends a full rerun signal for state changes. For token-by-token streaming, this is less efficient than NiceGUI's targeted WebSocket pushes.
- **Page navigation.** Multi-page apps are possible but each "page" is a separate script file. The menu-to-game transition would be clunky.

**Streaming token verdict:** Adequate for simple single-stream cases. The rerun model makes our multi-source sequential streaming pattern awkward.

### 2.4 Panel (HoloViz)

**What it is:** A data app framework from the HoloViz ecosystem. Has `pn.chat` components.

**Pros for TheAct:**
- `ChatFeed` and `ChatMessage` components exist.
- Supports streaming via callback-based updates.
- Can run as a Bokeh server.

**Cons for TheAct:**
- **Data-science focus.** The framework is optimized for dashboards and data visualization. Chat is a secondary use case.
- **Smaller chat ecosystem.** The chat components are newer and less battle-tested than Gradio's or Streamlit's.
- **Complex dependency tree.** Pulls in Bokeh, param, and the HoloViz ecosystem.
- **Less intuitive API.** More boilerplate than NiceGUI or Streamlit for equivalent functionality.
- **Thinking tokens.** No built-in collapsible component that integrates naturally with chat messages.

**Streaming token verdict:** Possible but requires more manual work than NiceGUI.

### 2.5 Recommendation: NiceGUI

NiceGUI is the clear winner for this project. The reasoning:

1. **WebSocket-native streaming** is the correct architecture for pushing tokens to a browser in real time. NiceGUI does this natively. Streamlit and Gradio both have impedance mismatches with our async iterator pattern.

2. **Async handlers** mean our turn engine's `async for event in engine.play_turn()` pattern works directly. No threading bridges, no event buffering, no rerun state machines.

3. **Component library** includes chat messages, collapsible panels, cards, tables, dialogs, and spinners -- everything we need without custom HTML.

4. **Input locking** is explicit via `.disable()` / `.enable()`. This gives us the same "UI locked during processing" behavior the user valued in Streamlit, but with finer control.

5. **Multi-view navigation** is natural. We can use `ui.page` decorators for different routes (menu, game session) or swap content within a single page using container visibility.

6. **Minimal frontend code.** Everything is Python. No React, no Vue templates, no build step. Auto-scroll uses NiceGUI's built-in `scroll_area.scroll_to()` -- JavaScript is rarely needed.

The tradeoff -- smaller community and less name recognition -- is acceptable for a local-only tool where we control the entire stack.

---

## 3. Architecture

### 3.1 Module Layout

```
src/theact/web/
    __init__.py          # Public API: start_web() entry point
    app.py               # NiceGUI app setup, page routing, shared state
    menu.py              # Game management views (list games, create/load/delete saves)
    session.py           # Gameplay view: chat display, input, streaming
    commands.py          # Slash command handling (reuses cli/commands.py logic)
    components.py        # Reusable UI components (chat bubble, thinking panel, etc.)
    styles.py            # Color constants, CSS classes, Tailwind utilities

web.py                   # Entry point: python web.py (or uv run python web.py)
```

### 3.2 Dependency Direction

```
web.py
  |
  v
web/app.py
  |
  +---> web/menu.py ---------> io/save_manager (list_games, create_save, load_save, list_saves, delete_save)
  |
  +---> web/session.py ------> engine/turn.py (TurnEngine, TurnEvent types)
  |       |                    versioning/git_save (undo, get_history)
  |       |                    io/save_manager (load_save — for reload after undo)
  |       v
  |     web/components.py
  |       |
  |       v
  |     web/styles.py
  |
  +---> web/commands.py -----> cli/commands.py (reuse parse_command, command logic)
                               versioning/git_save
                               io/save_manager
```

The web UI has the same dependency direction as the Rich CLI: it depends on the engine, save manager, and versioning layer. It never imports from CLI modules except optionally reusing command parsing logic. The engine remains unaware that a web frontend exists.

### 3.3 Engine Integration

The web UI consumes the turn engine through the same `TurnEvent` async iterator that the CLI uses:

```python
# Phase 03/04 established this pattern:
class TurnEngine:
    def __init__(self, game: LoadedGame, llm_config: LLMConfig): ...
    async def play_turn(self, player_input: str) -> AsyncIterator[TurnEvent]: ...
```

The `TurnEvent` types are:
- `NarratorThinking(chunk: str)`
- `NarratorContent(chunk: str)`
- `NarratorDone(full_text: str, metadata: dict)`
- `CharacterThinking(character: str, chunk: str)`
- `CharacterContent(character: str, chunk: str)`
- `CharacterDone(character: str, full_text: str)`
- `PostProcessingStart()`
- `PostProcessingDone(state: GameState)`
- `TurnComplete(turn: int)`

In the web UI, the `session.py` module iterates over these events inside an `async` handler and pushes updates to NiceGUI components. Since NiceGUI handlers run on the server's asyncio event loop, no threading is needed.

### 3.4 State Management

> **API note:** NiceGUI provides several storage scopes: `app.storage.general` (shared across all users), `app.storage.user` (per-user, persisted to JSON on disk via a browser cookie), `app.storage.tab` (per-browser-tab, in-memory only), and `app.storage.client` (per WebSocket connection, lost on reconnect). `app.storage.user` only supports JSON-serializable values -- complex Python objects like Pydantic models, async clients, or engine instances **cannot** be stored there.

We use **`app.storage.tab`** for live session objects (in-memory, per-tab):
- The `LoadedGame` instance
- The `TurnEngine` instance
- The `LLMConfig`

We use **`app.storage.user`** only for JSON-serializable preferences:
- `show_thinking` toggle (bool)
- Last loaded save ID (str, for convenience on return visits)

**Important:** `app.storage.user` requires a `storage_secret` argument in `ui.run()` to sign the identifying cookie. Without it, NiceGUI raises an error at runtime. The `start_web()` function must pass `storage_secret` to `ui.run()`.

State is server-side. The browser holds no game state. If the browser tab closes and reopens, the `app.storage.tab` data is lost (it is in-memory only). The user returns to the menu and reloads their save. The `app.storage.user` preferences (like `show_thinking`) survive because they are persisted to disk.

> **Multi-tab conflict warning:** If two browser tabs load the same save file, they will each have independent `TurnEngine` instances pointing at the same on-disk game directory. Concurrent turns could corrupt the save's git history. Mitigation: use a file lock (e.g., `filelock` library) on the save directory, acquired at game load and released on `/quit` or tab close. Alternatively, check for a `.lock` file before loading and warn the user.

---

## 4. UI Design

### 4.1 Page Structure

The web UI has two main views, implemented as either separate NiceGUI pages (`@ui.page`) or as sections within a single page with visibility toggling. The single-page approach is preferred because it avoids full page reloads.

**View 1: Menu** -- Game and save management.
**View 2: Gameplay** -- The chat interface.

Both views share a common layout wrapper: a centered column with a max width of ~800px, dark background, and a header bar.

### 4.2 Menu View

```
+----------------------------------------------------------+
|  T H E   A C T                                  [dark bg] |
|  an AI text-based RPG                                     |
+----------------------------------------------------------+
|                                                           |
|  +-- New Game ----------------------------------------+  |
|  |  Game: [dropdown: The Lost Island ▼]               |  |
|  |  Save Name: [text input: my-playthrough]           |  |
|  |  Player Name: [text input: Alex]                   |  |
|  |  [Start Game]                                      |  |
|  +----------------------------------------------------+  |
|                                                           |
|  +-- Continue Game -----------------------------------+  |
|  |  Save ID     | Game            | Turn | Last Played|  |
|  |  my-play...  | The Lost Island | 7    | 2h ago     |  |
|  |  [Load]      |                 |      |            |  |
|  |                                                    |  |
|  |  test-run    | The Lost Island | 12   | 1d ago     |  |
|  |  [Load]      |                 |      |            |  |
|  +----------------------------------------------------+  |
|                                                           |
|  +-- Delete Save -------------------------------------+  |
|  |  [dropdown: select save ▼]  [Delete]               |  |
|  +----------------------------------------------------+  |
|                                                           |
+----------------------------------------------------------+
```

Implementation notes:
- Each section is a `ui.card` with a `ui.expansion` or always-visible content.
- The game dropdown is populated from `save_manager.list_games()`.
- The save table is populated from `save_manager.list_saves()`.
- "Start Game" calls `save_manager.create_save()`, creates a `TurnEngine`, and transitions to the gameplay view.
- "Load" calls `save_manager.load_save()`, creates a `TurnEngine`, and transitions to the gameplay view.
- "Delete" shows a confirmation dialog (`ui.dialog`), then calls `save_manager.delete_save()` and refreshes the table.

### 4.3 Gameplay View

```
+----------------------------------------------------------+
|  The Lost Island - Turn 3 - The Crash     [Menu] [/help] |
+----------------------------------------------------------+
|                                                           |
|  +-- Turn 1 -----------------------------------------+  |
|  |                                                    |  |
|  |  > thinking... [click to expand]                   |  |
|  |                                                    |  |
|  |  NARRATOR                                          |  |
|  |  You open your eyes to white light and the taste   |  |
|  |  of salt. Sand grinds against your cheek...        |  |
|  |                                                    |  |
|  |  YOU                                               |  |
|  |  I try to free my arm and look around.             |  |
|  |                                                    |  |
|  +----------------------------------------------------+  |
|                                                           |
|  +-- Turn 2 -----------------------------------------+  |
|  |                                                    |  |
|  |  NARRATOR                                          |  |
|  |  The tide has pulled back, exposing the reef...    |  |
|  |                                                    |  |
|  |  MAYA CHEN                                [cyan]   |  |
|  |  She drops the piece of fuselage she was examining |  |
|  |  and looks where you're pointing...                |  |
|  |                                                    |  |
|  |  YOU                                               |  |
|  |  I suggest we move inland before dark.             |  |
|  |                                                    |  |
|  +----------------------------------------------------+  |
|                                                           |
|  +-- Turn 3 (streaming) -----------------------------+  |
|  |                                                    |  |
|  |  > thinking...                                     |  |
|  |    i need to consider what the player wants to     |  |
|  |    do. they want to explore the jungle. the chap   |  |
|  |    ter beat says...█                               |  |
|  |                                                    |  |
|  +----------------------------------------------------+  |
|                                                           |
+----------------------------------------------------------+
|  [text input: What do you do?        ] [Send]  [locked]  |
+----------------------------------------------------------+
```

Implementation notes:
- The chat area is a `ui.scroll_area` containing turn cards.
- Each turn is a `ui.card` containing message blocks.
- Each message block has a colored name label and body text.
- Thinking sections use `ui.expansion` (collapsed by default) within the turn card.
- During streaming, text is appended to the active message element. NiceGUI pushes updates via WebSocket.

> **Why not `ui.chat_message`?** The evaluation (Section 2.1) highlights NiceGUI's built-in `ui.chat_message` component. However, our design groups messages by **turn** (a card containing narrator + characters + player for one turn), while `ui.chat_message` renders individual messages in a flat chat-bubble layout. Using `ui.chat_message` would lose the turn-grouped structure and make thinking panels (which span the whole turn, not a single message) awkward to place. The custom `ui.card` + `ui.label` + `ui.html` approach gives us the turn-card layout from the wireframe above. If the turn-card grouping proves unnecessary during implementation, switching to `ui.chat_message` is straightforward -- it accepts `name`, `text`, and `stamp` parameters and supports `avatar` for per-character icons.
- The input area is fixed at the bottom using CSS positioning.
- The Send button and text input are disabled during turn processing and re-enabled on `TurnComplete`.
- The header bar shows game title, current turn, chapter title, and navigation buttons.
- Auto-scroll: after each token append, a small JS call scrolls to the bottom of the chat area.

### 4.4 Command Access

Slash commands are available through two mechanisms:

1. **Text input.** Typing `/undo`, `/history`, etc. in the chat input is intercepted before being sent to the turn engine. The command is executed and the result is displayed as a system message in the chat area.

2. **Header buttons / menu.** A dropdown or icon buttons in the header provide quick access to common commands: Undo, History, Status, Memory, Settings (think toggle).

The `/think` toggle is a switch in the header bar rather than a text command, since it is a UI preference.

### 4.5 Conversation History on Load

When a save is loaded, the existing conversation history must be displayed. The `LoadedGame.conversation` list is iterated and rendered as past turn cards (non-streaming, fully formed). This ensures the player sees where they left off.

Thinking tokens from past turns are not available (they are not persisted in conversation.yaml). Past turns therefore show only content, with no thinking sections.

### 4.6 Browser Refresh Behavior

> **NiceGUI internals:** `app.storage.tab` survives browser refresh (NiceGUI uses the browser's `sessionStorage` to maintain tab identity). However, all UI elements (the DOM) are destroyed and rebuilt from scratch on refresh. This means:
>
> - The `TurnEngine` and `LoadedGame` in `app.storage.tab` survive refresh.
> - But the chat area, turn cards, and message blocks are gone.
>
> **On page load**, the `@ui.page` handler must check whether `app.storage.tab` already contains a loaded game. If so, it should skip the menu and go directly to the gameplay view, re-rendering conversation history from the persisted `conversation.yaml`. This provides seamless refresh recovery.
>
> **Mid-turn refresh is destructive.** If the user refreshes during streaming, the in-flight turn is lost (the async generator is abandoned). Since the turn has not yet been committed to git, the game state on disk is still at the previous turn. The re-rendered conversation will show the correct last-committed state. The user simply re-submits their action. This is acceptable and should be documented in `/help` output.
>
> ```python
> @ui.page('/')
> async def index():
>     # Check for existing session
>     if 'game' in app.storage.tab and app.storage.tab['game'] is not None:
>         game = app.storage.tab['game']
>         engine = app.storage.tab['engine']
>         enter_gameplay(game, engine, restore=True)  # Re-render from conversation history
>     else:
>         show_menu()
> ```

---

## 5. Streaming Implementation

This is the most critical section. Streaming tokens to a browser in real time is the core UX requirement.

### 5.1 The Streaming Handler

```python
# src/theact/web/session.py (simplified)

async def handle_turn(player_input: str):
    """Process a turn, streaming results to the UI."""
    # Lock input
    input_field.disable()
    send_button.disable()

    # Create a new turn card in the chat area
    turn_card = create_turn_card(game.state.turn + 1, current_chapter_title())
    thinking_panel = create_thinking_panel(turn_card)
    current_message = None
    current_section = "idle"

    try:
        async for event in engine.play_turn(player_input):
            match event:
                case NarratorThinking(chunk=text):
                    if show_thinking:
                        thinking_panel.append_text(text)
                    current_section = "thinking"

                case NarratorContent(chunk=text):
                    if current_section != "narrator":
                        # Transition: create narrator message block
                        current_message = create_message_block(
                            turn_card, "Narrator", NARRATOR_COLOR
                        )
                        current_section = "narrator"
                    current_message.append_text(text)
                    auto_scroll()

                case NarratorDone(full_text=text):
                    pass  # message block already complete from streaming

                case CharacterThinking(character=name, chunk=text):
                    if show_thinking:
                        thinking_panel.append_text(f"[{name}] {text}")

                case CharacterContent(character=name, chunk=text):
                    if current_section != f"character:{name}":
                        # Transition: create character message block
                        color = get_character_color(name)
                        current_message = create_message_block(
                            turn_card, name, color
                        )
                        current_section = f"character:{name}"
                    current_message.append_text(text)
                    auto_scroll()

                case CharacterDone(character=name):
                    pass

                case PostProcessingStart():
                    show_spinner(turn_card)

                case PostProcessingDone(state=new_state):
                    hide_spinner(turn_card)

                case TurnComplete(turn=turn_num):
                    update_header(turn_num)
                    # Reload game state and update session storage
                    game = save_manager.load_save(game.save_path)
                    app.storage.tab['game'] = game

    except Exception as e:
        show_error_message(turn_card, str(e))

    finally:
        # Unlock input
        input_field.enable()
        send_button.enable()
        input_field.run_method('focus')  # Calls Quasar's QInput.focus() via WebSocket
```

### 5.2 How Token Appending Works in NiceGUI

NiceGUI elements have server-side state that is synced to the browser over WebSocket. For streaming text, we use a `ui.html` element and update its `content` property:

```python
class StreamingTextBlock:
    """A text block that supports token-by-token appending."""

    def __init__(self, container, label: str, color: str):
        with container:
            ui.label(label).style(f'color: {color}; font-weight: bold;')
            self._element = ui.html('')
        self._buffer = []

    def append_text(self, token: str):
        self._buffer.append(token)
        # Update the HTML content with the accumulated text
        # Convert newlines to <br>, escape HTML entities
        full_text = ''.join(self._buffer)
        self._element.content = self._text_to_html(full_text)

    @staticmethod
    def _text_to_html(text: str) -> str:
        """Convert plain text to safe HTML for display."""
        import html
        escaped = html.escape(text)
        return escaped.replace('\n', '<br>')
```

Each call to `append_text` updates the element's `.content` property. NiceGUI detects the change and sends a WebSocket message to the browser, which updates the DOM. This happens per-token, providing a smooth streaming experience.

### 5.3 Batching Consideration

> **NiceGUI internals note:** NiceGUI already coalesces multiple property updates that occur within the same asyncio event loop iteration into a single WebSocket message. Since `async for event in engine.play_turn()` yields tokens from an async generator, and each token triggers an `await` (giving the event loop a chance to flush), NiceGUI will typically send one WebSocket message per token. This is fine for a remote API like a streaming API, which streams tokens at ~20-50/second -- well within browser rendering capacity.
>
> However, if using a very fast local model (hundreds of tokens/second), the rate may exceed what is comfortable. The batching below is a safeguard for that case. **Start without batching** (simpler code) and add it only if profiling shows jank with a specific model.

If the LLM streams tokens very rapidly (e.g., a fast local model), updating the DOM on every single token could cause excessive WebSocket traffic. To handle this:

```python
import asyncio

class StreamingTextBlock:
    FLUSH_INTERVAL = 0.05  # 50ms -- 20 updates/second max

    def __init__(self, ...):
        ...
        self._pending = []
        self._last_flush = 0

    def append_text(self, token: str):
        self._buffer.append(token)
        self._pending.append(token)
        now = asyncio.get_running_loop().time()
        if now - self._last_flush >= self.FLUSH_INTERVAL:
            self._flush()

    def _flush(self):
        full_text = ''.join(self._buffer)
        self._element.content = self._text_to_html(full_text)
        self._pending.clear()
        self._last_flush = asyncio.get_running_loop().time()

    def finish(self):
        """Flush any remaining pending tokens."""
        if self._pending:
            self._flush()
```

This limits DOM updates to ~20/second while still accumulating every token. The result is smooth streaming without overwhelming the browser.

### 5.4 Auto-Scroll

After each text update, the chat area should scroll to the bottom so the latest text is visible.

> **NiceGUI API note:** `ui.scroll_area` has a built-in `.scroll_to(percent=1.0)` method that scrolls to the bottom via WebSocket command -- no raw JavaScript needed. Use this instead of `ui.run_javascript`. The scroll area element must be stored as an instance variable so the streaming handler can call it.

```python
# During layout setup:
chat_scroll = ui.scroll_area().classes('w-full flex-grow')

def auto_scroll():
    chat_scroll.scroll_to(percent=1.0)
```

> **Smart scroll caveat:** Calling `scroll_to` on every token is disruptive if the user has scrolled up to read earlier turns. A better approach: only auto-scroll if the user is already near the bottom. This requires a small JavaScript check:
>
> ```python
> async def auto_scroll_if_near_bottom():
>     """Only scroll if user is within 100px of the bottom."""
>     is_near = await ui.run_javascript(
>         f'(() => {{'
>         f'  const el = getElement({chat_scroll.id}).$el;'
>         f'  return el.scrollHeight - el.scrollTop - el.clientHeight < 100;'
>         f'}})()'
>     )
>     if is_near:
>         chat_scroll.scroll_to(percent=1.0)
> ```
>
> However, `await ui.run_javascript()` adds a round-trip per token, which is too slow during streaming. **Pragmatic approach:** always auto-scroll during active streaming (the user is watching new content arrive), and stop auto-scrolling once the turn completes. If the user scrolls up mid-stream, the scroll will snap back on the next token -- acceptable for a first version.

### 5.5 Thinking Token Display

Thinking tokens are displayed in a `ui.expansion` component within the turn card:

```python
def create_thinking_panel(turn_card) -> StreamingTextBlock:
    with turn_card:
        with ui.expansion('thinking...', icon='psychology').classes('w-full'):
            thinking_block = StreamingTextBlock(container=..., label='', color=THINKING_COLOR)
    return thinking_block
```

The expansion starts collapsed. The user can click to expand and see the thinking tokens as they stream in (or after the fact). If `show_thinking` is False, the expansion is hidden entirely via `.set_visibility(False)`.

When thinking tokens arrive for different agents (narrator thinking vs. character thinking), they are all appended to the same expansion panel with source labels:

```
> thinking... [click to expand]
  [Narrator] i need to consider what the player is doing...
  [Maya Chen] she would be concerned about the noise...
```

---

## 6. Game Management

### 6.1 Mapping CRUD Operations to UI

| Operation | Engine Function | UI Element | Trigger |
|---|---|---|---|
| List games | `save_manager.list_games()` | Dropdown in "New Game" card | On menu view load |
| List saves | `save_manager.list_saves()` | Table in "Continue Game" card | On menu view load |
| Create save | `save_manager.create_save()` | Form in "New Game" card | "Start Game" button |
| Load save | `save_manager.load_save()` | Row action in saves table | "Load" button per row |
| Delete save | `save_manager.delete_save()` | Dropdown + button in "Delete" card | "Delete" button with confirmation |

### 6.2 New Game Flow

```python
async def on_start_game():
    """Handler for the Start Game button."""
    game_id = game_dropdown.value
    save_name = slugify(save_name_input.value)
    player_name = player_name_input.value.strip()

    if not save_name or not player_name:
        ui.notify('Please fill in all fields.', type='warning')
        return

    try:
        save_path = save_manager.create_save(game_id, save_name, player_name)
        game = save_manager.load_save(save_name)
        enter_gameplay(game)
    except FileExistsError:
        ui.notify('A save with that name already exists.', type='negative')
    except Exception as e:
        ui.notify(f'Error creating save: {e}', type='negative')
```

### 6.3 Load Save Flow

```python
async def on_load_save(save_id: str):
    """Handler for the Load button on a save row."""
    try:
        game = save_manager.load_save(save_id)
        enter_gameplay(game)
    except Exception as e:
        ui.notify(f'Error loading save: {e}', type='negative')
```

### 6.4 Delete Save Flow

```python
async def on_delete_save(save_id: str):
    """Handler for the Delete button."""
    with ui.dialog() as dialog, ui.card():
        ui.label(f'Delete save "{save_id}"? This cannot be undone.')
        with ui.row():
            ui.button('Cancel', on_click=dialog.close)
            ui.button('Delete', color='red', on_click=lambda: confirm_delete(save_id, dialog))
    dialog.open()

async def confirm_delete(save_id: str, dialog):
    save_manager.delete_save(save_id)
    dialog.close()
    refresh_save_list()
    ui.notify(f'Save "{save_id}" deleted.', type='positive')
```

### 6.5 View Transition

Transitioning from the menu to gameplay (and back) is handled by hiding/showing containers:

```python
menu_container = ui.column()
gameplay_container = ui.column().set_visibility(False)

def enter_gameplay(game: LoadedGame):
    menu_container.set_visibility(False)
    gameplay_container.set_visibility(True)
    # Store in tab storage for refresh recovery (see Section 4.6)
    engine = TurnEngine(game, llm_config)
    app.storage.tab['game'] = game
    app.storage.tab['engine'] = engine
    # Initialize session state and render conversation history
    init_session(game, engine)

def return_to_menu():
    gameplay_container.set_visibility(False)
    menu_container.set_visibility(True)
    # Clear session state so refresh goes to menu
    app.storage.tab['game'] = None
    app.storage.tab['engine'] = None
    refresh_save_list()
```

This avoids full page reloads and preserves the NiceGUI WebSocket connection.

---

## 7. Command Handling

### 7.1 Input Interception

When the player submits input, the handler first checks for slash commands:

```python
async def on_submit():
    text = input_field.value.strip()
    input_field.value = ''

    if not text:
        return

    command = parse_command(text)
    if command:
        cmd_name, args = command
        await execute_command(cmd_name, args)
        return

    # Not a command -- treat as player input for the turn engine
    add_player_message(text)
    await handle_turn(text)
```

### 7.2 Command Implementations

Commands reuse the same logic as the CLI but render output to the web UI instead of Rich Console:

| Command | Web UI Behavior |
|---|---|
| `/help` | Display a system message card listing available commands |
| `/quit` | Return to menu view via `return_to_menu()` |
| `/undo [N]` | Call `git_save.undo()`, reload game, re-render conversation history, show confirmation notification |
| `/history` | Display a system message card with a table of turn history |
| `/save` | Display a system message card with save metadata |
| `/status` | Display a system message card with game state (chapter, turn, beats) |
| `/memory [character]` | Display a system message card with character memory content |
| `/think [on\|off]` | Toggle the `show_thinking` flag. Also togglable via header switch. |

### 7.3 System Messages

Command output is displayed as "system message" cards in the chat area -- visually distinct from narrator/character messages (e.g., muted background, no character label, smaller text). These cards are informational and do not represent game events.

```python
def show_system_message(content: str):
    """Add a system information card to the chat area."""
    with chat_area:
        # Use opacity and border instead of bg-gray-800 to work with Quasar dark mode
        with ui.card().classes('w-full text-gray-400 text-sm opacity-80 border border-gray-700'):
            ui.html(content)
    auto_scroll()
```

### 7.4 Undo Behavior

Undo is the most complex command in the web UI because it must re-render the conversation:

```python
async def cmd_undo_web(args: list[str]):
    steps = 1
    if args:
        try:
            steps = int(args[0])
            if steps < 1:
                raise ValueError
        except ValueError:
            ui.notify('Usage: /undo [N] where N is a positive integer.', type='warning')
            return

    try:
        new_turn = git_save.undo(Path(game.save_path), steps)
        game = save_manager.load_save(game.save_path)
        app.storage.tab['game'] = game  # Update session state
        # Clear chat area and re-render from conversation history
        chat_area.clear()
        render_conversation_history(game.conversation, game)
        ui.notify(f'Undone {steps} turn(s). Now at turn {new_turn}.', type='info')
    except ValueError as e:
        ui.notify(f'Cannot undo: {e}', type='warning')
```

The chat area is cleared and rebuilt from the persisted conversation. This is clean and correct because undo rewrites the git history -- the conversation.yaml on disk reflects the rewound state.

---

## 8. Implementation Steps

Build in this order. Each step produces a working, testable increment.

### Step 1: Project setup and skeleton

- Create `src/theact/web/__init__.py` with a `start_web()` function stub
- Create `web.py` entry point that calls `start_web()`
- Add `nicegui` to `pyproject.toml` under `[project.optional-dependencies]` as `web = ["nicegui>=2.0.0"]`
- Create `src/theact/web/styles.py` with color constants mirroring the CLI's color scheme
- Verify `uv sync` installs NiceGUI and `uv run python web.py` launches a browser with a blank page

**Files created:**
- `src/theact/web/__init__.py`
- `src/theact/web/styles.py`
- `web.py`

### Step 2: Menu view with game management

- Create `src/theact/web/app.py` with the NiceGUI application setup and page layout
- Create `src/theact/web/menu.py` with:
  - New Game form (game dropdown, save name input, player name input, Start button)
  - Continue Game table (saves listed with Load buttons)
  - Delete Save section (dropdown with Delete button and confirmation dialog)
- Wire up to `save_manager.list_games()`, `create_save()`, `list_saves()`, `delete_save()`
- Test: launch the web UI, verify games and saves are listed, create a new save, delete a save

**Files created:**
- `src/theact/web/app.py`
- `src/theact/web/menu.py`

### Step 3: Gameplay view skeleton

- Create `src/theact/web/session.py` with:
  - Gameplay layout: header bar, scrollable chat area, input bar
  - View transition (menu <-> gameplay)
  - Conversation history rendering: iterate `LoadedGame.conversation` and display past turns as static cards
- Create `src/theact/web/components.py` with:
  - `create_turn_card()` -- a card element for a single turn
  - `create_message_block()` -- a message within a turn card (label + text)
  - `show_system_message()` -- for command output
- Test: load a save with existing conversation, verify past turns display correctly

**Files created:**
- `src/theact/web/session.py`
- `src/theact/web/components.py`

### Step 4: Streaming text display

- Implement `StreamingTextBlock` in `components.py`:
  - Token-by-token appending
  - Flush batching (50ms interval)
  - HTML escaping and newline handling
  - `finish()` method for final flush
- Implement the `handle_turn()` async handler in `session.py`:
  - Iterate over `TurnEvent` objects from `engine.play_turn()`
  - Dispatch to `StreamingTextBlock` instances
  - Handle section transitions (thinking -> narrator -> character)
  - Input locking (disable/enable)
  - Auto-scroll
- Test: type a player action, verify narrator text streams in token by token, followed by character responses

### Step 5: Thinking token display

- Implement thinking panel as `ui.expansion` in `components.py`:
  - Collapsed by default
  - Streams thinking tokens into the expansion body
  - Labels thinking by source (Narrator, character name)
- Add think toggle: a `ui.switch` in the header bar
  - When off, thinking panels are hidden via `.set_visibility(False)`
  - State persists across turns within the session
- Test: verify thinking tokens appear in collapsible panel, toggle hides/shows the panel

### Step 6: Slash commands

- Create `src/theact/web/commands.py` with:
  - Input interception (check for `/` prefix)
  - Command dispatch
  - Web-specific renderers for each command (/help, /undo, /history, /status, /memory, /save, /quit, /think)
- Test each command:
  - `/help` shows command reference as a system card
  - `/undo` rewinds and re-renders conversation
  - `/history` shows turn history table
  - `/status` shows game state
  - `/memory maya` shows Maya's memory
  - `/quit` returns to menu

**Files created:**
- `src/theact/web/commands.py`

### Step 7: Error handling and edge cases

- Handle LLM errors during streaming: show error message in the turn card, unlock input
- Handle empty player input: ignore submission, refocus input field
- Handle very long conversations: verify the scroll area handles 50+ turn cards without performance degradation
- Handle server restart: if the NiceGUI server is restarted, all `app.storage.tab` data (game sessions, engine instances) is lost. NiceGUI will attempt to reconnect the browser's WebSocket, but the server-side state is gone. The page will rebuild and show the menu. `app.storage.user` preferences survive restart because they are persisted to disk.
- Handle concurrent sessions: verify that two browser tabs each have independent session state (NiceGUI handles this via `app.storage.tab`). See the multi-tab conflict warning in Section 3.4 -- two tabs loading the same save need a file-lock or warning.
- Handle opening narration: if turn == 0 on game load, automatically trigger the first turn with `"[game start]"` as player input

### Step 8: Polish and styling

- Dark theme is already enabled via `dark=True` in `ui.run()`. No need to also call `ui.dark_mode(True)` -- they do the same thing. Apply Tailwind classes for fine-tuning colors within the dark theme.
  - **Note:** In dark mode, NiceGUI's Quasar components use a dark card/surface color automatically. Custom `bg-gray-800` Tailwind classes on `ui.card` elements may conflict with Quasar's dark theme colors. Test that card backgrounds look correct and adjust to use Quasar's `q-dark` class or remove conflicting Tailwind backgrounds.
- Style the header bar, cards, message blocks, and input area
- Set character colors to match the CLI's `CHARACTER_COLORS` palette
- Add the game title banner to the menu view
- Add a loading spinner overlay during save creation/loading
- Add `ui.notify` toast notifications for confirmations and errors
- Test on different browser window sizes (the layout should be responsive via Tailwind `max-w-3xl mx-auto`)

---

## 9. Verification

### 9.1 Functional Tests

Phase 07 is complete when all of the following work correctly:

1. **Launch.** `uv run python web.py` starts the NiceGUI server and opens a browser to the menu view.

2. **New Game.** Selecting a game, entering a save name and player name, and clicking "Start Game" creates a new save and transitions to the gameplay view. The opening narration streams in automatically.

3. **Load Game.** The saves table shows existing saves. Clicking "Load" loads the save, displays conversation history, and shows the input prompt.

4. **Delete Game.** Selecting a save and clicking "Delete" shows a confirmation dialog. Confirming deletes the save and refreshes the table.

5. **Streaming.** Typing a player action and pressing Enter (or clicking Send) streams narrator text token by token, followed by character responses. Text appears smoothly without flicker or jank.

6. **Thinking Tokens.** During streaming, thinking tokens appear inside a collapsed expansion panel. Clicking the panel expands it to show thinking content. Toggling the think switch hides the panel entirely.

7. **Character Colors.** Each character's name label and text are displayed in a distinct color consistent with the CLI's color palette. The narrator uses white/italic styling.

8. **Input Locking.** During turn processing, the input field and Send button are disabled. They re-enable after `TurnComplete`. The input field is auto-focused after re-enabling.

9. **Slash Commands.** All seven commands work:
   - `/help` displays command reference
   - `/undo` rewinds game state and re-renders conversation
   - `/history` shows turn history
   - `/status` shows game state
   - `/memory maya` shows Maya's memory
   - `/save` shows save info
   - `/quit` returns to menu
   - `/think on|off` toggles thinking display

10. **Auto-Scroll.** The chat area scrolls to the bottom as new tokens stream in. The user can scroll up to review history; scrolling resumes when new content arrives.

11. **Error Handling.** If the LLM connection fails mid-stream, an error message appears in the turn card, the turn is not committed, and the input unlocks so the player can retry.

12. **Multiple Turns.** Playing 10+ consecutive turns works without UI degradation. The chat area remains scrollable and responsive.

13. **Undo and Resume.** After undoing 3 turns, the conversation history reflects the rewound state. Playing a new turn from the rewound state works correctly (new timeline).

### 9.2 Manual Test Script

Run through this sequence to verify end-to-end:

```
1. uv run python web.py
2. Browser opens. Verify menu shows "The Lost Island" in the game dropdown.
3. Create a new save: name="web-test", player="Alex". Click Start Game.
4. Verify opening narration streams in with thinking tokens.
5. Type: "I try to free my arm and look around." → Send.
6. Verify narrator response streams, followed by character responses.
7. Verify character names are colored.
8. Toggle thinking switch off. Play another turn. Verify no thinking panel.
9. Type "/status". Verify game state appears as system message.
10. Type "/memory maya". Verify Maya's memory appears.
11. Type "/undo". Verify conversation rewinds by one turn.
12. Type "/history". Verify turn history table appears.
13. Type "/quit". Verify return to menu.
14. In menu, verify the save appears in the Continue Game table.
15. Click Load. Verify conversation history is rendered.
16. Play another turn. Verify streaming works after reload.
17. Delete the save. Verify it disappears from the table.
```

### 9.3 Live Testing & Regression Capture

**Step 1 — Play a full session in the browser (10+ turns):**
- Play a real game through the web UI. Pay attention to:
  - Does streaming feel smooth in the browser? Any visible lag compared to the CLI?
  - Does auto-scroll work correctly? Does it interfere with reading history?
  - Does the thinking expansion panel work without layout jank?
  - Does input locking feel responsive? Is there a visible gap between pressing Send and the input disabling?
  - What happens if you refresh the browser mid-turn? Does the session recover?
  - What happens with two browser tabs on the same save? (Should be separate sessions.)
  - Does `/undo` correctly re-render the conversation without stale messages?

**Step 2 — Test edge cases:**
- Rapidly click Send multiple times — verify input locking prevents double-submission.
- Submit an extremely long player input — verify it doesn't break the layout.
- Play until a chapter advances — verify the transition is visible in the UI.
- Disconnect the network mid-stream — verify error recovery and input unlock.

**Step 3 — Fix and capture:**
- For any command or rendering issues, fix the code and write automated tests where possible (e.g., test that command parsing handles web-submitted input with trailing whitespace).
- For streaming/WebSocket issues, document the fix and the reproduction steps.

**Step 4 — Final validation:**
- Run `uv run pytest tests/ -v` — all tests pass.
- Play a 5-turn session in the browser to confirm all fixes.

---

## 10. Dependencies

Add to `pyproject.toml`:

```toml
[project.optional-dependencies]
web = [
    "nicegui>=2.0.0",
]
```

The web UI is an optional dependency. Players who only use the Rich CLI do not need to install NiceGUI and its transitive dependencies (FastAPI, uvicorn, Quasar/Vue via bundled assets).

Installation for web UI users:

```bash
uv sync --extra web
```

NiceGUI's transitive dependencies:
- **fastapi** -- ASGI framework (NiceGUI's server backbone)
- **uvicorn** -- ASGI server
- **httptools** / **websockets** -- HTTP and WebSocket handling
- **itsdangerous** -- session cookie signing (for `app.storage`)

No additional packages beyond NiceGUI itself are needed. NiceGUI bundles its own Vue.js and Quasar assets -- there is no `npm install` or frontend build step.

The entry point:

```python
# web.py
"""Launch TheAct web UI.

Usage:
    uv run python web.py
    uv run python web.py --port 8080
    uv run python web.py --host 0.0.0.0 --port 8080
"""

import argparse
from theact.web import start_web


def main():
    parser = argparse.ArgumentParser(description="Launch TheAct Web UI")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind to")
    parser.add_argument("--port", type=int, default=8080, help="Port to bind to")
    parser.add_argument("--reload", action="store_true", help="Enable auto-reload for development")
    args = parser.parse_args()

    start_web(host=args.host, port=args.port, reload=args.reload)


if __name__ == "__main__":
    main()
```

```python
# src/theact/web/__init__.py

from nicegui import ui


def start_web(host: str = "127.0.0.1", port: int = 8080, reload: bool = False):
    """Launch the NiceGUI web server."""
    from theact.web.app import setup_app
    setup_app()
    # storage_secret is required for app.storage.user (signs the identifying cookie).
    # For a local-only tool this can be a fixed string; for multi-user deployment
    # it should come from an environment variable.
    ui.run(
        host=host,
        port=port,
        reload=reload,
        title="TheAct",
        dark=True,
        storage_secret="theact-local-secret",
    )
```

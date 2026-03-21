# Phase 13: Web UI Expansion

> **Implementation note:** This phase depends on Phases 01-12 being complete. The web UI (Phase 07) currently provides basic gameplay — menu, turn execution with streaming, and slash commands typed as text. This phase closes the gap with the terminal CLI and adds web-native features that the terminal cannot offer. NiceGUI remains the framework. All new features must use the existing engine APIs (`run_turn`, `save_manager`, `git_save`, `creator`) — no engine changes unless explicitly noted.

## Overview

The terminal CLI (Phase 04) provides a rich set of features beyond basic gameplay: quick-action commands, character memory inspection, save versioning with undo/history/diff, game creation, playtest launching, and diagnostics viewing. The web UI currently requires users to type slash commands for all of these, has no visual game state display, and is missing several features entirely (game creation, playtesting, diagnostics, settings).

This phase expands the web UI across 9 steps (starting with a refactoring step):

| Step | File | Summary | Depends On |
|------|------|---------|------------|
| 00 | [00-Refactoring.md](00-Refactoring.md) | **MUST BE FIRST.** Split god classes, extract shared commands, modularize components | — |
| 01 | [01-GameplayToolbar.md](01-GameplayToolbar.md) | Header toolbar with quick-action buttons, turn info display, input improvements | 00 |
| 02 | [02-GameStateSidebar.md](02-GameStateSidebar.md) | Collapsible sidebar: character cards, chapter progress, memory viewer | 00, 01 |
| 03 | [03-SaveManagementAndHistory.md](03-SaveManagementAndHistory.md) | Enhanced saves table, visual save-as dialog, turn history timeline, peek/diff viewer | 00, 01 |
| 04 | [04-GameCreationWizard.md](04-GameCreationWizard.md) | Multi-step game creation wizard using the creator agent | 00 |
| 05 | [05-SettingsAndConfiguration.md](05-SettingsAndConfiguration.md) | Settings page for LLM config, model selection, display preferences | 00 |
| 06 | [06-PlaytestDashboard.md](06-PlaytestDashboard.md) | Launch, monitor, and review playtests from the web | 00, 05 |
| 07 | [07-DiagnosticsViewer.md](07-DiagnosticsViewer.md) | Call log viewer, token usage charts, error browser, diagnostics file viewer | 00, 06 |
| 08 | [08-PolishAndSafety.md](08-PolishAndSafety.md) | Multi-tab locking, refresh recovery, mobile layout, keyboard shortcuts, error retry | 00-07 |

## File Layout

After Step 00 refactoring, the web UI has a modular architecture. Steps 01-08 add to this structure.

```
src/theact/commands/             # Shared command logic (Step 00)
    __init__.py
    logic.py                     # Pure functions, no UI imports
    types.py                     # CommandResult dataclass

src/theact/web/
    __init__.py                  # start_web() — unchanged
    __main__.py                  # CLI args — unchanged
    styles.py                    # Colors — unchanged

    # Core architecture (Step 00)
    app.py                       # Slim: page routing only
    menu.py                      # MenuBuilder class
    session.py                   # GameplaySession — thin orchestrator
    state.py                     # GameSessionState — shared observable state
    turn_runner.py               # TurnRunner — wraps run_turn()
    streaming.py                 # StreamRenderer — routes tokens to UI
    command_router.py            # CommandRouter — dispatches commands
    commands.py                  # Thin web rendering layer over commands/logic

    # Components package (Step 00)
    components/
        __init__.py              # Re-exports for backward compat
        turn_card.py             # Turn card creation and info bar (Step 01 adds info bar)
        message_blocks.py        # StreamingTextBlock, narrator/character/player blocks
        thinking_panel.py        # Thinking panel component
        system_message.py        # System message card
        static_turn.py           # render_static_turn() for past turns
        dialogs.py               # Reusable confirmation/input dialogs
        html_utils.py            # HTML escaping, tables, render_result()

    # Feature modules (Steps 01-08)
    toolbar.py                   # Step 01: quick-action button bar
    sidebar.py                   # Step 02: game state sidebar panel
    history.py                   # Step 03: turn history browser
    creator_wizard.py            # Step 04: game creation wizard page
    settings.py                  # Step 05: settings page
    playtest_dashboard.py        # Step 06: playtest launcher and report viewer
    diagnostics_viewer.py        # Step 07: call log and diagnostics browser
    safety.py                    # Step 08: file locking, session recovery

tests/
    test_command_logic.py        # Step 00: shared command logic tests
    web/
        test_toolbar.py          # Step 01
        test_sidebar.py          # Step 02
        test_history.py          # Step 03
        test_creator_wizard.py   # Step 04
        test_settings.py         # Step 05
        test_playtest_dashboard.py # Step 06
        test_diagnostics.py      # Step 07
        test_safety.py           # Step 08
```

## What This Phase Does NOT Do

- No engine changes. All new features call existing APIs (`run_turn`, `save_manager`, `git_save`, `creator`, `playtest`).
- No new LLM agents. The game creation wizard and playtest dashboard call existing agent code.
- No changes to the terminal CLI. The CLI is unaffected by this phase.
- No changes to game file formats. YAML structures remain identical.
- No authentication or multi-user support. The web UI remains single-user, local-first.

## Architecture Principles

1. **Thin UI layer.** Web components call existing Python APIs. No business logic in the web layer.
2. **Shared observable state.** `GameSessionState` (from `state.py`) is the single source of truth. All components (sidebar, toolbar, history) read from it and register listeners. No stale references.
3. **Modular components.** Each component type lives in its own file under `components/`. Reusable utilities (`dialogs.py`, `html_utils.py`) prevent duplication.
4. **Shared command logic.** `commands/logic.py` contains pure functions with no UI imports. Both CLI and web are thin rendering layers over this shared logic.
5. **Session as orchestrator.** `GameplaySession` delegates to `TurnRunner`, `StreamRenderer`, and `CommandRouter`. It does not contain business logic.
6. **NiceGUI patterns.** Use `ui.refreshable` for reactive updates, `ui.timer` for polling, `app.storage.tab` for session persistence.
7. **Progressive enhancement.** Each step adds independently useful features. The web UI remains functional if any step is incomplete.

## Build Order Recommendation

**Step 00 (refactoring) MUST come first.** It restructures the codebase so all subsequent steps work cleanly.

Then: Steps 01-03 form the core gameplay improvements and should be built in order. Steps 04 and 05 are independent and can be parallelized. Steps 06-07 benefit from Step 05. Step 08 is a polish pass that should come last.

## Execution Guidance for Implementing Agents

### Playwright Validation Workflow

After implementing each step (or significant sub-feature), the executor agent MUST manually validate the result using the Playwright MCP browser tools. The workflow is:

1. **Start the dev server** if not already running: `uv run scripts/dev_server.py start --port 8111`
2. **Navigate** to the relevant page using `browser_navigate` to `http://localhost:8111`
3. **Take a screenshot** with `browser_take_screenshot` to visually verify the UI
4. **Interact** with the new feature using `browser_click`, `browser_fill_form`, `browser_snapshot`, etc.
5. **Verify behavior** — check that buttons work, dialogs open, data displays correctly
6. **Document issues** — if anything looks wrong, fix it before moving on

This is not optional. NiceGUI's rendering of Quasar components has quirks (spacing, dark mode colors, icon rendering) that are only visible in the browser. Screenshot verification catches layout issues, missing styles, and broken interactions that unit tests cannot.

### Convert Manual Testing to Regression Tests

Every issue discovered during Playwright manual validation MUST be captured as a test:

1. **During manual testing**, when you discover that something doesn't work or looks wrong, fix it.
2. **After fixing**, write a Playwright browser test that would have caught the issue. Add it to the step's test file (e.g., `tests/web/test_toolbar.py`).
3. **Also consider**: are there similar issues that could occur in related components? Write preventive tests for those too.
4. **Test pattern**: use `data-testid` attributes on key elements for stable Playwright selectors. The existing tests in `tests/web/test_gameplay.py` show the pattern.

The goal is that manual Playwright validation drives the creation of automated regression tests, so the same class of issue never recurs. Each step should end with more tests than the plan originally specified.

### Subagent Communication Protocol

When the executor agent delegates work to subagents (e.g., "implement toolbar.py", "write test file"), the executor MUST:

1. **Ask subagents to report back ideas and concerns.** Include this instruction in every subagent prompt:
   > "After completing your implementation, report back:
   > - Any concerns about the approach or potential issues you noticed
   > - Ideas for improvements or alternatives you considered
   > - Any assumptions you made that the main agent should verify
   > - Edge cases or error scenarios you encountered but didn't handle"

2. **Review subagent reports before proceeding.** The executor should read the concerns/ideas and decide whether to act on them, adjust the plan, or note them for later steps.

3. **Do not ignore subagent feedback.** If a subagent raises a valid concern (e.g., "NiceGUI's `ui.menu` doesn't anchor properly to `ui.input`"), the executor should investigate and potentially adjust the implementation rather than blindly merging.

4. **Subagents should not silently swallow problems.** If a subagent encounters an API that doesn't exist, a NiceGUI component that behaves differently than expected, or a data model field with a different name, they must report it — not guess or work around it silently.

### Per-Step Implementation Checklist

For each step, the executor agent should follow this sequence:

1. Read the step plan file and all referenced source files
2. Create a task list from the plan's sections
3. Implement (directly or via subagents with the communication protocol above)
4. Run existing tests: `uv run pytest tests/ -v` (catch regressions early)
5. Manually validate with Playwright MCP (screenshot + interaction)
6. Convert any manual findings into automated tests
7. Run the full test suite including new tests
8. Run `uv run prek run --all-files` for lint/format
9. Commit the step's changes with a descriptive message

## Reusable Context for Implementing Agents

When implementing any step, the agent should first read:
1. `CLAUDE.md` — project constraints (tiny prompts, one task per call, YAML everywhere)
2. `docs/plans/README.md` — cross-cutting notes
3. This file (`docs/plans/13-WebUIExpansion/README.md`) — phase overview
4. The specific step file (e.g., `01-GameplayToolbar.md`)
5. Current web UI code: `src/theact/web/` (all files)
6. Current web tests: `tests/web/` (all files)

### Key APIs the Web UI Calls

**Turn engine** (`src/theact/engine/turn.py`):
```python
async def run_turn(
    game: LoadedGame, player_input: str, llm_config: LLMConfig,
    on_token: StreamCallback | None = None,
    call_log: LLMCallLog | None = None, debug: bool = False,
) -> TurnResult
```

**Save manager** (`src/theact/io/save_manager.py`):
```python
def list_games(games_dir=None) -> list[GameMeta]
def list_saves(saves_dir=None) -> list[dict]  # {id, game_title, turn, last_modified}
def create_save(game_id, save_id, player_name, ...) -> Path
def load_save(save_id, saves_dir=None) -> LoadedGame
```

**Git versioning** (`src/theact/versioning/git_save.py`):
```python
def undo(save_path, steps=1) -> int  # returns new turn number
def get_history(save_path) -> list[TurnInfo]  # {turn, commit_hash, message, timestamp}
def save_as(save_path, new_save_id, saves_dir=None) -> Path
def peek_at_turn(save_path, turn_number) -> dict[str, str]  # filename -> contents
def diff_turns(save_path, turn_a, turn_b) -> str  # unified diff
```

**Game creation** (`src/theact/creator/session.py`):
```python
async def create_game(concept: str | None = None) -> Path | None
```

**Playtest** (`src/theact/playtest/runner.py`):
```python
class PlaytestRunner:
    def __init__(self, config: PlaytestConfig)
    async def run(self) -> PlaytestReport
```

**LLM call logging** (`src/theact/llm/call_log.py`):
```python
class LLMCallLog:
    def summary() -> dict
    def agent_summary() -> dict[str, dict]
    def records_for_turn(turn) -> list[LLMCallRecord]
```

### Key Data Models

**`LoadedGame`** (the central in-memory state):
```python
meta: GameMeta           # id, title, description, characters list, chapters list
world: World             # setting, tone, rules
characters: dict[str, Character]   # keyed by file stem
chapters: dict[str, Chapter]       # keyed by chapter id
state: GameState         # player_name, current_chapter, turn, beats_hit, flags, rolling_summary
conversation: list[ConversationEntry]  # turn, role, character, content
memories: dict[str, CharacterMemory]   # keyed by file stem: character, summary, key_facts
chapter_summaries: list[ChapterSummary]
save_path: Path
```

**`TurnResult`** (returned by `run_turn`):
```python
turn: int
narrator: NarratorOutput  # narration, responding_characters, mood
characters: list[CharacterResponse]  # character, response, thinking
memory_diffs: list[MemoryDiff]  # character, old/new summary, old/new facts
game_state: GameStateResult | None  # beats_hit, completed, reasoning
chapter_advanced: bool
new_chapter: str | None
summary_updated: bool
```

# Implementation Plans

## Overview

TheAct is built in sequential phases. Each plan document is self-contained with data models, code signatures, implementation steps, and verification criteria.

**Read order:** CLAUDE.md → docs/requirements.md → the specific phase plan.

## Phase Index

| Phase | File | Summary | Depends On |
|-------|------|---------|------------|
| 01 | [01-DataModelAndProjectStructure.md](01-DataModelAndProjectStructure.md) | Pydantic models, YAML I/O, save manager, git versioning | — |
| 02 | [02-LLMClientAndInference.md](02-LLMClientAndInference.md) | Async LLM wrapper, streaming, structured output, token estimation | — |
| 03 | [03-TurnEngineMemoryAndSummarization.md](03-TurnEngineMemoryAndSummarization.md) | Turn orchestration, context assembly, all agent prompts, memory, rolling summary | 01, 02 |
| 04 | [04-RichCLI.md](04-RichCLI.md) | Terminal interface with Rich, streaming display, commands | 01, 02, 03 |
| 05 | [05-ExampleGameAndPlaytest.md](05-ExampleGameAndPlaytest.md) | Lost Island game files, autonomous playtest framework | 01–04 |
| 06 | [06-GameCreationAgent.md](06-GameCreationAgent.md) | Interactive game creation with a larger model | 01, 04 |
| 07 | [07-WebUI.md](07-WebUI.md) | NiceGUI browser interface | 01–03 |
| 08 | [08-Documentation.md](08-Documentation.md) | Guides, design docs, documentation hub | All |
| 09 | [09-ObservabilityAndDiagnostics.md](09-ObservabilityAndDiagnostics.md) | LLM call logging, diagnostics filesystem, prompt linting, error taxonomy | 01–05 |
| 10 | [10-SaveVersioningAndTurnDebugger.md](10-SaveVersioningAndTurnDebugger.md) | Save-as/fork, peek, diff, interactive turn debugger | 01, 03, 09 |
| 11 | [11-SmallModelHardening.md](11-SmallModelHardening.md) | Prompt iteration, YAML reliability, token budgets, golden scenarios | 09, 10 |
| 12 | [12-CreatorSmallModelHardening.md](12-CreatorSmallModelHardening.md) | Brainstorm tool, decomposed proposal & generation, per-file fixing for small models | 06, 11 |
| 13 | [13-WebUIExpansion/](13-WebUIExpansion/README.md) | **Implemented.** Web UI expansion: toolbar, sidebar, history, creator wizard, settings, playtest dashboard, diagnostics viewer, polish & safety | 07, 01–12 |

## Cross-Cutting Implementation Notes

### Build order recommendation

Phases 01 and 02 are independent foundations — build them first (can be parallel).
Phase 03 is the core — build it next.
Then immediately jump to Phase 05's game files + playtest before polishing Phase 04's CLI.
Real model output reveals prompt issues faster than any amount of planning.

### Prompt iteration is expected

The prompt templates in Phase 03 (`agents/prompts.py`) look good on paper but will need 5-10 iterations once they hit the real 7B model. Keep prompts in a single file (`prompts.py`) so changes are one-line edits, not refactors. The playtest framework exists to make this iteration empirical.

### Don't over-abstract early

The plans show clean interfaces, but during Phase 03 implementation, resist the urge to build abstractions before the prompts are stable. A direct function call is better than a framework when you're still figuring out what the function should do.

### Conversation entry ordering

The turn engine records entries as: narrator → player → characters. This is a narrative convention (narrator sets the scene, player action is noted, characters react). It works but is slightly counterintuitive since chronologically the player spoke first. Be consistent with this ordering in context assembly.

### File size discipline

The single most important constraint: game files must stay tiny. Character files ~60 words, world ~6 sentences, chapter beats are short phrases. If you find yourself writing a 200-word character backstory, stop. A 7B model with 8K context cannot afford it.

### Phases 09-11: Context from prior implementation

Phases 01-07 are fully implemented. 396 tests pass. Here is critical context for implementing Phases 09-11:

**Live integration test results (Phase 03):** The 7B model (`olafangensan-glm-4.7-flash-heretic`) was tested with `scripts/test_turn.py` running 3 turns against Lost Island. Every structured output call failed — the model never produced fenced YAML blocks. The narrator returned empty `responding_characters` every turn. All YAML parsing fell back to the "no fenced block" path, which also failed. The model DID produce content (narration text), but it was not wrapped in YAML. This is the primary problem Phase 11 must solve, and Phases 09-10 build the tools to solve it efficiently.

**Thinking token behavior:** The model uses `<think>` tags and consumes 500-2000 tokens for reasoning before producing content. `max_tokens` was increased to 2048 for narrator and 1500 for other agents to accommodate this. The streaming layer correctly separates thinking from content tokens.

**`importlib.reload` caveat:** Phase 10's turn debugger `edit_and_replay` must reload BOTH `prompts.py` AND `context.py` because context.py uses `from theact.agents.prompts import ...` which copies values at import time. This is documented in the Phase 10 plan.

**Build order for 09-11:** Phase 09 and Phase 10 Part A (save versioning) are independent — can be built in parallel. Phase 10 Part B (turn debugger) benefits from Phase 09's `LLMCallLog` but degrades gracefully without it. Phase 11 depends on both 09 and 10 being operational.

**Existing diagnostic tooling:** `scripts/diagnose_agent.py` already exists and tests individual agents against the live API. `scripts/test_turn.py` runs 3-turn integration tests. `scripts/playtest.py` runs autonomous N-turn playtests. Phase 09 enhances these with structured logging; Phase 10 adds interactive debugging.

### Phase 13: Context from implementation

Phases 01-13 are fully implemented. Key decisions and patterns from Phase 13:

**Shared command logic.** Step 00 extracted command logic into `src/theact/commands/logic.py` — pure functions with no UI imports. Both CLI and web are thin rendering layers over this shared logic. This pattern prevents business logic from drifting into UI code.

**Observable state pattern.** `GameSessionState` (`src/theact/web/state.py`) is the single source of truth for the web UI. Components register as listeners and refresh automatically when state changes (after turns, undo, game reload). Components never mutate state directly.

**Settings persistence.** `settings.yaml` stores web-configurable settings (LLM endpoint, model, display preferences). The settings store lives in `src/theact/io/settings_store.py` (not in `web/`) so both `llm/config.py` and the web layer can import it without creating a core-to-web dependency. Load order: `.env` (secrets via dotenv) then `settings.yaml` overrides.

**File locking.** `safety.py` uses the `filelock` package to prevent concurrent writes from multiple browser tabs to the same save directory. Falls back to a no-op lock if `filelock` is not installed.

---

## Reusable Execution Prompt

Copy the prompt below into a new Claude Code session to execute any phase. Replace `XX` and the filename with the target phase.

---

```
I need you to implement Phase XX of TheAct project.

Before writing any code, read these files in this order:
1. CLAUDE.md — project context, constraints, architecture, conventions
2. docs/requirements.md — design rationale and the "why" behind decisions
3. docs/plans/README.md — cross-cutting implementation notes
4. docs/plans/XX-PlanFileName.md — the specific phase plan with implementation steps

Also read the current state of the codebase:
- pyproject.toml (current dependencies)
- src/theact/ (any existing code from prior phases)

Key reference files you may need (read only if the plan references them):
- ~/workspace/nottheact/saves/playtest-001/ — example game (original verbose version)
- ~/workspace/token_world/token_world/llm/xplore — prior art (predecessor project)

## Implementation approach

- Follow the implementation steps in the plan document in order
- Mark each step complete before moving to the next
- Write tests as specified in the verification section
- Run tests after each step to catch issues early

## Use subagents to prevent context rot

This is important. Your context window will degrade if you try to hold everything in your head.

- **Use Explore subagents** to read reference files (xplore, example game) rather than reading them in your main context
- **Use general-purpose subagents** for writing test files — describe what to test, let the subagent write the tests, review the result
- **Use general-purpose subagents** for implementing self-contained modules — if a module has a clear interface defined in the plan, delegate its implementation to a subagent with the interface spec
- **Keep your main context** for: orchestration, reviewing subagent output, making cross-module decisions, and running tests
- **Do NOT** duplicate work between your main context and subagents — if you delegate, trust the result and only review it

## When you're done

- Run the full test suite: `uv run pytest tests/ -v`
- Run any verification scripts specified in the plan
- Run `uv run prek run --all-files` to ensure lint/format compliance
- Summarize what was built, any deviations from the plan, and any issues discovered
```

---

### Phase-specific additions to append to the prompt

**Phase 01** — no additions needed, it's foundational.

**Phase 02** — append:
```
After implementation, run the smoke test against the live API endpoint:
  uv run python scripts/test_llm.py
This requires LLM_API_KEY in .env. Verify thinking tokens appear in output.
```

**Phase 03** — append:
```
This is the most critical phase. The prompt templates in agents/prompts.py
determine whether the 7B model can do its job. Keep prompts in a single file
so iteration is easy. Do NOT over-abstract — keep agent functions simple and
direct until prompts are proven via playtesting.

After implementation, do a quick manual test:
  - Load the Lost Island game (from Phase 05 game files, or create minimal test fixtures)
  - Run a single turn programmatically and inspect the output
  - Verify that structured YAML output parses correctly from the narrator
  - Verify that character responses are distinct and in-character
```

**Phase 04** — append:
```
The CLI is a thin layer. If you find yourself putting game logic in the CLI,
stop — it belongs in the engine (Phase 03). The CLI should only: render output,
collect input, and dispatch commands.
```

**Phase 05** — append:
```
This phase has two independent parts. Use subagents:
  - Subagent 1: Write the Lost Island game YAML files to games/lost-island/
  - Subagent 2: Implement the playtest framework under src/theact/playtest/
Then in your main context, run the playtest:
  uv run python scripts/playtest.py --game lost-island --turns 10
Review the playtest report. If the model produces empty responses, malformed
YAML, or repetitive output, iterate on the Phase 03 prompts.
```

**Phase 06** — append:
```
This agent uses a DIFFERENT, larger model than gameplay. The config needs a
separate LLM configuration (CreatorLLMConfig) that can point to a different
endpoint/model. The user may use Claude, GPT-4, or another capable model.
All generated output must pass Pydantic validation from Phase 01 models.
```

**Phase 07** — append:
```
NiceGUI is an optional dependency — add it under [project.optional-dependencies]
so CLI-only users aren't affected:
  [project.optional-dependencies]
  web = ["nicegui>=2.0"]
The web UI must use the same turn engine interface as the CLI. No engine changes.
```

**Phase 09** — append:
```
This phase is passive instrumentation — no prompt changes, no new features.
All new parameters (call_log, debug, turn) must be optional with defaults
so existing callers are unaffected. Run the full test suite after each step.
```

**Phase 10** — append:
```
Part A (save versioning) is independent infrastructure. Part B (turn debugger)
uses Phase 09's LLMCallLog if available but degrades gracefully without it.
The debugger wraps individual agent calls — it does NOT modify run_turn().
When implementing edit_and_replay, reload BOTH prompts.py AND context.py.
```

**Phase 11** — append:
```
This phase is iterative. Each step modifies prompts or parsing code, then
validates against the live model. You MUST have LLM_API_KEY in .env.

After each prompt change:
  1. Use the turn debugger to replay the affected agent (3+ times)
  2. Verify the fix works, then capture a fixture with the debugger
  3. Write a regression test from the fixture
  4. Run uv run pytest tests/ -v to ensure no regressions

After all steps:
  uv run python scripts/playtest.py --game lost-island --turns 20
Review the report against the success criteria in Section 17 of the plan.
```

**Phase 12** — append:
```
This phase has three components that should be built in order:
1. Brainstorm tool (standalone, no dependencies on other changes)
2. Decomposed proposal (rewrites proposer.py, updates session.py)
3. Decomposed generation pipeline (new per-file generators, updated fixer)

Use subagents:
  - Subagent 1: Implement brainstorm.py + scripts/brainstorm.py
  - Subagent 2: Implement per-file generators (world_gen.py, character_gen.py, chapter_gen.py)
  - Subagent 3: Implement assembler.py + pipeline.py
  - Main context: Prompt rewrite, session integration, fixer updates

NAMING CAUTION: The plan has two sets of similarly-named prompts:
  - Proposal phase: SETTING_SYSTEM, PROPOSAL_CHARACTERS_SYSTEM, PROPOSAL_CHAPTERS_SYSTEM
  - Generation phase: WORLD_SYSTEM, CHARACTER_SYSTEM, CHAPTER_SYSTEM
Keep the "PROPOSAL_" prefix on proposal-phase prompts to avoid confusion.

After implementation, test with the 7B model:
  CREATOR_MODEL=olafangensan-glm-4.7-flash-heretic uv run python scripts/brainstorm.py --create
  uv run python scripts/playtest.py --game <created-game-id> --turns 10
```

**Phase 13** — append:
```
Phase 13 is a FOLDER with a README and 8 step files (01-08). Read the
README first — it contains key API references, data models, and execution
guidance that applies to all steps.

Build steps in order (01 through 08). Steps 04 and 05 can be parallelized.

CRITICAL: After implementing each step or significant sub-feature:
  1. Start the dev server: uv run scripts/dev_server.py start --port 8111
  2. Use Playwright MCP to manually validate (navigate, screenshot, interact)
  3. Convert every issue found during manual testing into an automated test
  4. Run: uv run pytest tests/web/ -v

When delegating to subagents, ALWAYS include this instruction in the prompt:
  "After completing your implementation, report back any concerns about
   the approach, ideas for improvements, assumptions you made, and edge
   cases you noticed but didn't handle."

Review subagent reports before proceeding. Do not ignore their feedback.

Existing web tests are SYNC (playwright.sync_api, def not async def,
web_server fixture not running_app). Match this pattern for all new tests.

NiceGUI quirks to watch for:
  - ui.right_drawer must be a direct child of the page, not nested
  - ui.echart (not ui.chart) for Apache ECharts
  - app.storage.tab requires await ui.context.client.connected() first
  - ui.keyboard(ignore=[]) to capture shortcuts when input is focused
  - @ui.refreshable methods: call .refresh() attribute, not re-invoke
```

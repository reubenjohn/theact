# Implementation Plans

## Overview

TheAct is built in 7 sequential phases. Each plan document is self-contained with data models, code signatures, implementation steps, and verification criteria.

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

### `getting_started.py` is throwaway

`src/getting_started.py` is a Venice AI connection test from before planning. It will be superseded by `scripts/test_llm.py` in Phase 02. Remove it once Phase 02 is implemented.

### File size discipline

The single most important constraint: game files must stay tiny. Character files ~60 words, world ~6 sentences, chapter beats are short phrases. If you find yourself writing a 200-word character backstory, stop. A 7B model with 8K context cannot afford it.

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
After implementation, run the smoke test against the live Venice AI endpoint:
  uv run python scripts/test_llm.py
This requires VENICE_API_KEY in .env. Verify thinking tokens appear in output.
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

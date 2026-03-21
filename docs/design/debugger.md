# Turn Debugger Architecture

The turn debugger fills the gap between playtests (full turns, coarse feedback) and raw API calls (no game context). It operates at the agent level: one agent call at a time, with full game state loaded, so you can inspect and replay individual steps.

## Design: Wraps Agents, Not the Engine

`TurnDebugger` calls the same `run_narrator()`, `run_character()`, and other agent functions that `run_turn()` uses. It does not modify or fork `run_turn()`. This means debugger behavior always matches production behavior — there is no "debugger mode" that could mask bugs.

The debugger controls the sequence manually: call narrator, inspect the result, then call each character agent one at a time, then post-turn agents. At any point you can stop, edit prompts, and replay a step.

## Session Model

`DebugSession` holds mutable state for a single turn being debugged:

- **Completed steps** — which agents have run (narrator, each character, memory, game state)
- **Per-agent run history** — every `AgentResult` from every run and re-run of each step
- **Narrator output** — the parsed narrator response (narration text + responding characters list)
- **Character responses** — accumulated character dialogue

After the narrator completes, the debugger reads `responding_characters` from the narrator output and populates the pending step list: one step per responding character, then memory agents (one per character), then the game state agent. This mirrors the ordering in `run_turn()`.

## Edit and Replay

The debugger uses `importlib.reload()` to hot-reload prompt changes. It reloads both `prompts.py` and `context.py`. Why both? Because `context.py` uses `from theact.agents.prompts import ...`, which copies constant values at import time. Reloading only `prompts.py` leaves `context.py` holding stale references to the old prompt strings.

The reload sequence:

1. User edits `src/theact/agents/prompts.py`
2. Debugger calls `importlib.reload(theact.agents.prompts)`
3. Debugger calls `importlib.reload(theact.agents.context)` (picks up new constants)
4. User replays the agent step — it now uses the updated prompt

## Fixture Capture

`capture_fixture()` saves a full `AgentResult` — messages sent, raw response, parsed data, token counts — as a YAML file in `tests/fixtures/`. These fixtures feed directly into `tests/test_prompt_regression.py`, which replays saved inputs and asserts the output structure is still valid.

This closes the loop: debug a problem, capture the failing case, fix the prompt, and the captured fixture becomes a regression test.

## Key Constraint

The debugger requires a real game save to operate. It loads game state, character files, and conversation history from a save directory. For unit tests of the debugger itself, we create a temporary save from the lost-island game files using the same `SaveManager` that the engine uses.

## Further Reading

- [Architecture](architecture.md) — the turn pipeline the debugger wraps
- [Agents](agents.md) — the agent functions the debugger calls
- [Prompt Iteration](../guides/prompt-iteration.md) — the workflow the debugger supports

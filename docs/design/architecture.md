# Architecture

TheAct orchestrates text RPG turns entirely through code. The LLM never decides "what to do next" — it only responds to specific, narrow tasks. This makes the system reliable with 7B-class models that would fail with open-ended agent loops.

## Turn Pipeline

Every turn follows this fixed sequence:

```
1. Player Input
   │
2. Context Assembly (code)        ← builds message arrays for the narrator
   │
3. Narrator Agent (streaming)     ← describes what happens, picks responding characters
   │
4. Character Agents (sequential)  ← each responds in-character, seeing prior responses
   │
5. Post-Turn Agents (parallel)    ← memory updates + game state check via asyncio.gather
   │
6. Chapter Advancement            ← if completion condition met: summarize, advance
   │
7. Rolling Summary                ← if unsummarized conversation exceeds token budget
   │
8. Persist + Git Commit           ← write all files, commit the turn
```

The implementation lives in [`src/theact/engine/turn.py`](../../src/theact/engine/turn.py) — the `run_turn()` function maps directly to these steps.

## Module Map

```
src/theact/
  models/       Data structures (Pydantic). No logic, no I/O.
  io/           YAML reading/writing and save directory management.
  versioning/   Git operations on save directories.
  llm/          LLM client, streaming types, YAML parsing, token estimation.
  engine/       Turn orchestration and context assembly. The core.
  agents/       One module per agent type + shared prompt templates.
  cli/          Rich terminal interface. Consumes run_turn().
  web/          NiceGUI browser interface. Consumes run_turn().
  playtest/     Autonomous playtest framework with AI player agent.
  creator/      Game creation pipeline (uses a larger model).
```

The dependency flow is strictly layered: `models` and `llm` are foundations, `engine` and `agents` build on them, `cli`/`web`/`playtest`/`creator` are frontends that consume the engine.

## Concurrency Model

**Characters respond sequentially.** Each character agent sees prior characters' responses in the current turn. This is critical for coherent multi-character dialogue — Maya can react to what Joaquin just said.

See the character loop in [`turn.py`](../../src/theact/engine/turn.py) (the `for char_id in narrator_output.responding_characters` loop).

**Post-turn agents run in parallel.** Memory updates for each character and the game state check are independent tasks. They run concurrently via `asyncio.gather()` in [`turn.py`](../../src/theact/engine/turn.py).

## Streaming

Tokens flow from LLM to UI through a callback chain:

1. The LLM client yields `StreamChunk` objects ([`src/theact/llm/streaming.py`](../../src/theact/llm/streaming.py))
2. Agent functions accept an `on_token` callback and invoke it per chunk
3. `run_turn()` defines a `StreamCallback` type and wires agent callbacks to it
4. The frontend (CLI or web) provides a `StreamCallback` implementation that renders tokens in real time

This design means the engine has no knowledge of the UI — it just calls the callback. See `StreamCallback` in [`turn.py`](../../src/theact/engine/turn.py).

## Frontends

Both the CLI and web UI consume the same `run_turn()` interface:

- **CLI** — [`src/theact/cli/session.py`](../../src/theact/cli/session.py) manages the game loop. [`src/theact/cli/renderer.py`](../../src/theact/cli/renderer.py) streams tokens to the terminal via Rich.
- **Web** — [`src/theact/web/session.py`](../../src/theact/web/session.py) manages the game loop. [`src/theact/web/components.py`](../../src/theact/web/components.py) streams tokens to the browser via NiceGUI WebSockets.

Launch the CLI with `uv run python -m theact`. Launch the web UI with `uv run python -m theact.web`. See the [Getting Started guide](../guides/getting-started.md) for full instructions.

## Further Reading

- [Agents](agents.md) — what each agent does and how prompts are designed
- [Data Model](data-model.md) — game files, save files, Pydantic models
- [Memory & Summarization](memory-and-summarization.md) — how context stays within budget

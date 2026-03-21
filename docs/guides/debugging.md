# Debugging with the Turn Debugger

The turn debugger lets you step through a turn's agent calls one at a time, inspect the exact prompts and responses, edit prompts and replay without restarting, and capture test fixtures. It wraps individual agent calls — it does not modify the turn engine.

## Quick Start

```bash
uv run python scripts/debug_turn.py --save my-save --input "I look around."
```

This loads the save, runs a single turn with the given input, and pauses before each agent call so you can inspect and intervene.

## Interactive Commands

| Command | Key | Description |
|---------|-----|-------------|
| Step | `s` | Execute the current agent call and pause at the next one |
| Replay | `r` | Re-run the current agent call (same inputs, new LLM call) |
| Edit | `e` | Reload prompts from disk and replay the current agent call |
| Inspect | `i` | Show prompt (`p`), response (`r`), or call record (`c`) for the current step |
| Skip | `k` | Skip the current agent call and move to the next one |
| Continue | `c` | Run all remaining agent calls without pausing |
| Fixture | `f` | Save the current step's prompt/response as a test fixture |
| Compare | `m` | Diff the current response against the previous replay of the same step |
| Quit | `q` | Abort the turn and exit |

## Workflow: Fixing a Prompt

1. **Run the debugger** with the input that triggers the problem.
2. **Step** (`s`) through agents until you reach the one producing bad output.
3. **Inspect the prompt** — press `i` then `p` to see exactly what the model received. Check for bloated context, missing data, or unclear instructions.
4. **Inspect the response** — press `i` then `r` to see the raw model output. Identify what went wrong (bad format, hallucination, missing content).
5. **Edit the prompt** — open `src/theact/agents/prompts.py` in your editor. Change the template.
6. **Reload and replay** — press `e`. The debugger reloads prompts from disk and re-runs the agent call with the updated template. No restart needed.
7. **Compare** — press `m` to diff the new response against the old one.
8. **Capture a fixture** — when the output looks right, press `f` to save the prompt/response pair as a test fixture for regression testing.

This keeps you in a tight edit-test loop without restarting the debugger or re-running earlier agents.

## Replay Mode

Walk through historical turns from an existing save:

```bash
uv run python scripts/debug_turn.py --save my-save --replay
```

| Key | Action |
|-----|--------|
| Enter | Next turn |
| `p` | Previous turn |
| *N* | Jump to turn N |
| `d` | Diff current turn's agent outputs against the previous turn |
| `q` | Quit |

Replay mode reads from the diagnostics filesystem (requires the save to have been run with `debug=True`). It does not make LLM calls.

## Key Files

| File | Contents |
|------|----------|
| `src/theact/debugger/debugger.py` | `TurnDebugger` class — core stepping and replay logic |
| `src/theact/debugger/types.py` | `AgentResult`, `DebugStep`, `DebugSession` data types |
| `scripts/debug_turn.py` | CLI entry point |

## Further Reading

- [Observability & Diagnostics](diagnostics.md) — the logging and filesystem the debugger builds on
- [Prompt Iteration](prompt-iteration.md) — the broader prompt-fixing workflow
- [Agents](../design/agents.md) — what each agent does and its expected output

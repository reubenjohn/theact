# Observability & Diagnostics Architecture

Design rationale for the observability system. For usage, see [Observability & Diagnostics (guide)](../guides/diagnostics.md).

## Philosophy

Passive instrumentation only. Observability tools never change prompts, never alter agent behavior, and never add overhead unless opted in. All new parameters are optional with `None` defaults. The system observes — it does not intervene.

## Three-Layer Design

1. **Call logging** — always available. An `LLMCallLog` collects `LLMCallRecord` entries from every agent call. Zero cost if not passed. Used by playtests, the debugger, and the diagnostics writer.

2. **Diagnostics filesystem** — opt-in via `debug=True` on `run_turn()`. Writes every prompt, response, and call record to disk in a human-readable directory tree. Intended for deep inspection of individual turns.

3. **Context profiler** — on-demand analysis. Call `profile_messages()` against any agent's message list to see token allocation. Not part of the turn pipeline; used during development and prompt iteration.

Each layer builds on the one below it. The diagnostics writer consumes call records from the call log. The debugger consumes both.

## Error Taxonomy

Seven categories, each mapping to a different fix strategy:

| Type | What happened | Fix direction |
|------|--------------|---------------|
| `empty_response` | Model produced nothing | Check `max_tokens`, check for context overflow |
| `no_yaml_block` | Model wrote prose but no YAML | Strengthen the YAML format instruction in the prompt |
| `invalid_yaml` | Model attempted YAML but syntax is wrong | `repair_yaml_text` fallback handles most cases; if persistent, simplify the expected structure |
| `wrong_schema` | Valid YAML but wrong fields | Update the example in the prompt to match expected schema |
| `json_instead` | Model output JSON rather than YAML | Add explicit "Output YAML, not JSON" rule to the prompt |
| `echo_prompt` | Model echoed the prompt back | Reduce prompt size, check for context overflow |

Why these seven and not fewer? Because the fix for each is different. Lumping `no_yaml_block` and `invalid_yaml` together would hide whether the model is ignoring the format instruction or trying and failing. Lumping `empty_response` and `echo_prompt` would hide whether the issue is context overflow or max_tokens misconfiguration.

## Call Logging: Flat List, Not Nested

Post-turn agents run in parallel via `asyncio.gather` — memory agents for each character and the game state agent all fire concurrently. A nested structure (turn → agent → call) would require synchronized writes to a shared tree during concurrent execution.

Instead, the call log is a flat list of `LLMCallRecord` entries. Each record carries its own `turn` and `agent` fields. Filtering by turn or agent is a one-liner. No locking, no nested mutation, no ordering assumptions.

## Diagnostics Filesystem: Files, Not a Database

The primary consumer is a human with `cat`, `less`, and `diff`. Design follows from that:

- **Plain text for prompts and responses.** Not wrapped in YAML or JSON — just the raw text, directly readable.
- **YAML for structured metadata.** Token counts, latency, parse results — things you'd want to query or compare.
- **One directory per agent.** Makes `diff diagnostics/turn-001/narrator/ diagnostics/turn-002/narrator/` trivial.
- **One directory per turn.** `ls diagnostics/` shows all turns at a glance.

A database would add a dependency, require a viewer, and make diffs harder. Files are simple, portable, and work with every Unix tool.

## Integration Points

The call log flows through the system without tight coupling:

```
Agent function
  → creates LLMCallRecord after each LLM call
  → appends to LLMCallLog (if one was passed)
  → LLMCallLog consumed by:
      - Playtest report generator (aggregate stats, error counts)
      - Diagnostics writer (per-agent call_record.yaml files)
      - Turn debugger (inspect command)
```

All integration is optional. If no `LLMCallLog` is passed, agents still work — they just don't record. If `debug=False`, no filesystem writes happen. The debugger can function with or without either.

## Further Reading

- [Observability & Diagnostics (guide)](../guides/diagnostics.md) — how to use these tools
- [Agents](agents.md) — the agent calls being observed
- [Architecture](architecture.md) — where observability fits in the turn pipeline

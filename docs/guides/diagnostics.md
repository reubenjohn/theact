# Observability & Diagnostics

Three layers of observability, from always-on to on-demand: call logging, the diagnostics filesystem, and the context profiler.

## Call Logging

Every LLM call automatically produces an `LLMCallRecord` with:

| Field | Description |
|-------|-------------|
| `timestamp` | When the call started |
| `agent` | Which agent made the call (narrator, character-maya, memory-maya, etc.) |
| `turn` | Turn number |
| `prompt_tokens` | Tokens in the prompt |
| `thinking_tokens` | Tokens used for model reasoning |
| `content_tokens` | Tokens in the response content |
| `latency_ms` | Wall-clock time for the call |
| `finish_reason` | Why the model stopped (stop, length, etc.) |
| `parse_result` | Success or failure type (see Error Taxonomy below) |
| `parse_attempts` | How many parse attempts before success |
| `retry_count` | How many full retries were needed |
| `temperature` | Temperature used |
| `max_tokens` | Max tokens budget |

To capture call logs during gameplay, pass a log to the turn engine:

```python
from theact.llm.call_log import LLMCallLog

call_log = LLMCallLog()
await run_turn(state, player_input, call_log=call_log)

call_log.summary()         # Aggregate stats across all calls
call_log.agent_summary()   # Stats grouped by agent
call_log.dump_yaml(path)   # Write full log to YAML file
```

In playtests, call logs are saved to `llm_calls.yaml` and summarized in the playtest report automatically.

## Diagnostics Filesystem

Pass `debug=True` to `run_turn()` to write full prompt and response data to disk:

```
diagnostics/turn-001/
  narrator/
    system_prompt.txt    # Exact system prompt sent to model
    user_message.txt     # User message content
    raw_response.txt     # Full model output
    call_record.yaml     # Token counts, latency, parse result
  character-maya/
    ...
  memory-maya/
    ...
  game_state/
    ...
  summary.yaml           # Turn-level aggregates
```

Plain text files for prompts and responses (readable with `cat`/`less`). YAML for structured metadata. One directory per agent for easy `diff` between turns.

## Error Taxonomy

The `ParseFailureType` enum classifies every parse outcome:

| Type | Meaning |
|------|---------|
| `success` | Parsed correctly |
| `empty_response` | Model produced no output |
| `no_yaml_block` | Model wrote text but no YAML block |
| `invalid_yaml` | Model attempted YAML but syntax is broken |
| `wrong_schema` | Valid YAML but fields don't match expected schema |
| `json_instead` | Model output JSON instead of YAML |
| `echo_prompt` | Model echoed the prompt back |

Every `YAMLParseError` carries a `failure_type` field. These types appear in call logs and playtest reports, making it easy to spot patterns (e.g., "narrator returns `no_yaml_block` 40% of the time" points to a prompt issue).

## Context Profiler

Analyze token allocation for any agent's message list:

```python
from theact.llm.profiler import profile_messages, format_profile

profile = profile_messages("narrator", messages, max_tokens_budget=2000)
print(format_profile(profile))
```

This prints a breakdown showing how many tokens each message component uses, a visual bar, and remaining headroom. Use it to find which part of the context is eating the budget.

## Prompt Linting

Automated tests in the test suite enforce prompt constraints:

- All system prompts are 300 tokens or fewer (template form, before rendering)
- Rendered narrator prompts are 400 tokens or fewer (with real game data injected)
- No orphan `{placeholder}` strings survive after rendering
- All agents have headroom >= 0 when tested with real game data

These tests catch prompt bloat before it reaches the model. If you edit a prompt and tests fail, you've exceeded the budget — trim until they pass.

## Key Files

| File | Contents |
|------|----------|
| `src/theact/llm/call_log.py` | `LLMCallRecord`, `LLMCallLog` |
| `src/theact/engine/diagnostics.py` | Diagnostics filesystem writer |
| `src/theact/llm/profiler.py` | `profile_messages()`, `format_profile()` |
| `src/theact/llm/errors.py` | `YAMLParseError`, `ParseFailureType` |

## Further Reading

- [Observability Architecture](../design/observability.md) — design rationale behind these systems
- [Debugging with the Turn Debugger](debugging.md) — interactive tool built on top of this infrastructure
- [Prompt Iteration](prompt-iteration.md) — using diagnostics to fix prompt issues

# Prompt Iteration

When the model misbehaves during playtesting, the fix is almost always a prompt change. This guide covers the iteration loop and common fixes.

## Where Prompts Live

All prompt templates are in a single file: [`src/theact/agents/prompts.py`](../../src/theact/agents/prompts.py).

This is by design. When you need to fix a prompt, it's a one-line edit in one file — not a refactor across multiple modules. The prompt constants are imported by the context assembly layer ([`src/theact/engine/context.py`](../../src/theact/engine/context.py)), which injects game data into the template placeholders.

## The Iteration Loop

```
1. Run a playtest          →  scripts/playtest.py --game your-game --turns 10
2. Read the report         →  check for errors, missed beats, bad output
3. Identify the problem    →  which agent produced bad output?
4. Edit the prompt         →  src/theact/agents/prompts.py
5. Run another playtest    →  compare results
6. Repeat until stable
```

Short playtests (5-10 turns) are best for iteration. Save long runs (20+ turns) for validation after prompts stabilize.

## Rules for Small Models

These rules are baked into the existing prompts. Follow them when making changes:

- **~300 token system prompts.** Count your tokens. Every word in the system prompt competes with the model's reasoning space.
- **One task per call.** If you find yourself asking an agent to do two things, split it into two agents.
- **Imperative mood.** "Write narration" not "You should write narration." "Do NOT skip beats" not "Please try not to skip beats."
- **Concrete examples.** Show the exact output format with realistic (not placeholder) content. Small models learn more from examples than instructions.
- **State constraints as rules.** "Only list characters from ACTIVE CHARACTERS" not "It would be best to only include characters that are active."

See [Agents — Prompt Design](../design/agents.md#prompt-design-for-small-models) for the full philosophy.

## Common Fixes

### Model outputs prose instead of YAML

The model is ignoring the output format instruction. Fixes:
- Ensure the YAML example in the prompt uses realistic content, not placeholders
- Add or strengthen the YAML hint appended to user messages (see `YAML_HINT_*` constants in [`prompts.py`](../../src/theact/agents/prompts.py))
- Check that the system prompt isn't too long — the model may be losing the format instruction

### Character breaks voice

The personality description is too vague. Fixes:
- Add specific speech patterns: "Short declarative sentences" or "Uses nautical metaphors"
- Add anti-patterns: "Never uses slang" or "Does not ask questions"
- The personality field in the character YAML matters more than the prompt template here

### Narrator skips beats

The beat guidance isn't strong enough. Fixes:
- The prompt already says "Guide the story toward unfinished beats. Do NOT skip beats." If the model still skips, check that the beats are phrased as things that can happen naturally — not forced events
- Simplify beat text. "Player finds supplies" is better than "Player carefully searches through the wreckage and discovers useful supplies"

### Memory agent hallucinates facts

The agent is adding facts the character couldn't know. Fixes:
- The prompt constrains this with "Only include things {name} witnessed or learned. Do NOT include things {name} would not know." If this isn't enough, add a concrete negative example
- Check that the turn entries passed to the memory agent actually only include events the character was present for

### Game state never completes a chapter

The completion condition is too strict or too vague. Fixes:
- This is usually a game file issue, not a prompt issue. Loosen the `completion` field in the chapter YAML
- If the game state agent is correctly identifying beats but not triggering completion, the completion condition may not match the beat set

## Turn Debugger

The fastest way to iterate on prompts is the turn debugger. See [Debugging Guide](debugging.md) for full details.

Quick workflow:
1. `uv run python scripts/debug_turn.py --save test --input "I look around."`
2. Step to the failing agent
3. Inspect the prompt and response
4. Edit `src/theact/agents/prompts.py`
5. Press `e` to reload and replay — no restart needed

## Golden Scenarios

After fixing a prompt, verify it doesn't break other behaviors:
```bash
uv run python scripts/run_golden.py
```

See [Golden Scenarios Guide](golden-scenarios.md) for writing new scenarios.

## A/B Testing

For larger prompt changes, compare variants statistically:
```bash
uv run python scripts/ab_test.py --variant-b prompts_v2.py --runs 3
```

See [A/B Testing Guide](ab-testing.md) for details.

## Model Quirks

Known 7B model behaviors are documented in `docs/model-quirks.yaml`. Check this file before debugging — your issue may already have a known workaround.

## Further Reading

- [Agents](../design/agents.md) — what each agent does and how prompts are structured
- [Playtesting](playtesting.md) — run and interpret playtest reports
- [Memory & Summarization](../design/memory-and-summarization.md) — how memory agents work

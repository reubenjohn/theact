# Playtesting

The autonomous playtest framework runs an AI player agent through your game for N turns, logging every LLM call and producing a diagnostic report.

## What Playtesting Does

An AI "player agent" generates contextually appropriate actions each turn (with occasional edge-case inputs to stress-test the system). The framework:

- Runs the full turn pipeline for each turn (narrator, characters, memory, game state)
- Logs every LLM call and its output
- Tracks which beats are hit and whether chapters advance
- Catches and records errors without stopping (unless `--stop-on-error` is set)
- Produces a summary report at the end

## Running a Playtest

```bash
uv run python scripts/playtest.py --game lost-island --turns 20
```

Options:

| Flag | Default | Description |
|------|---------|-------------|
| `--game` | (required) | Game ID (directory name under `games/`) |
| `--turns` | 20 | Maximum turns to play |
| `--player-name` | Alex | Name for the player character |
| `--stop-on-error` | off | Stop on first error instead of continuing |

See [`scripts/playtest.py`](../../scripts/playtest.py) for the full CLI and [`src/theact/playtest/config.py`](../../src/theact/playtest/config.py) for configuration defaults.

The playtest creates a save directory (like a normal game) and writes logs/reports to the `playtests/` directory.

## Reading the Report

The report ([`src/theact/playtest/report.py`](../../src/theact/playtest/report.py)) tells you:

- **Turns completed** — Did the playtest run to completion or error out?
- **Beats hit** — Which story beats were triggered? Missing beats may indicate prompt issues.
- **Chapters advanced** — Did the game progress through chapters, or did it get stuck?
- **Errors** — Parse failures, empty responses, agent exceptions.

## Common Issues

| Symptom | Likely Cause | Fix |
|---------|-------------|-----|
| Empty narrator responses | System prompt too long, leaving no room for output | Trim world/chapter text. See [Data Model — Size Constraints](../design/data-model.md#size-constraints) |
| Malformed YAML | Model doesn't follow the format | Add a stricter example to the prompt. See [Prompt Iteration](prompt-iteration.md) |
| Repetitive narration | Rolling summary is stale or missing key details | Check `_maybe_update_rolling_summary()` thresholds in [`turn.py`](../../src/theact/engine/turn.py) |
| Characters break voice | Personality description too vague | Tighten the character's personality field with specific speech patterns |
| No beats hit after many turns | Beats are too specific or narrator ignores them | Simplify beat phrases. Add beat guidance to narrator prompt |
| Game stuck on one chapter | Completion condition is too strict | Loosen the `completion` field in the chapter YAML |

For all prompt-related fixes, see [Prompt Iteration](prompt-iteration.md).

## Further Reading

- [Prompt Iteration](prompt-iteration.md) — the fix workflow for playtest failures
- [Agents](../design/agents.md) — understand what each agent outputs
- [Creating a Game](creating-a-game.md) — make sure your game files follow the constraints

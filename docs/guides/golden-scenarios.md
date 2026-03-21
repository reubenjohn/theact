# Golden Scenarios

Golden scenarios are multi-turn behavioral tests that script specific player inputs and assert structural properties of the system's response. They sit between unit tests (too narrow) and full playtests (too broad) — each scenario tests one specific behavior in 3-5 turns.

## Running Scenarios

```bash
uv run python scripts/run_golden.py                              # All scenarios
uv run python scripts/run_golden.py --scenario crash_opening     # Single scenario
```

Each scenario creates a temporary save, runs its turns against the real engine, and reports pass/fail per assertion.

## Scenario Format

Scenarios are YAML files in `tests/golden_scenarios/`. Each file defines a name, the target game, and a sequence of turns with assertions:

```yaml
name: Crash Opening Sequence
description: First 3 turns produce coherent crash scene
game: lost-island
turns:
  - input: null          # null = opening narration (no player input)
    expect:
      narrator_not_empty: true
  - input: "I look for survivors."
    expect:
      narrator_not_empty: true
      characters_responded_min: 1
```

Use `null` for the first turn's input — this triggers the opening narration without player action.

## Available Assertions

| Assertion | Type | Description |
|-----------|------|-------------|
| `narrator_not_empty` | bool | Narration is non-empty |
| `narrator_word_count_min` | int | Minimum narration word count |
| `narrator_word_count_max` | int | Maximum narration word count |
| `characters_responded_min` | int | Minimum characters that responded |
| `characters_responded_max` | int | Maximum characters that responded |
| `characters_responded_includes` | list | Specific character IDs that must respond |
| `beats_hit_any` | bool | At least one beat was hit this turn |
| `beats_hit_count_min` | int | Minimum number of beats hit |

All assertions are structural — they check counts and presence, not text content. This makes them deterministic across different model outputs.

## Existing Scenarios

| File | Tests |
|------|-------|
| `crash_opening.yaml` | Opening narration and first interactions produce coherent output with minimum word count |
| `maya_dialogue.yaml` | Direct character interaction triggers at least one character response |
| `short_input.yaml` | System handles minimal inputs ("ok", "yes") without crashing |
| `adversarial_input.yaml` | Meta-gaming, gibberish, and contradictory inputs produce valid narration |
| `both_characters.yaml` | Group interaction elicits responses from multiple characters |

## Writing New Scenarios

- **Keep turns short.** 3-5 turns per scenario. Golden scenarios test specific behaviors, not endurance.
- **Use structural assertions.** Never assert on exact text — model output varies between runs. Check word counts, response counts, and beat progress instead.
- **Test one behavior per scenario.** "Does the narrator handle gibberish?" is one scenario. "Does Maya respond and are beats hit?" is two scenarios.
- **Use `null` input for opening turns.** The first turn of any game has no player input.
- **Name files descriptively.** The filename (without extension) is used as the `--scenario` argument.

## Further Reading

- [Playtesting](playtesting.md) — full autonomous playtests for broader validation
- [Prompt Iteration](prompt-iteration.md) — fixing issues that golden scenarios reveal

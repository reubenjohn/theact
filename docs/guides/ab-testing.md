# A/B Testing Prompts

The A/B testing script runs the same playtest multiple times with two different prompt files and compares metrics side by side. This removes guesswork from prompt changes — you see exactly what improved and what regressed.

## Quick Start

```bash
# Copy the current prompts and edit the copy
cp src/theact/agents/prompts.py src/theact/agents/prompts_v2.py
# Make your changes to prompts_v2.py

# Run the comparison
uv run python scripts/ab_test.py \
  --game lost-island --turns 10 \
  --variant-a current --variant-b src/theact/agents/prompts_v2.py \
  --runs 3
```

Use `--variant-a current` to compare against the live prompts without copying them.

## How It Works

For each run, the script:

1. Loads the variant's prompt module
2. Monkey-patches `theact.agents.prompts` with the variant's constants
3. Runs a full playtest through the standard engine
4. Restores the original prompts

Each run uses `random.seed(run_number)` so the AI player agent produces the same input sequence across variants. This isolates prompt differences from player randomness.

## Metrics Compared

The comparison report includes these metrics, averaged across runs:

| Metric | Description |
|--------|-------------|
| YAML parse success | Percentage of LLM calls that produced valid YAML |
| Character response rate | Percentage of turns where at least one character responded |
| Avg narration word count | Mean word count of narrator output |
| Avg thinking tokens | Mean thinking tokens per LLM call |
| Total tokens | Total tokens consumed across all turns |
| Mean turn latency | Average wall-clock time per turn |
| Beats hit | Total story beats triggered |
| Quality composite | Weighted score combining parse success, response rate, and beats |

## Interpreting Results

"Better" prompts show:

- **Higher parse success and character response rate.** These are reliability metrics. Regressions here mean the model is confused by the new prompt.
- **Lower thinking tokens.** The model needs less internal reasoning to follow the prompt — it understood faster.
- **Similar or higher quality composite.** This is the overall signal. Small regressions in one metric are fine if the composite improves.

A variant that improves thinking tokens but drops parse success is worse, not better — reliability comes first.

## Tips

- **Start small.** Use `--turns 3 --runs 2` while iterating. Save long runs for final validation.
- **Change one thing at a time.** If you change three prompt constants and metrics improve, you don't know which change helped.
- **Use `--variant-a current` consistently.** This always compares against the working state, so results across sessions are comparable.
- **Check the per-run breakdown.** Averages can hide variance. If variant B is better on 2 runs but catastrophically worse on 1, the prompt may be fragile.

## Further Reading

- [Prompt Iteration](prompt-iteration.md) — the manual iteration loop
- [Playtesting](playtesting.md) — understanding playtest reports

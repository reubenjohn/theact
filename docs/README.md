# TheAct Documentation

TheAct is a programmatically-driven text RPG engine designed for small language models (7B-class). Code orchestrates every turn — narrator, characters, memory, game state — with each LLM call doing exactly one focused task.

**New here?** Start with the [Getting Started guide](guides/getting-started.md).

## Using TheAct

| Guide | Description |
|-------|-------------|
| [Getting Started](guides/getting-started.md) | Install, configure, play your first game |
| [Creating a Game](guides/creating-a-game.md) | Write game YAML files or use the creator agent |
| [Playtesting](guides/playtesting.md) | Run and interpret autonomous playtests |
| [Prompt Iteration](guides/prompt-iteration.md) | Tune prompts when the model misbehaves |

## Debugging & Testing

| Guide | Description |
|-------|-------------|
| [Debugging](guides/debugging.md) | Step through agents with the turn debugger |
| [Diagnostics](guides/diagnostics.md) | Call logging, error taxonomy, context profiling |
| [Golden Scenarios](guides/golden-scenarios.md) | Behavioral test scenarios with structural assertions |
| [A/B Testing](guides/ab-testing.md) | Compare prompt variants with statistical metrics |

## Understanding the Architecture

| Document | Description |
|----------|-------------|
| [Architecture](design/architecture.md) | Turn pipeline, module map, concurrency, streaming |
| [Agents](design/agents.md) | Agent roles, prompt design, structured output |
| [Data Model](design/data-model.md) | Game files, save files, Pydantic models |
| [Memory & Summarization](design/memory-and-summarization.md) | Character memory, rolling summary, context budgeting |
| [Observability](design/observability.md) | Call logging, diagnostics, error taxonomy design |
| [Turn Debugger](design/debugger.md) | Debugger architecture and design decisions |

## Reference

| Document | Description |
|----------|-------------|
| [Requirements & Rationale](requirements.md) | Why decisions were made |
| [Model Quirks](model-quirks.yaml) | Observed 7B model behaviors and workarounds |
| [Phase Plans](plans/) | Step-by-step implementation plans (Phases 01-11) |
| [CLAUDE.md](../CLAUDE.md) | Context for AI-assisted development |

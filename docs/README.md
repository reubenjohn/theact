# Documentation

New here? Start with [Core Concepts](concepts.md), then [Getting Started](getting-started.md).

## Using TheAct

| Document | Description |
|----------|-------------|
| [Getting Started](getting-started.md) | Install, configure, play your first game (CLI and Web UI) |
| [Creating a Game](guides/creating-a-game.md) | Write game YAML files or use the creator agent |

## Understanding the System

| Document | Description |
|----------|-------------|
| [Core Concepts](concepts.md) | Key terms and how the system works at a high level |
| [Architecture](architecture/overview.md) | Turn pipeline, module map, concurrency, streaming |
| [Data Model](architecture/data-model.md) | Game files, save files, Pydantic models |
| [Agents](architecture/agents.md) | Agent roles, prompt design, structured output |
| [Memory & Summarization](architecture/memory.md) | Character memory, rolling summary, context budgeting |

## Development & Debugging

| Document | Description |
|----------|-------------|
| [Observability](reference/observability.md) | Call logging, diagnostics, error taxonomy, profiler |
| [Debugging](guides/debugging.md) | Turn debugger and troubleshooting |
| [Playtesting](guides/playtesting.md) | Autonomous playtest framework, golden scenarios |
| [Prompt Engineering](guides/prompt-engineering.md) | Prompt iteration, A/B testing, model quirks |

## Reference

| Document | Description |
|----------|-------------|
| [Save Versioning](architecture/save-versioning.md) | Git-based saves, forking, undo |
| [Game Creation Pipeline](reference/game-creation-pipeline.md) | Creator agent internals |
| [Requirements & Rationale](reference/requirements.md) | Why design decisions were made |
| [Model Quirks](reference/model-quirks.yaml) | Observed 7B model behaviors and workarounds |
| [Phase Plans](plans/) | Step-by-step implementation plans (01-13) |

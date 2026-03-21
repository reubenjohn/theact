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

## Understanding the Architecture

| Document | Description |
|----------|-------------|
| [Architecture](design/architecture.md) | Turn pipeline, module map, concurrency, streaming |
| [Agents](design/agents.md) | Agent roles, prompt design, structured output |
| [Data Model](design/data-model.md) | Game files, save files, Pydantic models |
| [Memory & Summarization](design/memory-and-summarization.md) | Character memory, rolling summary, context budgeting |

## Implementation History

| Document | Description |
|----------|-------------|
| [Requirements & Rationale](requirements.md) | Why decisions were made |
| [Phase Plans](plans/) | Step-by-step implementation plans (Phases 01-08) |
| [CLAUDE.md](../CLAUDE.md) | Context for AI-assisted development |

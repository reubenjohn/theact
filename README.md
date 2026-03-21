# TheAct

An AI-driven text-based RPG engine designed for small language models.

TheAct programmatically orchestrates narrative turns using specialized agents — a narrator, individual character agents, memory managers, and game state evaluators — each making a single focused LLM call. This architecture enables compelling interactive fiction with 7B-class models that would struggle with traditional agent frameworks.

## Quick Start

```bash
# Install dependencies
uv sync

# Set up environment
cp .env.example .env
# Edit .env with your Venice AI API key

# Verify LLM connection
uv run python scripts/test_llm.py

# Launch the game
uv run python -m theact
```

## How It Works

Each turn follows a fixed pipeline:

1. **Player** types an action
2. **Narrator agent** describes what happens and decides which characters respond
3. **Character agents** respond sequentially (each sees prior responses)
4. **Post-turn agents** run in parallel: update each character's memory + check chapter progress
5. **Save** all changes and commit to git (enabling unlimited undo)

The game definition lives in simple YAML files — world, characters (~60 words each), and chapters with story beats and completion criteria. A game creation agent can generate these from a concept description.

## Project Structure

```
src/theact/
  models/       # Pydantic data models
  io/           # YAML I/O, save management
  versioning/   # Git-based save versioning
  llm/          # LLM client, streaming, structured output
  engine/       # Turn orchestration, context assembly
  agents/       # Narrator, character, memory, game state agents
  cli/          # Rich terminal interface
  playtest/     # Autonomous playtest framework
  creator/      # Game creation agent
  web/          # NiceGUI web interface

games/          # Game definitions (templates)
saves/          # Active game saves (gitignored)
docs/plans/     # Detailed implementation plans
```

## Documentation

Start at [docs/README.md](docs/README.md) for the full index. Key entry points:

- **Guides:** [Getting Started](docs/guides/getting-started.md) | [Creating a Game](docs/guides/creating-a-game.md) | [Playtesting](docs/guides/playtesting.md) | [Prompt Iteration](docs/guides/prompt-iteration.md)
- **Design:** [Architecture](docs/design/architecture.md) | [Agents](docs/design/agents.md) | [Data Model](docs/design/data-model.md) | [Memory & Summarization](docs/design/memory-and-summarization.md)
- **Reference:** [Requirements & Rationale](docs/requirements.md) | [Phase Plans](docs/plans/) | [CLAUDE.md](CLAUDE.md)

## Tech Stack

- **Python 3.11** with uv package manager
- **Venice AI** (OpenAI-compatible endpoint) with small thinking models
- **Pydantic v2** for data validation
- **PyYAML** for all data files
- **GitPython** for save versioning
- **Rich** for terminal UI
- **NiceGUI** for web UI (optional)

# TheAct

**An AI-driven text-based RPG engine designed for small language models.**

TheAct programmatically orchestrates narrative turns using specialized agents — a narrator, individual character agents, memory managers, and game state evaluators — each making a single focused LLM call. This architecture enables compelling interactive fiction with 7B-class models that would struggle with traditional agent frameworks.

## How It Works

Each turn follows a fixed pipeline:

1. **Player** types an action
2. **Narrator agent** describes what happens and decides which characters respond
3. **Character agents** respond sequentially (each sees prior responses)
4. **Post-turn agents** run in parallel: update each character's memory + check chapter progress
5. **Save** all changes and commit to git (enabling unlimited undo)

The game definition lives in simple YAML files — world, characters (~60 words each), and chapters with story beats and completion criteria. A [game creation agent](design/creator.md) can generate these from a concept description.

## Quick Start

```bash
# Install dependencies
uv sync

# Set up environment
cp .env.example .env
# Edit .env with your Venice AI API key

# Verify LLM connection
uv run python scripts/test_llm.py

# Launch the game (CLI)
uv run python -m theact

# Launch the game (Web UI)
uv run python -m theact.web
```

See the [Getting Started guide](guides/getting-started.md) for full setup instructions.

## Documentation

| Section | What you'll find |
|---------|-----------------|
| [Guides](guides/getting-started.md) | Setup, gameplay, game creation, playtesting, prompt tuning |
| [Architecture](design/architecture.md) | Turn pipeline, agents, data model, memory system |
| [Debugging & Testing](guides/debugging.md) | Turn debugger, diagnostics, golden scenarios, A/B testing |
| [Reference](requirements.md) | Design rationale, model quirks, implementation plans |

## Tech Stack

- **Python 3.11** with uv package manager
- **Venice AI** (OpenAI-compatible endpoint) with small thinking models
- **Pydantic v2** for data validation
- **PyYAML** for all data files
- **GitPython** for save versioning
- **Rich** for terminal UI
- **NiceGUI** for web UI

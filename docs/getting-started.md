# Getting Started

Go from zero to playing a game in under 5 minutes.

## Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) — Python package manager
- Venice AI API key — Sign up at [venice.ai](https://venice.ai)

## Install

```bash
git clone https://github.com/reubenjohn/theact.git
cd theact
uv sync
```

## Configure

```bash
cp .env.example .env
```

Edit `.env` and set `VENICE_API_KEY=your_key_here`. The default model and endpoint are pre-configured. See `.env.example` for optional overrides.

### Custom data directory

Set `THEACT_DATA_DIR` in `.env` to store `games/` and `saves/` outside the codebase:

```
THEACT_DATA_DIR=/path/to/your/data
```

When not set, data lives alongside the codebase.

## Verify the LLM connection

```bash
uv run python scripts/test_llm.py
```

You should see a short response from the model confirming the connection works.

## Play via CLI

```bash
uv run python -m theact
```

Select a game from the list, enter your player name, and start playing. In-game commands:

| Command   | Action                        |
|-----------|-------------------------------|
| `/undo`   | Rewind to the previous turn   |
| `/status` | Show current game state       |
| `/quit`   | Save and exit                 |

## Play via Web UI

```bash
uv sync --extra web
uv run python -m theact.web
```

Opens at [localhost:8080](http://localhost:8080).

## See Also

- [Core Concepts](concepts.md)
- [Creating a Game](guides/creating-a-game.md)
- [Architecture](architecture/overview.md)

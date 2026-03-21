# Getting Started

Go from zero to playing a game in under 5 minutes.

## Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) — Python package manager
- An API key from any OpenAI-compatible provider (see below)

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

Edit `.env` and set your API key, base URL, and model. TheAct works with any OpenAI-compatible endpoint:

| Provider | Base URL | Where to get a key |
|---|---|---|
| OpenAI | `https://api.openai.com/v1` | [platform.openai.com/api-keys](https://platform.openai.com/api-keys) |
| OpenRouter | `https://openrouter.ai/api/v1` | [openrouter.ai/settings/keys](https://openrouter.ai/settings/keys) |
| Together AI | `https://api.together.ai/v1` | [api.together.ai/settings/api-keys](https://api.together.ai/settings/api-keys) |
| Groq | `https://api.groq.com/openai/v1` | [console.groq.com/keys](https://console.groq.com/keys) |
| Venice AI | `https://api.venice.ai/api/v1` | [venice.ai/settings/api](https://venice.ai/settings/api) |
| Ollama (local) | `http://localhost:11434/v1` | No key needed — use `"ollama"` |

TheAct is optimized for small, fast models (7B-class) with thinking token support. See `.env.example` for full configuration with model name examples.

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

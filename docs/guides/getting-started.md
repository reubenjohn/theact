# Getting Started

Go from zero to playing a game in under 5 minutes.

## Prerequisites

- **Python 3.11+**
- **[uv](https://docs.astral.sh/uv/)** — Python package manager
- **Venice AI API key** — Sign up at [venice.ai](https://venice.ai) and get an API key

## Install

```bash
git clone <repo-url>
cd theact
uv sync
```

## Configure

```bash
cp .env.example .env
```

Edit `.env` and set your API key:

```
VENICE_API_KEY=your_key_here
```

The default model (`olafangensan-glm-4.7-flash-heretic`) and endpoint are pre-configured. See [`.env.example`](../../.env.example) for optional overrides.

## Verify the LLM connection

```bash
uv run python scripts/test_llm.py
```

This sends a test prompt and prints the response. If you see output with thinking tokens, the connection works.

## Play via CLI

```bash
uv run python -m theact
```

The CLI will prompt you to:
1. Select a game (Lost Island is included)
2. Enter your player name
3. Start playing — type actions and watch the story unfold

Commands during play:
- `/undo` — revert the last turn
- `/status` — show current chapter progress
- `/quit` — save and exit

## Play via Web UI

Install the web dependencies and launch:

```bash
uv sync --extra web
uv run python -m theact.web
```

Open `http://localhost:8080` in your browser. The web UI provides the same game experience with a chat-style interface and streaming token display.

## Next Steps

- [Creating a Game](creating-a-game.md) — write your own game or generate one with the creator agent
- [Architecture](../design/architecture.md) — understand how the system works under the hood

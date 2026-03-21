# Contributing to TheAct

## Working with Claude Code

### Prerequisites

- Python 3.11+ managed with [uv](https://docs.astral.sh/uv/)
- Node.js 18+ (for Playwright MCP and browser tests)
- Pre-commit formatting via `prek` (`uv tool install prek && prek install`)

### Playwright MCP Setup

Claude Code uses a [Playwright MCP server](https://github.com/anthropics/model-context-protocol) to interact with the web UI in a real browser. This enables Claude to navigate pages, inspect the DOM, and verify UI behavior directly.

**1. Install Chromium for Playwright:**
```bash
npx -y @playwright/test@latest install chromium
```

**2. Register the MCP server with Claude Code:**
```bash
claude mcp add playwright -- npx -y @playwright/mcp@latest --headless
```

This adds the server to your local Claude config (`~/.claude.json`). The `--headless` flag runs Chromium without a GUI window, which is required in WSL and headless environments.

**3. Verify it works:**

Launch `claude` in the project directory and ask it to open a URL with Playwright. The MCP tools (`browser_navigate`, `browser_snapshot`, `browser_click`, etc.) should be available.

### Running Tests

```bash
# Unit tests (fast, no browser needed)
uv run pytest tests/ -x

# Web UI browser tests (requires Chromium installed)
uv run pytest tests/web/ -x

# All tests
uv run pytest -x
```

### Web UI Development

```bash
# Start the web UI server
uv run python -m theact.web

# Start with auto-reload for development
uv run python -m theact.web --reload
```

The web UI runs at `http://localhost:8080` by default.

### Test Structure

- `tests/` — Unit tests (models, IO, LLM client, engine, CLI, agents)
- `tests/web/` — Web UI tests split into:
  - Unit tests for pure logic (slugify, commands, styles)
  - Browser integration tests using `pytest-playwright` (run against a live NiceGUI server)

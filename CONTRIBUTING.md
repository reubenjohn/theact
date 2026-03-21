# Contributing to TheAct

## Development Setup

**Prerequisites:** Python 3.11+, [uv](https://docs.astral.sh/uv/), Node.js 18+ (browser tests only)

```bash
git clone https://github.com/reubenjohn/theact.git
cd theact
uv sync
cp .env.example .env    # Add your LLM_API_KEY, LLM_BASE_URL, LLM_MODEL
```

Install the pre-commit formatter:

```bash
uv tool install prek && prek install
```

## Running Tests

```bash
uv run pytest tests/ -x            # Unit tests
uv run pytest tests/web/ -x        # Browser tests (requires Chromium)
uv run pytest -x                   # All tests
```

Browser tests require Chromium. Install it with:

```bash
npx -y @playwright/test@latest install chromium
```

## Development Tools

| Tool | Command | Docs |
|------|---------|------|
| Playtest | `scripts/playtest.py` | [Playtesting](docs/guides/playtesting.md) |
| Turn Debugger | `scripts/debug_turn.py` | [Debugging](docs/guides/debugging.md) |
| Golden Scenarios | `scripts/run_golden.py` | [Playtesting](docs/guides/playtesting.md) |
| A/B Testing | `scripts/ab_test.py` | [Prompt Engineering](docs/guides/prompt-engineering.md) |
| Dev Server | `scripts/dev_server.py` | -- |

All scripts are run via `uv run python <script>`. See linked docs for usage details.

## Web UI Development

```bash
uv sync --extra web
uv run python -m theact.web --reload
```

Runs at `localhost:8080` with hot reload.

## Code Style

- **Formatting:** ruff, enforced via `prek` pre-commit hook
- **Type hints** throughout -- no untyped public functions
- **Pydantic v2** with `extra="forbid"` to catch typos in data files
- **All LLM calls are async** -- use `AsyncOpenAI` and `await`
- **YAML for everything** -- data files, structured LLM output, game content

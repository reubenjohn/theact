# TheAct — AI Text-Based RPG Engine

## Project Overview

TheAct is a programmatically-driven text RPG engine designed to work with small language models (7B-class thinking models). It is NOT an agent framework — the turn logic is entirely orchestrated by code, with each LLM call doing exactly one focused task.

The system uses Venice AI's OpenAI-compatible API with the model `olafangensan-glm-4.7-flash-heretic`. Every design decision optimizes for small model reliability.

## Critical Constraints

- **Tiny prompts.** System prompts must stay under ~300 tokens. Every word must earn its place. A 7B model with 8K context cannot afford waste.
- **One task per LLM call.** Never ask the model to do two things. Narrator narrates. Memory agent updates memory. Game state agent checks completion. Separate calls.
- **Tiny game files.** Character files ~60 words. World file ~6 sentences. Chapter beats are short phrases, not paragraphs. These files are injected into prompts — bloat here kills model performance.
- **YAML everywhere.** All data files use YAML (not JSON). Use `pyyaml`. Structured LLM output is also YAML in fenced code blocks.
- **Sequential characters, parallel post-turn.** Character agents respond one at a time (each sees prior responses). Memory updates and game state checks run in parallel via `asyncio.gather`.

## Architecture

```
Player Input → Context Assembly (code) → Narrator Agent (streaming)
→ Character Agents (sequential, streaming) → Post-Turn Agents (parallel)
→ Persist + Git Commit
```

Code layout:
- `src/theact/models/` — Pydantic data models
- `src/theact/io/` — YAML I/O, save manager
- `src/theact/versioning/` — Git-based save versioning
- `src/theact/llm/` — LLM client, streaming, structured output parsing
- `src/theact/engine/` — Turn engine, context assembly
- `src/theact/agents/` — Narrator, character, memory, game state, summarizer agents
- `src/theact/cli/` — Rich terminal CLI
- `src/theact/playtest/` — Autonomous playtest framework
- `src/theact/creator/` — Game creation agent
- `src/theact/web/` — NiceGUI web interface

## Documentation

- `docs/README.md` — Documentation hub (start here for navigation)
- `docs/design/` — Architecture, agents, data model, memory & summarization
- `docs/guides/` — Getting started, creating games, playtesting, prompt iteration
- `docs/requirements.md` — Design rationale — the "why" behind decisions

## Implementation Plans

Detailed phase-by-phase plans are in `docs/plans/`. Read them in order:
1. `01-DataModelAndProjectStructure.md` — Data models, YAML files, git versioning
2. `02-LLMClientAndInference.md` — LLM wrapper, streaming, structured output
3. `03-TurnEngineMemoryAndSummarization.md` — **The core.** Turn orchestration, prompts, memory, summarization
4. `04-RichCLI.md` — Terminal interface with Rich
5. `05-ExampleGameAndPlaytest.md` — Lost Island game + autonomous playtest framework
6. `06-GameCreationAgent.md` — Interactive game creation (uses larger model)
7. `07-WebUI.md` — NiceGUI web interface
8. `08-Documentation.md` — Guides and design docs

## Commands

```bash
uv sync                              # Install dependencies
uv run pytest tests/                 # Run tests (unit only)
uv run pytest tests/web/             # Run web UI browser tests (requires Chromium)
uv run python scripts/test_llm.py    # Smoke test LLM client (needs VENICE_API_KEY)
uv run python scripts/playtest.py --game lost-island --turns 20  # Autonomous playtest
uv run python -m theact              # Launch CLI (Phase 04)
uv run python -m theact.web          # Launch Web UI (port 8080)
```

## Playwright MCP (Browser Testing)

A Playwright MCP server is configured for this project, giving Claude Code direct browser interaction capabilities (navigate, click, inspect DOM via accessibility snapshots).

- **Config location:** `~/.claude.json` → `projects["/home/reuben/workspace/theact"].mcpServers.playwright`
- **Mode:** headless Chromium (no GUI needed in WSL)
- **Command:** `npx -y @playwright/mcp@latest --headless --browser chromium`
- **Browser cache:** `~/.cache/ms-playwright/`

To reinstall the browser binary if needed:
```bash
npx -y @playwright/test@latest install chromium
```

## Environment

Requires a `.env` file (already configured in the project root):
```
VENICE_API_KEY=<set>
VENICE_BASE_URL=https://api.venice.ai/api/v1     # optional
VENICE_MODEL=olafangensan-glm-4.7-flash-heretic   # optional
```

The API key is available for live model testing, diagnostics, and playtest runs.

## Key Technical Decisions

- **Git for save versioning** — Each save is its own git repo. One commit per turn. Undo = `git reset --hard HEAD~N`. Scales to hundreds of turns.
- **Rolling summary** — Incremental merge (existing summary + expired turns → updated summary). Not full re-summarization. Keeps summary calls cheap.
- **Character memory** — Per-character YAML files with a 3-5 sentence summary + max 10 key facts. Updated by a dedicated memory agent per character (never cross-contaminated).
- **Chapter completion** — Each chapter has explicit completion criteria and beats. A dedicated game state agent evaluates progress each turn.
- **Token estimation** — Simple `len(text) // 4` heuristic. No tiktoken dependency.
- **Structured output** — YAML in fenced code blocks, parsed with `yaml.safe_load()`, retry with error feedback on parse failure. Small models can't reliably use JSON mode.

## Coding Conventions

- Python 3.11, managed with `uv`
- Pydantic v2 for data models (`extra="forbid"` to catch typos)
- All LLM calls are async (`AsyncOpenAI`)
- Type hints throughout
- Pre-commit: ruff lint + format via `prek`
- Tests: pytest with `tmp_path` fixtures for file operations

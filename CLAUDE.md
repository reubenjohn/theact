# TheAct — AI Text-Based RPG Engine

## Project Overview

TheAct is a programmatically-driven text RPG engine designed to work with small language models (7B-class thinking models). It is NOT an agent framework — the turn logic is entirely orchestrated by code, with each LLM call doing exactly one focused task.

The system uses any OpenAI-compatible API endpoint — AI, OpenAI, OpenRouter, Together AI, Groq, Venice, or a local server (Ollama/vLLM). Every design decision optimizes for small model reliability.

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
- `src/theact/io/` — YAML I/O, save manager, settings persistence (`settings_store.py`)
- `src/theact/versioning/` — Git-based save versioning (`save_as`, `peek_at_turn`, `diff_turns`)
- `src/theact/llm/` — LLM client, streaming, structured output, call logging, profiler
- `src/theact/engine/` — Turn engine, context assembly, diagnostics writer
- `src/theact/agents/` — Narrator, character, memory, game state, summarizer agents
- `src/theact/debugger/` — Interactive turn debugger for prompt engineering
- `src/theact/cli/` — Rich terminal CLI
- `src/theact/commands/` — Shared command logic (pure functions, no UI imports) used by both CLI and web
- `src/theact/playtest/` — Autonomous playtest framework with quality scoring
- `src/theact/creator/` — Game creation agent
- `src/theact/web/` — NiceGUI web interface (modular: `state.py`, `turn_runner.py`, `streaming.py`, `command_router.py`, `components/`, plus feature modules for toolbar, sidebar, history, creator wizard, settings, playtest dashboard, diagnostics viewer, and safety)

## Documentation

- `docs/README.md` — **Start here.** Navigation hub for all documentation.
- `docs/concepts.md` — Core concepts, glossary, design principles
- `docs/getting-started.md` — Install, configure, play your first game
- `docs/architecture/` — Turn pipeline, data model, agents, memory, save versioning
- `docs/guides/` — Creating games, playtesting, debugging, prompt engineering
- `docs/reference/` — Observability, game creation pipeline, design rationale, model quirks

## Observability & Debugging Tools

These tools exist for diagnosing and improving model behavior. See `docs/reference/observability.md` and `docs/guides/debugging.md` for details.

- **Call logging** — Every LLM call records tokens, latency, parse result. See `src/theact/llm/call_log.py`.
- **Diagnostics writer** — `run_turn(..., debug=True)` writes per-agent artifacts (prompts, responses, parsed output) to `diagnostics/turn-NNN/`.
- **Context profiler** — `src/theact/llm/profiler.py` — analyze token budget allocation per agent.
- **Turn debugger** — `scripts/debug_turn.py` — step through agents interactively, replay with edited prompts, capture fixtures. See `docs/guides/debugging.md` for usage.
- **Error taxonomy** — 7-category `ParseFailureType` in `src/theact/llm/errors.py` classifies why YAML parsing failed.
- **Prompt linting** — `tests/test_prompt_lint.py` enforces ≤300 token budgets and no orphan placeholders.

## Testing & Validation Tools

- **Playtest framework** — `scripts/playtest.py` — autonomous N-turn playtests with quality scoring and LLM call reports.
- **Golden scenarios** — `scripts/run_golden.py` — behavioral test scenarios with structural assertions (not textual). See `tests/golden_scenarios/`.
- **A/B testing** — `scripts/ab_test.py` — compare two prompt variants with statistical metrics.
- **Agent diagnostics** — `scripts/diagnose_agent.py` — test individual agents against the live API.

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
9. `09-ObservabilityAndDiagnostics.md` — Call logging, diagnostics, profiler, error taxonomy
10. `10-SaveVersioningAndTurnDebugger.md` — Save forking, history peek/diff, interactive debugger
11. `11-SmallModelHardening.md` — Prompt iteration, YAML reliability, golden scenarios
12. `12-CreatorSmallModelHardening.md` — Brainstorm tool, decomposed proposal & generation, per-file fixing
13. `13-WebUIExpansion/` — Web UI expansion: toolbar, sidebar, history, creator wizard, settings, playtest dashboard, diagnostics viewer, polish & safety
14. `14-CI.md` — GitHub Actions CI: lint, test (matrix), browser tests, build, coverage

## Commands

```bash
uv sync                              # Install dependencies
uv run pytest tests/                 # Run tests (unit only)
uv run pytest tests/web/             # Run web UI browser tests (requires Chromium)
uv run python -m theact              # Launch CLI
uv run python -m theact.web          # Launch Web UI (port 8080)
uv run scripts/dev_server.py start --port 8111  # Start dev server (background)
uv run scripts/dev_server.py stop               # Stop dev server
uv run scripts/dev_server.py restart --port 8111 # Restart dev server
uv run scripts/dev_server.py status             # Check if dev server is running

# LLM testing (requires LLM_API_KEY in .env)
uv run python scripts/test_llm.py                              # Smoke test LLM client
uv run python scripts/diagnose_agent.py narrator "I look around"  # Test one agent
uv run python scripts/playtest.py --game lost-island --turns 20   # Autonomous playtest
uv run python scripts/debug_turn.py --save test --input "I look around"  # Turn debugger
uv run python scripts/run_golden.py                              # Golden scenario suite
uv run python scripts/ab_test.py --variant-b prompts_v2.py --runs 3  # A/B test
```

## CI

GitHub Actions runs on push to main and PRs. See `.github/workflows/ci.yml`.
- **Lint:** `ruff check .` + `ruff format --check .` (pinned to v0.11.4, matching `prek.toml`)
- **Unit tests:** `pytest tests/ --ignore=tests/web/` with coverage (Python 3.11 + 3.12 matrix, includes `--extra web` for web unit tests)
- **Browser tests:** `pytest tests/web/` with Playwright Chromium (`continue-on-error`)
- **Build:** `uv build`
- **Coverage:** Codecov (uploaded from Python 3.12 run only)

## Environment

Requires a `.env` file (see `docs/getting-started.md` for full setup):
```bash
cp .env.example .env
# Edit .env with your API key and model settings
```

Web UI browser tests require Chromium: `npx -y @playwright/test@latest install chromium`

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

## Web UI Change Workflow

When modifying the web UI, always manually validate with Playwright MCP:

1. **Start the dev server:** `uv run scripts/dev_server.py restart --port 8111`
2. **Navigate and inspect** using Playwright MCP tools (`browser_navigate`, `browser_snapshot`, `browser_take_screenshot`)
3. **Test both static and streaming paths** — static renders from saved conversation history; streaming renders live during a turn. They use different code paths.
4. **Any visual surprise** discovered during Playwright validation should be captured as a regression test in `tests/` (unit test) or `tests/web/` (browser test) to prevent recurrence.

## Contributing to CLAUDE.md

This file is checked into the repo and read by all contributors' AI tools. Keep it generic:
- **No absolute paths** — use relative paths or `~` notation
- **No machine-specific config** — put personal setup in Claude Code memory or local dotfiles
- **No API keys or secrets** — reference `.env.example` instead

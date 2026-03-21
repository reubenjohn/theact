# Phase 08: Documentation

> **Goal:** Make the codebase approachable to someone seeing it for the first time with no context, without creating documentation that rots as the code changes.

## 1. Overview

This phase adds two new documentation directories — `docs/design/` for architectural deep-dives and `docs/guides/` for task-oriented walkthroughs — plus a `docs/README.md` hub that ties everything together.

The existing `docs/plans/` remain as-is; they capture *what was built and why* during each phase. The new docs are evergreen: they describe the system as it is today.

### Design principles

- **Reference source, don't copy it.** Instead of embedding code blocks that go stale, point readers to the file and line range. A reader can always `grep` a function name; they can't grep for *why it exists*.
- **Cross-reference, don't repeat.** Each document owns one topic. Other docs link to it rather than restating.
- **Source of truth hierarchy.** Code > CLAUDE.md > docs/design/ > docs/guides/ > docs/plans/. If a doc contradicts the code, the code wins.

---

## 2. Documentation Map

```
docs/
  README.md                      # Hub — one-paragraph summary + links to everything
  requirements.md                # (existing) Design rationale — the "why"
  plans/                         # (existing) Phase-by-phase implementation plans
  design/
    architecture.md              # System overview, turn pipeline, module map
    agents.md                    # Agent roles, prompt design philosophy, structured output
    data-model.md                # Game files, save files, Pydantic models
    memory-and-summarization.md  # Character memory, rolling summary, context budgeting
  guides/
    getting-started.md           # Install, configure, run your first game
    creating-a-game.md           # Write game YAML files or use the creator agent
    playtesting.md               # Run and interpret autonomous playtests
    prompt-iteration.md          # How to tune prompts for small models
```

---

## 3. Document Specifications

### 3.1 `docs/README.md` — Documentation Hub

**Purpose:** Single entry point. A newcomer reads this first.

**Contents:**
- One paragraph describing what TheAct is
- "Start here" callout pointing to `guides/getting-started.md`
- Table of links organized by audience:
  - **Using TheAct** → guides/
  - **Understanding the architecture** → design/
  - **Implementation history** → plans/, requirements.md
  - **AI-assisted development** → CLAUDE.md

**Length:** Under 40 lines. No prose beyond the intro paragraph.

---

### 3.2 `docs/design/architecture.md` — System Architecture

**Purpose:** Explain how a turn flows from player input to git commit. This is the doc a new contributor reads to build a mental model.

**Sections:**

1. **Turn Pipeline** — ASCII diagram of the full turn flow (same as CLAUDE.md's but expanded with step numbers). Reference `src/theact/engine/turn.py:run_turn()` for the implementation.

2. **Module Map** — One sentence per package describing its responsibility. Reference the actual `src/theact/` directory structure. Do NOT list every file — just the packages and their purpose.

3. **Concurrency Model** — Explain sequential characters vs. parallel post-turn. Reference `turn.py`'s `asyncio.gather` call.

4. **Streaming** — How tokens flow from the LLM through the engine to the UI. Reference `StreamCallback` in `turn.py` and `src/theact/llm/streaming.py`.

5. **Frontends** — CLI and web UI both consume the same `run_turn()` interface. Reference `src/theact/cli/session.py` and `src/theact/web/session.py`. Link to `guides/getting-started.md` for how to launch each.

**Cross-references:**
- Links to `design/agents.md` for agent details
- Links to `design/data-model.md` for game/save file structure
- Links to `design/memory-and-summarization.md` for context management

---

### 3.3 `docs/design/agents.md` — Agent System

**Purpose:** Explain what each agent does, how prompts are designed for small models, and how structured output works.

**Sections:**

1. **Agent Inventory** — Table listing each agent (narrator, character, memory, game state, chapter summarizer, rolling summarizer) with: purpose, input, output format, source file. Reference `src/theact/agents/` modules.

2. **Prompt Design for Small Models** — The rules: one task per call, ~300 token system prompts, imperative mood, concrete examples in the prompt. Reference `src/theact/agents/prompts.py` as the single source of all prompt templates. Link to `guides/prompt-iteration.md` for how to modify them.

3. **Structured Output** — YAML in fenced code blocks. How the parsing works (regex extraction + `yaml.safe_load` + retry with error feedback). Reference `src/theact/llm/parsing.py`.

4. **Context Assembly** — How each agent's message list is built. Token budgeting and overflow trimming. Reference `src/theact/engine/context.py` and the `build_*_messages()` functions.

**Cross-references:**
- Links to `design/architecture.md` for where agents fit in the pipeline
- Links to `design/memory-and-summarization.md` for memory/summary agent details

---

### 3.4 `docs/design/data-model.md` — Data Model

**Purpose:** Explain the YAML file formats (game definition + save state) and their Pydantic backing models.

**Sections:**

1. **Game Definition Files** — The template a game author creates. Walk through the `games/lost-island/` directory as a concrete example:
   - `game.yaml` → `GameMeta` model
   - `world.yaml` → `World` model
   - `characters/*.yaml` → `Character` model
   - `chapters/*.yaml` → `Chapter` model

   Reference each model in `src/theact/models/` and each example file in `games/lost-island/`. Explain the size constraints (character ~60 words, world ~6 sentences) and *why* (they're injected into prompts for a model with 8K context).

2. **Save Files** — What gets created when a player starts a game. Walk through the save directory structure:
   - `state.yaml` → `GameState` model
   - `conversation.yaml` → list of `ConversationEntry`
   - `memories/*.yaml` → `CharacterMemory` model
   - `summaries.yaml` → list of `ChapterSummary`

   Reference `src/theact/io/save_manager.py` for the I/O layer and `src/theact/models/state.py` for the state model.

3. **Git Versioning** — Each save is a git repo. One commit per turn. Undo via `git reset`. Reference `src/theact/versioning/git_save.py`.

4. **Loading a Game** — How `LoadedGame` assembles template + save into a single in-memory structure. Reference `src/theact/models/game.py`.

**Cross-references:**
- Links to `guides/creating-a-game.md` for how to write game files
- Links to `design/memory-and-summarization.md` for how memories evolve

---

### 3.5 `docs/design/memory-and-summarization.md` — Memory & Summarization

**Purpose:** Explain how the system manages a growing conversation within a tiny context window.

**Sections:**

1. **The Problem** — A 7B model has ~8K context. A game can last 50+ turns. The raw conversation would be ~25K tokens. Something must give.

2. **Character Memory** — Per-character YAML files with a summary (3-5 sentences) and key facts (max 10). Updated by the memory agent each turn. Memory is never cross-contaminated between characters. Reference `src/theact/agents/memory.py` and `src/theact/models/memory.py`.

3. **Rolling Summary** — When unsummarized conversation exceeds ~1500 tokens, the oldest turns are compressed into a running summary. Incremental merge, not full re-summarization. Reference `_maybe_update_rolling_summary()` in `src/theact/engine/turn.py`.

4. **Chapter Summaries** — When a chapter completes, a dedicated summarizer creates a 2-3 sentence summary. These are injected into the narrator's context for continuity. Reference `src/theact/agents/summarizer.py`.

5. **Context Budgeting** — How `build_narrator_messages()` and `build_character_messages()` check token budgets and trim conversation if needed. Reference `src/theact/engine/context.py` and `src/theact/llm/tokens.py`.

**Cross-references:**
- Links to `design/agents.md` for the memory and summarizer agent details
- Links to `design/data-model.md` for memory file format

---

### 3.6 `docs/guides/getting-started.md` — Getting Started

**Purpose:** Zero-to-playing in under 5 minutes.

**Sections:**

1. **Prerequisites** — Python 3.11+, uv, an LLM API key
2. **Install** — `uv sync`, `.env` setup
3. **Verify** — `uv run python scripts/test_llm.py`
4. **Play (CLI)** — `uv run python -m theact`, select Lost Island, walk through a turn
5. **Play (Web)** — `uv sync --extra web && uv run python -m theact.web`, open browser
6. **Next steps** — Links to `guides/creating-a-game.md` and `design/architecture.md`

**Cross-references:**
- Links to `design/architecture.md` for understanding the pipeline
- Links to `design/data-model.md` for file format details

---

### 3.7 `docs/guides/creating-a-game.md` — Creating a Game

**Purpose:** How to create a new game, either manually or with the creator agent.

**Sections:**

1. **Game Directory Structure** — What files you need to create. Reference `games/lost-island/` as a template.

2. **Writing Game Files by Hand** — Walk through each file type with the constraints (word counts, tone guidelines). Reference `design/data-model.md` for the full model specs. DO NOT duplicate the field descriptions — just show the minimal structure and link.

3. **Using the Creator Agent** — `uv run python scripts/create_game.py`. What it does: proposes → validates → fixes → writes. Reference `src/theact/creator/session.py` for the pipeline.

4. **Testing Your Game** — Run a short playtest: `uv run python scripts/playtest.py --game your-game --turns 5`. Link to `guides/playtesting.md`.

**Cross-references:**
- Links to `design/data-model.md` for detailed model specs
- Links to `guides/playtesting.md` for validation

---

### 3.8 `docs/guides/playtesting.md` — Playtesting

**Purpose:** How to use the autonomous playtest framework to validate a game and tune prompts.

**Sections:**

1. **What Playtesting Does** — An AI player agent plays the game for N turns. The system logs every LLM call, tracks beats hit, and produces a report.

2. **Running a Playtest** — `uv run python scripts/playtest.py --game lost-island --turns 20`. Reference `scripts/playtest.py` for CLI args. Reference `src/theact/playtest/config.py` for configuration.

3. **Reading the Report** — What the report tells you: turns completed, beats hit, chapters advanced, errors. Reference `src/theact/playtest/report.py`.

4. **Common Issues** — What to look for: empty responses, malformed YAML, repetitive narration, characters breaking voice. Each links to `guides/prompt-iteration.md` for the fix.

**Cross-references:**
- Links to `guides/prompt-iteration.md` for fixing issues
- Links to `design/agents.md` for understanding agent output

---

### 3.9 `docs/guides/prompt-iteration.md` — Prompt Iteration

**Purpose:** How to modify prompts when the model misbehaves. This is the guide that turns playtest failures into fixes.

**Sections:**

1. **Where Prompts Live** — `src/theact/agents/prompts.py`. All prompts in one file, by design. One-line edits, not refactors.

2. **The Iteration Loop** — Change prompt → playtest → read report → repeat. Reference the specific scripts.

3. **Rules for Small Models** — Recap the constraints: ~300 token system prompts, one task per call, imperative mood, concrete examples. Link to `design/agents.md` for the full philosophy.

4. **Common Fixes** — Practical tips:
   - Model outputs prose instead of YAML → add a stricter example
   - Character breaks voice → tighten the personality constraint
   - Narrator skips beats → add "Do NOT skip beats" (already present, but may need reinforcement)
   - Memory agent hallucinates facts → narrow the witness constraint

**Cross-references:**
- Links to `design/agents.md` for prompt design philosophy
- Links to `guides/playtesting.md` for the feedback loop

---

## 4. Implementation Steps

### Step 1: Create directory structure

```bash
mkdir -p docs/design docs/guides
```

### Step 2: Write `docs/README.md`

The documentation hub. Follow spec in 3.1.

### Step 3: Write design docs

Write in this order (each builds on the previous):
1. `docs/design/architecture.md` (3.2)
2. `docs/design/data-model.md` (3.4)
3. `docs/design/memory-and-summarization.md` (3.5)
4. `docs/design/agents.md` (3.3)

### Step 4: Write guides

Write in this order:
1. `docs/guides/getting-started.md` (3.6)
2. `docs/guides/creating-a-game.md` (3.7)
3. `docs/guides/playtesting.md` (3.8)
4. `docs/guides/prompt-iteration.md` (3.9)

### Step 5: Update `CLAUDE.md`

Add a brief section pointing to the new docs. Do not duplicate content — just add pointers. The existing Architecture and Key Technical Decisions sections stay as-is (they serve a different audience: AI assistants need inline context, not links).

### Step 6: Update root `README.md`

Replace the Documentation section with a more complete listing that includes the new docs.

### Step 7: Update `docs/plans/README.md`

Add Phase 08 to the phase index table.

---

## 5. Verification

- [ ] Every internal link resolves (no broken cross-references)
- [ ] No document duplicates content from another — each states a fact once and links elsewhere
- [ ] Design docs reference source files, not embedded code blocks
- [ ] Guides are task-oriented (a verb in each section title)
- [ ] `docs/README.md` is under 40 lines
- [ ] A newcomer can go from `docs/README.md` → `guides/getting-started.md` → playing a game without reading any other doc
- [ ] The source of truth hierarchy holds: no doc contradicts the code or CLAUDE.md

---

## 6. Maintenance Notes

These docs are designed to be low-maintenance:

- **Design docs** reference source files by path and function name, not by copying code. When code changes, the reference still points to the right place (function names are more stable than line numbers, but line numbers can be included as hints).
- **Guides** describe workflows (commands to run, files to create), not implementation details. They survive refactors as long as the CLI interface stays the same.
- **If a doc goes stale**, delete it rather than letting it mislead. A missing doc is better than a wrong one.

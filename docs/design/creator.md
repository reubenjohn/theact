# Creator Agent

The creator agent is a multi-step pipeline that generates a complete game from a free-text concept description. Unlike the gameplay agents (which use a 7B model), the creator uses a larger, more capable model — game generation requires producing structurally valid, cross-referenced YAML across multiple files.

Source: [`src/theact/creator/`](../../src/theact/creator/)

## Pipeline Overview

```
Concept (free text)
  → Proposal (LLM generates high-level structure)
  → User review loop (approve or revise)
  → Generation (LLM produces all game YAML files)
  → Validation (Pydantic models + cross-reference checks)
  → Auto-fix loop (LLM corrects validation errors, up to 3 attempts)
  → Size warnings (flag files exceeding token budgets)
  → User review loop (approve or revise specific files)
  → Write to disk (games/<game-id>/)
```

Orchestrated by [`session.py`](../../src/theact/creator/session.py).

## How game-id Is Determined

The game-id is **chosen by the LLM** during the proposal step. The proposal prompt ([`prompts.py`](../../src/theact/creator/prompts.py)) instructs the model to produce `id: "url-safe-slug"` as part of the proposal YAML. The model derives the slug from the game concept (e.g., a concept about a lost island might produce `id: "lost-island"`).

This id flows unchanged through the entire pipeline:

1. **Proposal** — LLM generates `id: "url-safe-slug"` based on the concept
2. **Generation** — The id is carried forward into `game.id` in the full YAML output
3. **Validation** — Parsed into `GameMeta.id` (a plain `str` field, no format validation)
4. **Disk write** — Used as the directory name: `games/<id>/`

There is no code-side slugification or uniqueness check beyond the overwrite confirmation in the session flow. If a directory with that id already exists, the user is prompted before overwriting.

## Module Responsibilities

| Module | Role |
|--------|------|
| [`session.py`](../../src/theact/creator/session.py) | Orchestrates the full interactive flow (7 steps) |
| [`proposer.py`](../../src/theact/creator/proposer.py) | Generates and revises high-level proposals |
| [`generator.py`](../../src/theact/creator/generator.py) | Generates full game YAML from an approved proposal |
| [`validator.py`](../../src/theact/creator/validator.py) | Validates game data against Pydantic models + cross-references |
| [`fixer.py`](../../src/theact/creator/fixer.py) | Feeds validation errors back to the LLM for auto-correction |
| [`writer.py`](../../src/theact/creator/writer.py) | Writes validated game files to `games/<id>/` |
| [`display.py`](../../src/theact/creator/display.py) | Rich-formatted display of proposals, files, errors, and warnings |
| [`prompts.py`](../../src/theact/creator/prompts.py) | All prompt templates (proposal, generation, fix, revision) |
| [`config.py`](../../src/theact/creator/config.py) | LLM configuration with `CREATOR_*` / `VENICE_*` env var fallback |

## Two-Phase LLM Interaction

The creator makes multiple LLM calls, but they follow the same one-task-per-call principle as gameplay agents:

### Phase 1: Proposal

The proposer generates a **high-level game structure** — title, id, setting, tone, rules, character list, and chapter list. This is a lightweight YAML structure (~30 lines) that the user can review and revise before committing to full generation.

- Prompt: `PROPOSAL_SYSTEM` + `PROPOSAL_USER`
- Revision: `PROPOSAL_SYSTEM` + `PROPOSAL_REVISION_USER` (feeds current proposal + user feedback)
- Output: YAML with keys `title`, `id`, `setting`, `tone`, `rules`, `characters`, `chapters`

### Phase 2: Generation

Once the proposal is approved, the generator produces **all game definition files** in a single YAML block — `game.yaml`, `world.yaml`, all character files, and all chapter files.

- Prompt: `GENERATION_SYSTEM` + `GENERATION_USER`
- Output: YAML with top-level keys `game`, `world`, `characters`, `chapters`
- Retry: Up to 3 attempts on YAML parse failure, feeding the error back each time

## Validation

Validation ([`validator.py`](../../src/theact/creator/validator.py)) runs in two layers:

1. **Pydantic model validation** — Each file is validated against its model (`GameMeta`, `World`, `Character`, `Chapter`). Uses `extra="forbid"` to catch unexpected fields.

2. **Cross-reference checks** — Structural consistency across files:
   - Characters listed in `game.yaml` must have corresponding character files
   - Chapter `next` chains must form a valid sequence matching `game.yaml` order
   - Relationship keys must reference valid character stems (not self-referencing)
   - Characters referenced in chapters must exist
   - Circular chapter chains are detected

## Auto-Fix

When validation fails, the fixer ([`fixer.py`](../../src/theact/creator/fixer.py)) sends the errors and current YAML back to the LLM with instructions to fix only the errors. Up to 3 attempts. If the LLM produces unparseable YAML during a fix attempt, the previous data is preserved and the loop retries.

## Size Warnings

After validation passes, [`check_size_warnings()`](../../src/theact/creator/validator.py) flags files that exceed recommended budgets:

- `world.yaml` over 150 words (target: under 120)
- Character files over 80 words (target: ~60)
- Chapters with fewer than 4 or more than 6 beats
- Individual beats over 15 words

These are warnings, not errors — the user decides whether to revise.

## Configuration

The creator uses its own LLM config ([`config.py`](../../src/theact/creator/config.py)), separate from gameplay:

| Env var | Fallback | Default |
|---------|----------|---------|
| `CREATOR_BASE_URL` | `VENICE_BASE_URL` | `https://api.venice.ai/api/v1` |
| `CREATOR_API_KEY` | `VENICE_API_KEY` | (required) |
| `CREATOR_MODEL` | `VENICE_MODEL` | `olafangensan-glm-4.7-flash-heretic` |

If the resolved model is the 7B gameplay model, a warning is printed — game creation works best with a larger model.

## Targeted Revision

During the final review step, users can request changes to specific parts of the generated game. This uses `TARGETED_REVISION_USER`, which sends the current YAML + user feedback. The LLM must output the **complete** YAML (all files), not just the changed parts, to keep parsing simple. Up to 3 retry attempts on parse failure.

## Further Reading

- [Creating a Game](../guides/creating-a-game.md) — user-facing guide for the creator
- [Data Model](data-model.md) — game file format specs and size constraints
- [Agents](agents.md) — gameplay agents (separate from the creator)

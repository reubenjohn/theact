# Creating a Game

You can create a game by writing YAML files by hand or by using the creator agent to generate them from a concept description.

## Game Directory Structure

A game is a directory under `games/` containing:

```
games/your-game/
  game.yaml           # Title, description, character and chapter lists
  world.yaml          # Setting, tone, narrative rules
  characters/
    alice.yaml         # One file per character
  chapters/
    01-opening.yaml    # Chapters in order
    02-midpoint.yaml
```

Use [`games/lost-island/`](../../games/lost-island/) as a reference. For the full model specs of each file, see [Data Model](../design/data-model.md).

## Writing Game Files by Hand

### `game.yaml`

Lists the characters and chapters by their file stems (filenames without `.yaml`):

```yaml
id: your-game
title: Your Game Title
description: One sentence pitch.
characters:
  - alice
chapters:
  - 01-opening
  - 02-midpoint
```

### `world.yaml`

Defines the narrative voice. Keep it short — this is injected into every narrator prompt.

```yaml
setting: >
  Two sentences describing when, where, and what's happening.
tone: >
  Narrative style guidance. Person, tense, word count per turn.
rules: >
  Hard constraints the narrator must follow.
```

### Characters

Each character file has ~60 words total. Resist the urge to write backstories.

```yaml
name: Alice Park
role: Short role description.
personality: >
  A few sentences. Speech patterns and coping mechanisms,
  not life history.
secret: One sentence the character hides.
relationships:
  bob: "What Alice thinks of Bob."
```

### Chapters

Each chapter has beats (short phrases, not paragraphs) and a completion condition:

```yaml
id: 01-opening
title: The Opening
summary: >
  One sentence describing the chapter's purpose.
beats:
  - Something happens
  - Another thing happens
  - A character is introduced
completion: One sentence describing when this chapter is done.
characters:
  - alice
next: 02-midpoint
```

The last chapter omits `next` — this signals the end of the game.

### Size discipline

The single most important constraint: **game files must stay tiny.** These are injected into prompts for a 7B model with ~8K context. See [Data Model — Size Constraints](../design/data-model.md#size-constraints) for the rationale.

## Using the Creator Agent

The creator agent generates a complete game from a text description:

```bash
uv run python scripts/create_game.py
```

The interactive session walks you through these steps:

1. **Describe your concept** — Genre, setting, characters, what the player does. A few sentences is enough.
2. **Review the proposal** — The LLM generates a high-level structure (title, id, setting, tone, characters, chapters). Type feedback to revise, or `ok` to proceed.
3. **Generation** — The LLM produces all game YAML files from the approved proposal.
4. **Validation & auto-fix** — Files are validated against Pydantic models and cross-reference checks. Errors are automatically sent back to the LLM for correction (up to 3 attempts).
5. **Size warnings** — Files exceeding recommended token budgets are flagged.
6. **Final review** — You see all generated files. Type feedback to revise specific parts, or `ok` to finalize.
7. **Write to disk** — Files are written to `games/<game-id>/`.

### How game-id is determined

The **LLM chooses the game-id** during the proposal step. The prompt asks it to generate `id: "url-safe-slug"` based on your concept (e.g., a pirate adventure might get `id: "black-tide"`). This id becomes both the `game.yaml` id field and the directory name under `games/`. If a directory with that id already exists, you'll be prompted before overwriting.

### Configuration

The creator uses a **larger model** than the 7B gameplay model. Configure it via environment variables in `.env`:

| Variable | Fallback | Purpose |
|----------|----------|---------|
| `CREATOR_MODEL` | `VENICE_MODEL` | Model to use for generation |
| `CREATOR_API_KEY` | `VENICE_API_KEY` | API key |
| `CREATOR_BASE_URL` | `VENICE_BASE_URL` | API endpoint |

If no `CREATOR_MODEL` is set and the resolved model is the 7B default, a warning is printed. Game creation works best with a more capable model.

For the full design details, see [Creator Agent](../design/creator.md).

## Testing Your Game

Run a short playtest to verify the game works:

```bash
uv run python scripts/playtest.py --game your-game --turns 5
```

This runs an AI player through your game and produces a report. See [Playtesting](playtesting.md) for how to interpret results and iterate.

## Further Reading

- [Data Model](../design/data-model.md) — full model specs and file format details
- [Playtesting](playtesting.md) — validate your game with autonomous testing
- [Prompt Iteration](prompt-iteration.md) — tune prompts if the model struggles with your game

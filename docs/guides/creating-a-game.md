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

It will ask for your game concept, then run a multi-step pipeline: propose game structure, validate against Pydantic models, fix any issues, and write the files to `games/`.

The creator uses a **larger model** (configured via `CREATOR_*` environment variables in `.env`). See [`.env.example`](../../.env.example) for configuration. The pipeline is implemented in [`src/theact/creator/session.py`](../../src/theact/creator/session.py).

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

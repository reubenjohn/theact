# Creating a Game

You can create a game by writing YAML files by hand or by using the creator agent to generate them from a concept description.

## Game Directory Structure

Every game lives in its own directory under `games/`:

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

See `games/lost-island/` for a complete working example. See [Data Model](../architecture/data-model.md) for full model specifications.

## Writing Game Files by Hand

### game.yaml

The root manifest lists characters and chapters by ID:

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

### world.yaml

Setting, tone, and hard rules for the narrator:

```yaml
setting: >
  Two sentences describing when, where, and what's happening.
tone: >
  Narrative style guidance. Person, tense, word count per turn.
rules: >
  Hard constraints the narrator must follow.
```

### Characters (~60 words each)

One file per character in `characters/`:

```yaml
name: Alice Park
role: Short role description.
personality: >
  A few sentences. Speech patterns and coping mechanisms, not life history.
secret: One sentence the character hides.
relationships:
  bob: "What Alice thinks of Bob."
```

### Chapters

One file per chapter in `chapters/`:

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

The last chapter omits `next` — this signals game end.

## Size Discipline

Game files are injected directly into prompts for a 7B model with ~8K context. Every word costs tokens.

- **Character files**: ~60 words
- **World file**: ~6 sentences
- **Chapter beats**: short phrases, not paragraphs

Bloated game files degrade model performance. See [Data Model — Size Constraints](../architecture/data-model.md#size-constraints) for rationale.

## Using the Creator Agent

```bash
uv run python scripts/create_game.py
```

The creator agent walks you through a 7-step interactive flow:

1. **Describe your concept** — genre, setting, characters, themes
2. **Review the proposal** — approve or request revisions
3. **Generation** — the LLM produces all game YAML files
4. **Validation & auto-fix** — Pydantic validation and cross-reference checks
5. **Size warnings** — flagged if files exceed recommended limits
6. **Final review** — revise individual files or approve
7. **Write to disk** — files written to `games/<game-id>/`

### Configuration

The creator agent supports its own model configuration, since game creation works best with a larger model than the 7B gameplay model:

| Env var | Fallback | Default |
|---|---|---|
| `CREATOR_BASE_URL` | `LLM_BASE_URL` | `https://api.openai.com/v1` |
| `CREATOR_API_KEY` | `LLM_API_KEY` | (required) |
| `CREATOR_MODEL` | `LLM_MODEL` | (none) |

See [Game Creation Pipeline](../reference/game-creation-pipeline.md) for internal design details.

## Testing Your Game

Run a quick autonomous playtest to verify your game works:

```bash
uv run python scripts/playtest.py --game your-game --turns 5
```

This will play through 5 turns with an AI player and report any issues. See [Playtesting](playtesting.md) for the full playtest framework.

## See Also

- [Data Model](../architecture/data-model.md) — file format specifications and constraints
- [Playtesting](playtesting.md) — autonomous playtest framework
- [Game Creation Pipeline](../reference/game-creation-pipeline.md) — creator agent internals

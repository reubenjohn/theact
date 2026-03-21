# Data Model

All data in TheAct is YAML. Game definitions are templates that ship with the game. Save files are mutable state that evolves as the player plays. Pydantic models back every file with strict validation (`extra="forbid"`).

## Game Definition Files

A game is a directory under `games/` with this structure:

```
games/lost-island/
  game.yaml               # GameMeta: id, title, character/chapter lists
  world.yaml              # World: setting, tone, rules
  characters/
    maya.yaml              # Character: name, role, personality, secret, relationships
    joaquin.yaml
  chapters/
    01-the-crash.yaml      # Chapter: id, title, summary, beats, completion, next
    02-the-discovery.yaml
    03-the-heart.yaml
```

See [`games/lost-island/`](../../games/lost-island/) for a complete example.

### Size constraints

These files are injected directly into LLM prompts. A 7B model with ~8K context cannot afford bloat:

- **Character files:** ~60 words. Personality is a few sentences, not a backstory.
- **World file:** ~6 sentences across setting, tone, and rules.
- **Chapter beats:** Short phrases like "Player wakes on the beach, disoriented" — not paragraphs.

### Pydantic models

Each file type has a corresponding model in [`src/theact/models/`](../../src/theact/models/):

| File | Model | Module |
|------|-------|--------|
| `game.yaml` | `GameMeta` | [`models/game.py`](../../src/theact/models/game.py) |
| `world.yaml` | `World` | [`models/world.py`](../../src/theact/models/world.py) |
| `characters/*.yaml` | `Character` | [`models/character.py`](../../src/theact/models/character.py) |
| `chapters/*.yaml` | `Chapter` | [`models/chapter.py`](../../src/theact/models/chapter.py) |

## Save Files

When a player starts a game, a save directory is created under `saves/` with copies of the game definition plus mutable state files:

```
saves/lost-island-001/
  game.yaml                # Copied from template
  world.yaml               # Copied from template
  characters/              # Copied from template
  chapters/                # Copied from template
  state.yaml               # GameState: turn counter, current chapter, beats hit, flags
  conversation.yaml        # List of ConversationEntry: the full dialogue log
  memories/
    maya.yaml              # CharacterMemory: summary + key facts for Maya
    joaquin.yaml           # CharacterMemory: summary + key facts for Joaquin
  summaries.yaml           # List of ChapterSummary: completed chapter recaps
```

### Mutable state models

| File | Model | Module |
|------|-------|--------|
| `state.yaml` | `GameState` | [`models/state.py`](../../src/theact/models/state.py) |
| `conversation.yaml` | `ConversationEntry` (list) | [`models/conversation.py`](../../src/theact/models/conversation.py) |
| `memories/*.yaml` | `CharacterMemory` | [`models/memory.py`](../../src/theact/models/memory.py) |
| `summaries.yaml` | `ChapterSummary` (list) | [`models/chapter.py`](../../src/theact/models/chapter.py) |

The I/O layer for reading and writing these files lives in [`src/theact/io/save_manager.py`](../../src/theact/io/save_manager.py). YAML serialization helpers are in [`src/theact/io/yaml_io.py`](../../src/theact/io/yaml_io.py).

## Git Versioning

Each save directory is a git repository. One commit per turn. This gives:

- **Unlimited undo** — `git reset --hard HEAD~N` reverts N turns
- **Full history** — `git log` shows every turn
- **Cheap storage** — git compresses YAML diffs efficiently

The git layer lives in [`src/theact/versioning/git_save.py`](../../src/theact/versioning/git_save.py).

## LoadedGame

At runtime, the engine works with `LoadedGame` — an in-memory aggregate that combines the game template and save state into a single object. It is never persisted directly; it's reconstructed on load.

See [`LoadedGame`](../../src/theact/models/game.py) for the full definition. It holds: `GameMeta`, `World`, all `Character`s, all `Chapter`s, `GameState`, the conversation log, character memories, and chapter summaries.

## Further Reading

- [Creating a Game](../guides/creating-a-game.md) — how to write game files
- [Memory & Summarization](memory-and-summarization.md) — how memories and summaries evolve during play
- [Architecture](architecture.md) — how data flows through the system

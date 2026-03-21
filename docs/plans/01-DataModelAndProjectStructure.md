# Phase 01: Data Model, Project Structure, Save Format, and Versioning

## 1. Overview

This phase lays the foundation for TheAct by defining everything that exists before a single LLM call is made: how the project code is organized, how games are defined, how saves are structured, how data moves between YAML on disk and Pydantic models in memory, and how git-based versioning gives players unlimited undo.

After this phase is complete, we can:
- Define a game entirely in YAML files (world, characters, chapters)
- Load those files into validated Pydantic models
- Create a new save from a game definition (copy + git init)
- Append to the conversation log
- Commit after every turn, undo to any previous turn, inspect history
- Run tests proving all of the above works

No LLM calls, no CLI, no agents. Just the data layer and the versioning layer.

---

## 2. Directory Structure

### 2.1 Project Source Layout

```
theact/
  .env                      # LLM_API_KEY, model config
  .env.example
  .gitignore
  pyproject.toml
  main.py                   # Entry point (Phase 04)
  src/
    theact/
      __init__.py
      models/
        __init__.py
        world.py            # World model
        character.py        # Character model
        chapter.py          # Chapter model
        state.py            # GameState model
        memory.py           # CharacterMemory model
        conversation.py     # ConversationEntry model
        game.py             # Game (aggregate root — loads everything)
      io/
        __init__.py
        yaml_io.py          # Load/dump YAML, model serialization
        save_manager.py     # Create save, load save, list saves
      versioning/
        __init__.py
        git_save.py         # Git init, commit, undo, history
      engine/               # Phase 03
      agents/               # Phase 03
      llm/                  # Phase 02
      cli/                  # Phase 04
  games/
    lost-island/            # Example game definition
      game.yaml
      world.yaml
      characters/
        maya.yaml
        joaquin.yaml
      chapters/
        01-the-crash.yaml
        02-survival.yaml
  saves/                    # Created at runtime, gitignored from project repo
    lost-island-001/        # Each save is its own git repo
      ...
  tests/
    __init__.py
    test_models.py
    test_yaml_io.py
    test_save_manager.py
    test_git_save.py
    conftest.py             # Fixtures: sample game data, tmp dirs
```

### 2.2 Game Definition (Template)

A game definition is a read-only template. It lives under `games/<game-id>/` and contains everything needed to start a new playthrough.

```
games/lost-island/
  game.yaml                 # Metadata: title, description, character list, chapter order
  world.yaml                # Setting, tone, rules — one short paragraph each
  characters/
    maya.yaml
    joaquin.yaml
  chapters/
    01-the-crash.yaml
    02-survival.yaml
    03-the-discovery.yaml
```

### 2.3 Save Directory (Runtime)

A save is a copy of the game definition plus runtime state. It is a git repository. New files are added as play progresses; game definition files are never modified.

```
saves/lost-island-001/
  .git/                     # Git repo — one commit per turn
  game.yaml                 # Copied from game definition (immutable)
  world.yaml                # Copied from game definition (immutable)
  characters/
    maya.yaml               # Copied from game definition (immutable)
    joaquin.yaml            # Copied from game definition (immutable)
  chapters/
    01-the-crash.yaml       # Copied from game definition (immutable)
    02-survival.yaml        # Copied from game definition (immutable)
  state.yaml                # Created at save init — mutable, updated each turn
  conversation.yaml         # Created at save init — append-only, one entry per message
  memory/
    maya.yaml               # Created when Maya first acts — rolling memory per character
    joaquin.yaml            # Created when Joaquin first acts
  summaries.yaml            # Chapter summaries — appended as chapters complete
```

---

## 3. Data Models

All models use Pydantic v2 (`BaseModel`). Field descriptions serve as documentation. Models define `model_config = ConfigDict(extra="forbid")` to catch typos in YAML.

### 3.1 Game Metadata

```python
# src/theact/models/game.py

from pydantic import BaseModel, ConfigDict

class GameMeta(BaseModel):
    """Top-level game definition metadata. Loaded from game.yaml."""
    model_config = ConfigDict(extra="forbid")

    id: str                    # URL-safe slug, e.g. "lost-island"
    title: str                 # Display name, e.g. "The Lost Island"
    description: str           # One-sentence pitch
    characters: list[str]      # Character file stems, e.g. ["maya", "joaquin"]
    chapters: list[str]        # Chapter file stems in order, e.g. ["01-the-crash", ...]
```

### 3.2 World

```python
# src/theact/models/world.py

from pydantic import BaseModel, ConfigDict

class World(BaseModel):
    """World definition. Loaded from world.yaml. Keep each field to 1-3 sentences."""
    model_config = ConfigDict(extra="forbid")

    setting: str               # Where and when. ~2 sentences.
    tone: str                  # Narrative voice and style. ~2 sentences.
    rules: str                 # Key constraints the narrator must follow. ~2 sentences.
```

### 3.3 Character

```python
# src/theact/models/character.py

from pydantic import BaseModel, ConfigDict

class Character(BaseModel):
    """Character definition. Loaded from characters/<name>.yaml. ~60 words total."""
    model_config = ConfigDict(extra="forbid")

    name: str                  # Display name
    role: str                  # One-line role in the story
    personality: str           # Core traits, speech patterns. 2-3 sentences.
    secret: str                # Hidden motivation or knowledge. 1 sentence.
    relationships: dict[str, str]  # name -> one-line relationship stance
```

### 3.4 Chapter

```python
# src/theact/models/chapter.py

from pydantic import BaseModel, ConfigDict

class Chapter(BaseModel):
    """Chapter definition. Loaded from chapters/<id>.yaml."""
    model_config = ConfigDict(extra="forbid")

    id: str                    # e.g. "01-the-crash"
    title: str                 # e.g. "The Crash"
    summary: str               # What this chapter is about. 2-3 sentences.
    beats: list[str]           # Key events that should happen. Short phrases.
    completion: str            # What must be true for chapter to end. 1 sentence.
    characters: list[str]      # Which characters are active in this chapter.
    next: str | None = None    # Next chapter id, or None if final chapter.
```

### 3.5 Game State

```python
# src/theact/models/state.py

from pydantic import BaseModel, ConfigDict

class GameState(BaseModel):
    """Mutable game state. Written to state.yaml. Updated every turn."""
    model_config = ConfigDict(extra="forbid")

    player_name: str
    current_chapter: str       # Chapter id
    turn: int                  # Monotonically increasing turn counter
    beats_hit: list[str]       # Beat phrases from current chapter that have occurred
                               # Reset to [] when chapter advances.
    flags: dict[str, str]      # Arbitrary key-value pairs set by agents
    chapter_history: list[str] # List of completed chapter ids
    rolling_summary: str = ""  # Incremental summary of expired conversation turns.
                               # Updated when old turns are trimmed from context window.
                               # Used by context assembly (Phase 03) to give agents
                               # a compressed view of earlier events.
```

### 3.6 Conversation Entry

```python
# src/theact/models/conversation.py

from pydantic import BaseModel, ConfigDict
from typing import Literal

class ConversationEntry(BaseModel):
    """Single message in the conversation log. Appended to conversation.yaml."""
    model_config = ConfigDict(extra="forbid")

    turn: int
    role: Literal["narrator", "character", "player"]
    character: str | None = None   # Set when role is "character"
    content: str
```

### 3.7 Character Memory

```python
# src/theact/models/memory.py

from pydantic import BaseModel, ConfigDict

class CharacterMemory(BaseModel):
    """Per-character rolling memory. Written to memory/<name>.yaml."""
    model_config = ConfigDict(extra="forbid")

    character: str             # Character name
    summary: str               # Rolling summary of what this character knows/feels.
                               # Updated each turn by merging new info into existing summary.
                               # ~3-5 sentences. Never grows unbounded.
    key_facts: list[str]       # Important discrete facts. Max ~10, oldest pruned.
```

### 3.8 Chapter Summary

```python
# src/theact/models/chapter.py  (same file, additional model)

class ChapterSummary(BaseModel):
    """Summary of a completed chapter. Appended to summaries.yaml."""
    model_config = ConfigDict(extra="forbid")

    chapter_id: str
    title: str
    summary: str               # 2-3 sentence summary of what happened.
```

### 3.9 Loaded Game (Aggregate)

```python
# src/theact/models/game.py  (same file, additional model)

class LoadedGame(BaseModel):
    """A fully loaded game with all data resolved. Not persisted — constructed in memory."""
    model_config = ConfigDict(extra="forbid")

    meta: GameMeta
    world: World
    characters: dict[str, Character]       # keyed by character file stem
    chapters: dict[str, Chapter]           # keyed by chapter id
    state: GameState
    conversation: list[ConversationEntry]
    memories: dict[str, CharacterMemory]   # keyed by character name
    chapter_summaries: list[ChapterSummary]
    save_path: Path                        # Absolute path to save directory

    # Note: characters and memories dicts are keyed by file stem (e.g. "maya"),
    # while Character.name and CharacterMemory.character store display names
    # (e.g. "Maya Chen"). The save_manager must handle this mapping.                        # Absolute path to save directory
```

---

## 4. File Formats

Every file uses YAML. Examples below show the target size — these are what a 7B model will actually see in its prompt context. They must be small.

### 4.1 game.yaml

```yaml
id: lost-island
title: The Lost Island
description: Survivors of a plane crash on an uncharted island discover something ancient beneath the jungle.
characters:
  - maya
  - joaquin
chapters:
  - 01-the-crash
  - 02-survival
  - 03-the-discovery
```

### 4.2 world.yaml

```yaml
setting: >
  Uncharted volcanic island, South Pacific, 2024. Survivors of Flight NZ-417
  crashed into the northern reef. No GPS, no radio, no rescue coming.

tone: >
  Second person, present tense. Sensory-first narration. Slow-burn tension
  through small wrong details. 150-300 words per turn.

rules: >
  The supernatural is always ambiguous — every anomaly has a mundane explanation.
  NPCs remember everything. Never break the second-person frame.
```

### 4.3 characters/maya.yaml (~60 words)

```yaml
name: Maya Chen
role: Fellow crash survivor, pragmatic engineer, player's primary ally.
personality: >
  Direct, sharp, dry humor. Speaks in short declarative sentences.
  Competence is her coping mechanism — idle hands make her anxious.
  Slow to trust, fiercely loyal once earned.
secret: Racing home to her estranged mother who has cancer.
relationships:
  joaquin: "Respects his calm but distrusts his evasiveness."
```

### 4.4 characters/joaquin.yaml (~60 words)

```yaml
name: Father Joaquin Reyes
role: Mysterious priest who has been to this island before.
personality: >
  Calm, cryptic, speaks in parables and questions. Genuinely kind but
  evasive about specifics. Gets quieter when most serious.
  Never raises his voice.
secret: Visited this island 40 years ago. His companions entered the caves and never returned.
relationships:
  maya: "Admires her strength but worries about her refusal to accept mystery."
```

### 4.5 chapters/01-the-crash.yaml

```yaml
id: 01-the-crash
title: The Crash
summary: >
  Player wakes alone on the beach amid wreckage. They explore, find evidence
  of death, and discover Maya — the first sign they are not alone.
beats:
  - Player wakes on the beach, disoriented and injured
  - Explores crash debris and finds supplies
  - Discovers a body — death is real here
  - Finds Maya working alone beyond the headland
  - Together they establish a basic camp
  - First night — strange sounds from the jungle
completion: Player and Maya have established camp and survived the first night.
characters:
  - maya
next: 02-survival
```

### 4.6 state.yaml (created at save init)

```yaml
player_name: ""
current_chapter: 01-the-crash
turn: 0
beats_hit: []
flags: {}
chapter_history: []
rolling_summary: ""
```

### 4.7 conversation.yaml (created at save init, append-only)

```yaml
- turn: 1
  role: narrator
  content: >
    You open your eyes to white light and the taste of salt. Sand grinds
    against your cheek. Your left arm is pinned under something heavy.
    Somewhere beyond the ringing in your ears, waves break against metal.

- turn: 1
  role: player
  content: I try to free my arm and look around.

- turn: 1
  role: narrator
  content: >
    You wrench your arm free — a duffel bag, half-buried. Sitting up sends
    the world tilting. Beach. Wreckage. No engines. No voices. Just the reef
    and the wind and the cry of a single bird circling overhead.

- turn: 2
  role: character
  character: Maya Chen
  content: >
    She looks up sharply, a strip of seatbelt dangling from one hand. Her
    eyes sweep you head to toe — assessing, not greeting. "You're bleeding.
    How many others did you see?"
```

### 4.8 memory/maya.yaml (created during play)

```yaml
character: Maya Chen
summary: >
  Met the player on the beach after the crash. They seem resourceful —
  found supplies before finding her. Worked together to build camp.
  Heard the drums that first night but neither of us spoke about it.
key_facts:
  - Player found a lighter and first-aid kit
  - Camp is in the fuselage section on north beach
  - Strange drumming sound from jungle at nightfall
```

### 4.9 summaries.yaml (appended as chapters complete)

```yaml
- chapter_id: 01-the-crash
  title: The Crash
  summary: >
    Player woke amid the wreckage of Flight NZ-417. Found Maya beyond the
    headland. Together they built a camp in the fuselage. That first night,
    they both heard drums from the jungle but said nothing.
```

---

## 5. YAML Serialization

### 5.1 yaml_io.py Interface

```python
# src/theact/io/yaml_io.py

from pathlib import Path
from typing import TypeVar, Type
from pydantic import BaseModel
import yaml

T = TypeVar("T", bound=BaseModel)

def load_yaml(path: Path, model: Type[T]) -> T:
    """Load a YAML file and validate it against a Pydantic model."""
    with open(path) as f:
        data = yaml.safe_load(f)
    return model.model_validate(data)

def load_yaml_list(path: Path, model: Type[T]) -> list[T]:
    """Load a YAML file containing a list and validate each item."""
    with open(path) as f:
        data = yaml.safe_load(f)
    if data is None:
        return []
    return [model.model_validate(item) for item in data]

def dump_yaml(path: Path, model: BaseModel) -> None:
    """Serialize a Pydantic model to YAML and write to file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        yaml.dump(
            model.model_dump(exclude_none=True),
            f,
            default_flow_style=False,
            allow_unicode=True,
            sort_keys=False,
        )

def dump_yaml_list(path: Path, models: list[BaseModel]) -> None:
    """Serialize a list of Pydantic models to YAML and write to file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    data = [m.model_dump(exclude_none=True) for m in models]
    with open(path, "w") as f:
        yaml.dump(
            data,
            f,
            default_flow_style=False,
            allow_unicode=True,
            sort_keys=False,
        )

def append_yaml_entry(path: Path, model: BaseModel) -> None:
    """Append a single model as a YAML list entry to an existing file.

    If the file doesn't exist or is empty, creates it with a single-item list.
    If the file exists, loads the list, appends, and rewrites.

    Note: For conversation.yaml, this means a full rewrite on each append.
    At 500 turns with ~4 messages per turn, that's ~2000 entries — still fast
    since each entry is a few lines of text. If this ever becomes a bottleneck,
    we can switch to streaming YAML output, but premature optimization is
    not warranted here.
    """
    if path.exists():
        with open(path) as f:
            data = yaml.safe_load(f) or []
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        data = []
    data.append(model.model_dump(exclude_none=True))
    with open(path, "w") as f:
        yaml.dump(
            data,
            f,
            default_flow_style=False,
            allow_unicode=True,
            sort_keys=False,
        )
```

---

## 6. Save Manager

### 6.1 save_manager.py Interface

```python
# src/theact/io/save_manager.py

from pathlib import Path
from theact.models.game import GameMeta, LoadedGame
from theact.models.state import GameState

# Resolved relative to project root. Callers (including tests) can override
# by passing explicit paths to create_save/load_save.
GAMES_DIR = Path("games")
SAVES_DIR = Path("saves")

def list_games() -> list[GameMeta]:
    """List all available game definitions."""
    ...

def list_saves() -> list[dict]:
    """List all existing saves with basic info.

    Returns list of dicts with keys: id, game_title, turn, last_modified.
    """
    ...

def create_save(game_id: str, save_id: str, player_name: str) -> Path:
    """Create a new save from a game definition.

    1. Copy game definition files to saves/<save_id>/
    2. Create initial state.yaml with player_name and turn=0
    3. Create empty conversation.yaml
    4. Create empty summaries.yaml
    5. Create memory/ directory
    6. Initialize git repo and make initial commit

    Returns the save directory path.
    """
    ...

def load_save(save_id: str) -> LoadedGame:
    """Load a complete save into memory.

    Reads all YAML files, validates against Pydantic models,
    returns a LoadedGame aggregate.
    """
    ...

def save_state(save_path: Path, state: GameState) -> None:
    """Write updated game state to state.yaml."""
    ...

def append_conversation(save_path: Path, entry: "ConversationEntry") -> None:
    """Append a message to conversation.yaml."""
    ...

def save_memory(save_path: Path, memory: "CharacterMemory") -> None:
    """Write updated character memory to memory/<name>.yaml."""
    ...

def save_summaries(save_path: Path, summaries: list["ChapterSummary"]) -> None:
    """Write the full list of chapter summaries to summaries.yaml (full rewrite).

    Caller must load existing summaries, append, and pass the complete list.
    """
    ...
```

---

## 7. Save Versioning (Git)

### 7.1 Design

Each save directory is an independent git repository. One commit is created after each complete turn (narrator response + all character responses + player input + memory updates + state update). This means:

- Every file change within a turn is captured atomically in one commit
- Undo = `git reset --hard HEAD~1` (discard last commit)
- Undo N turns = `git reset --hard HEAD~N`
- History = `git log --oneline` gives a turn-by-turn timeline
- Hundreds of turns are efficient because git stores diffs, not full copies
- The conversation.yaml grows linearly but git only stores the appended portion as a diff

### 7.2 git_save.py Interface

```python
# src/theact/versioning/git_save.py

from pathlib import Path
from dataclasses import dataclass
from git import Repo  # gitpython

@dataclass
class TurnInfo:
    """Summary of a single turn from git history.
    Uses dataclass (not BaseModel) since this is a transient data carrier,
    never serialized to YAML.
    """
    turn: int
    commit_hash: str
    message: str
    timestamp: str

def init_repo(save_path: Path) -> Repo:
    """Initialize a git repo in the save directory and make the initial commit.

    The initial commit contains the game definition files and empty state/conversation.
    Commit message: 'New game: <game title>'
    """
    ...

def commit_turn(save_path: Path, turn: int, summary: str) -> str:
    """Stage all changes and commit.

    Commit message format: 'Turn <N>: <one-line summary>'
    The summary is a brief description derived from the narrator's output.

    Returns the commit hash.
    """
    ...

def undo(save_path: Path, steps: int = 1) -> int:
    """Undo the last N turns by resetting to HEAD~N.

    Returns the turn number we've rewound to.
    Raises ValueError if steps exceeds available history (excluding initial commit).
    """
    ...

def get_history(save_path: Path) -> list[TurnInfo]:
    """Get the full turn history from git log.

    Returns most recent first. Excludes the initial 'New game' commit.
    Parses turn number from commit message.
    """
    ...

def get_turn_count(save_path: Path) -> int:
    """Get the number of completed turns (number of turn commits)."""
    ...
```

### 7.3 Commit Strategy

```
Commit 0: "New game: The Lost Island"        ← initial state, all game files
Commit 1: "Turn 1: Player wakes on beach"    ← conversation + state changes
Commit 2: "Turn 2: Found Maya"               ← conversation + state + memory
Commit 3: "Turn 3: Built camp together"       ← conversation + state + memory
...
```

Each turn commit includes all files that changed during that turn:
- `conversation.yaml` (always — new messages appended)
- `state.yaml` (always — turn counter incremented, possibly beats_hit/flags updated)
- `memory/<name>.yaml` (if a character's memory was updated)
- `summaries.yaml` (if a chapter was completed this turn)

### 7.4 Undo Semantics

Undo is destructive — it discards commits. This is intentional. The player is rewinding time; the future that was discarded should not persist. If we ever want a "redo" feature, we can stash the branch ref before resetting, but that is not in scope for Phase 01.

```
Before undo:    A --- B --- C --- D (HEAD)
After undo(2):  A --- B (HEAD)
```

The player is now back at the state after turn B. Their next action creates a new turn C' that diverges from the original timeline.

---

## 8. Implementation Steps

Build in this order. Each step should produce working, tested code before moving to the next.

### Step 1: Project scaffolding
- Create the `src/theact/` package structure with `__init__.py` files
- Create `models/`, `io/`, `versioning/` sub-packages
- Create `tests/` directory with `conftest.py`
- Add `saves/` and `playtests/` to `.gitignore`
- Add dependencies to `pyproject.toml`
- Verify `uv sync` works

### Step 2: Pydantic models
- Implement all models from Section 3 in their respective files
- Write `tests/test_models.py`:
  - Test that each model validates correct data
  - Test that each model rejects extra fields (`extra="forbid"`)
  - Test optional fields default correctly
  - Test that example YAML data from Section 4 round-trips through models

### Step 3: YAML I/O
- Implement `yaml_io.py` with all functions from Section 5
- Write `tests/test_yaml_io.py`:
  - Test `load_yaml` / `dump_yaml` round-trip for each model
  - Test `load_yaml_list` / `dump_yaml_list` for list-based files
  - Test `append_yaml_entry` creates file if missing
  - Test `append_yaml_entry` appends to existing file
  - Test error handling: missing file, invalid YAML, validation failure

### Step 4: Example game definition
- Create `games/lost-island/` with all YAML files from Section 4
- Manually verify they load through the YAML I/O layer
- This serves as both test fixture and the Phase 05 starting point

### Step 5: Save manager
- Implement `save_manager.py` with all functions from Section 6
- Write `tests/test_save_manager.py`:
  - Test `create_save` produces correct directory structure
  - Test `create_save` copies all game files
  - Test `create_save` creates valid initial state
  - Test `load_save` returns a fully populated `LoadedGame`
  - Test `list_saves` finds existing saves
  - Test `save_state`, `append_conversation`, `save_memory` write correctly
  - Test round-trip: create_save -> modify -> load_save sees modifications

### Step 6: Git versioning
- Implement `git_save.py` with all functions from Section 7
- Write `tests/test_git_save.py`:
  - Test `init_repo` creates a valid git repo with initial commit
  - Test `commit_turn` creates commits with correct messages
  - Test `undo` rewinds state correctly (verify file contents revert)
  - Test `undo` raises on over-rewinding
  - Test `get_history` returns correct turn list
  - Test multi-turn sequence: 10 turns, undo 3, verify state at turn 7
  - All tests use `tmp_path` fixture to avoid polluting the real filesystem

### Step 7: Integration
- Wire `save_manager.create_save` to call `git_save.init_repo`
- Ensure `save_manager.load_save` works on git-versioned saves
- Write integration test: create game -> make 5 turns of fake data -> undo 2 -> verify state
- Verify `.gitignore` in the project root excludes `saves/` from the project's own git repo

---

## 9. Verification

Phase 01 is complete when all of the following pass:

1. `uv run pytest tests/` — all tests green
2. Manual check: `games/lost-island/` contains valid YAML that loads without errors
3. Manual check: Creating a save from lost-island produces correct directory structure
4. Manual check: After 5 simulated turns, `git log` in the save dir shows 6 commits (1 initial + 5 turns)
5. Manual check: Undo 2 turns, verify conversation.yaml has only 3 turns of content
6. Manual check: File sizes — world.yaml < 500 bytes, each character YAML < 400 bytes, each chapter YAML < 500 bytes

### 9.1 Live Testing & Regression Capture

After unit and manual tests pass, perform the following live validation cycle. The goal is to discover edge cases in real usage and lock them down with automated tests so they never regress.

**Step 1 — Exploratory testing:**
- Create a save from Lost Island, manually edit game files (introduce typos, missing fields, extra fields), and verify Pydantic rejects them with clear errors.
- Create a save, simulate 10 turns of fake conversation data (use a script), then undo 5, undo 3 more, verify state is correct after each undo.
- Test with unusually long player input (500+ words) in a conversation entry. Verify YAML round-trips correctly (no truncation, no encoding issues).
- Test with special characters in player input (quotes, colons, newlines, unicode) — these can break YAML serialization.

**Step 2 — Fix and capture:**
- For every issue discovered, fix the code, then write a regression test in `tests/` that reproduces the exact failure scenario.
- Example: if YAML serialization breaks on a colon in player input, write `test_conversation_entry_with_colon()` that appends an entry containing `"Where are we: lost?"` and verifies it round-trips.

**Step 3 — Verify regression suite:**
- Run `uv run pytest tests/ -v` and confirm all new regression tests pass alongside existing tests.

---

## 10. Dependencies

Add to `pyproject.toml`:

```toml
dependencies = [
    "openai>=2.29.0",
    "python-dotenv>=1.2.2",
    "pydantic>=2.10.0",
    "pyyaml>=6.0",
    "gitpython>=3.1.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
]
```

Summary of new packages:
- **pydantic** — Data validation and model definitions
- **pyyaml** — YAML parsing and serialization
- **gitpython** — Git operations for save versioning
- **pytest** — Test runner (dev dependency)

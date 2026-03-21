"""Save management: create, load, list, and update saves."""

import os
import shutil
from pathlib import Path

from theact.io.yaml_io import (
    append_yaml_entry,
    dump_yaml,
    dump_yaml_list,
    load_yaml,
    load_yaml_list,
)
from theact.models.chapter import Chapter, ChapterSummary
from theact.models.character import Character
from theact.models.conversation import ConversationEntry
from theact.models.game import GameMeta, LoadedGame
from theact.models.memory import CharacterMemory
from theact.models.state import GameState
from theact.models.world import World
from theact.versioning.git_save import init_repo

# When THEACT_DATA_DIR is set, games/ and saves/ live under that directory.
# Otherwise they resolve relative to the working directory (original behavior).
_DATA_DIR = os.environ.get("THEACT_DATA_DIR")
GAMES_DIR = Path(_DATA_DIR) / "games" if _DATA_DIR else Path("games")
SAVES_DIR = Path(_DATA_DIR) / "saves" if _DATA_DIR else Path("saves")


def list_games(games_dir: Path | None = None) -> list[GameMeta]:
    """List all available game definitions."""
    gdir = games_dir or GAMES_DIR
    if not gdir.exists():
        return []
    result = []
    for game_path in sorted(gdir.iterdir()):
        game_yaml = game_path / "game.yaml"
        if game_yaml.exists():
            meta = load_yaml(game_yaml, GameMeta)
            result.append(meta)
    return result


def list_saves(saves_dir: Path | None = None) -> list[dict]:
    """List all existing saves with basic info.

    Returns list of dicts with keys: id, game_title, turn, last_modified.
    """
    sdir = saves_dir or SAVES_DIR
    if not sdir.exists():
        return []
    result = []
    for save_path in sorted(sdir.iterdir()):
        if not save_path.is_dir():
            continue
        state_yaml = save_path / "state.yaml"
        game_yaml = save_path / "game.yaml"
        if not state_yaml.exists() or not game_yaml.exists():
            continue
        state = load_yaml(state_yaml, GameState)
        meta = load_yaml(game_yaml, GameMeta)
        result.append(
            {
                "id": save_path.name,
                "game_title": meta.title,
                "turn": state.turn,
                "last_modified": state_yaml.stat().st_mtime,
            }
        )
    return result


def create_save(
    game_id: str,
    save_id: str,
    player_name: str,
    games_dir: Path | None = None,
    saves_dir: Path | None = None,
) -> Path:
    """Create a new save from a game definition.

    1. Copy game definition files to saves/<save_id>/
    2. Create initial state.yaml with player_name and turn=0
    3. Create empty conversation.yaml
    4. Create empty summaries.yaml
    5. Create memory/ directory
    6. Initialize git repo and make initial commit

    Returns the save directory path.
    """
    gdir = games_dir or GAMES_DIR
    sdir = saves_dir or SAVES_DIR

    game_path = gdir / game_id
    if not game_path.exists():
        raise FileNotFoundError(f"Game definition not found: {game_path}")

    save_path = sdir / save_id
    if save_path.exists():
        raise FileExistsError(f"Save already exists: {save_path}")

    # Load game meta to get first chapter and title
    meta = load_yaml(game_path / "game.yaml", GameMeta)

    # Copy game definition files
    save_path.mkdir(parents=True)

    # Copy game.yaml and world.yaml
    shutil.copy2(game_path / "game.yaml", save_path / "game.yaml")
    shutil.copy2(game_path / "world.yaml", save_path / "world.yaml")

    # Copy characters
    chars_dir = save_path / "characters"
    chars_dir.mkdir()
    for char_stem in meta.characters:
        src = game_path / "characters" / f"{char_stem}.yaml"
        shutil.copy2(src, chars_dir / f"{char_stem}.yaml")

    # Copy chapters
    chaps_dir = save_path / "chapters"
    chaps_dir.mkdir()
    for chap_stem in meta.chapters:
        src = game_path / "chapters" / f"{chap_stem}.yaml"
        shutil.copy2(src, chaps_dir / f"{chap_stem}.yaml")

    # Create initial state.yaml
    first_chapter = meta.chapters[0] if meta.chapters else ""
    initial_state = GameState(
        player_name=player_name,
        current_chapter=first_chapter,
        turn=0,
        beats_hit=[],
        flags={},
        chapter_history=[],
        rolling_summary="",
    )
    dump_yaml(save_path / "state.yaml", initial_state)

    # Create empty conversation.yaml
    dump_yaml_list(save_path / "conversation.yaml", [])

    # Create empty summaries.yaml
    dump_yaml_list(save_path / "summaries.yaml", [])

    # Create memory/ directory
    (save_path / "memory").mkdir()

    # Initialize git repo and make initial commit
    init_repo(save_path, meta.title)

    return save_path


def load_save(save_id: str, saves_dir: Path | None = None) -> LoadedGame:
    """Load a complete save into memory.

    Reads all YAML files, validates against Pydantic models,
    returns a LoadedGame aggregate.
    """
    sdir = saves_dir or SAVES_DIR
    save_path = sdir / save_id

    if not save_path.exists():
        raise FileNotFoundError(f"Save not found: {save_path}")

    # Load metadata and world
    meta = load_yaml(save_path / "game.yaml", GameMeta)
    world = load_yaml(save_path / "world.yaml", World)

    # Load characters
    characters: dict[str, Character] = {}
    for char_stem in meta.characters:
        char = load_yaml(save_path / "characters" / f"{char_stem}.yaml", Character)
        characters[char_stem] = char

    # Load chapters
    chapters: dict[str, Chapter] = {}
    for chap_stem in meta.chapters:
        chap = load_yaml(save_path / "chapters" / f"{chap_stem}.yaml", Chapter)
        chapters[chap.id] = chap

    # Load state
    state = load_yaml(save_path / "state.yaml", GameState)

    # Load conversation
    conversation = load_yaml_list(save_path / "conversation.yaml", ConversationEntry)

    # Load memories (may not exist yet for all characters)
    memories: dict[str, CharacterMemory] = {}
    memory_dir = save_path / "memory"
    if memory_dir.exists():
        for char_stem in meta.characters:
            mem_path = memory_dir / f"{char_stem}.yaml"
            if mem_path.exists():
                mem = load_yaml(mem_path, CharacterMemory)
                memories[char_stem] = mem

    # Load chapter summaries
    chapter_summaries = load_yaml_list(save_path / "summaries.yaml", ChapterSummary)

    return LoadedGame(
        meta=meta,
        world=world,
        characters=characters,
        chapters=chapters,
        state=state,
        conversation=conversation,
        memories=memories,
        chapter_summaries=chapter_summaries,
        save_path=save_path.resolve(),
    )


def save_state(save_path: Path, state: GameState) -> None:
    """Write updated game state to state.yaml."""
    dump_yaml(save_path / "state.yaml", state)


def append_conversation(save_path: Path, entry: ConversationEntry) -> None:
    """Append a message to conversation.yaml."""
    append_yaml_entry(save_path / "conversation.yaml", entry)


def save_memory(save_path: Path, memory: CharacterMemory) -> None:
    """Write updated character memory to memory/<name>.yaml.

    The filename is derived from the character file stem. Callers must provide
    a character_stem parameter or we derive it from the character name.
    For simplicity, we use the character name lowered and split on first word.
    """
    # Find the right filename by scanning existing characters
    # For simplicity, accept a character_stem kwarg or derive from name
    mem_dir = save_path / "memory"
    mem_dir.mkdir(parents=True, exist_ok=True)

    # Determine filename: check if any existing memory file matches this character
    # If not, use a sanitized version of the character name
    stem = _character_name_to_stem(save_path, memory.character)
    dump_yaml(mem_dir / f"{stem}.yaml", memory)


def _character_name_to_stem(save_path: Path, character_name: str) -> str:
    """Map a character display name to its file stem.

    Looks up game.yaml characters and matches by loading each character file.
    Falls back to the first word of the name lowered.
    """
    game_yaml = save_path / "game.yaml"
    if game_yaml.exists():
        meta = load_yaml(game_yaml, GameMeta)
        for char_stem in meta.characters:
            char_path = save_path / "characters" / f"{char_stem}.yaml"
            if char_path.exists():
                char = load_yaml(char_path, Character)
                if char.name == character_name:
                    return char_stem
    # Fallback: first word of name, lowered
    return character_name.split()[0].lower()


def save_summaries(save_path: Path, summaries: list[ChapterSummary]) -> None:
    """Write the full list of chapter summaries to summaries.yaml (full rewrite)."""
    dump_yaml_list(save_path / "summaries.yaml", summaries)

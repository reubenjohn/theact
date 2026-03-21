"""Write validated game files to disk."""

from __future__ import annotations

from pathlib import Path

from theact.creator.validator import ValidationResult
from theact.io.save_manager import GAMES_DIR
from theact.io.yaml_io import dump_yaml


def write_game_files(
    game_id: str,
    result: ValidationResult,
    overwrite: bool = False,
    games_dir: Path | None = None,
) -> Path:
    """Write all validated game files to games/<game_id>/.

    Args:
        game_id: The game's URL-safe slug.
        result: A valid ValidationResult with all models populated.
        overwrite: If True, overwrite an existing game directory.
                   If False and the directory exists, raise FileExistsError.
        games_dir: Override the default games directory (for testing).

    Returns:
        Path to the created game directory.

    Raises:
        FileExistsError: If the game directory already exists and
                         overwrite is False.
    """
    base = games_dir or GAMES_DIR
    game_dir = base / game_id
    if game_dir.exists() and not overwrite:
        raise FileExistsError(
            f"Game directory already exists: {game_dir}. "
            "Pass overwrite=True to replace it."
        )
    game_dir.mkdir(parents=True, exist_ok=True)

    # game.yaml
    dump_yaml(game_dir / "game.yaml", result.game)

    # world.yaml
    dump_yaml(game_dir / "world.yaml", result.world)

    # characters/
    char_dir = game_dir / "characters"
    char_dir.mkdir(exist_ok=True)
    for stem, character in result.characters.items():
        dump_yaml(char_dir / f"{stem}.yaml", character)

    # chapters/
    chap_dir = game_dir / "chapters"
    chap_dir.mkdir(exist_ok=True)
    for cid, chapter in result.chapters.items():
        dump_yaml(chap_dir / f"{cid}.yaml", chapter)

    return game_dir

"""Validation of generated game files against Pydantic models."""

from __future__ import annotations

from dataclasses import dataclass, field

from theact.models.chapter import Chapter
from theact.models.character import Character
from theact.models.game import GameMeta
from theact.models.world import World


@dataclass
class ValidationError:
    """A single validation error."""

    file: str  # e.g. "characters/maya.yaml"
    field: str  # e.g. "relationships"
    message: str  # human-readable error description


@dataclass
class ValidationResult:
    """Result of validating all generated game files."""

    valid: bool
    errors: list[ValidationError] = field(default_factory=list)
    game: GameMeta | None = None
    world: World | None = None
    characters: dict[str, Character] = field(default_factory=dict)
    chapters: dict[str, Chapter] = field(default_factory=dict)


def validate_game_data(data: dict) -> ValidationResult:
    """Validate all game data against Pydantic models.

    Args:
        data: dict with keys "game", "world", "characters", "chapters"
              where "characters" and "chapters" are dicts keyed by stem/id.

    Returns:
        ValidationResult with all errors collected (not raised).
    """
    errors: list[ValidationError] = []
    game = None
    world = None
    characters: dict[str, Character] = {}
    chapters: dict[str, Chapter] = {}

    # 1. Validate game.yaml
    try:
        game = GameMeta.model_validate(data.get("game", {}))
    except Exception as e:
        errors.append(ValidationError("game.yaml", "", str(e)))

    # 2. Validate world.yaml
    try:
        world = World.model_validate(data.get("world", {}))
    except Exception as e:
        errors.append(ValidationError("world.yaml", "", str(e)))

    # 3. Validate each character
    for stem, char_data in data.get("characters", {}).items():
        try:
            characters[stem] = Character.model_validate(char_data)
        except Exception as e:
            errors.append(ValidationError(f"characters/{stem}.yaml", "", str(e)))

    # 4. Validate each chapter
    for cid, chap_data in data.get("chapters", {}).items():
        try:
            chapters[cid] = Chapter.model_validate(chap_data)
        except Exception as e:
            errors.append(ValidationError(f"chapters/{cid}.yaml", "", str(e)))

    # 5. Character count check (requirements mandate 1-3 AI characters max)
    if len(characters) > 3:
        errors.append(
            ValidationError(
                "game.yaml",
                "characters",
                f"Too many characters ({len(characters)}). The runtime engine "
                "supports a maximum of 3 AI characters. Consolidate or remove.",
            )
        )
    if len(characters) == 0 and not any(
        e.file.startswith("characters/") for e in errors
    ):
        errors.append(
            ValidationError(
                "game.yaml",
                "characters",
                "No characters defined. At least 1 character is required.",
            )
        )

    # 6. Cross-file consistency checks
    if game:
        errors.extend(_check_cross_references(game, characters, chapters))

    return ValidationResult(
        valid=len(errors) == 0,
        errors=errors,
        game=game,
        world=world,
        characters=characters,
        chapters=chapters,
    )


def _check_cross_references(
    game: GameMeta,
    characters: dict[str, Character],
    chapters: dict[str, Chapter],
) -> list[ValidationError]:
    """Check that all cross-references between files are consistent."""
    errors: list[ValidationError] = []

    # Characters listed in game.yaml must have files
    for stem in game.characters:
        if stem not in characters:
            errors.append(
                ValidationError(
                    "game.yaml",
                    "characters",
                    f"Character '{stem}' listed in game.yaml but no file generated",
                )
            )

    # Character files not listed in game.yaml
    for stem in characters:
        if stem not in game.characters:
            errors.append(
                ValidationError(
                    f"characters/{stem}.yaml",
                    "",
                    f"Character file exists but '{stem}' not listed in game.yaml",
                )
            )

    # Chapters listed in game.yaml must have files
    for cid in game.chapters:
        if cid not in chapters:
            errors.append(
                ValidationError(
                    "game.yaml",
                    "chapters",
                    f"Chapter '{cid}' listed in game.yaml but no file generated",
                )
            )

    # Chapter next-chain validation
    for cid, chapter in chapters.items():
        if chapter.next and chapter.next not in chapters:
            errors.append(
                ValidationError(
                    f"chapters/{cid}.yaml",
                    "next",
                    f"Chapter '{cid}' references next='{chapter.next}' which does not exist",
                )
            )
        # Characters referenced in chapters must exist
        for char_stem in chapter.characters:
            if char_stem not in characters and char_stem not in game.characters:
                errors.append(
                    ValidationError(
                        f"chapters/{cid}.yaml",
                        "characters",
                        f"Chapter '{cid}' references character '{char_stem}' which does not exist",
                    )
                )

    # Relationship keys must reference valid character file stems.
    # Each character must NOT have a relationship entry for themselves.
    for stem, char in characters.items():
        for rel_name in char.relationships:
            if rel_name == stem:
                errors.append(
                    ValidationError(
                        f"characters/{stem}.yaml",
                        "relationships",
                        f"Character '{stem}' has a relationship with itself",
                    )
                )
            elif rel_name not in characters and rel_name not in game.characters:
                errors.append(
                    ValidationError(
                        f"characters/{stem}.yaml",
                        "relationships",
                        f"Relationship key '{rel_name}' does not match any character stem",
                    )
                )

    # Chapter order: next-chain should match game.yaml chapter order.
    chapter_list = game.chapters
    for i, cid in enumerate(chapter_list):
        if cid not in chapters:
            continue
        expected_next = chapter_list[i + 1] if i + 1 < len(chapter_list) else None
        actual_next = chapters[cid].next
        if actual_next != expected_next:
            errors.append(
                ValidationError(
                    f"chapters/{cid}.yaml",
                    "next",
                    f"Expected next='{expected_next}' but got next='{actual_next}'",
                )
            )

    # Explicit circular chain detection: follow next pointers and verify
    # we reach None within len(chapters) steps.
    if chapter_list and chapter_list[0] in chapters:
        visited: set[str] = set()
        current: str | None = chapter_list[0]
        while current is not None:
            if current in visited:
                errors.append(
                    ValidationError(
                        f"chapters/{current}.yaml",
                        "next",
                        f"Circular chapter chain detected: '{current}' is reached twice",
                    )
                )
                break
            visited.add(current)
            current = chapters[current].next if current in chapters else None

    return errors


def check_size_warnings(
    world: World | None,
    characters: dict[str, Character],
    chapters: dict[str, Chapter],
) -> list[str]:
    """Check for files that exceed recommended size limits."""
    warnings: list[str] = []

    if world:
        word_count = len(f"{world.setting} {world.tone} {world.rules}".split())
        if word_count > 150:
            warnings.append(
                f"world.yaml is {word_count} words (target: under 120). "
                "Runtime model may struggle with long world definitions."
            )

    for stem, char in characters.items():
        word_count = len(
            f"{char.role} {char.personality} {char.secret} "
            f"{' '.join(char.relationships.values())}".split()
        )
        if word_count > 80:
            warnings.append(
                f"characters/{stem}.yaml is {word_count} words (target: ~60). "
                "Consider trimming personality or relationships."
            )

    for cid, chap in chapters.items():
        if len(chap.beats) > 6:
            warnings.append(
                f"chapters/{cid}.yaml has {len(chap.beats)} beats (target: 4-6). "
                "Too many beats confuse the runtime narrator."
            )
        if len(chap.beats) < 4:
            warnings.append(
                f"chapters/{cid}.yaml has {len(chap.beats)} beats (target: 4-6). "
                "Too few beats leave the narrator without direction."
            )
        beat_word_counts = [len(b.split()) for b in chap.beats]
        for i, wc in enumerate(beat_word_counts):
            if wc > 15:
                warnings.append(
                    f"chapters/{cid}.yaml beat {i + 1} is {wc} words. "
                    "Beats should be short phrases (under 12 words)."
                )

    return warnings

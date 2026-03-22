"""Extract structural hints from free-text game concepts.

Uses regex to detect character counts, chapter counts, and character names
from the user's concept text. No LLM call -- pure code extraction.

When a hint is not found, the field is None/empty, and callers fall back
to default prompt constraints.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# Runtime limit: small models can't maintain more than 3 distinct voices.
MAX_CHARACTERS = 3

# Reasonable upper bound for chapters (sequential, so no hard runtime limit).
MAX_CHAPTERS = 20

# Word-to-digit mapping for natural language numbers.
_WORD_TO_INT: dict[str, int] = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
}

_NUMBER_PATTERN = r"(\d+|" + "|".join(_WORD_TO_INT.keys()) + r")"


@dataclass(frozen=True)
class ConceptHints:
    """Structural hints extracted from the user's concept text.

    All fields are optional -- None means the concept did not specify
    a preference, so the LLM should use its default judgment.
    """

    character_count: int | None = None
    chapter_count: int | None = None
    character_names: list[str] = field(default_factory=list)
    character_stems: list[str] = field(default_factory=list)


def _parse_number(text: str) -> int | None:
    """Parse a digit string or English word-number into an int."""
    text = text.strip().lower()
    if text.isdigit():
        return int(text)
    return _WORD_TO_INT.get(text)


def _name_to_stem(name: str) -> str:
    """Convert a character name to a file stem (lowercase, hyphenated)."""
    return re.sub(r"\s+", "-", name.strip().lower())


def _extract_count(concept: str, noun: str) -> int | None:
    """Extract a count for a noun like 'characters' or 'chapters'."""
    # Match "N characters" or "N character"
    pattern = _NUMBER_PATTERN + r"\s+" + noun + r"s?"
    match = re.search(pattern, concept, re.IGNORECASE)
    if match:
        return _parse_number(match.group(1))
    return None


def _extract_character_names(concept: str) -> list[str]:
    """Extract character names from patterns in the concept text.

    Recognizes patterns like:
      - "named Maya and Joaquin"
      - "characters named Maya, Joaquin, and Leo"
      - "characters include Maya and Joaquin"
      - "characters: Maya, Joaquin"
      - "2 characters Maya and Joaquin"
      - "proposals for Maya and Joaquin"
    """
    names: list[str] = []

    # Pattern: "named/called/include/including" followed by capitalized names
    # separated by commas and/or "and". Capture everything up to a period,
    # newline, or lowercase word that isn't "and".
    pattern = (
        r"(?:named|called|includes?\b|including|proposals?\s+for)\s+"
        r"((?:[A-Z][\w'-]*(?:\s+[A-Z][\w'-]*)*)(?:(?:\s*,\s*(?:and\s+)?|\s+and\s+)"
        r"(?:[A-Z][\w'-]*(?:\s+[A-Z][\w'-]*)*))*)"
    )
    match = re.search(pattern, concept)
    if match:
        raw = match.group(1)
        # Split on commas, "and", or ", and"
        parts = re.split(r"\s*,\s*(?:and\s+)?|\s+and\s+", raw)
        for part in parts:
            part = part.strip()
            if part and part[0].isupper():
                names.append(part)

    # Pattern: "characters: Name1, Name2" (colon-separated list)
    colon_pattern = r"characters?\s*:\s*((?:[A-Z][\w'-]*(?:\s+[A-Z][\w'-]*)*)(?:\s*[,]\s*(?:[A-Z][\w'-]*(?:\s+[A-Z][\w'-]*)*))+)"
    match = re.search(colon_pattern, concept)
    if match and not names:
        raw = match.group(1)
        parts = re.split(r"\s*,\s*", raw)
        for part in parts:
            part = part.strip()
            if part and part[0].isupper():
                names.append(part)

    return names


def extract_concept_hints(concept: str) -> ConceptHints:
    """Extract structural hints from free-text concept using regex.

    Returns a ConceptHints with None/empty for any field not found.
    Character count is clamped to MAX_CHARACTERS (runtime constraint).
    """
    if not concept:
        return ConceptHints()

    # Extract counts
    char_count = _extract_count(concept, "character")
    chap_count = _extract_count(concept, "chapter")

    # Clamp character count to runtime max
    if char_count is not None:
        char_count = min(max(char_count, 1), MAX_CHARACTERS)

    # Clamp chapter count to reasonable range
    if chap_count is not None:
        chap_count = min(max(chap_count, 1), MAX_CHAPTERS)

    # Extract character names
    char_names = _extract_character_names(concept)

    # Generate stems from names
    char_stems = [_name_to_stem(name) for name in char_names]

    return ConceptHints(
        character_count=char_count,
        chapter_count=chap_count,
        character_names=char_names,
        character_stems=char_stems,
    )

"""Quality scoring for playtest turns."""

from __future__ import annotations

from dataclasses import dataclass

from theact.models.character import Character

# Stop words to exclude from personality markers
_STOP_WORDS = {
    "the",
    "a",
    "an",
    "is",
    "are",
    "was",
    "were",
    "be",
    "been",
    "being",
    "have",
    "has",
    "had",
    "do",
    "does",
    "did",
    "will",
    "would",
    "could",
    "should",
    "may",
    "might",
    "shall",
    "can",
    "that",
    "this",
    "with",
    "from",
    "for",
    "and",
    "but",
    "or",
    "not",
    "no",
    "so",
    "if",
    "then",
    "than",
    "too",
    "very",
    "just",
    "about",
    "also",
    "into",
    "over",
    "after",
    "before",
    "between",
    "under",
    "above",
    "of",
    "to",
    "in",
    "on",
    "at",
    "by",
    "up",
    "out",
    "off",
    "her",
    "his",
    "its",
    "who",
    "she",
    "he",
    "they",
    "them",
    "their",
    "it",
    "you",
    "your",
    "we",
}


def _content_words(text: str) -> set[str]:
    """Extract content words (>3 chars after stripping punctuation)."""
    return {
        stripped
        for w in text.lower().split()
        if len(stripped := w.strip(".,;:!?\"'()")) > 3
    }


def has_fact_summary_overlap(
    facts: list[str], summary: str, threshold: float = 0.7
) -> bool:
    """Check if any fact's content words overlap with summary above threshold."""
    if not summary or not facts:
        return False
    summary_words = _content_words(summary)
    for fact in facts:
        fact_words = [
            w.strip(".,;:!?\"'()")
            for w in fact.lower().split()
            if len(w.strip(".,;:!?\"'()")) > 3
        ]
        if (
            fact_words
            and sum(1 for w in fact_words if w in summary_words) / len(fact_words)
            > threshold
        ):
            return True
    return False


@dataclass
class TurnQualityScore:
    """Quality metrics for a single playtest turn."""

    narration_length_ok: bool  # 150-300 words?
    yaml_first_attempt: bool  # parsed without retry?
    character_personality: float  # 0.0-1.0, personality marker match
    memory_relevance: bool  # memory update references turn events?
    composite: float  # weighted average


def _extract_personality_markers(character: Character) -> list[str]:
    """Extract keywords from character personality field."""
    words = character.personality.lower().split()
    markers = [w.strip(".,;:!?\"'()") for w in words]
    return [m for m in markers if m and len(m) > 2 and m not in _STOP_WORDS]


def _check_personality_markers(response: str, markers: list[str]) -> float:
    """Return ratio of personality markers found in response. Capped at 1.0."""
    if not markers:
        return 1.0  # No markers to check
    response_lower = response.lower()
    hits = sum(1 for m in markers if m in response_lower)
    threshold = max(1, len(markers) * 0.3)  # Need 30% of markers
    return min(hits / threshold, 1.0)


def _check_memory_relevance(
    memory_updates: list[str],
    narrator_text: str,
    character_texts: list[str],
) -> bool:
    """Check if memory facts reference actual turn events."""
    if not memory_updates:
        return True  # No updates = vacuously relevant
    all_text = (narrator_text + " " + " ".join(character_texts)).lower()
    # At least one memory fact should reference something from the turn
    for fact in memory_updates:
        words = fact.lower().split()
        content_words = [
            w.strip(".,;:!?")
            for w in words
            if len(w) > 3 and w.lower() not in _STOP_WORDS
        ]
        if any(w in all_text for w in content_words):
            return True
    return False


def score_turn(
    narration: str,
    character_responses: list[str],
    characters: list[Character],
    memory_updates: list[str],
    yaml_issues: list[str],
) -> TurnQualityScore:
    """Score a single turn's quality."""
    word_count = len(narration.split())
    narration_length_ok = 150 <= word_count <= 300

    yaml_first_attempt = not any(
        "yaml" in issue.lower() or "parse" in issue.lower() for issue in yaml_issues
    )

    # Character personality check - average across all responding characters
    personality_scores: list[float] = []
    for response, char in zip(character_responses, characters):
        markers = _extract_personality_markers(char)
        personality_scores.append(_check_personality_markers(response, markers))
    character_personality = (
        sum(personality_scores) / len(personality_scores) if personality_scores else 1.0
    )

    memory_relevance = _check_memory_relevance(
        memory_updates, narration, character_responses
    )

    # Weighted composite
    composite = (
        0.3 * (1.0 if narration_length_ok else 0.0)
        + 0.2 * (1.0 if yaml_first_attempt else 0.0)
        + 0.3 * character_personality
        + 0.2 * (1.0 if memory_relevance else 0.0)
    )

    return TurnQualityScore(
        narration_length_ok=narration_length_ok,
        yaml_first_attempt=yaml_first_attempt,
        character_personality=character_personality,
        memory_relevance=memory_relevance,
        composite=composite,
    )

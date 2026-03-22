"""Tests for playtest quality scoring."""

from __future__ import annotations

from theact.models.character import Character
from theact.playtest.scoring import (
    TurnQualityScore,
    _check_memory_relevance,
    _check_personality_markers,
    _extract_personality_markers,
    has_fact_summary_overlap,
    score_turn,
)


def _make_character(
    name: str = "Maya Chen",
    personality: str = "Cautious, analytical, speaks with precision and dry humor.",
) -> Character:
    """Build a minimal Character for testing."""
    return Character(
        name=name,
        role="Marine biologist",
        personality=personality,
        secret="Knows more than she lets on.",
        relationships={"joaquin": "Distrusts him"},
    )


# -- Personality Markers ---------------------------------------------------


class TestPersonalityMarkers:
    def test_extract_filters_stop_words(self):
        char = _make_character(personality="She is very cautious and also analytical.")
        markers = _extract_personality_markers(char)
        # "she", "is", "very", "and", "also" are stop words
        assert "she" not in markers
        assert "very" not in markers
        assert "also" not in markers

    def test_extract_keeps_meaningful_words(self):
        char = _make_character(
            personality="Cautious, analytical, speaks with precision and dry humor."
        )
        markers = _extract_personality_markers(char)
        assert "cautious" in markers
        assert "analytical" in markers
        assert "precision" in markers
        assert "humor" in markers
        assert "speaks" in markers

    def test_extract_strips_punctuation(self):
        char = _make_character(personality="Bold! Reckless, daring.")
        markers = _extract_personality_markers(char)
        assert "bold" in markers
        assert "reckless" in markers
        assert "daring" in markers
        # No punctuation attached
        assert "bold!" not in markers
        assert "reckless," not in markers

    def test_extract_filters_short_words(self):
        char = _make_character(personality="Is an ok dry wit.")
        markers = _extract_personality_markers(char)
        # "is", "an", "ok" are <= 2 chars or stop words
        assert "ok" not in markers
        assert "dry" in markers
        assert "wit" in markers

    def test_check_markers_all_present(self):
        markers = ["cautious", "analytical", "precision"]
        response = "She was cautious and analytical, speaking with precision."
        score = _check_personality_markers(response, markers)
        assert score == 1.0

    def test_check_markers_none_present(self):
        markers = ["cautious", "analytical", "precision", "humor"]
        response = "He ran quickly through the forest without stopping."
        score = _check_personality_markers(response, markers)
        assert score == 0.0

    def test_check_markers_partial(self):
        markers = ["cautious", "analytical", "precision", "humor", "speaks"]
        # 30% threshold = max(1, 5*0.3) = 1.5, so need 1.5 hits for 1.0
        # With 1 hit: 1/1.5 = 0.667
        response = "She was cautious about the situation."
        score = _check_personality_markers(response, markers)
        assert 0.0 < score < 1.0

    def test_check_markers_empty_list(self):
        score = _check_personality_markers("Any response text here.", [])
        assert score == 1.0


# -- Memory Relevance ------------------------------------------------------


class TestMemoryRelevance:
    def test_relevant_memory(self):
        updates = ["Player explored the beach and found shells"]
        narrator = "You walk along the sandy beach, finding colorful shells."
        chars = ["Be careful near the water."]
        assert _check_memory_relevance(updates, narrator, chars) is True

    def test_irrelevant_memory(self):
        updates = ["Discovered ancient spacecraft technology"]
        narrator = "You sit by the campfire eating fruit."
        chars = ["The fire is warm."]
        assert _check_memory_relevance(updates, narrator, chars) is False

    def test_empty_updates_is_relevant(self):
        assert _check_memory_relevance([], "Any narration.", ["Any response."]) is True

    def test_relevance_checks_character_text_too(self):
        updates = ["Maya mentioned the ruins"]
        narrator = "You walk through the jungle."
        chars = ["I saw the ruins yesterday."]
        assert _check_memory_relevance(updates, narrator, chars) is True

    def test_relevance_ignores_short_words(self):
        # Memory fact with only short/stop words should not match
        updates = ["He is at the top"]
        narrator = "A completely unrelated narration about cooking dinner."
        chars = ["Pass me the salt."]
        assert _check_memory_relevance(updates, narrator, chars) is False


# -- Score Turn -----------------------------------------------------------


class TestScoreTurn:
    def test_perfect_turn(self):
        # 200 words narration (within 150-300 range)
        narration = " ".join(["word"] * 200)
        char = _make_character(personality="Cautious analytical precision humor.")
        response = "She was cautious and analytical, speaking with precision and humor."
        memory = ["Player explored the word area"]

        score = score_turn(
            narration=narration,
            character_responses=[response],
            characters=[char],
            memory_updates=memory,
            yaml_issues=[],
        )

        assert score.narration_length_ok is True
        assert score.yaml_first_attempt is True
        assert score.character_personality == 1.0
        assert score.memory_relevance is True
        assert score.composite == 1.0

    def test_short_narration(self):
        narration = "Very short."
        score = score_turn(
            narration=narration,
            character_responses=[],
            characters=[],
            memory_updates=[],
            yaml_issues=[],
        )
        assert score.narration_length_ok is False
        # No characters means personality defaults to 1.0
        # No memory updates means relevance is True
        # Composite: 0.3*0 + 0.2*1 + 0.3*1 + 0.2*1 = 0.7
        assert score.composite == 0.7

    def test_long_narration(self):
        narration = " ".join(["word"] * 350)
        score = score_turn(
            narration=narration,
            character_responses=[],
            characters=[],
            memory_updates=[],
            yaml_issues=[],
        )
        assert score.narration_length_ok is False

    def test_yaml_failure_reduces_score(self):
        narration = " ".join(["word"] * 200)
        score = score_turn(
            narration=narration,
            character_responses=[],
            characters=[],
            memory_updates=[],
            yaml_issues=["YAML parse error on line 3"],
        )
        assert score.yaml_first_attempt is False
        # Composite: 0.3*1 + 0.2*0 + 0.3*1 + 0.2*1 = 0.8
        assert score.composite == 0.8

    def test_no_characters_still_scores(self):
        narration = " ".join(["word"] * 200)
        score = score_turn(
            narration=narration,
            character_responses=[],
            characters=[],
            memory_updates=[],
            yaml_issues=[],
        )
        assert score.character_personality == 1.0  # defaults to 1.0
        assert score.composite == 1.0

    def test_composite_weights(self):
        # All bad: narration too short, yaml failed, no personality, irrelevant memory
        narration = "Short."
        char = _make_character(personality="Cautious analytical precision humor.")
        response = "Totally unrelated text without any personality markers whatsoever."
        memory = ["Discovered ancient spacecraft technology"]

        score = score_turn(
            narration=narration,
            character_responses=[response],
            characters=[char],
            memory_updates=memory,
            yaml_issues=["parse failure"],
        )

        assert score.narration_length_ok is False
        assert score.yaml_first_attempt is False
        assert score.memory_relevance is False
        # Composite should be close to 0.3 * personality_score only
        assert score.composite < 0.5

    def test_dataclass_fields(self):
        score = TurnQualityScore(
            narration_length_ok=True,
            yaml_first_attempt=False,
            character_personality=0.75,
            memory_relevance=True,
            composite=0.65,
        )
        assert score.narration_length_ok is True
        assert score.yaml_first_attempt is False
        assert score.character_personality == 0.75
        assert score.memory_relevance is True
        assert score.composite == 0.65

    def test_parse_issue_detection_case_insensitive(self):
        """YAML/parse detection in issues should be case-insensitive."""
        narration = " ".join(["word"] * 200)
        score = score_turn(
            narration=narration,
            character_responses=[],
            characters=[],
            memory_updates=[],
            yaml_issues=["YAML Parse Error"],
        )
        assert score.yaml_first_attempt is False

    def test_multiple_characters_averaged(self):
        """Personality score averages across multiple characters."""
        char1 = _make_character(name="Maya", personality="Cautious analytical.")
        char2 = _make_character(name="Joaquin", personality="Bold reckless daring.")
        # Response 1 matches char1's markers, response 2 doesn't match char2's
        response1 = "She was cautious and analytical in her approach."
        response2 = "He sat quietly by the fire without saying much."

        score = score_turn(
            narration=" ".join(["word"] * 200),
            character_responses=[response1, response2],
            characters=[char1, char2],
            memory_updates=[],
            yaml_issues=[],
        )

        # char1 should score high, char2 should score low
        # Average should be between
        assert 0.0 < score.character_personality < 1.0


class TestFactSummaryOverlap:
    def test_high_overlap_detected(self):
        facts = ["Maya explored the dark dense jungle carefully"]
        summary = "Maya explored the dark dense jungle and found a river"
        assert has_fact_summary_overlap(facts, summary) is True

    def test_distinct_facts_no_overlap(self):
        facts = ["Has a flare gun from the wreckage"]
        summary = "Maya explored the jungle and found a river"
        assert has_fact_summary_overlap(facts, summary) is False

    def test_empty_inputs(self):
        assert has_fact_summary_overlap([], "some summary") is False
        assert has_fact_summary_overlap(["fact"], "") is False

    def test_short_words_ignored(self):
        # Words <= 3 chars after stripping should not count
        facts = ["He is on it"]
        summary = "He is on it too"
        assert has_fact_summary_overlap(facts, summary) is False

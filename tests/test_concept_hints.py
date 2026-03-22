"""Tests for concept hint extraction."""

from theact.creator.concept_hints import ConceptHints, extract_concept_hints


class TestExtractCharacterCount:
    def test_digit_count(self):
        hints = extract_concept_hints("A game with 2 characters")
        assert hints.character_count == 2

    def test_word_count(self):
        hints = extract_concept_hints("A game with three characters")
        assert hints.character_count == 3

    def test_singular(self):
        hints = extract_concept_hints("1 character in the story")
        assert hints.character_count == 1

    def test_clamps_to_max_3(self):
        hints = extract_concept_hints("A game with 5 characters")
        assert hints.character_count == 3

    def test_clamps_word_to_max_3(self):
        hints = extract_concept_hints("A game with four characters")
        assert hints.character_count == 3

    def test_no_character_count(self):
        hints = extract_concept_hints("A fantasy adventure in a magical realm")
        assert hints.character_count is None


class TestExtractChapterCount:
    def test_digit_count(self):
        hints = extract_concept_hints("An adventure across 8 chapters")
        assert hints.chapter_count == 8

    def test_word_count(self):
        hints = extract_concept_hints("A story in five chapters")
        assert hints.chapter_count == 5

    def test_twelve_chapters(self):
        hints = extract_concept_hints("An epic with twelve chapters")
        assert hints.chapter_count == 12

    def test_singular(self):
        hints = extract_concept_hints("1 chapter game")
        assert hints.chapter_count == 1

    def test_no_chapter_count(self):
        hints = extract_concept_hints("A noir mystery game")
        assert hints.chapter_count is None


class TestExtractCharacterNames:
    def test_named_pattern(self):
        hints = extract_concept_hints("Characters named Maya and Joaquin")
        assert "Maya" in hints.character_names
        assert "Joaquin" in hints.character_names

    def test_include_pattern(self):
        hints = extract_concept_hints("Characters include Dolores and Kowalski")
        assert "Dolores" in hints.character_names
        assert "Kowalski" in hints.character_names

    def test_proposals_for_pattern(self):
        hints = extract_concept_hints("proposals for Maya and Joaquin")
        assert "Maya" in hints.character_names
        assert "Joaquin" in hints.character_names

    def test_comma_separated(self):
        hints = extract_concept_hints("Characters named Maya, Joaquin, and Leo")
        assert len(hints.character_names) == 3
        assert "Maya" in hints.character_names
        assert "Joaquin" in hints.character_names
        assert "Leo" in hints.character_names

    def test_no_names(self):
        hints = extract_concept_hints("A game about survival")
        assert hints.character_names == []

    def test_multi_word_names(self):
        hints = extract_concept_hints("Characters named Father Joaquin and Maya Chen")
        assert "Father Joaquin" in hints.character_names
        assert "Maya Chen" in hints.character_names


class TestCharacterStems:
    def test_simple_stems(self):
        hints = extract_concept_hints("Characters named Maya and Joaquin")
        assert "maya" in hints.character_stems
        assert "joaquin" in hints.character_stems

    def test_multi_word_stems(self):
        hints = extract_concept_hints("Characters named Father Joaquin")
        assert "father-joaquin" in hints.character_stems


class TestEdgeCases:
    def test_empty_string(self):
        hints = extract_concept_hints("")
        assert hints == ConceptHints()

    def test_both_counts(self):
        hints = extract_concept_hints(
            "A noir mystery with 2 characters across 8 chapters"
        )
        assert hints.character_count == 2
        assert hints.chapter_count == 8

    def test_full_concept(self):
        concept = (
            "A noir detective mystery set in 1940s LA. "
            "2 characters named Dolores and Kowalski. "
            "8 chapters spanning the investigation."
        )
        hints = extract_concept_hints(concept)
        assert hints.character_count == 2
        assert hints.chapter_count == 8
        assert "Dolores" in hints.character_names
        assert "Kowalski" in hints.character_names
        assert "dolores" in hints.character_stems
        assert "kowalski" in hints.character_stems

    def test_case_insensitive_counts(self):
        hints = extract_concept_hints("TWO CHARACTERS and FIVE CHAPTERS")
        assert hints.character_count == 2
        assert hints.chapter_count == 5

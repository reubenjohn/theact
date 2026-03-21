"""Tests for prompt template formatting."""

import re

from theact.agents.prompts import (
    CHARACTER_SYSTEM,
    CHAPTER_SUMMARY_SYSTEM,
    GAME_STATE_SYSTEM,
    MEMORY_UPDATE_SYSTEM,
    NARRATOR_SYSTEM,
    ROLLING_SUMMARY_SYSTEM,
)


def _has_orphan_braces(text: str) -> bool:
    """Check for orphan format braces (unfilled placeholders).

    Returns True if the text contains {word} patterns that look like
    unfilled Python format placeholders. Ignores YAML blocks that use
    braces as part of the example syntax (like ``{name}`` inside
    triple-quoted prompt examples).
    """
    # Look for single braces that aren't doubled ({{ or }}) and aren't
    # inside a YAML code block example.
    # A placeholder is {identifier} where identifier is [a-zA-Z_]\w*
    matches = re.findall(r"(?<!\{)\{([a-zA-Z_]\w*)\}(?!\})", text)
    return len(matches) > 0


class TestNarratorSystemPrompt:
    def test_formats_with_all_placeholders(self):
        result = NARRATOR_SYSTEM.format(
            world_setting="A dark island.",
            world_tone="Tense and atmospheric.",
            world_rules="NPCs remember everything.",
            chapter_context="CURRENT CHAPTER: The Crash\nGoal: Survive.",
            active_characters="Maya Chen, Father Joaquin",
        )
        assert "A dark island." in result
        assert "Tense and atmospheric." in result
        assert "Maya Chen, Father Joaquin" in result
        assert not _has_orphan_braces(result)

    def test_with_empty_values(self):
        result = NARRATOR_SYSTEM.format(
            world_setting="",
            world_tone="",
            world_rules="",
            chapter_context="",
            active_characters="",
        )
        # Should still format without error
        assert "SETTING:" in result
        assert not _has_orphan_braces(result)


class TestCharacterSystemPrompt:
    def test_formats_with_all_placeholders(self):
        result = CHARACTER_SYSTEM.format(
            name="Maya Chen",
            role="Crash survivor and engineer",
            personality="Direct, sharp, dry humor.",
            secret="Racing home to her mother.",
            relationships="Relationships:\n- joaquin: Distrusts his evasiveness",
            memory_block="Your memories:\nMet the player.\nKey facts:\n- Player is lost",
        )
        assert "Maya Chen" in result
        assert "Crash survivor" in result
        assert "Racing home" in result
        assert not _has_orphan_braces(result)

    def test_with_empty_memory(self):
        result = CHARACTER_SYSTEM.format(
            name="Maya Chen",
            role="Engineer",
            personality="Direct.",
            secret="None.",
            relationships="",
            memory_block="",
        )
        assert "Maya Chen" in result
        assert not _has_orphan_braces(result)

    def test_with_empty_relationships(self):
        result = CHARACTER_SYSTEM.format(
            name="Maya Chen",
            role="Engineer",
            personality="Direct.",
            secret="None.",
            relationships="",
            memory_block="Your memories:\nSummary text",
        )
        assert "Maya Chen" in result
        assert not _has_orphan_braces(result)


class TestMemoryUpdateSystemPrompt:
    def test_formats_with_name(self):
        result = MEMORY_UPDATE_SYSTEM.format(name="Maya Chen")
        assert "Maya Chen" in result
        assert not _has_orphan_braces(result)

    def test_all_name_occurrences_replaced(self):
        result = MEMORY_UPDATE_SYSTEM.format(name="Joaquin")
        # The prompt uses {name} multiple times
        assert "{name}" not in result
        # Every occurrence should be replaced
        assert "Joaquin" in result


class TestGameStateSystemPrompt:
    def test_no_placeholders(self):
        """Game state system prompt has no placeholders -- it's a static template."""
        assert not _has_orphan_braces(GAME_STATE_SYSTEM)

    def test_contains_key_instructions(self):
        assert "chapter_complete" in GAME_STATE_SYSTEM
        assert "new_beats" in GAME_STATE_SYSTEM


class TestChapterSummarySystemPrompt:
    def test_no_placeholders(self):
        assert not _has_orphan_braces(CHAPTER_SUMMARY_SYSTEM)

    def test_contains_instructions(self):
        assert "2-3 sentences" in CHAPTER_SUMMARY_SYSTEM


class TestRollingSummarySystemPrompt:
    def test_no_placeholders(self):
        assert not _has_orphan_braces(ROLLING_SUMMARY_SYSTEM)

    def test_contains_instructions(self):
        assert "5 sentences" in ROLLING_SUMMARY_SYSTEM

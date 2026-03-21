"""Prompt linting tests: token budgets, orphan placeholders, YAML hints.

These tests are static checks that run without any LLM calls. They verify
that prompt templates stay within size budgets and are correctly structured.
"""

import re

import pytest

from theact.agents.prompts import (
    CHARACTER_SYSTEM,
    CHAPTER_SUMMARY_SYSTEM,
    GAME_STATE_SYSTEM,
    MEMORY_UPDATE_SYSTEM,
    NARRATOR_SYSTEM,
    ROLLING_SUMMARY_SYSTEM,
)
from theact.llm.tokens import estimate_tokens


def _has_orphan_braces(text: str) -> list[str]:
    """Find orphan {placeholder} patterns that look like unfilled format vars.

    Returns a list of placeholder names found.
    """
    return re.findall(r"(?<!\{)\{([a-zA-Z_]\w*)\}(?!\})", text)


# Sample data for rendering templates with all placeholders filled.
_NARRATOR_VARS = {
    "world_setting": "A dark island in the South Pacific.",
    "world_tone": "Tense and atmospheric.",
    "world_rules": "NPCs remember everything.",
    "chapter_context": "CURRENT CHAPTER: The Crash\nGoal: Survive.",
    "active_characters": "maya (Maya Chen), joaquin (Father Joaquin)",
}

_CHARACTER_VARS = {
    "name": "Maya Chen",
    "role": "Crash survivor and engineer",
    "personality": "Direct, sharp, dry humor.",
    "secret": "Racing home to her mother.",
    "relationships": "Relationships:\n- joaquin: Distrusts his evasiveness",
    "memory_block": "Your memories:\nMet the player.\nKey facts:\n- Player is lost",
}

_MEMORY_VARS = {
    "name": "Maya Chen",
}


# ── Static prompt templates (no placeholders) ──

STATIC_TEMPLATES = [
    ("GAME_STATE_SYSTEM", GAME_STATE_SYSTEM),
    ("CHAPTER_SUMMARY_SYSTEM", CHAPTER_SUMMARY_SYSTEM),
    ("ROLLING_SUMMARY_SYSTEM", ROLLING_SUMMARY_SYSTEM),
]

# ── Parameterized prompt templates ──

PARAMETERIZED_TEMPLATES = [
    ("NARRATOR_SYSTEM", NARRATOR_SYSTEM, _NARRATOR_VARS),
    ("CHARACTER_SYSTEM", CHARACTER_SYSTEM, _CHARACTER_VARS),
    ("MEMORY_UPDATE_SYSTEM", MEMORY_UPDATE_SYSTEM, _MEMORY_VARS),
]


class TestTemplateTokenBudget:
    """System prompt templates must stay under ~300 tokens (raw template text)."""

    @pytest.mark.parametrize(
        "name,template",
        STATIC_TEMPLATES,
        ids=[t[0] for t in STATIC_TEMPLATES],
    )
    def test_static_template_under_300_tokens(self, name, template):
        tokens = estimate_tokens(template)
        assert tokens <= 300, (
            f"{name} is {tokens} tokens (budget: 300). Trim the template."
        )

    @pytest.mark.parametrize(
        "name,template,vars_",
        PARAMETERIZED_TEMPLATES,
        ids=[t[0] for t in PARAMETERIZED_TEMPLATES],
    )
    def test_parameterized_template_skeleton_under_300_tokens(
        self, name, template, vars_
    ):
        """The template skeleton (before filling placeholders) should be concise."""
        # Replace placeholders with short stand-ins to measure skeleton size
        skeleton = template
        for key in vars_:
            skeleton = skeleton.replace("{" + key + "}", "X")
        tokens = estimate_tokens(skeleton)
        assert tokens <= 300, (
            f"{name} skeleton is {tokens} tokens (budget: 300). Trim the template."
        )


class TestNoOrphanPlaceholders:
    """After rendering, no {placeholder} should remain."""

    @pytest.mark.parametrize(
        "name,template",
        STATIC_TEMPLATES,
        ids=[t[0] for t in STATIC_TEMPLATES],
    )
    def test_static_no_orphans(self, name, template):
        orphans = _has_orphan_braces(template)
        assert not orphans, f"{name} has orphan placeholders: {orphans}"

    @pytest.mark.parametrize(
        "name,template,vars_",
        PARAMETERIZED_TEMPLATES,
        ids=[t[0] for t in PARAMETERIZED_TEMPLATES],
    )
    def test_parameterized_no_orphans_after_render(self, name, template, vars_):
        rendered = template.format(**vars_)
        orphans = _has_orphan_braces(rendered)
        assert not orphans, f"{name} has orphans after rendering: {orphans}"


class TestYAMLHintExamples:
    """YAML hint examples in prompt templates must include required fields."""

    def test_narrator_yaml_example_has_required_fields(self):
        # The narrator prompt must mention all three output fields
        assert "narration:" in NARRATOR_SYSTEM
        assert "responding_characters:" in NARRATOR_SYSTEM
        assert "mood:" in NARRATOR_SYSTEM

    def test_memory_yaml_example_has_required_fields(self):
        rendered = MEMORY_UPDATE_SYSTEM.format(name="Test")
        assert "add:" in rendered
        assert "remove:" in rendered
        assert "update:" in rendered
        assert "summary:" in rendered

    def test_game_state_yaml_example_has_required_fields(self):
        assert "chapter_complete:" in GAME_STATE_SYSTEM
        assert "new_beats:" in GAME_STATE_SYSTEM
        assert "reason:" in GAME_STATE_SYSTEM


class TestNarratorFullyRendered:
    """A fully rendered narrator prompt must stay under 400 tokens."""

    def test_rendered_narrator_under_400_tokens(self):
        rendered = NARRATOR_SYSTEM.format(**_NARRATOR_VARS)
        tokens = estimate_tokens(rendered)
        assert tokens <= 400, (
            f"Fully rendered narrator system prompt is {tokens} tokens "
            f"(budget: 400). This is the system prompt with sample data "
            f"filled in — reduce world/chapter context if needed."
        )

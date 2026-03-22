"""Tests for creator prompt templates."""

from theact.creator.prompts import (
    BRAINSTORM_SUMMARIZE_SYSTEM,
    BRAINSTORM_SYSTEM,
    CHAPTER_SYSTEM,
    CHAPTER_USER,
    CHARACTER_SYSTEM,
    CHARACTER_USER,
    CLASSIFY_SYSTEM,
    CLASSIFY_USER,
    FIX_SYSTEM,
    FIX_USER,
    GENERATION_SYSTEM,
    GENERATION_USER,
    LEGACY_GENERATION_SYSTEM,
    LEGACY_GENERATION_USER,
    PROPOSAL_CHAPTERS_SYSTEM,
    PROPOSAL_CHAPTERS_USER,
    PROPOSAL_CHARACTERS_SYSTEM,
    PROPOSAL_CHARACTERS_USER,
    PROPOSAL_REVISION_USER,
    PROPOSAL_SYSTEM,
    PROPOSAL_USER,
    SETTING_REVISION_USER,
    SETTING_SYSTEM,
    SETTING_USER,
    TARGETED_REVISION_USER,
    WORLD_SYSTEM,
    WORLD_USER,
    chapters_system_prompt,
    chapters_user_prompt,
    characters_system_prompt,
    characters_user_prompt,
)


class TestPromptsExist:
    """All prompts should be non-empty strings."""

    def test_proposal_system(self):
        assert isinstance(PROPOSAL_SYSTEM, str)
        assert len(PROPOSAL_SYSTEM) > 100

    def test_proposal_user(self):
        assert isinstance(PROPOSAL_USER, str)
        assert len(PROPOSAL_USER) > 10

    def test_proposal_revision_user(self):
        assert isinstance(PROPOSAL_REVISION_USER, str)
        assert len(PROPOSAL_REVISION_USER) > 10

    def test_generation_system(self):
        assert isinstance(GENERATION_SYSTEM, str)
        assert len(GENERATION_SYSTEM) > 100

    def test_generation_user(self):
        assert isinstance(GENERATION_USER, str)
        assert len(GENERATION_USER) > 10

    def test_fix_system(self):
        assert isinstance(FIX_SYSTEM, str)
        assert len(FIX_SYSTEM) > 10

    def test_fix_user(self):
        assert isinstance(FIX_USER, str)
        assert len(FIX_USER) > 10

    def test_targeted_revision_user(self):
        assert isinstance(TARGETED_REVISION_USER, str)
        assert len(TARGETED_REVISION_USER) > 10

    def test_brainstorm_system(self):
        assert isinstance(BRAINSTORM_SYSTEM, str)
        assert len(BRAINSTORM_SYSTEM) > 10

    def test_brainstorm_summarize_system(self):
        assert isinstance(BRAINSTORM_SUMMARIZE_SYSTEM, str)
        assert len(BRAINSTORM_SUMMARIZE_SYSTEM) > 10

    def test_setting_system(self):
        assert isinstance(SETTING_SYSTEM, str)
        assert len(SETTING_SYSTEM) > 10

    def test_world_system(self):
        assert isinstance(WORLD_SYSTEM, str)
        assert len(WORLD_SYSTEM) > 10

    def test_character_system(self):
        assert isinstance(CHARACTER_SYSTEM, str)
        assert len(CHARACTER_SYSTEM) > 10

    def test_chapter_system(self):
        assert isinstance(CHAPTER_SYSTEM, str)
        assert len(CHAPTER_SYSTEM) > 10

    def test_classify_system(self):
        assert isinstance(CLASSIFY_SYSTEM, str)
        assert len(CLASSIFY_SYSTEM) > 10

    def test_legacy_aliases(self):
        assert GENERATION_SYSTEM is LEGACY_GENERATION_SYSTEM
        assert GENERATION_USER is LEGACY_GENERATION_USER


class TestPromptPlaceholders:
    """Prompts that use format() should have the expected placeholders."""

    def test_proposal_user_has_concept(self):
        assert "{concept}" in PROPOSAL_USER

    def test_proposal_revision_has_placeholders(self):
        assert "{current_proposal}" in PROPOSAL_REVISION_USER
        assert "{user_feedback}" in PROPOSAL_REVISION_USER

    def test_generation_user_has_proposal(self):
        assert "{proposal}" in GENERATION_USER

    def test_fix_user_has_placeholders(self):
        assert "{error_list}" in FIX_USER
        assert "{file_yaml}" in FIX_USER

    def test_targeted_revision_has_placeholders(self):
        assert "{user_feedback}" in TARGETED_REVISION_USER
        assert "{current_output}" in TARGETED_REVISION_USER

    def test_setting_user_has_concept(self):
        assert "{concept}" in SETTING_USER

    def test_setting_revision_has_placeholders(self):
        assert "{current_setting}" in SETTING_REVISION_USER
        assert "{user_feedback}" in SETTING_REVISION_USER

    def test_world_user_has_placeholders(self):
        assert "{title}" in WORLD_USER
        assert "{setting}" in WORLD_USER

    def test_character_user_has_placeholders(self):
        assert "{name}" in CHARACTER_USER
        assert "{other_characters}" in CHARACTER_USER

    def test_chapter_user_has_placeholders(self):
        assert "{chapter_id}" in CHAPTER_USER
        assert "{next_chapter_id}" in CHAPTER_USER

    def test_classify_user_has_placeholders(self):
        assert "{feedback}" in CLASSIFY_USER

    def test_proposal_characters_user_has_placeholders(self):
        assert "{title}" in PROPOSAL_CHARACTERS_USER

    def test_proposal_chapters_user_has_placeholders(self):
        assert "{character_list}" in PROPOSAL_CHAPTERS_USER


class TestPromptSizeReasonable:
    """No prompt should be excessively large (rough token estimate: len // 4)."""

    MAX_TOKENS = 2000

    def test_proposal_system_size(self):
        assert len(PROPOSAL_SYSTEM) // 4 < self.MAX_TOKENS

    def test_generation_system_size(self):
        assert len(GENERATION_SYSTEM) // 4 < self.MAX_TOKENS

    def test_fix_system_size(self):
        assert len(FIX_SYSTEM) // 4 < self.MAX_TOKENS


class TestPerFilePromptsUnder300Tokens:
    """Each new per-file system prompt must be under 300 tokens."""

    MAX_TOKENS = 300

    def _token_estimate(self, text: str) -> int:
        return len(text) // 4

    def test_brainstorm_system(self):
        assert self._token_estimate(BRAINSTORM_SYSTEM) < self.MAX_TOKENS

    def test_brainstorm_summarize_system(self):
        assert self._token_estimate(BRAINSTORM_SUMMARIZE_SYSTEM) < self.MAX_TOKENS

    def test_setting_system(self):
        assert self._token_estimate(SETTING_SYSTEM) < self.MAX_TOKENS

    def test_proposal_characters_system(self):
        assert self._token_estimate(PROPOSAL_CHARACTERS_SYSTEM) < self.MAX_TOKENS

    def test_proposal_chapters_system(self):
        assert self._token_estimate(PROPOSAL_CHAPTERS_SYSTEM) < self.MAX_TOKENS

    def test_world_system(self):
        assert self._token_estimate(WORLD_SYSTEM) < self.MAX_TOKENS

    def test_character_system(self):
        assert self._token_estimate(CHARACTER_SYSTEM) < self.MAX_TOKENS

    def test_chapter_system(self):
        assert self._token_estimate(CHAPTER_SYSTEM) < self.MAX_TOKENS

    def test_fix_system(self):
        assert self._token_estimate(FIX_SYSTEM) < self.MAX_TOKENS

    def test_classify_system(self):
        assert self._token_estimate(CLASSIFY_SYSTEM) < self.MAX_TOKENS

    def test_characters_system_with_hint(self):
        prompt = characters_system_prompt(hint_count=2)
        assert self._token_estimate(prompt) < self.MAX_TOKENS

    def test_chapters_system_with_hint(self):
        prompt = chapters_system_prompt(hint_count=8)
        assert self._token_estimate(prompt) < self.MAX_TOKENS


class TestDynamicPromptFunctions:
    """Tests for the dynamic prompt template functions."""

    def test_characters_system_default(self):
        prompt = characters_system_prompt()
        assert "1-3 characters" in prompt

    def test_characters_system_with_count(self):
        prompt = characters_system_prompt(hint_count=2)
        assert "Exactly 2 characters" in prompt
        assert "1-3" not in prompt

    def test_characters_system_is_backward_compatible(self):
        assert PROPOSAL_CHARACTERS_SYSTEM == characters_system_prompt()

    def test_chapters_system_default(self):
        prompt = chapters_system_prompt()
        assert "3-5 chapters" in prompt

    def test_chapters_system_with_count(self):
        prompt = chapters_system_prompt(hint_count=8)
        assert "Exactly 8 chapters" in prompt
        assert "3-5" not in prompt

    def test_chapters_system_is_backward_compatible(self):
        assert PROPOSAL_CHAPTERS_SYSTEM == chapters_system_prompt()

    def test_characters_user_without_concept(self):
        prompt = characters_user_prompt("Title", "Setting", "Tone")
        assert "Title" in prompt
        assert "Original concept" not in prompt

    def test_characters_user_with_concept(self):
        prompt = characters_user_prompt(
            "Title", "Setting", "Tone", concept="My concept"
        )
        assert "Original concept" in prompt
        assert "My concept" in prompt

    def test_characters_user_with_names(self):
        prompt = characters_user_prompt(
            "Title", "Setting", "Tone", character_names=["Maya", "Joaquin"]
        )
        assert "Maya" in prompt
        assert "Joaquin" in prompt

    def test_chapters_user_without_concept(self):
        prompt = chapters_user_prompt("Title", "Setting", "Maya, Joaquin")
        assert "Original concept" not in prompt

    def test_chapters_user_with_concept(self):
        prompt = chapters_user_prompt("Title", "Setting", "Maya", concept="My concept")
        assert "Original concept" in prompt
        assert "My concept" in prompt

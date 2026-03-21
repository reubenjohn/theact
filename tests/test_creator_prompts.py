"""Tests for creator prompt templates."""

from theact.creator.prompts import (
    FIX_SYSTEM,
    FIX_USER,
    GENERATION_SYSTEM,
    GENERATION_USER,
    PROPOSAL_REVISION_USER,
    PROPOSAL_SYSTEM,
    PROPOSAL_USER,
    TARGETED_REVISION_USER,
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
        assert "{errors}" in FIX_USER
        assert "{original_output}" in FIX_USER

    def test_targeted_revision_has_placeholders(self):
        assert "{user_feedback}" in TARGETED_REVISION_USER
        assert "{current_output}" in TARGETED_REVISION_USER


class TestPromptSizeReasonable:
    """No prompt should be excessively large (rough token estimate: len // 4)."""

    MAX_TOKENS = 2000

    def test_proposal_system_size(self):
        assert len(PROPOSAL_SYSTEM) // 4 < self.MAX_TOKENS

    def test_generation_system_size(self):
        assert len(GENERATION_SYSTEM) // 4 < self.MAX_TOKENS

    def test_fix_system_size(self):
        assert len(FIX_SYSTEM) // 4 < self.MAX_TOKENS

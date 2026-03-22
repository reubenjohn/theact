"""Tests for decomposed proposal generation."""

from __future__ import annotations

import pytest
import yaml

from tests.conftest import creator_config, make_mock_client
from theact.creator.concept_hints import ConceptHints
from theact.creator.proposer import (
    assemble_proposal,
    generate_setting,
    generate_characters_proposal,
    generate_chapters_proposal,
)


@pytest.mark.asyncio
class TestGenerateSetting:
    async def test_produces_setting_data(self):
        setting = {
            "title": "Dark Forest",
            "id": "dark-forest",
            "setting": "A dark forest at dusk.",
            "tone": "Second person, present tense.",
            "rules": "No magic.",
        }
        response = f"```yaml\n{yaml.dump(setting)}```"
        client = make_mock_client([response])
        result = await generate_setting("A dark forest game", client, creator_config())
        assert result["title"] == "Dark Forest"
        assert result["id"] == "dark-forest"


@pytest.mark.asyncio
class TestGenerateCharactersProposal:
    async def test_produces_characters_data(self):
        chars = {
            "characters": [
                {"stem": "maya", "name": "Maya", "role": "Guide"},
            ]
        }
        response = f"```yaml\n{yaml.dump(chars)}```"
        setting = {"title": "Test", "setting": "Forest.", "tone": "2p."}
        client = make_mock_client([response])
        result = await generate_characters_proposal(setting, client, creator_config())
        assert "characters" in result
        assert len(result["characters"]) == 1


@pytest.mark.asyncio
class TestGenerateChaptersProposal:
    async def test_produces_chapters_data(self):
        chaps = {
            "chapters": [
                {"id": "01-start", "title": "Start", "summary": "Begin."},
            ]
        }
        response = f"```yaml\n{yaml.dump(chaps)}```"
        setting = {"title": "Test", "setting": "Forest."}
        chars = {"characters": [{"stem": "maya", "name": "Maya", "role": "Guide"}]}
        client = make_mock_client([response])
        result = await generate_chapters_proposal(
            setting, chars, client, creator_config()
        )
        assert "chapters" in result


@pytest.mark.asyncio
class TestCharactersProposalWithHints:
    async def test_concept_and_hints_accepted(self):
        """Verify concept and hints params are accepted and result is valid."""
        chars = {
            "characters": [
                {"stem": "dolores", "name": "Dolores", "role": "Detective"},
                {"stem": "kowalski", "name": "Kowalski", "role": "Informant"},
            ]
        }
        response = f"```yaml\n{yaml.dump(chars)}```"
        setting = {"title": "Noir", "setting": "1940s LA.", "tone": "Dark."}
        client = make_mock_client([response])
        hints = ConceptHints(
            character_count=2,
            character_names=["Dolores", "Kowalski"],
            character_stems=["dolores", "kowalski"],
        )
        result = await generate_characters_proposal(
            setting,
            client,
            creator_config(),
            concept="A noir mystery with 2 characters named Dolores and Kowalski",
            hints=hints,
        )
        assert len(result["characters"]) == 2

    async def test_works_without_concept_or_hints(self):
        """Backward compat: concept/hints default to None."""
        chars = {"characters": [{"stem": "maya", "name": "Maya", "role": "Guide"}]}
        response = f"```yaml\n{yaml.dump(chars)}```"
        setting = {"title": "Test", "setting": "Forest.", "tone": "2p."}
        client = make_mock_client([response])
        result = await generate_characters_proposal(setting, client, creator_config())
        assert "characters" in result


@pytest.mark.asyncio
class TestChaptersProposalWithHints:
    async def test_concept_and_hints_accepted(self):
        """Verify concept and hints params are accepted and result is valid."""
        chaps = {
            "chapters": [
                {"id": f"{i:02d}-ch", "title": f"Ch {i}", "summary": "Action."}
                for i in range(1, 9)
            ]
        }
        response = f"```yaml\n{yaml.dump(chaps)}```"
        setting = {"title": "Adventure", "setting": "Jungle."}
        chars = {"characters": [{"stem": "maya", "name": "Maya", "role": "Guide"}]}
        client = make_mock_client([response])
        hints = ConceptHints(chapter_count=8)
        result = await generate_chapters_proposal(
            setting,
            chars,
            client,
            creator_config(),
            concept="An adventure across 8 chapters",
            hints=hints,
        )
        assert len(result["chapters"]) == 8

    async def test_works_without_concept_or_hints(self):
        """Backward compat: concept/hints default to None."""
        chaps = {
            "chapters": [{"id": "01-start", "title": "Start", "summary": "Begin."}]
        }
        response = f"```yaml\n{yaml.dump(chaps)}```"
        setting = {"title": "Test", "setting": "Forest."}
        chars = {"characters": [{"stem": "maya", "name": "Maya", "role": "Guide"}]}
        client = make_mock_client([response])
        result = await generate_chapters_proposal(
            setting, chars, client, creator_config()
        )
        assert "chapters" in result


class TestAssembleProposal:
    def test_assembles_complete_proposal(self):
        setting = {"title": "T", "id": "t", "setting": "S", "tone": "T", "rules": "R"}
        characters = {"characters": [{"stem": "m", "name": "M", "role": "R"}]}
        chapters = {"chapters": [{"id": "01-x", "title": "X", "summary": "S"}]}
        result = assemble_proposal(setting, characters, chapters)
        assert result["title"] == "T"
        assert result["id"] == "t"
        assert result["setting"] == "S"
        assert len(result["characters"]) == 1
        assert len(result["chapters"]) == 1

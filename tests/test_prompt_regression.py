"""Regression tests for agent output parsing.

These tests verify that parse_yaml_response() handles known model output
patterns correctly. Fixtures are real (or realistic) model responses.
"""

import pytest
import yaml
from pathlib import Path

from theact.llm.parsing import parse_yaml_response, YAMLParseError

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> dict:
    with open(FIXTURES_DIR / name) as f:
        return yaml.safe_load(f)


class TestNarratorParsing:
    def test_valid_narrator_with_characters(self):
        content = """```yaml
narration: |
  You open your eyes to chaos. Metal groans around you. Smoke
  fills the air as you struggle to free yourself from the wreckage.
  A woman's voice calls out nearby.
responding_characters:
  - maya
mood: tense
```"""
        data = parse_yaml_response(content)
        assert "narration" in data
        assert isinstance(data["responding_characters"], list)
        assert "maya" in data["responding_characters"]
        assert data["mood"] == "tense"

    def test_narrator_empty_characters_list(self):
        content = """```yaml
narration: |
  You sit alone on the beach, watching the waves.
responding_characters: []
mood: calm
```"""
        data = parse_yaml_response(content)
        assert data["responding_characters"] == []

    def test_narrator_missing_closing_backticks(self):
        content = """```yaml
narration: |
  You wake up.
responding_characters:
  - maya
mood: tense
"""
        data = parse_yaml_response(content)
        assert data["narration"].strip() == "You wake up."

    def test_narrator_with_thinking_prefix(self):
        """Model output that had thinking stripped, leaving just content."""
        content = """Here is my response:

```yaml
narration: |
  The jungle closes in around you.
responding_characters:
  - joaquin
mood: mysterious
```"""
        data = parse_yaml_response(content)
        assert "jungle" in data["narration"]
        assert data["responding_characters"] == ["joaquin"]

    def test_narrator_opening_fixture(self):
        """Parse the narrator opening fixture file."""
        fixture = load_fixture("narrator_opening_001.yaml")
        data = parse_yaml_response(fixture["content"])
        assert "pain and confusion" in data["narration"]
        assert data["responding_characters"] == ["maya"]
        assert data["mood"] == "tense"

    def test_narrator_no_fence_fixture(self):
        """Parse narrator output without fenced code block."""
        fixture = load_fixture("narrator_no_fence_001.yaml")
        data = parse_yaml_response(fixture["content"])
        assert "narration" in data
        assert "beach" in data["narration"]


class TestMemoryParsing:
    def test_memory_with_facts_and_summary(self):
        content = """```yaml
summary: |
  Maya knows about the crash and has met the player.
  She is wary but willing to cooperate.
key_facts:
  - "Player seems trustworthy"
  - "Found fresh water source"
```"""
        data = parse_yaml_response(content)
        assert "summary" in data
        assert len(data["key_facts"]) == 2

    def test_memory_empty_facts(self):
        content = """```yaml
summary: |
  Maya knows they crashed.
key_facts: []
```"""
        data = parse_yaml_response(content)
        assert data["key_facts"] == []

    def test_memory_no_fenced_block(self):
        """Model outputs YAML without fences."""
        content = """summary: |
  Maya remembers the crash.
key_facts:
  - "Beach is dangerous at night"
"""
        data = parse_yaml_response(content)
        assert "summary" in data

    def test_memory_update_fixture(self):
        """Parse the memory update fixture file."""
        fixture = load_fixture("memory_update_001.yaml")
        data = parse_yaml_response(fixture["content"])
        assert "summary" in data
        assert len(data["key_facts"]) == 2


class TestGameStateParsing:
    def test_no_beats_hit(self):
        content = """```yaml
chapter_complete: false
reason: "Player has not explored yet"
new_beats: []
```"""
        data = parse_yaml_response(content)
        assert data["chapter_complete"] is False

    def test_beats_hit(self):
        content = """```yaml
chapter_complete: false
reason: "Player found water but hasn't built shelter"
new_beats:
  - "Find fresh water source"
```"""
        data = parse_yaml_response(content)
        assert len(data["new_beats"]) == 1

    def test_chapter_complete(self):
        content = """```yaml
chapter_complete: true
reason: "All beats have been hit and camp is established"
new_beats:
  - "Establish base camp"
```"""
        data = parse_yaml_response(content)
        assert data["chapter_complete"] is True

    def test_game_state_no_beats_fixture(self):
        """Parse the game state no-beats fixture file."""
        fixture = load_fixture("game_state_no_beats_001.yaml")
        data = parse_yaml_response(fixture["content"])
        assert data["chapter_complete"] is False
        assert data["new_beats"] == []

    def test_game_state_beats_hit_fixture(self):
        """Parse the game state beats-hit fixture file."""
        fixture = load_fixture("game_state_beats_hit_001.yaml")
        data = parse_yaml_response(fixture["content"])
        assert data["chapter_complete"] is False
        assert len(data["new_beats"]) == 1

    def test_game_state_complete_fixture(self):
        """Parse the game state complete fixture file."""
        fixture = load_fixture("game_state_complete_001.yaml")
        data = parse_yaml_response(fixture["content"])
        assert data["chapter_complete"] is True


class TestEdgeCases:
    def test_json_object_parses_as_yaml(self):
        """JSON objects are valid YAML dicts, so parse_yaml_response accepts them."""
        content = '{"narration": "You wake up", "mood": "tense"}'
        data = parse_yaml_response(content)
        assert data["narration"] == "You wake up"

    def test_json_array_raises(self):
        """A JSON array is not a dict, so parse_yaml_response rejects it."""
        content = '[{"narration": "You wake up"}]'
        with pytest.raises(YAMLParseError):
            parse_yaml_response(content)

    def test_plain_text_raises(self):
        content = "You wake up on a beach. The sun is bright."
        with pytest.raises(YAMLParseError):
            parse_yaml_response(content)

    def test_tabs_normalized(self):
        content = "```yaml\nnarration: |\n\tYou look around.\nresponding_characters: []\nmood: calm\n```"
        data = parse_yaml_response(content)
        assert "look around" in data["narration"]

    def test_empty_string_raises(self):
        with pytest.raises(YAMLParseError):
            parse_yaml_response("")

    def test_whitespace_only_raises(self):
        with pytest.raises(YAMLParseError):
            parse_yaml_response("   \n  \n  ")

    def test_multiple_yaml_blocks_takes_last(self):
        content = "```yaml\nnarration: wrong\n```\n\n```yaml\nnarration: correct\nmood: tense\n```"
        data = parse_yaml_response(content)
        assert data["narration"] == "correct"

    def test_yaml_block_with_trailing_prose(self):
        content = "```yaml\nnarration: |\n  You step forward.\nresponding_characters: []\nmood: calm\n```\n\nI hope this response is helpful!"
        data = parse_yaml_response(content)
        assert "step forward" in data["narration"]


class TestFixtureIntegrity:
    """Verify all fixture files load and have expected structure."""

    @pytest.mark.parametrize(
        "fixture_name",
        [
            "narrator_opening_001.yaml",
            "narrator_no_fence_001.yaml",
            "character_maya_001.yaml",
            "game_state_no_beats_001.yaml",
            "game_state_beats_hit_001.yaml",
            "game_state_complete_001.yaml",
            "memory_update_001.yaml",
        ],
    )
    def test_fixture_loads_and_has_required_fields(self, fixture_name):
        fixture = load_fixture(fixture_name)
        assert "agent" in fixture, f"{fixture_name} missing 'agent' field"
        assert "content" in fixture, f"{fixture_name} missing 'content' field"
        assert "finish_reason" in fixture, (
            f"{fixture_name} missing 'finish_reason' field"
        )
        assert "parse_success" in fixture, (
            f"{fixture_name} missing 'parse_success' field"
        )

    @pytest.mark.parametrize(
        "fixture_name",
        [
            "narrator_opening_001.yaml",
            "narrator_no_fence_001.yaml",
            "game_state_no_beats_001.yaml",
            "game_state_beats_hit_001.yaml",
            "game_state_complete_001.yaml",
            "memory_update_001.yaml",
        ],
    )
    def test_parseable_fixtures_parse_successfully(self, fixture_name):
        """Fixtures marked parse_success=true should parse without error."""
        fixture = load_fixture(fixture_name)
        if fixture["parse_success"]:
            data = parse_yaml_response(fixture["content"])
            assert isinstance(data, dict)

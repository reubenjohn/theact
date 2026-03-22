"""Tests for creator generator (YAML parsing)."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from theact.creator.config import CreatorLLMConfig
from theact.creator.generator import (
    YAMLParseError,
    call_llm,
    extract_yaml,
    _parse_generation_response,
    _parse_proposal_response,
)


# --- Sample YAML for tests ---

VALID_GENERATION_YAML = """\
game:
  id: test-game
  title: Test Game
  description: A test game.
  characters:
    - maya
  chapters:
    - 01-start

world:
  setting: A dark forest.
  tone: Second person, present tense.
  rules: Magic does not exist.

characters:
  maya:
    name: Maya
    role: Guide.
    personality: Calm and focused.
    secret: Knows the way out.
    relationships: {}

chapters:
  01-start:
    id: 01-start
    title: The Start
    summary: The beginning.
    beats:
      - Player enters the forest
      - Meets Maya
      - Discovers the path
      - Reaches the clearing
    completion: Player has reached the clearing.
    characters:
      - maya
    next: null
"""

VALID_PROPOSAL_YAML = """\
title: Test Game
id: test-game
setting: A dark forest.
tone: Second person, present tense.
rules: No magic.
characters:
  - stem: maya
    name: Maya
    role: Guide through the forest.
chapters:
  - id: 01-start
    title: The Start
    summary: Enter the forest.
"""


class TestParseGenerationResponse:
    def test_fenced_yaml(self):
        text = f"Here is the output:\n\n```yaml\n{VALID_GENERATION_YAML}```\n\nDone."
        result = _parse_generation_response(text)
        assert "game" in result
        assert "world" in result
        assert "characters" in result
        assert "chapters" in result
        assert result["game"]["id"] == "test-game"

    def test_raw_yaml_no_fencing(self):
        result = _parse_generation_response(VALID_GENERATION_YAML)
        assert "game" in result
        assert result["game"]["title"] == "Test Game"

    def test_fenced_without_yaml_tag(self):
        text = f"```\n{VALID_GENERATION_YAML}```"
        result = _parse_generation_response(text)
        assert "game" in result

    def test_malformed_yaml_raises(self):
        bad = "```yaml\n{invalid: [yaml: !!error\n```"
        with pytest.raises(YAMLParseError, match="not valid YAML"):
            _parse_generation_response(bad)

    def test_non_dict_raises(self):
        text = "- just\n- a\n- list\n"
        with pytest.raises(YAMLParseError, match="Expected a YAML mapping"):
            _parse_generation_response(text)

    def test_missing_keys_raises(self):
        text = "game:\n  id: test\nworld:\n  setting: here\n"
        with pytest.raises(YAMLParseError, match="missing required top-level keys"):
            _parse_generation_response(text)

    def test_plain_string_raises(self):
        with pytest.raises(YAMLParseError, match="Expected a YAML mapping"):
            _parse_generation_response("just a string response without yaml")


class TestParseProposalResponse:
    def test_valid_proposal(self):
        text = f"```yaml\n{VALID_PROPOSAL_YAML}```"
        result = _parse_proposal_response(text)
        assert result["title"] == "Test Game"
        assert result["id"] == "test-game"
        assert len(result["characters"]) == 1
        assert len(result["chapters"]) == 1

    def test_raw_proposal(self):
        result = _parse_proposal_response(VALID_PROPOSAL_YAML)
        assert result["title"] == "Test Game"

    def test_missing_title_raises(self):
        text = "id: test\ncharacters: []\nchapters: []\n"
        with pytest.raises(YAMLParseError, match="missing required keys"):
            _parse_proposal_response(text)

    def test_missing_chapters_raises(self):
        text = "title: X\nid: x\ncharacters: []\n"
        with pytest.raises(YAMLParseError, match="missing required keys"):
            _parse_proposal_response(text)

    def test_malformed_yaml_raises(self):
        with pytest.raises(YAMLParseError):
            _parse_proposal_response("```yaml\n{bad: [yaml\n```")


class TestExtractYaml:
    def test_public_function_works(self):
        result = extract_yaml("key: value\n")
        assert result == {"key": "value"}

    def test_strips_think_tags(self):
        text = "<think>reasoning here</think>```yaml\nkey: value\n```"
        result = extract_yaml(text)
        assert result == {"key": "value"}

    def test_strips_multiline_think_tags(self):
        text = "<think>\nlong\nreasoning\n</think>\nkey: value\n"
        result = extract_yaml(text)
        assert result == {"key": "value"}

    def test_truncated_fence_fallback(self):
        """Handle responses with opening fence but no closing fence."""
        text = "```yaml\nkey: value\nanother: thing\n"
        result = extract_yaml(text)
        assert result == {"key": "value", "another": "thing"}

    def test_empty_response_raises(self):
        with pytest.raises(YAMLParseError, match="empty response"):
            extract_yaml("")

    def test_whitespace_only_raises(self):
        with pytest.raises(YAMLParseError, match="empty response"):
            extract_yaml("   \n\n  ")

    def test_think_tags_only_raises(self):
        text = "<think>long reasoning about the world\nwith multiple lines</think>"
        with pytest.raises(YAMLParseError, match="only reasoning/thinking content"):
            extract_yaml(text)

    def test_think_tags_only_whitespace_after_raises(self):
        text = "<think>reasoning</think>  \n  "
        with pytest.raises(YAMLParseError, match="only reasoning/thinking content"):
            extract_yaml(text)

    def test_backward_compatible_alias(self):
        from theact.creator.generator import _extract_yaml

        result = _extract_yaml("key: value\n")
        assert result == {"key": "value"}


def _mock_client(content: str | None, finish_reason: str = "stop") -> AsyncMock:
    """Build an AsyncOpenAI mock returning a single completion."""
    client = AsyncMock()
    choice = MagicMock()
    choice.message.content = content
    choice.finish_reason = finish_reason
    response = MagicMock()
    response.choices = [choice]
    client.chat.completions.create.return_value = response
    return client


def _config() -> CreatorLLMConfig:
    return CreatorLLMConfig(api_key="test-key", model="test-model")


@pytest.mark.asyncio
class TestCallLlmTruncation:
    async def test_truncated_empty_raises(self):
        """finish_reason=length with empty content should raise immediately."""
        client = _mock_client("", finish_reason="length")
        with pytest.raises(YAMLParseError, match="max_tokens.*exhausted"):
            await call_llm(client, _config(), [{"role": "user", "content": "hi"}])

    async def test_truncated_think_only_raises(self):
        """finish_reason=length with only think tags should raise."""
        client = _mock_client(
            "<think>very long reasoning</think>", finish_reason="length"
        )
        with pytest.raises(YAMLParseError, match="max_tokens.*exhausted"):
            await call_llm(client, _config(), [{"role": "user", "content": "hi"}])

    async def test_truncated_with_content_passes(self):
        """finish_reason=length with actual content should return text for retry."""
        client = _mock_client(
            "<think>reasoning</think>```yaml\nkey: val", finish_reason="length"
        )
        result = await call_llm(client, _config(), [{"role": "user", "content": "hi"}])
        assert "key: val" in result

    async def test_normal_response_passes(self):
        """finish_reason=stop should return text normally."""
        client = _mock_client("```yaml\nkey: value\n```", finish_reason="stop")
        result = await call_llm(client, _config(), [{"role": "user", "content": "hi"}])
        assert "key: value" in result

    async def test_none_content_truncated_raises(self):
        """finish_reason=length with None content should raise."""
        client = _mock_client(None, finish_reason="length")
        with pytest.raises(YAMLParseError, match="max_tokens.*exhausted"):
            await call_llm(client, _config(), [{"role": "user", "content": "hi"}])

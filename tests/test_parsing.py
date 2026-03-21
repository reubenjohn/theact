"""Tests for YAML extraction and parsing."""

import pytest

from theact.llm.parsing import (
    YAMLParseError,
    extract_yaml_block,
    parse_yaml_response,
    validate_yaml_fields,
)


class TestExtractYamlBlock:
    def test_fenced_yaml_block(self):
        text = "Some text before.\n\n```yaml\nkey: value\nother: 42\n```\n\nSome text after."
        result = extract_yaml_block(text)
        assert result == "key: value\nother: 42"

    def test_generic_fenced_block(self):
        text = "Response text.\n\n```\nkey: value\n```"
        result = extract_yaml_block(text)
        assert result == "key: value"

    def test_yaml_block_preferred_over_generic(self):
        text = "```\ngeneric: true\n```\n\n```yaml\nspecific: true\n```"
        result = extract_yaml_block(text)
        assert result == "specific: true"

    def test_last_yaml_block_used(self):
        # Model may include example YAML before the actual answer
        text = "```yaml\nexample: true\n```\n\nNow here is my answer:\n\n```yaml\nanswer: true\n```"
        result = extract_yaml_block(text)
        assert result == "answer: true"

    def test_no_code_block_falls_back_to_full_text(self):
        text = "key: value\nother: 42"
        result = extract_yaml_block(text)
        assert result == "key: value\nother: 42"

    def test_multiline_yaml(self):
        text = "```yaml\nnarration: |\n  The hero enters.\n  The room is dark.\nmood: tense\n```"
        result = extract_yaml_block(text)
        assert "narration: |" in result
        assert "mood: tense" in result

    def test_empty_yaml_block(self):
        text = "```yaml\n\n```"
        result = extract_yaml_block(text)
        assert result == ""

    def test_yaml_with_extra_whitespace(self):
        text = "```yaml  \n  key: value  \n```"
        result = extract_yaml_block(text)
        assert result == "key: value"


class TestParseYamlResponse:
    def test_valid_yaml_in_fenced_block(self):
        text = '```yaml\nnarration: "Hello world"\nmood: calm\n```'
        result = parse_yaml_response(text)
        assert result == {"narration": "Hello world", "mood": "calm"}

    def test_valid_yaml_no_block(self):
        text = "narration: Hello\nmood: tense"
        result = parse_yaml_response(text)
        assert result["narration"] == "Hello"
        assert result["mood"] == "tense"

    def test_invalid_yaml_raises(self):
        text = "```yaml\n{invalid yaml: [}\n```"
        with pytest.raises(YAMLParseError, match="YAML parse error"):
            parse_yaml_response(text)

    def test_non_dict_yaml_raises(self):
        text = "```yaml\n- item1\n- item2\n```"
        with pytest.raises(
            YAMLParseError, match="Expected YAML to parse as a dictionary"
        ):
            parse_yaml_response(text)

    def test_scalar_yaml_raises(self):
        text = "```yaml\njust a string\n```"
        with pytest.raises(
            YAMLParseError, match="Expected YAML to parse as a dictionary"
        ):
            parse_yaml_response(text)

    def test_error_preserves_raw_content(self):
        text = "```yaml\n{bad: [}\n```"
        with pytest.raises(YAMLParseError) as exc_info:
            parse_yaml_response(text)
        assert exc_info.value.raw_content == text

    def test_complex_yaml(self):
        text = """```yaml
narration: |
  The hero enters the dark tavern.
  Candles flicker on wooden tables.
responding_characters:
  - bartender
  - mysterious_stranger
mood: mysterious
```"""
        result = parse_yaml_response(text)
        assert "hero enters" in result["narration"]
        assert len(result["responding_characters"]) == 2
        assert result["mood"] == "mysterious"

    def test_yaml_with_surrounding_text(self):
        text = """Here is my narration:

The hero walks in boldly.

```yaml
narration: "The hero enters"
mood: calm
```

That's my response."""
        result = parse_yaml_response(text)
        assert result["narration"] == "The hero enters"


class TestValidateYamlFields:
    def test_all_fields_present(self):
        data = {"name": "test", "value": 42}
        missing = validate_yaml_fields(data, ["name", "value"])
        assert missing == []

    def test_missing_fields(self):
        data = {"name": "test"}
        missing = validate_yaml_fields(data, ["name", "value", "other"])
        assert missing == ["value", "other"]

    def test_no_required_fields(self):
        data = {"anything": True}
        missing = validate_yaml_fields(data, [])
        assert missing == []

    def test_empty_data(self):
        missing = validate_yaml_fields({}, ["field1", "field2"])
        assert missing == ["field1", "field2"]

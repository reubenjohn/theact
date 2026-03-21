"""Tests for error taxonomy: ParseFailureType and classify_parse_failure."""

from theact.llm.errors import ParseFailureType
from theact.llm.parsing import YAMLParseError, classify_parse_failure


class TestParseFailureType:
    def test_enum_values(self):
        assert ParseFailureType.success == "success"
        assert ParseFailureType.no_yaml_block == "no_yaml_block"
        assert ParseFailureType.invalid_yaml == "invalid_yaml"
        assert ParseFailureType.wrong_schema == "wrong_schema"
        assert ParseFailureType.empty_response == "empty_response"
        assert ParseFailureType.echo_prompt == "echo_prompt"
        assert ParseFailureType.json_instead == "json_instead"

    def test_is_string_enum(self):
        assert isinstance(ParseFailureType.success, str)
        assert ParseFailureType.success == "success"


class TestClassifyParseFailure:
    def test_empty_response(self):
        assert classify_parse_failure("") == ParseFailureType.empty_response
        assert classify_parse_failure("   ") == ParseFailureType.empty_response
        assert classify_parse_failure("\n\n") == ParseFailureType.empty_response

    def test_none_treated_as_empty(self):
        # None is falsy, should hit empty check
        assert classify_parse_failure("") == ParseFailureType.empty_response

    def test_json_instead_curly(self):
        assert (
            classify_parse_failure('{"key": "value"}') == ParseFailureType.json_instead
        )

    def test_json_instead_bracket(self):
        assert (
            classify_parse_failure('[{"key": "value"}]')
            == ParseFailureType.json_instead
        )

    def test_echo_prompt(self):
        assert (
            classify_parse_failure("You are the narrator of a text RPG.\n\nSETTING...")
            == ParseFailureType.echo_prompt
        )

    def test_echo_prompt_only_checks_first_50_chars(self):
        # "You are" after 50 chars should NOT be classified as echo
        text = "x" * 50 + "You are the narrator"
        assert classify_parse_failure(text) != ParseFailureType.echo_prompt

    def test_invalid_yaml_in_fenced_block(self):
        text = "```yaml\n{invalid: [yaml: broken}\n```"
        assert classify_parse_failure(text) == ParseFailureType.invalid_yaml

    def test_valid_yaml_no_fenced_block(self):
        text = "narration: Hello\nmood: tense"
        assert classify_parse_failure(text) == ParseFailureType.no_yaml_block

    def test_valid_yaml_in_fenced_block_wrong_schema(self):
        text = "```yaml\nwrong_field: true\n```"
        assert classify_parse_failure(text) == ParseFailureType.wrong_schema

    def test_default_wrong_schema(self):
        text = "Some random text that isn't YAML or JSON"
        assert classify_parse_failure(text) == ParseFailureType.wrong_schema

    def test_empty_string_classified(self):
        result = classify_parse_failure("")
        assert result == ParseFailureType.empty_response


class TestYAMLParseErrorBackwardCompat:
    def test_original_signature_still_works(self):
        """Existing callers pass (message, raw_content=...) — must not break."""
        e = YAMLParseError("parse failed", raw_content="some raw text")
        assert str(e) == "parse failed"
        assert e.raw_content == "some raw text"
        assert e.failure_type == ParseFailureType.wrong_schema  # default

    def test_with_failure_type(self):
        e = YAMLParseError(
            "empty",
            raw_content="",
            failure_type=ParseFailureType.empty_response,
        )
        assert e.failure_type == ParseFailureType.empty_response

    def test_message_only_with_raw_content(self):
        """Common pattern: YAMLParseError('msg', raw_content='...')."""
        e = YAMLParseError("error message", raw_content="raw")
        assert str(e) == "error message"
        assert e.raw_content == "raw"

    def test_default_raw_content_is_empty(self):
        e = YAMLParseError("error")
        assert e.raw_content == ""
        assert e.failure_type == ParseFailureType.empty_response

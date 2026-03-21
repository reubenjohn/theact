"""Tests for CLI command parsing and menu utilities."""

from theact.cli.commands import parse_command
from theact.cli.menu import slugify
from theact.cli.styles import CHARACTER_COLORS, get_character_color


class TestParseCommand:
    """Tests for the slash command parser."""

    def test_simple_command(self):
        assert parse_command("/help") == ("help", [])

    def test_command_with_args(self):
        assert parse_command("/undo 3") == ("undo", ["3"])

    def test_command_with_multiple_args(self):
        assert parse_command("/memory maya chen") == ("memory", ["maya", "chen"])

    def test_not_a_command(self):
        assert parse_command("hello") is None

    def test_empty_string(self):
        assert parse_command("") is None

    def test_just_slash(self):
        assert parse_command("/") is None

    def test_leading_whitespace(self):
        assert parse_command("  /help") == ("help", [])

    def test_trailing_whitespace(self):
        assert parse_command("/help  ") == ("help", [])

    def test_extra_spaces_between_args(self):
        assert parse_command("/undo  3") == ("undo", ["3"])

    def test_uppercase_normalized(self):
        assert parse_command("/UNDO") == ("undo", [])

    def test_mixed_case_normalized(self):
        assert parse_command("/Help") == ("help", [])

    def test_command_think_on(self):
        assert parse_command("/think on") == ("think", ["on"])

    def test_command_think_off(self):
        assert parse_command("/think off") == ("think", ["off"])

    def test_command_conversation_with_count(self):
        assert parse_command("/conversation 10") == ("conversation", ["10"])

    def test_command_retry(self):
        assert parse_command("/retry") == ("retry", [])


class TestSlugify:
    """Tests for the slugify function."""

    def test_simple(self):
        assert slugify("my playthrough") == "my-playthrough"

    def test_uppercase(self):
        assert slugify("My Playthrough") == "my-playthrough"

    def test_special_characters(self):
        assert slugify("my play!through@2") == "my-playthrough2"

    def test_multiple_spaces(self):
        assert slugify("my  play  through") == "my-play-through"

    def test_leading_trailing_spaces(self):
        assert slugify("  my playthrough  ") == "my-playthrough"

    def test_hyphens_preserved(self):
        assert slugify("my-playthrough") == "my-playthrough"

    def test_multiple_hyphens_collapsed(self):
        assert slugify("my---playthrough") == "my-playthrough"

    def test_empty_string_returns_save(self):
        assert slugify("") == "save"

    def test_only_special_chars_returns_save(self):
        assert slugify("!!!") == "save"


class TestGetCharacterColor:
    """Tests for deterministic character color assignment."""

    def test_first_character(self):
        chars = ["maya", "joaquin"]
        assert get_character_color("maya", chars) == CHARACTER_COLORS[0]

    def test_second_character(self):
        chars = ["maya", "joaquin"]
        assert get_character_color("joaquin", chars) == CHARACTER_COLORS[1]

    def test_deterministic(self):
        chars = ["maya", "joaquin"]
        c1 = get_character_color("maya", chars)
        c2 = get_character_color("maya", chars)
        assert c1 == c2

    def test_unknown_character_uses_hash_fallback(self):
        chars = ["maya", "joaquin"]
        # Should not raise -- uses hash fallback
        color = get_character_color("unknown", chars)
        assert color in CHARACTER_COLORS

    def test_wraps_around_palette(self):
        # More characters than colors
        chars = [f"char{i}" for i in range(len(CHARACTER_COLORS) + 2)]
        # The character at index len(CHARACTER_COLORS) wraps to index 0
        assert (
            get_character_color(chars[len(CHARACTER_COLORS)], chars)
            == CHARACTER_COLORS[0]
        )

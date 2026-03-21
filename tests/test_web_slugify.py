"""Tests for the web UI slugify function."""

from theact.web.app import slugify


class TestSlugify:
    """Tests for slugify — converts free-form text to URL-safe slugs."""

    # --- Basic transformations ---

    def test_spaces_become_hyphens(self):
        assert slugify("my playthrough") == "my-playthrough"

    def test_uppercase_lowered(self):
        assert slugify("My Playthrough") == "my-playthrough"

    def test_special_characters_removed(self):
        assert slugify("my play!through@2") == "my-playthrough2"

    def test_multiple_spaces_collapsed(self):
        assert slugify("my  play  through") == "my-play-through"

    def test_multiple_hyphens_collapsed(self):
        assert slugify("my---playthrough") == "my-playthrough"

    def test_leading_trailing_whitespace_stripped(self):
        assert slugify("  my playthrough  ") == "my-playthrough"

    def test_hyphens_preserved(self):
        assert slugify("my-playthrough") == "my-playthrough"

    # --- Fallback to "save" ---

    def test_empty_string_returns_save(self):
        assert slugify("") == "save"

    def test_whitespace_only_returns_save(self):
        assert slugify("   ") == "save"

    def test_only_special_chars_returns_save(self):
        assert slugify("!!!@#$%^&*()") == "save"

    def test_only_hyphens_returns_save(self):
        assert slugify("---") == "save"

    # --- Numbers ---

    def test_numbers_preserved(self):
        assert slugify("save 42") == "save-42"

    def test_numeric_only_input(self):
        assert slugify("123") == "123"

    # --- Mixed hyphens and spaces ---

    def test_mixed_hyphens_and_spaces(self):
        assert slugify("my - play - through") == "my-play-through"

    def test_spaces_around_hyphens(self):
        assert slugify("hello - world") == "hello-world"

    # --- Unicode and emoji ---

    def test_unicode_stripped(self):
        assert slugify("cafe\u0301") == "cafe"

    def test_emoji_stripped(self):
        assert slugify("fun \U0001f525 game") == "fun-game"

    def test_all_emoji_returns_save(self):
        assert slugify("\U0001f600\U0001f525\U0001f3ae") == "save"

    # --- Whitespace variants ---

    def test_tab_characters_become_hyphens(self):
        assert slugify("my\tplaythrough") == "my-playthrough"

    def test_newline_characters_become_hyphens(self):
        assert slugify("my\nplaythrough") == "my-playthrough"

    def test_mixed_whitespace(self):
        assert slugify("my \t\n playthrough") == "my-playthrough"

    # --- Edge cases ---

    def test_single_character(self):
        assert slugify("a") == "a"

    def test_single_number(self):
        assert slugify("7") == "7"

    def test_leading_hyphens_stripped(self):
        assert slugify("-hello") == "hello"

    def test_trailing_hyphens_stripped(self):
        assert slugify("hello-") == "hello"

    def test_leading_and_trailing_hyphens_stripped(self):
        assert slugify("--hello--") == "hello"

    def test_leading_special_chars_produce_clean_slug(self):
        assert slugify("!!!hello") == "hello"

    def test_trailing_special_chars_produce_clean_slug(self):
        assert slugify("hello!!!") == "hello"

    def test_already_valid_slug(self):
        assert slugify("good-slug-123") == "good-slug-123"

    def test_long_mixed_input(self):
        assert slugify("  Hello,  World!  --  2024  ") == "hello-world-2024"

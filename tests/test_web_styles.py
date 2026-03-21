"""Tests for the web UI styles module — color palette and assignment."""

import re

from theact.web.styles import CHARACTER_COLORS, get_character_color


class TestCharacterColors:
    """Tests for the CHARACTER_COLORS palette constant."""

    def test_palette_has_six_colors(self):
        assert len(CHARACTER_COLORS) == 6

    def test_all_colors_are_valid_hex(self):
        hex_pattern = re.compile(r"^#[0-9a-fA-F]{6}$")
        for color in CHARACTER_COLORS:
            assert hex_pattern.match(color), f"{color} is not valid hex"

    def test_all_colors_unique(self):
        assert len(set(CHARACTER_COLORS)) == len(CHARACTER_COLORS)


class TestGetCharacterColor:
    """Tests for get_character_color — deterministic color by roster index."""

    # --- Index-based assignment ---

    def test_first_character_gets_first_color(self):
        chars = ["maya", "joaquin"]
        assert get_character_color("maya", chars) == CHARACTER_COLORS[0]

    def test_second_character_gets_second_color(self):
        chars = ["maya", "joaquin"]
        assert get_character_color("joaquin", chars) == CHARACTER_COLORS[1]

    def test_all_six_colors_assigned_in_order(self):
        chars = [f"char{i}" for i in range(6)]
        for i, name in enumerate(chars):
            assert get_character_color(name, chars) == CHARACTER_COLORS[i]

    def test_wrapping_beyond_six(self):
        chars = [f"char{i}" for i in range(8)]
        # Index 6 wraps to color 0
        assert get_character_color("char6", chars) == CHARACTER_COLORS[0]
        # Index 7 wraps to color 1
        assert get_character_color("char7", chars) == CHARACTER_COLORS[1]

    # --- Hash fallback for unknown characters ---

    def test_unknown_character_uses_hash_fallback(self):
        chars = ["maya", "joaquin"]
        color = get_character_color("unknown", chars)
        assert color in CHARACTER_COLORS

    def test_hash_fallback_is_deterministic(self):
        chars = ["maya", "joaquin"]
        c1 = get_character_color("unknown", chars)
        c2 = get_character_color("unknown", chars)
        assert c1 == c2

    def test_empty_list_uses_hash_fallback(self):
        color = get_character_color("maya", [])
        assert color in CHARACTER_COLORS

    def test_result_is_valid_hex_color(self):
        chars = ["maya", "joaquin"]
        hex_pattern = re.compile(r"^#[0-9a-fA-F]{6}$")
        for name in chars:
            color = get_character_color(name, chars)
            assert hex_pattern.match(color), f"{color} is not valid hex"

    # --- Edge cases ---

    def test_empty_string_name_in_list(self):
        chars = ["", "joaquin"]
        color = get_character_color("", chars)
        assert color == CHARACTER_COLORS[0]

    def test_empty_string_name_not_in_list(self):
        chars = ["maya"]
        color = get_character_color("", chars)
        assert color in CHARACTER_COLORS

    def test_duplicate_names_returns_first_occurrence(self):
        chars = ["maya", "joaquin", "maya"]
        # list.index returns first occurrence (0), so color should be index 0
        assert get_character_color("maya", chars) == CHARACTER_COLORS[0]

    def test_same_name_different_positions(self):
        # "maya" at index 0 in one list, index 2 in another
        assert get_character_color("maya", ["maya", "b"]) == CHARACTER_COLORS[0]
        assert get_character_color("maya", ["a", "b", "maya"]) == CHARACTER_COLORS[2]

    def test_single_character_list(self):
        assert get_character_color("solo", ["solo"]) == CHARACTER_COLORS[0]

    def test_known_character_deterministic(self):
        chars = ["maya", "joaquin", "silva"]
        c1 = get_character_color("silva", chars)
        c2 = get_character_color("silva", chars)
        assert c1 == c2
        assert c1 == CHARACTER_COLORS[2]

    def test_different_unknown_chars_can_differ(self):
        """Two unknown names with different hashes may get different colors."""
        chars = ["maya"]
        c1 = get_character_color("alpha", chars)
        c2 = get_character_color("beta", chars)
        # Both must be valid colors (they may or may not differ)
        assert c1 in CHARACTER_COLORS
        assert c2 in CHARACTER_COLORS

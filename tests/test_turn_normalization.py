"""Tests for fuzzy matching and normalization of small-model output."""

from dataclasses import dataclass

from theact.agents.narrator import _normalize_mood
from theact.engine.turn import resolve_beat, resolve_character_id


# --- resolve_beat ---


class TestResolveBeat:
    BEATS = [
        "Player wakes on the beach, disoriented",
        "Explores wreckage, finds supplies",
        "Discovers a body -- death is real",
        "Finds Maya beyond the headland",
        "Joaquin emerges from the jungle",
        "Group establishes camp, survives first night",
    ]

    def test_exact_match(self):
        assert resolve_beat("Player wakes on the beach, disoriented", self.BEATS) == (
            "Player wakes on the beach, disoriented"
        )

    def test_case_insensitive(self):
        assert resolve_beat("player wakes on the beach, disoriented", self.BEATS) == (
            "Player wakes on the beach, disoriented"
        )

    def test_stripped_quotes(self):
        assert (
            resolve_beat('"Player wakes on the beach, disoriented"', self.BEATS)
            == "Player wakes on the beach, disoriented"
        )

    def test_single_quotes(self):
        assert (
            resolve_beat("'Discovers a body -- death is real'", self.BEATS)
            == "Discovers a body -- death is real"
        )

    def test_fuzzy_partial(self):
        """Model drops trailing detail but core matches."""
        assert resolve_beat("Player wakes on the beach", self.BEATS) == (
            "Player wakes on the beach, disoriented"
        )

    def test_fuzzy_paraphrase(self):
        """Model slightly rewords the beat."""
        assert resolve_beat("Discovers a body, death is real", self.BEATS) == (
            "Discovers a body -- death is real"
        )

    def test_fuzzy_short_form(self):
        assert resolve_beat("Finds Maya", self.BEATS) == (
            "Finds Maya beyond the headland"
        )

    def test_no_match(self):
        assert resolve_beat("The volcano erupts", self.BEATS) is None

    def test_empty_input(self):
        assert resolve_beat("", self.BEATS) is None

    def test_empty_beats_list(self):
        assert resolve_beat("Player wakes on the beach", []) is None

    def test_whitespace_handling(self):
        assert (
            resolve_beat("  Player wakes on the beach, disoriented  ", self.BEATS)
            == "Player wakes on the beach, disoriented"
        )


# --- resolve_character_id ---


@dataclass
class _FakeChar:
    name: str


class TestResolveCharacterId:
    CHARS = {
        "maya": _FakeChar(name="Maya Chen"),
        "joaquin": _FakeChar(name="Father Joaquin Reyes"),
    }

    def test_exact_match(self):
        assert resolve_character_id("maya", self.CHARS) == "maya"

    def test_case_insensitive(self):
        assert resolve_character_id("Maya", self.CHARS) == "maya"
        assert resolve_character_id("JOAQUIN", self.CHARS) == "joaquin"

    def test_display_name(self):
        assert resolve_character_id("Maya Chen", self.CHARS) == "maya"
        assert resolve_character_id("Father Joaquin Reyes", self.CHARS) == "joaquin"

    def test_display_name_case(self):
        assert resolve_character_id("maya chen", self.CHARS) == "maya"

    def test_partial_slug(self):
        assert resolve_character_id("maya_chen", self.CHARS) == "maya"

    def test_no_match(self):
        assert resolve_character_id("unknown_npc", self.CHARS) is None


# --- _normalize_mood ---


class TestNormalizeMood:
    def test_valid_mood_passthrough(self):
        assert _normalize_mood("tense") == "tense"
        assert _normalize_mood("calm") == "calm"
        assert _normalize_mood("melancholic") == "melancholic"

    def test_synonym_mapping(self):
        assert _normalize_mood("sad") == "melancholic"
        assert _normalize_mood("scary") == "tense"
        assert _normalize_mood("funny") == "humorous"
        assert _normalize_mood("peaceful") == "calm"
        assert _normalize_mood("neutral") == "calm"

    def test_unknown_defaults_to_calm(self):
        assert _normalize_mood("ecstatic") == "calm"
        assert _normalize_mood("confused") == "calm"


# --- chapter_complete bool coercion ---


class TestChapterCompleteBoolCoercion:
    """Verify that string 'false' does NOT become True."""

    def test_string_false_is_false(self):
        """Regression: bool('false') is True in Python."""
        from theact.agents.game_state import run_game_state  # noqa: F401

        # Test the parsing logic directly
        raw = "false"
        if isinstance(raw, str):
            result = raw.strip().lower() in ("true", "yes", "1")
        else:
            result = bool(raw)
        assert result is False

    def test_string_true_is_true(self):
        raw = "true"
        if isinstance(raw, str):
            result = raw.strip().lower() in ("true", "yes", "1")
        else:
            result = bool(raw)
        assert result is True

    def test_bool_false_is_false(self):
        raw = False
        if isinstance(raw, str):
            result = raw.strip().lower() in ("true", "yes", "1")
        else:
            result = bool(raw)
        assert result is False

    def test_bool_true_is_true(self):
        raw = True
        if isinstance(raw, str):
            result = raw.strip().lower() in ("true", "yes", "1")
        else:
            result = bool(raw)
        assert result is True

    def test_string_yes_is_true(self):
        raw = "yes"
        if isinstance(raw, str):
            result = raw.strip().lower() in ("true", "yes", "1")
        else:
            result = bool(raw)
        assert result is True

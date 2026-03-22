"""Tests for fuzzy beat matching and character ID normalization."""

from dataclasses import dataclass

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

    def test_empty_string(self):
        assert resolve_character_id("", self.CHARS) is None

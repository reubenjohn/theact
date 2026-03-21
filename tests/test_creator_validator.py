"""Tests for creator validator."""

from theact.creator.validator import (
    check_size_warnings,
    validate_game_data,
)


def _valid_game_data() -> dict:
    """A fully valid game data dict modeled on Lost Island."""
    return {
        "game": {
            "id": "test-game",
            "title": "Test Game",
            "description": "A test game for validation.",
            "characters": ["maya", "joaquin"],
            "chapters": ["01-the-crash", "02-survival"],
        },
        "world": {
            "setting": "An uncharted island in the South Pacific, 2024.",
            "tone": "Second person, present tense. 150-300 words per turn.",
            "rules": "NPCs remember everything. Never break the second-person frame.",
        },
        "characters": {
            "maya": {
                "name": "Maya Chen",
                "role": "Fellow survivor, pragmatic engineer.",
                "personality": "Direct, sharp, dry humor. Short sentences. Competence is her coping mechanism.",
                "secret": "Racing home to her estranged mother who has cancer.",
                "relationships": {
                    "joaquin": "Respects his calm but distrusts his evasiveness.",
                },
            },
            "joaquin": {
                "name": "Father Joaquin Reyes",
                "role": "Mysterious priest who has been here before.",
                "personality": "Calm, cryptic, speaks in parables. Genuinely kind but evasive.",
                "secret": "Visited this island 40 years ago.",
                "relationships": {
                    "maya": "Admires her strength but worries about her stubbornness.",
                },
            },
        },
        "chapters": {
            "01-the-crash": {
                "id": "01-the-crash",
                "title": "The Crash",
                "summary": "Player wakes on the beach. Finds Maya. They establish camp.",
                "beats": [
                    "Player wakes on the beach",
                    "Explores crash debris",
                    "Discovers a body",
                    "Finds Maya beyond the headland",
                    "Together they establish camp",
                ],
                "completion": "Player and Maya have established camp.",
                "characters": ["maya"],
                "next": "02-survival",
            },
            "02-survival": {
                "id": "02-survival",
                "title": "Survival",
                "summary": "Struggle to survive. Find Joaquin in the jungle.",
                "beats": [
                    "Search for fresh water",
                    "Discover fruit trees with strange markings",
                    "Find Joaquin praying at a stone altar",
                    "Tensions rise as supplies dwindle",
                ],
                "completion": "All three survivors are together.",
                "characters": ["maya", "joaquin"],
                "next": None,
            },
        },
    }


class TestValidateGameData:
    def test_valid_data_passes(self):
        data = _valid_game_data()
        result = validate_game_data(data)
        assert result.valid is True
        assert result.errors == []
        assert result.game is not None
        assert result.world is not None
        assert len(result.characters) == 2
        assert len(result.chapters) == 2

    def test_missing_game_field(self):
        data = _valid_game_data()
        del data["game"]["id"]
        result = validate_game_data(data)
        assert result.valid is False
        assert any("game.yaml" in e.file for e in result.errors)

    def test_missing_world_field(self):
        data = _valid_game_data()
        del data["world"]["setting"]
        result = validate_game_data(data)
        assert result.valid is False
        assert any("world.yaml" in e.file for e in result.errors)

    def test_extra_field_rejected(self):
        data = _valid_game_data()
        data["world"]["mood"] = "spooky"
        result = validate_game_data(data)
        assert result.valid is False
        assert any("world.yaml" in e.file for e in result.errors)

    def test_character_missing_field(self):
        data = _valid_game_data()
        del data["characters"]["maya"]["name"]
        result = validate_game_data(data)
        assert result.valid is False
        assert any("characters/maya.yaml" in e.file for e in result.errors)

    def test_chapter_missing_field(self):
        data = _valid_game_data()
        del data["chapters"]["01-the-crash"]["beats"]
        result = validate_game_data(data)
        assert result.valid is False
        assert any("chapters/01-the-crash.yaml" in e.file for e in result.errors)


class TestCrossReferences:
    def test_missing_character_file(self):
        data = _valid_game_data()
        data["game"]["characters"].append("ghost")
        result = validate_game_data(data)
        assert result.valid is False
        assert any("ghost" in e.message for e in result.errors)

    def test_extra_character_file(self):
        data = _valid_game_data()
        data["characters"]["ghost"] = {
            "name": "Ghost",
            "role": "Haunts the island.",
            "personality": "Silent.",
            "secret": "Was once alive.",
            "relationships": {},
        }
        result = validate_game_data(data)
        assert result.valid is False
        assert any("not listed in game.yaml" in e.message for e in result.errors)

    def test_missing_chapter_file(self):
        data = _valid_game_data()
        data["game"]["chapters"].append("03-missing")
        result = validate_game_data(data)
        assert result.valid is False
        assert any("03-missing" in e.message for e in result.errors)

    def test_broken_chapter_next(self):
        data = _valid_game_data()
        data["chapters"]["01-the-crash"]["next"] = "99-nonexistent"
        result = validate_game_data(data)
        assert result.valid is False
        assert any("99-nonexistent" in e.message for e in result.errors)

    def test_invalid_chapter_character_ref(self):
        data = _valid_game_data()
        data["chapters"]["01-the-crash"]["characters"] = ["ghost"]
        result = validate_game_data(data)
        assert result.valid is False
        assert any("ghost" in e.message for e in result.errors)

    def test_self_referencing_relationship(self):
        data = _valid_game_data()
        data["characters"]["maya"]["relationships"]["maya"] = "Talks to herself."
        result = validate_game_data(data)
        assert result.valid is False
        assert any("relationship with itself" in e.message for e in result.errors)

    def test_invalid_relationship_key(self):
        data = _valid_game_data()
        data["characters"]["maya"]["relationships"]["nonexistent"] = "Unknown."
        result = validate_game_data(data)
        assert result.valid is False
        assert any("nonexistent" in e.message for e in result.errors)

    def test_chapter_next_chain_mismatch(self):
        """next chain should match game.yaml chapter order."""
        data = _valid_game_data()
        # Game says [01, 02] so 01->02 and 02->None.
        # Break it by making 01 point to None.
        data["chapters"]["01-the-crash"]["next"] = None
        result = validate_game_data(data)
        assert result.valid is False
        assert any("Expected next=" in e.message for e in result.errors)


class TestCharacterCountLimits:
    def test_zero_characters(self):
        data = _valid_game_data()
        data["characters"] = {}
        data["game"]["characters"] = []
        result = validate_game_data(data)
        assert result.valid is False
        assert any(
            "No characters" in e.message or "At least 1" in e.message
            for e in result.errors
        )

    def test_four_characters_too_many(self):
        data = _valid_game_data()
        for name in ["c1", "c2", "c3", "c4"]:
            data["characters"][name] = {
                "name": name.upper(),
                "role": "Extra.",
                "personality": "None.",
                "secret": "None.",
                "relationships": {},
            }
        data["game"]["characters"] = list(data["characters"].keys())
        result = validate_game_data(data)
        assert result.valid is False
        assert any("Too many characters" in e.message for e in result.errors)

    def test_three_characters_ok(self):
        data = _valid_game_data()
        data["characters"]["elena"] = {
            "name": "Elena",
            "role": "Doctor.",
            "personality": "Calm.",
            "secret": "None.",
            "relationships": {
                "maya": "Neutral.",
                "joaquin": "Curious.",
            },
        }
        data["game"]["characters"].append("elena")
        # Fix existing character relationships to include elena
        data["characters"]["maya"]["relationships"]["elena"] = "Skeptical."
        data["characters"]["joaquin"]["relationships"]["elena"] = "Interested."
        result = validate_game_data(data)
        assert result.valid is True


class TestCircularChain:
    def test_detects_circular_chain(self):
        data = _valid_game_data()
        # Make 02 point back to 01 (circular)
        data["chapters"]["02-survival"]["next"] = "01-the-crash"
        result = validate_game_data(data)
        assert result.valid is False
        # Should detect both the chain mismatch and the circular chain
        error_messages = [e.message for e in result.errors]
        assert any("Circular" in m for m in error_messages)


class TestSizeWarnings:
    def test_no_warnings_for_small_files(self):
        data = _valid_game_data()
        result = validate_game_data(data)
        warnings = check_size_warnings(result.world, result.characters, result.chapters)
        assert warnings == []

    def test_warns_on_verbose_world(self):
        data = _valid_game_data()
        result = validate_game_data(data)
        # Inject a very long setting
        result.world.setting = " ".join(["word"] * 200)  # type: ignore[union-attr]
        warnings = check_size_warnings(result.world, result.characters, result.chapters)
        assert any("world.yaml" in w for w in warnings)

    def test_warns_on_verbose_character(self):
        data = _valid_game_data()
        result = validate_game_data(data)
        result.characters["maya"].personality = " ".join(["word"] * 100)
        warnings = check_size_warnings(result.world, result.characters, result.chapters)
        assert any("characters/maya.yaml" in w for w in warnings)

    def test_warns_on_too_many_beats(self):
        data = _valid_game_data()
        data["chapters"]["01-the-crash"]["beats"] = [f"Beat {i}" for i in range(8)]
        result = validate_game_data(data)
        warnings = check_size_warnings(result.world, result.characters, result.chapters)
        assert any("too many" in w.lower() or "8 beats" in w for w in warnings)

    def test_warns_on_too_few_beats(self):
        data = _valid_game_data()
        data["chapters"]["01-the-crash"]["beats"] = ["Only one beat"]
        result = validate_game_data(data)
        warnings = check_size_warnings(result.world, result.characters, result.chapters)
        assert any("too few" in w.lower() or "1 beats" in w for w in warnings)

    def test_warns_on_long_beat(self):
        data = _valid_game_data()
        data["chapters"]["01-the-crash"]["beats"][0] = " ".join(["word"] * 20)
        result = validate_game_data(data)
        warnings = check_size_warnings(result.world, result.characters, result.chapters)
        assert any("beat" in w.lower() and "words" in w.lower() for w in warnings)

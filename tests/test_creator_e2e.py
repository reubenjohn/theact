"""End-to-end test for game creation: proposal -> generation -> validation -> write."""

from pathlib import Path

import pytest

from tests.conftest import creator_config, make_mock_client
from theact.creator.generator import generate_game_files
from theact.creator.proposer import generate_proposal
from theact.creator.validator import check_size_warnings, validate_game_data
from theact.creator.writer import write_game_files
from theact.io.yaml_io import load_yaml
from theact.models.chapter import Chapter
from theact.models.character import Character
from theact.models.game import GameMeta
from theact.models.world import World


# --- Canned LLM responses ---

CANNED_PROPOSAL = """\
title: "Midnight on Vine"
id: "midnight-on-vine"
setting: |
  Los Angeles, 1947. Rain-slicked boulevards and neon signs.
tone: |
  Second person, present tense. Hard-boiled narration. 100-250 words per turn.
rules: |
  Every character has an alibi and a lie. Never reveal a character's secret directly.
characters:
  - stem: "dolores"
    name: "Dolores Vane"
    role: "Nightclub singer, the missing person's sister."
  - stem: "kowalski"
    name: "Sergeant Kowalski"
    role: "Homicide cop, friendly on the surface."
chapters:
  - id: "01-the-office"
    title: "The Office"
    summary: "A woman walks in with a photo and a story."
  - id: "02-the-nightclub"
    title: "The Nightclub"
    summary: "Player visits the Blue Moon to ask questions."
  - id: "03-the-truth"
    title: "The Truth"
    summary: "The threads converge. Someone is lying."
"""

CANNED_GENERATION = """\
game:
  id: "midnight-on-vine"
  title: "Midnight on Vine"
  description: "A noir detective mystery in 1940s Los Angeles."
  characters:
    - dolores
    - kowalski
  chapters:
    - 01-the-office
    - 02-the-nightclub
    - 03-the-truth

world:
  setting: |
    Los Angeles, 1947. Rain-slicked boulevards, neon signs, and the smell
    of cigarette smoke. The war is over but its ghosts linger.
  tone: |
    Second person, present tense. Hard-boiled narration -- short sentences,
    sharp observations, moral ambiguity. 100-250 words per turn.
  rules: |
    Every character has an alibi and a lie. The player can miss clues but
    never be blocked from progress. Never reveal a character's secret directly.

characters:
  dolores:
    name: "Dolores Vane"
    role: "Nightclub singer, the missing person's sister."
    personality: |
      Sultry voice, guarded eyes. Speaks in half-truths and
      deflections. Lights a cigarette when she's stalling.
    secret: "She knows her sister is already dead."
    relationships:
      kowalski: "Despises him but needs his protection."

  kowalski:
    name: "Sergeant Kowalski"
    role: "Homicide cop, friendly on the surface."
    personality: |
      Big smile, firm handshake. Asks questions like
      he already knows the answers. Never raises his voice.
    secret: "He is being blackmailed by the nightclub owner."
    relationships:
      dolores: "Attracted to her but suspects she is involved."

chapters:
  01-the-office:
    id: "01-the-office"
    title: "The Office"
    summary: |
      A woman walks into the player's office with a photo
      and a story that doesn't add up.
    beats:
      - "Woman arrives with a photograph"
      - "Player examines the photo -- something is wrong"
      - "She mentions the Blue Moon nightclub"
      - "Player agrees to take the case"
    completion: "Player has agreed to investigate and has the photograph."
    characters:
      - dolores
    next: "02-the-nightclub"

  02-the-nightclub:
    id: "02-the-nightclub"
    title: "The Nightclub"
    summary: |
      The player visits the Blue Moon to ask questions.
      Everyone has an answer, none of them match.
    beats:
      - "Player enters the Blue Moon"
      - "Dolores performs on stage"
      - "Kowalski appears at the bar"
      - "Player finds a clue in the back room"
    completion: "Player has spoken to both Dolores and Kowalski at the club."
    characters:
      - dolores
      - kowalski
    next: "03-the-truth"

  03-the-truth:
    id: "03-the-truth"
    title: "The Truth"
    summary: |
      The threads converge. Someone is lying about the
      night of the disappearance.
    beats:
      - "Player confronts Dolores with evidence"
      - "Kowalski arrives uninvited"
      - "A third party reveals a crucial detail"
      - "Player must choose who to trust"
    completion: "Player has uncovered the truth about the disappearance."
    characters:
      - dolores
      - kowalski
    next: null
"""


@pytest.mark.asyncio
class TestEndToEnd:
    async def test_full_creation_flow(self, tmp_path: Path):
        """Test: concept -> proposal -> generation -> validation -> write."""
        client = make_mock_client(
            [
                f"```yaml\n{CANNED_PROPOSAL}```",
                f"```yaml\n{CANNED_GENERATION}```",
            ]
        )
        config = creator_config()

        # Step 1: Generate proposal
        proposal = await generate_proposal(
            "A noir detective mystery in 1940s LA",
            client,
            config,
        )
        assert proposal["title"] == "Midnight on Vine"
        assert proposal["id"] == "midnight-on-vine"
        assert len(proposal["characters"]) == 2
        assert len(proposal["chapters"]) == 3

        # Step 2: Generate game files
        data = await generate_game_files(proposal, client, config)
        assert "game" in data
        assert "world" in data
        assert "characters" in data
        assert "chapters" in data

        # Step 3: Validate
        result = validate_game_data(data)
        assert result.valid, f"Validation errors: {result.errors}"
        assert result.game is not None
        assert result.world is not None
        assert len(result.characters) == 2
        assert len(result.chapters) == 3

        # Step 4: Size warnings
        warnings = check_size_warnings(result.world, result.characters, result.chapters)
        # The canned data should be within limits
        for w in warnings:
            assert "too many" not in w.lower()

        # Step 5: Write to disk
        game_path = write_game_files("midnight-on-vine", result, games_dir=tmp_path)
        assert game_path.exists()

        # Step 6: Verify written files load back
        meta = load_yaml(game_path / "game.yaml", GameMeta)
        assert meta.id == "midnight-on-vine"
        assert meta.characters == ["dolores", "kowalski"]
        assert len(meta.chapters) == 3

        world = load_yaml(game_path / "world.yaml", World)
        assert "Los Angeles" in world.setting

        dolores = load_yaml(game_path / "characters" / "dolores.yaml", Character)
        assert dolores.name == "Dolores Vane"
        assert "kowalski" in dolores.relationships

        kowalski = load_yaml(game_path / "characters" / "kowalski.yaml", Character)
        assert kowalski.name == "Sergeant Kowalski"

        ch1 = load_yaml(game_path / "chapters" / "01-the-office.yaml", Chapter)
        assert ch1.next == "02-the-nightclub"

        ch3 = load_yaml(game_path / "chapters" / "03-the-truth.yaml", Chapter)
        assert ch3.next is None

    async def test_generated_files_within_size_limits(self, tmp_path: Path):
        """Verify the canned output meets size constraints."""
        client = make_mock_client(
            [
                f"```yaml\n{CANNED_PROPOSAL}```",
                f"```yaml\n{CANNED_GENERATION}```",
            ]
        )
        config = creator_config()

        proposal = await generate_proposal("test", client, config)
        data = await generate_game_files(proposal, client, config)
        result = validate_game_data(data)
        assert result.valid

        # World under 150 words
        world = result.world
        world_words = len(f"{world.setting} {world.tone} {world.rules}".split())
        assert world_words <= 150, f"World is {world_words} words"

        # Each character under 80 words
        for stem, char in result.characters.items():
            char_words = len(
                f"{char.role} {char.personality} {char.secret} "
                f"{' '.join(char.relationships.values())}".split()
            )
            assert char_words <= 80, f"{stem} is {char_words} words"

        # Each chapter has 4-6 beats
        for cid, chap in result.chapters.items():
            assert 4 <= len(chap.beats) <= 6, f"{cid} has {len(chap.beats)} beats"

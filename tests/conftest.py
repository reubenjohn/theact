"""Shared fixtures for TheAct tests."""

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from unittest.mock import AsyncMock, MagicMock

import pytest

from theact.creator.config import CreatorLLMConfig

# Path to the example game definition included in the repo
GAMES_DIR = Path(__file__).parent.parent / "games"


@pytest.fixture
def sample_world_data() -> dict:
    return {
        "setting": "A dark forest in medieval Europe, 1347.",
        "tone": "Second person, present tense. Gritty and tense.",
        "rules": "Magic does not exist. Death is permanent.",
    }


@pytest.fixture
def sample_character_data() -> dict:
    return {
        "name": "Elena",
        "role": "A traveling healer seeking a cure for the plague.",
        "personality": "Calm and methodical. Speaks precisely. Hides her fear behind competence.",
        "secret": "She is immune to the plague and does not know why.",
        "relationships": {"brother": "Protective but resentful of his recklessness."},
    }


@pytest.fixture
def sample_chapter_data() -> dict:
    return {
        "id": "01-arrival",
        "title": "The Arrival",
        "summary": "The player arrives at the village gate. The guards are suspicious.",
        "beats": [
            "Player approaches the village",
            "Guards challenge the player",
            "Player gains entry",
        ],
        "completion": "Player has entered the village.",
        "characters": ["elena"],
        "next": "02-the-market",
    }


@pytest.fixture
def sample_state_data() -> dict:
    return {
        "player_name": "Alex",
        "current_chapter": "01-arrival",
        "turn": 3,
        "beats_hit": ["Player approaches the village"],
        "flags": {"village_gate": "open"},
        "chapter_history": [],
        "rolling_summary": "",
    }


@pytest.fixture
def sample_conversation_entry_data() -> dict:
    return {
        "turn": 1,
        "role": "narrator",
        "content": "You stand before the village gate. Torchlight flickers above.",
    }


@pytest.fixture
def sample_memory_data() -> dict:
    return {
        "character": "Elena",
        "summary": "Met the player at the gate. They seem trustworthy but secretive.",
        "key_facts": [
            "Player arrived alone",
            "Player carries a sealed letter",
        ],
    }


@pytest.fixture
def sample_game_meta_data() -> dict:
    return {
        "id": "test-game",
        "title": "Test Game",
        "description": "A game for testing.",
        "characters": ["elena"],
        "chapters": ["01-arrival"],
    }


@pytest.fixture
def games_dir(tmp_path: Path) -> Path:
    """Copy the example games directory to a temp location for testing."""
    dest = tmp_path / "games"
    shutil.copytree(GAMES_DIR, dest)
    return dest


@pytest.fixture
def saves_dir(tmp_path: Path) -> Path:
    """Create an empty saves directory for testing."""
    d = tmp_path / "saves"
    d.mkdir()
    return d


def make_mock_client(responses: list[str]) -> AsyncMock:
    """Create an AsyncOpenAI mock that returns canned responses in sequence."""
    client = AsyncMock()
    call_count = 0

    async def fake_create(**kwargs):
        nonlocal call_count
        idx = min(call_count, len(responses) - 1)
        call_count += 1
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = responses[idx]
        return mock_response

    client.chat.completions.create = fake_create
    return client


def creator_config(**overrides) -> CreatorLLMConfig:
    """Create a CreatorLLMConfig for testing with sensible defaults."""
    defaults = {"api_key": "test-key", "model": "test-model"}
    defaults.update(overrides)
    return CreatorLLMConfig(**defaults)


# ---------------------------------------------------------------------------
# Shared helpers for simulating OpenAI streaming responses
# ---------------------------------------------------------------------------


@dataclass
class FakeDelta:
    content: Optional[str] = None
    model_extra: Optional[dict] = None


@dataclass
class FakeChoice:
    delta: FakeDelta
    finish_reason: Optional[str] = None


@dataclass
class FakeChunk:
    choices: list[FakeChoice]


class AsyncChunkIterator:
    """Async iterator over a list of fake chunks."""

    def __init__(self, chunks):
        self._chunks = chunks
        self._index = 0

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._index >= len(self._chunks):
            raise StopAsyncIteration
        chunk = self._chunks[self._index]
        self._index += 1
        return chunk


def make_chunks(specs: list[dict]) -> list[FakeChunk]:
    """Create fake streaming chunks from a list of specs.

    Each spec can have:
    - content: str -- delta content text
    - reasoning_content: str -- thinking via model_extra
    - finish_reason: str -- e.g. "stop"
    """
    chunks = []
    for spec in specs:
        model_extra = None
        if "reasoning_content" in spec:
            model_extra = {"reasoning_content": spec["reasoning_content"]}

        delta = FakeDelta(
            content=spec.get("content"),
            model_extra=model_extra,
        )
        choice = FakeChoice(
            delta=delta,
            finish_reason=spec.get("finish_reason"),
        )
        chunks.append(FakeChunk(choices=[choice]))
    return chunks


def make_chunk(
    content=None,
    reasoning_content=None,
    reasoning=None,
    finish_reason=None,
) -> FakeChunk:
    """Build a single FakeChunk with the given fields.

    Supports both ``reasoning_content`` (primary) and ``reasoning``
    (fallback) keys in model_extra.
    """
    model_extra = None
    if reasoning_content is not None:
        model_extra = {"reasoning_content": reasoning_content}
    elif reasoning is not None:
        model_extra = {"reasoning": reasoning}

    delta = FakeDelta(content=content, model_extra=model_extra)
    choice = FakeChoice(delta=delta, finish_reason=finish_reason)
    return FakeChunk(choices=[choice])

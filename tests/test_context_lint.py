"""Context window lint tests: verify agent prompts fit within budget.

Uses a real game fixture (lost-island) to build actual messages for each
agent, then profiles them to ensure prompt + max_tokens <= context_limit.
"""

import shutil
from pathlib import Path

import pytest

from theact.engine.context import (
    build_character_messages,
    build_game_state_messages,
    build_memory_messages,
    build_narrator_messages,
    build_rolling_summary_messages,
    build_summary_messages,
)
from theact.engine.types import NarratorOutput
from theact.io.save_manager import create_save, load_save
from theact.llm.config import (
    CHARACTER_CONFIG,
    GAME_STATE_CONFIG,
    LLMConfig,
    MEMORY_UPDATE_CONFIG,
    NARRATOR_CONFIG,
    SUMMARIZER_CONFIG,
)
from theact.llm.profiler import profile_messages
from theact.models.conversation import ConversationEntry
from theact.models.game import LoadedGame

GAMES_DIR = Path(__file__).parent.parent / "games"


@pytest.fixture
def llm_config() -> LLMConfig:
    return LLMConfig(api_key="test-key-not-real")


@pytest.fixture
def lost_island_game(tmp_path: Path) -> LoadedGame:
    games_dir = tmp_path / "games"
    shutil.copytree(GAMES_DIR, games_dir)
    saves_dir = tmp_path / "saves"
    saves_dir.mkdir()
    create_save(
        "lost-island",
        "lint-test",
        "Alex",
        games_dir=games_dir,
        saves_dir=saves_dir,
    )
    return load_save("lint-test", saves_dir=saves_dir)


def _make_entries(num_turns: int = 2) -> list[ConversationEntry]:
    entries: list[ConversationEntry] = []
    for t in range(1, num_turns + 1):
        entries.append(
            ConversationEntry(turn=t, role="narrator", content=f"Turn {t} narration.")
        )
        entries.append(
            ConversationEntry(turn=t, role="player", content=f"Turn {t} player action.")
        )
    return entries


class TestContextFitsWindow:
    """All agents must have prompt + max_tokens <= context_limit (headroom >= 0)."""

    def test_narrator_headroom(
        self, lost_island_game: LoadedGame, llm_config: LLMConfig
    ):
        messages = build_narrator_messages(
            lost_island_game, "I look around.", llm_config
        )
        max_tokens = NARRATOR_CONFIG.max_tokens or llm_config.default_max_tokens
        profile = profile_messages(
            "narrator", messages, max_tokens, llm_config.context_limit
        )
        assert profile.headroom >= 0, (
            f"Narrator is over budget: headroom={profile.headroom}, "
            f"prompt={profile.total_prompt_tokens}, "
            f"max_tokens={max_tokens}"
        )

    def test_character_headroom(
        self, lost_island_game: LoadedGame, llm_config: LLMConfig
    ):
        maya = lost_island_game.characters["maya"]
        narrator_output = NarratorOutput(
            narration="You see someone ahead.",
            responding_characters=["maya"],
            mood="tense",
        )
        messages = build_character_messages(
            lost_island_game,
            maya,
            None,
            "Hello?",
            narrator_output,
            [],
            llm_config,
        )
        max_tokens = CHARACTER_CONFIG.max_tokens or llm_config.default_max_tokens
        profile = profile_messages(
            "character:maya", messages, max_tokens, llm_config.context_limit
        )
        assert profile.headroom >= 0, (
            f"Character is over budget: headroom={profile.headroom}, "
            f"prompt={profile.total_prompt_tokens}, "
            f"max_tokens={max_tokens}"
        )

    def test_memory_headroom(self, lost_island_game: LoadedGame, llm_config: LLMConfig):
        maya = lost_island_game.characters["maya"]
        entries = _make_entries(2)
        messages = build_memory_messages(maya, None, entries)
        max_tokens = MEMORY_UPDATE_CONFIG.max_tokens or llm_config.default_max_tokens
        profile = profile_messages(
            "memory:maya", messages, max_tokens, llm_config.context_limit
        )
        assert profile.headroom >= 0, (
            f"Memory is over budget: headroom={profile.headroom}, "
            f"prompt={profile.total_prompt_tokens}, "
            f"max_tokens={max_tokens}"
        )

    def test_game_state_headroom(
        self, lost_island_game: LoadedGame, llm_config: LLMConfig
    ):
        entries = _make_entries(2)
        messages = build_game_state_messages(lost_island_game, entries)
        if not messages:
            pytest.skip("No current chapter — game_state returns empty")
        max_tokens = GAME_STATE_CONFIG.max_tokens or llm_config.default_max_tokens
        profile = profile_messages(
            "game_state", messages, max_tokens, llm_config.context_limit
        )
        assert profile.headroom >= 0, (
            f"Game state is over budget: headroom={profile.headroom}, "
            f"prompt={profile.total_prompt_tokens}, "
            f"max_tokens={max_tokens}"
        )

    def test_chapter_summary_headroom(
        self, lost_island_game: LoadedGame, llm_config: LLMConfig
    ):
        lost_island_game.conversation = _make_entries(3)
        chapter = lost_island_game.chapters["01-the-crash"]
        messages = build_summary_messages(lost_island_game, chapter)
        max_tokens = SUMMARIZER_CONFIG.max_tokens or llm_config.default_max_tokens
        profile = profile_messages(
            "summarizer", messages, max_tokens, llm_config.context_limit
        )
        assert profile.headroom >= 0, (
            f"Summarizer is over budget: headroom={profile.headroom}, "
            f"prompt={profile.total_prompt_tokens}, "
            f"max_tokens={max_tokens}"
        )

    def test_rolling_summary_headroom(self, llm_config: LLMConfig):
        entries = _make_entries(3)
        messages = build_rolling_summary_messages("Summary so far.", entries)
        max_tokens = SUMMARIZER_CONFIG.max_tokens or llm_config.default_max_tokens
        profile = profile_messages(
            "summarizer", messages, max_tokens, llm_config.context_limit
        )
        assert profile.headroom >= 0, (
            f"Rolling summary is over budget: headroom={profile.headroom}, "
            f"prompt={profile.total_prompt_tokens}, "
            f"max_tokens={max_tokens}"
        )

"""Unit tests for GameplaySession methods that don't require NiceGUI context.

GameplaySession.__init__ only stores references — it does NOT create UI
elements. So we can construct a session and test pure-logic properties
and methods without a running NiceGUI server.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock


from theact.llm.config import LLMConfig
from theact.models.chapter import Chapter
from theact.models.character import Character
from theact.models.game import GameMeta, LoadedGame
from theact.models.state import GameState
from theact.models.world import World
from theact.web.session import GameplaySession


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_character(name: str) -> Character:
    return Character(
        name=name,
        role="Guide",
        personality="Stoic",
        secret="None",
        relationships={},
    )


def _make_chapter(chapter_id: str, title: str) -> Chapter:
    return Chapter(
        id=chapter_id,
        title=title,
        summary="Summary",
        beats=["a"],
        completion="Done",
        characters=[],
        next=None,
    )


def _make_game(
    tmp_path: Path,
    characters: dict[str, Character] | None = None,
    chapters: dict[str, Chapter] | None = None,
    current_chapter: str = "01-arrival",
) -> LoadedGame:
    save_path = tmp_path / "saves" / "test-save"
    save_path.mkdir(parents=True, exist_ok=True)

    if characters is None:
        characters = {
            "elena": _make_character("Elena"),
        }
    if chapters is None:
        chapters = {
            "01-arrival": _make_chapter("01-arrival", "The Arrival"),
        }

    return LoadedGame(
        meta=GameMeta(
            id="test",
            title="Test",
            description="Test",
            characters=list(characters.keys()),
            chapters=list(chapters.keys()),
        ),
        world=World(setting="Forest", tone="Grim", rules="No magic"),
        characters=characters,
        chapters=chapters,
        state=GameState(
            player_name="Alex",
            current_chapter=current_chapter,
            turn=3,
            beats_hit=[],
            flags={},
            chapter_history=[],
        ),
        conversation=[],
        memories={},
        chapter_summaries=[],
        save_path=save_path,
    )


def _make_session(game: LoadedGame) -> GameplaySession:
    return GameplaySession(
        game=game,
        llm_config=LLMConfig(api_key="test"),
        on_quit=MagicMock(),
    )


# ---------------------------------------------------------------------------
# Tests: character_list property
# ---------------------------------------------------------------------------


class TestCharacterList:
    def test_returns_character_keys(self, tmp_path: Path) -> None:
        game = _make_game(
            tmp_path,
            characters={
                "elena": _make_character("Elena"),
                "joaquin": _make_character("Joaquin"),
            },
        )
        session = _make_session(game)
        assert session.character_list == ["elena", "joaquin"]

    def test_empty_characters(self, tmp_path: Path) -> None:
        game = _make_game(tmp_path, characters={})
        session = _make_session(game)
        assert session.character_list == []

    def test_single_character(self, tmp_path: Path) -> None:
        game = _make_game(
            tmp_path,
            characters={"maya": _make_character("Maya")},
        )
        session = _make_session(game)
        assert session.character_list == ["maya"]

    def test_order_matches_insertion(self, tmp_path: Path) -> None:
        characters = {
            "zara": _make_character("Zara"),
            "amir": _make_character("Amir"),
            "luna": _make_character("Luna"),
        }
        game = _make_game(tmp_path, characters=characters)
        session = _make_session(game)
        assert session.character_list == ["zara", "amir", "luna"]


# ---------------------------------------------------------------------------
# Tests: _current_chapter_title method
# ---------------------------------------------------------------------------


class TestCurrentChapterTitle:
    def test_known_chapter_returns_title(self, tmp_path: Path) -> None:
        game = _make_game(
            tmp_path,
            chapters={"01-arrival": _make_chapter("01-arrival", "The Arrival")},
            current_chapter="01-arrival",
        )
        session = _make_session(game)
        assert session._current_chapter_title() == "The Arrival"

    def test_unknown_chapter_returns_id(self, tmp_path: Path) -> None:
        game = _make_game(
            tmp_path,
            chapters={"01-arrival": _make_chapter("01-arrival", "The Arrival")},
            current_chapter="99-missing",
        )
        session = _make_session(game)
        assert session._current_chapter_title() == "99-missing"

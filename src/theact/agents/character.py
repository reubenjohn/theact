"""Character agent: streams a single character's in-character response."""

from __future__ import annotations

from typing import Awaitable, Callable

from theact.engine.context import build_character_messages
from theact.engine.types import CharacterResponse, NarratorOutput
from theact.llm.config import CHARACTER_CONFIG, LLMConfig
from theact.llm.inference import stream
from theact.models.character import Character
from theact.models.game import LoadedGame
from theact.models.memory import CharacterMemory

StreamCallback = Callable[[str], Awaitable[None]]


async def run_character(
    game: LoadedGame,
    character: Character,
    memory: CharacterMemory | None,
    player_input: str,
    narrator_output: NarratorOutput,
    prior_responses: list[CharacterResponse],
    llm_config: LLMConfig,
    on_token: StreamCallback | None = None,
) -> CharacterResponse:
    """Run a character agent.

    Streams plain text tokens for live display.
    Returns the character's dialogue/action response.
    """
    messages = build_character_messages(
        game=game,
        character=character,
        memory=memory,
        player_input=player_input,
        narrator_output=narrator_output,
        prior_responses=prior_responses,
        llm_config=llm_config,
    )

    content_parts: list[str] = []

    async for chunk in await stream(
        messages=messages,
        llm_config=llm_config,
        agent_config=CHARACTER_CONFIG,
    ):
        if chunk.content:
            content_parts.append(chunk.content)
            if on_token:
                await on_token(chunk.content)

    content = "".join(content_parts)

    return CharacterResponse(
        character=character.name,
        response=content.strip(),
    )

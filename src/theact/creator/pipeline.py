"""Decomposed generation pipeline: per-file generation orchestrated by code."""

from __future__ import annotations

from collections.abc import Callable

from openai import AsyncOpenAI

from theact.creator.assembler import assemble_game_meta, enforce_consistency
from theact.creator.chapter_gen import generate_chapter
from theact.creator.character_gen import generate_character
from theact.creator.config import CreatorLLMConfig
from theact.creator.world_gen import generate_world


async def run_generation_pipeline(
    proposal: dict,
    client: AsyncOpenAI,
    config: CreatorLLMConfig,
    on_progress: Callable[[str], None] | None = None,
) -> dict:
    """Generate all game files through a decomposed pipeline.

    Calls each generator in sequence:
    1. World (1 call)
    2. Characters (1 call each, sequential -- each sees prior characters)
    3. Chapters (1 call each, sequential -- each sees characters + prior chapters)
    4. game.yaml (code-assembled, no LLM call)

    Args:
        proposal: Approved proposal dict.
        client: AsyncOpenAI client.
        config: Creator LLM configuration.
        on_progress: Optional callback for status updates.

    Returns:
        dict with keys: "game", "world", "characters", "chapters"
    """
    if not proposal.get("characters"):
        raise ValueError("Proposal has no characters. At least 1 is required.")

    if on_progress:
        on_progress("Generating world...")
    world_data = await generate_world(proposal, client, config)

    characters_data: dict[str, dict] = {}
    char_stems = [c["stem"] for c in proposal["characters"]]
    for char_info in proposal["characters"]:
        stem = char_info["stem"]
        if on_progress:
            on_progress(f"Generating character: {char_info['name']}...")
        characters_data[stem] = await generate_character(
            proposal=proposal,
            char_info=char_info,
            all_stems=char_stems,
            prior_characters=characters_data,
            client=client,
            config=config,
        )

    chapters_data: dict[str, dict] = {}
    for i, chap_info in enumerate(proposal["chapters"]):
        cid = chap_info["id"]
        if on_progress:
            on_progress(f"Generating chapter: {chap_info['title']}...")
        next_id = (
            proposal["chapters"][i + 1]["id"]
            if i + 1 < len(proposal["chapters"])
            else None
        )
        chapters_data[cid] = await generate_chapter(
            proposal=proposal,
            chap_info=chap_info,
            characters=characters_data,
            prior_chapters=chapters_data,
            next_chapter_id=next_id,
            client=client,
            config=config,
        )

    # Assemble game.yaml from the generated data -- pure code, no LLM
    game_data = assemble_game_meta(proposal, characters_data, chapters_data)

    result = {
        "game": game_data,
        "world": world_data,
        "characters": characters_data,
        "chapters": chapters_data,
    }

    # Apply code-enforced consistency fixes
    return enforce_consistency(result)

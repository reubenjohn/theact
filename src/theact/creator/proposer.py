"""Generate and revise game proposals via LLM.

Phase 12: Decomposed into 3 focused steps (setting → characters → chapters)
plus assembly. The monolithic generate_proposal() is retained for backward
compatibility but the session now uses the decomposed flow.
"""

from __future__ import annotations

import yaml
from openai import AsyncOpenAI

from theact.creator.config import CreatorLLMConfig
from theact.creator.generator import (
    YAMLParseError,
    extract_yaml,
    parse_proposal_response,
)
from theact.creator.prompts import (
    CHAPTERS_REVISION_USER,
    CHARACTERS_REVISION_USER,
    PROPOSAL_CHAPTERS_SYSTEM,
    PROPOSAL_CHAPTERS_USER,
    PROPOSAL_CHARACTERS_SYSTEM,
    PROPOSAL_CHARACTERS_USER,
    PROPOSAL_REVISION_USER,
    PROPOSAL_SYSTEM,
    PROPOSAL_USER,
    SETTING_REVISION_USER,
    SETTING_SYSTEM,
    SETTING_USER,
)


# ---------------------------------------------------------------------------
# Decomposed proposal steps
# ---------------------------------------------------------------------------


async def generate_setting(
    concept: str,
    client: AsyncOpenAI,
    config: CreatorLLMConfig,
) -> dict:
    """Generate setting, tone, and rules from a concept.

    Returns:
        dict with keys: title, id, setting, tone, rules
    """
    messages: list[dict] = [
        {"role": "system", "content": SETTING_SYSTEM},
        {"role": "user", "content": SETTING_USER.format(concept=concept)},
    ]

    response = await client.chat.completions.create(
        model=config.model,
        messages=messages,
        temperature=config.temperature,
        max_tokens=config.max_tokens_for("proposal"),
    )
    response_text = response.choices[0].message.content or ""

    data = extract_yaml(response_text)
    required = {"title", "id"}
    missing = required - set(data.keys())
    if missing:
        raise YAMLParseError(f"Setting YAML missing required keys: {missing}")
    return data


async def revise_setting(
    current_setting: dict,
    feedback: str,
    client: AsyncOpenAI,
    config: CreatorLLMConfig,
) -> dict:
    """Revise setting based on user feedback."""
    setting_yaml = yaml.dump(
        current_setting, default_flow_style=False, allow_unicode=True, sort_keys=False
    )
    messages: list[dict] = [
        {"role": "system", "content": SETTING_SYSTEM},
        {
            "role": "user",
            "content": SETTING_REVISION_USER.format(
                current_setting=setting_yaml,
                user_feedback=feedback,
            ),
        },
    ]

    response = await client.chat.completions.create(
        model=config.model,
        messages=messages,
        temperature=config.temperature,
        max_tokens=config.max_tokens_for("proposal"),
    )
    response_text = response.choices[0].message.content or ""
    return extract_yaml(response_text)


async def generate_characters_proposal(
    setting_data: dict,
    client: AsyncOpenAI,
    config: CreatorLLMConfig,
) -> dict:
    """Generate character sketches from the setting.

    Returns:
        dict with key: characters (list of {stem, name, role})
    """
    messages: list[dict] = [
        {"role": "system", "content": PROPOSAL_CHARACTERS_SYSTEM},
        {
            "role": "user",
            "content": PROPOSAL_CHARACTERS_USER.format(
                title=setting_data.get("title", ""),
                setting=setting_data.get("setting", ""),
                tone=setting_data.get("tone", ""),
            ),
        },
    ]

    response = await client.chat.completions.create(
        model=config.model,
        messages=messages,
        temperature=config.temperature,
        max_tokens=config.max_tokens_for("proposal"),
    )
    response_text = response.choices[0].message.content or ""

    data = extract_yaml(response_text)
    if "characters" not in data:
        raise YAMLParseError("Characters YAML missing 'characters' key")
    return data


async def revise_characters_proposal(
    current_characters: dict,
    setting_data: dict,
    feedback: str,
    client: AsyncOpenAI,
    config: CreatorLLMConfig,
) -> dict:
    """Revise character sketches based on user feedback."""
    chars_yaml = yaml.dump(
        current_characters,
        default_flow_style=False,
        allow_unicode=True,
        sort_keys=False,
    )
    messages: list[dict] = [
        {"role": "system", "content": PROPOSAL_CHARACTERS_SYSTEM},
        {
            "role": "user",
            "content": CHARACTERS_REVISION_USER.format(
                current_characters=chars_yaml,
                setting=setting_data.get("setting", ""),
                user_feedback=feedback,
            ),
        },
    ]

    response = await client.chat.completions.create(
        model=config.model,
        messages=messages,
        temperature=config.temperature,
        max_tokens=config.max_tokens_for("proposal"),
    )
    response_text = response.choices[0].message.content or ""
    return extract_yaml(response_text)


async def generate_chapters_proposal(
    setting_data: dict,
    characters_data: dict,
    client: AsyncOpenAI,
    config: CreatorLLMConfig,
) -> dict:
    """Generate chapter arc from setting and characters.

    Returns:
        dict with key: chapters (list of {id, title, summary})
    """
    char_names = [
        f"{c['name']} ({c['stem']})" for c in characters_data.get("characters", [])
    ]
    character_list = ", ".join(char_names) if char_names else "none"

    messages: list[dict] = [
        {"role": "system", "content": PROPOSAL_CHAPTERS_SYSTEM},
        {
            "role": "user",
            "content": PROPOSAL_CHAPTERS_USER.format(
                title=setting_data.get("title", ""),
                setting=setting_data.get("setting", ""),
                character_list=character_list,
            ),
        },
    ]

    response = await client.chat.completions.create(
        model=config.model,
        messages=messages,
        temperature=config.temperature,
        max_tokens=config.max_tokens_for("proposal"),
    )
    response_text = response.choices[0].message.content or ""

    data = extract_yaml(response_text)
    if "chapters" not in data:
        raise YAMLParseError("Chapters YAML missing 'chapters' key")
    return data


async def revise_chapters_proposal(
    current_chapters: dict,
    setting_data: dict,
    characters_data: dict,
    feedback: str,
    client: AsyncOpenAI,
    config: CreatorLLMConfig,
) -> dict:
    """Revise chapter arc based on user feedback."""
    chaps_yaml = yaml.dump(
        current_chapters,
        default_flow_style=False,
        allow_unicode=True,
        sort_keys=False,
    )
    char_names = [
        f"{c['name']} ({c['stem']})" for c in characters_data.get("characters", [])
    ]
    character_list = ", ".join(char_names) if char_names else "none"

    messages: list[dict] = [
        {"role": "system", "content": PROPOSAL_CHAPTERS_SYSTEM},
        {
            "role": "user",
            "content": CHAPTERS_REVISION_USER.format(
                current_chapters=chaps_yaml,
                title=setting_data.get("title", ""),
                character_list=character_list,
                user_feedback=feedback,
            ),
        },
    ]

    response = await client.chat.completions.create(
        model=config.model,
        messages=messages,
        temperature=config.temperature,
        max_tokens=config.max_tokens_for("proposal"),
    )
    response_text = response.choices[0].message.content or ""
    return extract_yaml(response_text)


def assemble_proposal(
    setting_data: dict,
    characters_data: dict,
    chapters_data: dict,
) -> dict:
    """Assemble a proposal dict from the 3 decomposed steps."""
    return {
        "title": setting_data["title"],
        "id": setting_data["id"],
        "setting": setting_data.get("setting", ""),
        "tone": setting_data.get("tone", ""),
        "rules": setting_data.get("rules", ""),
        "characters": characters_data["characters"],
        "chapters": chapters_data["chapters"],
    }


# ---------------------------------------------------------------------------
# Legacy monolithic proposal (retained for backward compatibility)
# ---------------------------------------------------------------------------


async def generate_proposal(
    concept: str,
    client: AsyncOpenAI,
    config: CreatorLLMConfig,
) -> dict:
    """Generate a game proposal from a concept description.

    Args:
        concept: The user's free-text game concept.
        client: AsyncOpenAI client.
        config: Creator LLM configuration.

    Returns:
        Proposal dict with keys: title, id, setting, tone, rules,
        characters, chapters.
    """
    messages: list[dict] = [
        {"role": "system", "content": PROPOSAL_SYSTEM},
        {"role": "user", "content": PROPOSAL_USER.format(concept=concept)},
    ]

    response = await client.chat.completions.create(
        model=config.model,
        messages=messages,
        temperature=config.temperature,
        max_tokens=config.proposal_max_tokens,
    )
    response_text = response.choices[0].message.content or ""

    return parse_proposal_response(response_text)


async def revise_proposal(
    current_proposal: dict,
    feedback: str,
    client: AsyncOpenAI,
    config: CreatorLLMConfig,
) -> dict:
    """Revise a proposal based on user feedback.

    Args:
        current_proposal: The current proposal dict.
        feedback: The user's feedback text.
        client: AsyncOpenAI client.
        config: Creator LLM configuration.

    Returns:
        Revised proposal dict.
    """
    proposal_yaml = yaml.dump(
        current_proposal,
        default_flow_style=False,
        allow_unicode=True,
        sort_keys=False,
    )

    messages: list[dict] = [
        {"role": "system", "content": PROPOSAL_SYSTEM},
        {
            "role": "user",
            "content": PROPOSAL_REVISION_USER.format(
                current_proposal=proposal_yaml,
                user_feedback=feedback,
            ),
        },
    ]

    response = await client.chat.completions.create(
        model=config.model,
        messages=messages,
        temperature=config.temperature,
        max_tokens=config.proposal_max_tokens,
    )
    response_text = response.choices[0].message.content or ""

    return parse_proposal_response(response_text)

"""Generate and revise game proposals via LLM."""

from __future__ import annotations

import yaml
from openai import AsyncOpenAI

from theact.creator.config import CreatorLLMConfig
from theact.creator.generator import _parse_proposal_response
from theact.creator.prompts import (
    PROPOSAL_REVISION_USER,
    PROPOSAL_SYSTEM,
    PROPOSAL_USER,
)


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

    return _parse_proposal_response(response_text)


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

    return _parse_proposal_response(response_text)

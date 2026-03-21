"""Generate full game definition files from an approved proposal."""

from __future__ import annotations

import re

import yaml
from openai import AsyncOpenAI

from theact.creator.config import CreatorLLMConfig
from theact.creator.prompts import GENERATION_SYSTEM, GENERATION_USER


class YAMLParseError(Exception):
    """Raised when the LLM response cannot be parsed as YAML."""


def _extract_yaml(response_text: str) -> dict:
    """Extract YAML from an LLM response, handling fenced or raw YAML.

    Returns the parsed dict. Raises YAMLParseError on failure.
    """
    match = re.search(r"```(?:yaml)?\s*\n(.*?)```", response_text, re.DOTALL)
    yaml_text = match.group(1) if match else response_text

    try:
        data = yaml.safe_load(yaml_text)
    except yaml.YAMLError as e:
        raise YAMLParseError(
            f"LLM response is not valid YAML: {e}\n"
            f"First 200 chars of response: {response_text[:200]}"
        )

    if not isinstance(data, dict):
        raise YAMLParseError(
            f"Expected a YAML mapping, got {type(data).__name__}. "
            f"First 200 chars: {response_text[:200]}"
        )

    return data


def _parse_proposal_response(response_text: str) -> dict:
    """Extract and parse a proposal YAML from the LLM response.

    The proposal has keys: title, id, setting, tone, rules, characters, chapters.

    Returns:
        Proposal dict.

    Raises:
        YAMLParseError: if YAML cannot be extracted or parsed
    """
    data = _extract_yaml(response_text)

    required_keys = {"title", "id", "characters", "chapters"}
    missing = required_keys - set(data.keys())
    if missing:
        raise YAMLParseError(f"Proposal YAML is missing required keys: {missing}")

    return data


def _parse_generation_response(response_text: str) -> dict:
    """Extract and parse YAML from the LLM's generation response.

    Returns:
        dict with keys: "game", "world", "characters", "chapters"

    Raises:
        YAMLParseError: if YAML cannot be extracted or parsed
    """
    data = _extract_yaml(response_text)

    required_keys = {"game", "world", "characters", "chapters"}
    missing = required_keys - set(data.keys())
    if missing:
        raise YAMLParseError(f"YAML is missing required top-level keys: {missing}")

    return data


async def generate_game_files(
    proposal: dict,
    client: AsyncOpenAI,
    config: CreatorLLMConfig,
) -> dict:
    """Generate all game definition files from an approved proposal.

    Calls the LLM with the generation prompt, parses the YAML response,
    and retries up to 2 times on YAML parse failure.

    Args:
        proposal: The approved proposal dict from the proposer.
        client: AsyncOpenAI client.
        config: Creator LLM configuration.

    Returns:
        dict with keys: "game", "world", "characters", "chapters"

    Raises:
        YAMLParseError: if YAML cannot be parsed after all retries
    """
    proposal_yaml = yaml.dump(
        proposal, default_flow_style=False, allow_unicode=True, sort_keys=False
    )

    messages: list[dict] = [
        {"role": "system", "content": GENERATION_SYSTEM},
        {"role": "user", "content": GENERATION_USER.format(proposal=proposal_yaml)},
    ]

    last_error: YAMLParseError | None = None

    for attempt in range(3):
        response = await client.chat.completions.create(
            model=config.model,
            messages=messages,
            temperature=config.temperature,
            max_tokens=config.max_tokens,
        )
        response_text = response.choices[0].message.content or ""

        try:
            return _parse_generation_response(response_text)
        except YAMLParseError as e:
            last_error = e
            if attempt < 2:
                messages.append({"role": "assistant", "content": response_text})
                messages.append(
                    {
                        "role": "user",
                        "content": f"That output was not valid YAML: {e}\nPlease try again.",
                    }
                )

    raise last_error  # type: ignore[misc]

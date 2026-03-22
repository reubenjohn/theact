"""Generate full game definition files from an approved proposal."""

from __future__ import annotations

import re

import yaml
from openai import AsyncOpenAI

from theact.creator.config import CreatorLLMConfig
from theact.creator.prompts import GENERATION_SYSTEM, GENERATION_USER
from theact.llm.inference import strip_think_tags


class YAMLParseError(Exception):
    """Raised when the LLM response cannot be parsed as YAML."""


async def call_llm(
    client: AsyncOpenAI,
    config: CreatorLLMConfig,
    messages: list[dict],
    call_type: str | None = None,
) -> str:
    """Call the LLM and return the response text content.

    Args:
        call_type: Optional call type ("world", "character", "chapter", "fix")
            to select per-type max_tokens via config.max_tokens_for().
            When None, uses config.max_tokens.
    """
    budget = config.max_tokens_for(call_type) if call_type else config.max_tokens
    response = await client.chat.completions.create(
        model=config.model,
        messages=messages,
        temperature=config.temperature,
        max_tokens=budget,
    )
    choice = response.choices[0]
    text = choice.message.content or ""

    # Detect truncation with no usable content (common with thinking models
    # that spend the entire token budget on internal reasoning)
    if choice.finish_reason == "length" and not strip_think_tags(text).strip():
        raise YAMLParseError(
            f"Model response was truncated (max_tokens={budget} exhausted) "
            "with no YAML content produced. The model likely spent the entire "
            "token budget on internal reasoning. Increase max_tokens in "
            "creator settings."
        )

    return text


def serialize_game_data(data: dict) -> str:
    """Serialize a game data dict to a YAML string for prompt injection."""
    return yaml.dump(
        data, default_flow_style=False, allow_unicode=True, sort_keys=False
    )


def extract_yaml(response_text: str) -> dict:
    """Extract YAML from an LLM response, handling fenced or raw YAML.

    Strips <think>...</think> tags before parsing.
    Returns the parsed dict. Raises YAMLParseError on failure.
    """
    cleaned = strip_think_tags(response_text)

    if not cleaned.strip():
        if response_text.strip():
            raise YAMLParseError(
                "Model response contained only reasoning/thinking content "
                "with no YAML output. If using a thinking model, try "
                "increasing max_tokens in creator settings."
            )
        raise YAMLParseError("Model returned an empty response.")

    # Try to match a fully-fenced block first
    match = re.search(r"```(?:yaml)?\s*\n(.*?)```", cleaned, re.DOTALL)
    if match:
        yaml_text = match.group(1)
    else:
        # Fallback: handle truncated responses with opening fence but no closing
        open_match = re.search(r"```(?:yaml)?\s*\n(.*)", cleaned, re.DOTALL)
        yaml_text = open_match.group(1) if open_match else cleaned

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


def parse_proposal_response(response_text: str) -> dict:
    """Extract and parse a proposal YAML from the LLM response.

    The proposal has keys: title, id, setting, tone, rules, characters, chapters.

    Returns:
        Proposal dict.

    Raises:
        YAMLParseError: if YAML cannot be extracted or parsed
    """
    data = extract_yaml(response_text)

    required_keys = {"title", "id", "characters", "chapters"}
    missing = required_keys - set(data.keys())
    if missing:
        raise YAMLParseError(f"Proposal YAML is missing required keys: {missing}")

    return data


def parse_generation_response(response_text: str) -> dict:
    """Extract and parse YAML from the LLM's generation response.

    Returns:
        dict with keys: "game", "world", "characters", "chapters"

    Raises:
        YAMLParseError: if YAML cannot be extracted or parsed
    """
    data = extract_yaml(response_text)

    required_keys = {"game", "world", "characters", "chapters"}
    missing = required_keys - set(data.keys())
    if missing:
        raise YAMLParseError(f"YAML is missing required top-level keys: {missing}")

    return data


# Backward-compatible aliases for internal callers
_extract_yaml = extract_yaml
_parse_proposal_response = parse_proposal_response
_parse_generation_response = parse_generation_response


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

    MAX_ATTEMPTS = 3
    last_error: YAMLParseError | None = None

    for attempt in range(MAX_ATTEMPTS):
        response_text = await call_llm(client, config, messages)

        try:
            return parse_generation_response(response_text)
        except YAMLParseError as e:
            last_error = e
            if attempt < MAX_ATTEMPTS - 1:
                messages.append({"role": "assistant", "content": response_text})
                messages.append(
                    {
                        "role": "user",
                        "content": f"That output was not valid YAML: {e}\nPlease try again.",
                    }
                )

    raise last_error  # type: ignore[misc]

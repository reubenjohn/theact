"""Fix validation errors by feeding them back to the LLM."""

from __future__ import annotations

from openai import AsyncOpenAI

from theact.creator.config import CreatorLLMConfig
from theact.creator.generator import (
    YAMLParseError,
    _parse_generation_response,
    call_llm,
    serialize_game_data,
)
from theact.creator.prompts import FIX_SYSTEM, FIX_USER
from theact.creator.validator import ValidationResult, validate_game_data

MAX_FIX_ATTEMPTS = 3


async def fix_validation_errors(
    data: dict,
    validation_result: ValidationResult,
    client: AsyncOpenAI,
    config: CreatorLLMConfig,
) -> tuple[dict, ValidationResult]:
    """Attempt to fix validation errors by sending them back to the LLM.

    Returns the (possibly fixed) data and final validation result.
    Tries up to MAX_FIX_ATTEMPTS times.

    Handles two failure modes per attempt:
    1. LLM produces invalid YAML (YAMLParseError) -- counts as a failed attempt
    2. LLM produces valid YAML that fails Pydantic validation -- feeds errors back
    """
    current_data = data
    current_result = validation_result

    for _attempt in range(MAX_FIX_ATTEMPTS):
        if current_result.valid:
            return current_data, current_result

        error_text = "\n".join(
            f"- {e.file}: {e.message}" for e in current_result.errors
        )

        # Re-serialize current_data to YAML string for the prompt
        yaml_text = serialize_game_data(current_data)

        messages = [
            {"role": "system", "content": FIX_SYSTEM},
            {
                "role": "user",
                "content": FIX_USER.format(
                    errors=error_text,
                    original_output=yaml_text,
                ),
            },
        ]

        response = await call_llm(client, config, messages)
        try:
            current_data = _parse_generation_response(response)
        except YAMLParseError:
            # LLM produced unparseable output -- keep previous data and
            # let the loop retry with the same errors
            continue
        current_result = validate_game_data(current_data)

    return current_data, current_result

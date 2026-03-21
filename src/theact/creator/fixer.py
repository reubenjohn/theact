"""Fix validation errors by feeding them back to the LLM, file by file."""

from __future__ import annotations

import yaml
from openai import AsyncOpenAI

from theact.creator.assembler import assemble_game_meta_from_data, enforce_consistency
from theact.creator.config import CreatorLLMConfig
from theact.creator.generator import YAMLParseError, call_llm, extract_yaml
from theact.creator.prompts import FIX_SYSTEM, FIX_USER
from theact.creator.validator import (
    ValidationError,
    ValidationResult,
    validate_game_data,
)

MAX_FIX_ATTEMPTS = 3


async def fix_file(
    file_type: str,
    file_key: str,
    file_data: dict,
    errors: list[ValidationError],
    context: dict,
    client: AsyncOpenAI,
    config: CreatorLLMConfig,
) -> dict:
    """Fix validation errors in a single file.

    Returns the corrected data dict for this one file.
    """
    error_list = "\n".join(f"- {e.message}" for e in errors)
    file_yaml = yaml.dump(
        file_data, default_flow_style=False, allow_unicode=True, sort_keys=False
    )

    messages: list[dict] = [
        {"role": "system", "content": FIX_SYSTEM},
        {
            "role": "user",
            "content": FIX_USER.format(
                file_type=file_type,
                file_key=file_key,
                error_list=error_list,
                file_yaml=file_yaml,
            ),
        },
    ]

    response = await call_llm(client, config, messages)
    try:
        return extract_yaml(response)
    except YAMLParseError:
        return file_data  # Return unmodified on parse failure


def _group_errors_by_file(
    errors: list[ValidationError],
) -> dict[str, list[ValidationError]]:
    """Group validation errors by their file field."""
    groups: dict[str, list[ValidationError]] = {}
    for e in errors:
        groups.setdefault(e.file, []).append(e)
    return groups


def _parse_file_key(file_key: str) -> tuple[str, str]:
    """Parse a file key like 'characters/maya.yaml' into (type, stem).

    Returns:
        (file_type, stem) where file_type is 'world', 'characters', 'chapters', or 'game'
    """
    if file_key == "world.yaml":
        return "world", "world"
    if file_key == "game.yaml":
        return "game", "game"
    if "/" in file_key:
        # e.g., "characters/maya.yaml" -> ("characters", "maya")
        parts = file_key.replace(".yaml", "").split("/", 1)
        return parts[0], parts[1]
    return "unknown", file_key


def _update_data(data: dict, file_type: str, stem: str, fixed: dict) -> None:
    """Update the data dict in-place with a fixed file."""
    if file_type == "world":
        data["world"] = fixed
    elif file_type == "characters":
        data["characters"][stem] = fixed
    elif file_type == "chapters":
        data["chapters"][stem] = fixed


async def fix_validation_errors(
    data: dict,
    validation_result: ValidationResult,
    client: AsyncOpenAI,
    config: CreatorLLMConfig,
) -> tuple[dict, ValidationResult]:
    """Fix validation errors file-by-file.

    Groups errors by file, fixes each broken file individually,
    then re-validates the whole game. Repeats up to MAX_FIX_ATTEMPTS.
    """
    current_data = data

    for _attempt in range(MAX_FIX_ATTEMPTS):
        current_result = validate_game_data(current_data)
        if current_result.valid:
            return current_data, current_result

        errors_by_file = _group_errors_by_file(current_result.errors)

        for file_key, file_errors in errors_by_file.items():
            file_type, stem = _parse_file_key(file_key)
            if file_type == "world":
                file_data = current_data.get("world", {})
            elif file_type == "characters":
                file_data = current_data.get("characters", {}).get(stem, {})
            elif file_type == "chapters":
                file_data = current_data.get("chapters", {}).get(stem, {})
            else:
                # game.yaml errors are fixed by reassembly below
                continue

            fixed = await fix_file(
                file_type,
                stem,
                file_data,
                file_errors,
                context={"title": current_data.get("game", {}).get("title", "")},
                client=client,
                config=config,
            )
            _update_data(current_data, file_type, stem, fixed)

        # Always re-assemble game.yaml after fixes
        current_data["game"] = assemble_game_meta_from_data(current_data)

        # Apply code-enforced consistency fixes
        current_data = enforce_consistency(current_data)

    current_result = validate_game_data(current_data)
    return current_data, current_result

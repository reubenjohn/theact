"""YAML extraction and parsing for structured LLM output."""

from __future__ import annotations

import logging
import re
from typing import Any

import yaml

logger = logging.getLogger(__name__)


class YAMLParseError(Exception):
    """Raised when YAML extraction or parsing fails."""

    def __init__(self, message: str, raw_content: str):
        super().__init__(message)
        self.raw_content = raw_content


def extract_yaml_block(text: str) -> str:
    """Extract YAML content from a fenced code block in the response.

    Looks for ```yaml ... ``` first.
    Falls back to ``` ... ``` (unfenced but code-blocked).
    Falls back to treating the entire response as YAML if no blocks found.
    """
    # Try ```yaml ... ``` first.
    # Use findall and take the LAST match -- the model may include example
    # YAML blocks earlier in its response before the actual answer.
    matches = re.findall(r"```yaml\s*\n(.*?)```", text, re.DOTALL)
    if matches:
        return matches[-1].strip()

    # Try generic ``` ... ```
    matches = re.findall(r"```\s*\n(.*?)```", text, re.DOTALL)
    if matches:
        return matches[-1].strip()

    # No code block found -- try the whole text as YAML.
    logger.warning(
        "No fenced YAML block found in response; attempting to parse "
        "entire text as YAML. This may produce unexpected results."
    )
    return text.strip()


def parse_yaml_response(text: str) -> dict[str, Any]:
    """Extract and parse YAML from LLM response text.

    Raises YAMLParseError with a descriptive message on failure.
    """
    yaml_str = extract_yaml_block(text)

    try:
        result = yaml.safe_load(yaml_str)
    except yaml.YAMLError as e:
        raise YAMLParseError(
            f"YAML parse error: {e}",
            raw_content=text,
        ) from e

    if not isinstance(result, dict):
        raise YAMLParseError(
            f"Expected YAML to parse as a dictionary, got {type(result).__name__}",
            raw_content=text,
        )

    return result


def validate_yaml_fields(
    data: dict[str, Any],
    required_fields: list[str],
) -> list[str]:
    """Check that required fields are present.

    Returns list of missing field names.
    Does not raise -- caller decides whether to retry or proceed
    with partial data.
    """
    return [f for f in required_fields if f not in data]

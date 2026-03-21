"""YAML extraction and parsing for structured LLM output."""

from __future__ import annotations

import logging
import re
from typing import Any

import yaml

from theact.llm.errors import ParseFailureType

logger = logging.getLogger(__name__)


class YAMLParseError(Exception):
    """Raised when YAML extraction or parsing fails."""

    def __init__(
        self,
        message: str,
        raw_content: str = "",
        failure_type: ParseFailureType | None = None,
    ):
        super().__init__(message)
        self.raw_content = raw_content
        self.failure_type = failure_type or classify_parse_failure(raw_content)


def classify_parse_failure(
    raw_content: str, error: Exception | None = None
) -> ParseFailureType:
    """Classify a parse failure based on the raw LLM response content.

    Returns the most specific ParseFailureType that matches the content.
    """
    # Empty or whitespace-only
    if not raw_content or not raw_content.strip():
        return ParseFailureType.empty_response

    stripped = raw_content.strip()

    # Starts with JSON-like characters
    if stripped.startswith("{") or stripped.startswith("["):
        return ParseFailureType.json_instead

    # Echo prompt detection: "You are" in first 50 chars
    if "You are" in raw_content[:50]:
        return ParseFailureType.echo_prompt

    # Has ```yaml block but YAML parsing fails
    if "```yaml" in raw_content:
        # Extract the YAML block and try to parse it
        matches = re.findall(r"```yaml\s*\n(.*?)```", raw_content, re.DOTALL)
        if matches:
            try:
                yaml.safe_load(matches[-1].strip())
            except yaml.YAMLError:
                return ParseFailureType.invalid_yaml
            # YAML parsed fine but caller still failed => wrong_schema
            return ParseFailureType.wrong_schema

    # Has valid YAML content but no fenced block
    if "```" not in raw_content:
        try:
            result = yaml.safe_load(stripped)
            if isinstance(result, dict):
                return ParseFailureType.no_yaml_block
        except yaml.YAMLError:
            pass

    # Default
    return ParseFailureType.wrong_schema


def extract_yaml_block(text: str) -> str:
    """Extract YAML content from a fenced code block in the response.

    Fallback chain (returns first that works):
    1. ```yaml ... ``` (take LAST match — model may restart blocks)
    2. ``` ... ```     (generic fenced block, LAST match)
    3. ```yaml without closing ``` (model ran out of tokens)
    4. ``` without closing ```
    5. Entire text as YAML
    """
    # 1. Try ```yaml ... ``` — take last match.
    matches = re.findall(r"```yaml\s*\n(.*?)```", text, re.DOTALL)
    if matches:
        return matches[-1].strip()

    # 2. Try generic ``` ... ``` — take last match.
    matches = re.findall(r"```\s*\n(.*?)```", text, re.DOTALL)
    if matches:
        return matches[-1].strip()

    # 3. Try ```yaml without closing backticks (model ran out of tokens).
    m = re.search(r"```yaml\s*\n(.*)", text, re.DOTALL)
    if m:
        logger.warning(
            "Found ```yaml block without closing backticks; "
            "model may have run out of tokens."
        )
        return m.group(1).strip()

    # 4. Try ``` without closing backticks.
    m = re.search(r"```\s*\n(.*)", text, re.DOTALL)
    if m:
        logger.warning(
            "Found ``` block without closing backticks; "
            "model may have run out of tokens."
        )
        return m.group(1).strip()

    # 5. No code block found — try the whole text as YAML.
    logger.warning(
        "No fenced YAML block found in response; attempting to parse "
        "entire text as YAML. This may produce unexpected results."
    )
    return text.strip()


def repair_yaml_text(text: str) -> str:
    """Attempt to fix common YAML formatting issues from 7B models.

    Applied fixes (in order):
    - Fix missing newline after ``|`` in block scalars:
      ``key: |value`` becomes ``key: |\\n  value``
    - Strip trailing non-YAML prose after valid YAML structure.
    """
    # Fix missing newline after | in block scalars.
    text = re.sub(r"(\w+): \|(\S)", r"\1: |\n  \2", text)

    # Strip trailing non-YAML prose: look for lines that are clearly
    # not YAML structure (no leading whitespace, no colon, no list dash).
    lines = text.split("\n")
    yaml_end = len(lines)
    # Walk backwards to find the last line that looks like YAML content.
    for i in range(len(lines) - 1, -1, -1):
        line = lines[i]
        stripped = line.strip()
        if not stripped:
            continue
        # Looks like YAML: key:, - item, or indented content
        if (
            re.match(r"^\s*[\w\"'].*:", line)
            or re.match(r"^\s*-\s", line)
            or re.match(r"^\s+\S", line)
        ):
            yaml_end = i + 1
            break
        # Looks like prose — keep walking back
    else:
        # All lines look like prose; return as-is (let caller handle error)
        return text

    return "\n".join(lines[:yaml_end])


def parse_yaml_response(text: str) -> dict[str, Any]:
    """Extract and parse YAML from LLM response text.

    Raises YAMLParseError with a descriptive message on failure.
    """
    yaml_str = extract_yaml_block(text)

    # Normalize tabs to two spaces (7B models sometimes use tabs).
    yaml_str = yaml_str.replace("\t", "  ")

    try:
        result = yaml.safe_load(yaml_str)
    except yaml.YAMLError:
        # First parse failed — try repair before giving up.
        repaired = repair_yaml_text(yaml_str)
        try:
            result = yaml.safe_load(repaired)
            logger.warning(
                "YAML parse succeeded after repair; original text had "
                "formatting issues."
            )
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

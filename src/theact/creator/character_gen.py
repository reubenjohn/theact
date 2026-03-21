"""Generate one character's YAML data."""

from __future__ import annotations

from openai import AsyncOpenAI

from theact.creator.config import CreatorLLMConfig
from theact.creator.generator import YAMLParseError, call_llm, extract_yaml
from theact.creator.prompts import CHARACTER_SYSTEM, CHARACTER_USER


async def generate_character(
    proposal: dict,
    char_info: dict,
    all_stems: list[str],
    prior_characters: dict[str, dict],
    client: AsyncOpenAI,
    config: CreatorLLMConfig,
    feedback: str | None = None,
) -> dict:
    """Generate one character's YAML data.

    Args:
        proposal: Full proposal dict (for title/setting context).
        char_info: This character's proposal entry (stem, name, role).
        all_stems: All character stems in the game.
        prior_characters: Already-generated character data dicts.
        feedback: Optional user feedback for revision.

    Returns:
        dict with keys: "name", "role", "personality", "secret", "relationships"
    """
    stem = char_info["stem"]
    other_stems = [s for s in all_stems if s != stem]
    other_characters = ", ".join(other_stems) if other_stems else "none"

    # Build prior character context
    prior_lines = []
    for prev_stem, prev_data in prior_characters.items():
        prior_lines.append(
            f"  {prev_data.get('name', prev_stem)} ({prev_stem}): {prev_data.get('role', '')}"
        )
    prior_context = (
        "Already-created characters:\n" + "\n".join(prior_lines) if prior_lines else ""
    )

    user_content = CHARACTER_USER.format(
        title=proposal.get("title", ""),
        setting_summary=proposal.get("setting", ""),
        name=char_info.get("name", ""),
        role=char_info.get("role", ""),
        other_characters=other_characters,
        prior_character_context=prior_context,
    )
    if feedback:
        user_content += f"\n\nAdditional guidance: {feedback}"

    messages: list[dict] = [
        {"role": "system", "content": CHARACTER_SYSTEM},
        {"role": "user", "content": user_content},
    ]

    MAX_ATTEMPTS = 2
    last_error: YAMLParseError | None = None

    for attempt in range(MAX_ATTEMPTS):
        response_text = await call_llm(client, config, messages)
        try:
            data = extract_yaml(response_text)
            required = {"name", "role", "personality", "secret"}
            missing = required - set(data.keys())
            if missing:
                raise YAMLParseError(f"Character YAML missing required keys: {missing}")
            # Ensure relationships dict exists
            if "relationships" not in data:
                data["relationships"] = {}
            return data
        except YAMLParseError as e:
            last_error = e
            if attempt < MAX_ATTEMPTS - 1:
                messages.append({"role": "assistant", "content": response_text})
                messages.append(
                    {
                        "role": "user",
                        "content": f"That was not valid YAML: {e}\nPlease try again.",
                    }
                )

    raise last_error  # type: ignore[misc]

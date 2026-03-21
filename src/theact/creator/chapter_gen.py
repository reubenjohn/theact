"""Generate one chapter's YAML data."""

from __future__ import annotations

from openai import AsyncOpenAI

from theact.creator.config import CreatorLLMConfig
from theact.creator.generator import YAMLParseError, call_llm, extract_yaml
from theact.creator.prompts import CHAPTER_SYSTEM, CHAPTER_USER


async def generate_chapter(
    proposal: dict,
    chap_info: dict,
    characters: dict[str, dict],
    prior_chapters: dict[str, dict],
    next_chapter_id: str | None,
    client: AsyncOpenAI,
    config: CreatorLLMConfig,
    feedback: str | None = None,
) -> dict:
    """Generate one chapter's YAML data.

    Args:
        proposal: Full proposal dict (for title context).
        chap_info: This chapter's proposal entry (id, title, summary).
        characters: All generated character data dicts.
        prior_chapters: Already-generated chapter data dicts.
        next_chapter_id: The ID of the next chapter, or None for the last.
        feedback: Optional user feedback for revision.

    Returns:
        dict with keys: "id", "title", "summary", "beats", "completion",
                        "characters", "next"
    """
    character_list = ", ".join(characters.keys()) if characters else "none"

    # Build prior chapter context
    prior_lines = []
    for prev_id, prev_data in prior_chapters.items():
        prior_lines.append(
            f"  {prev_data.get('title', prev_id)}: {prev_data.get('summary', '')}"
        )
    prior_context = (
        "Previous chapters:\n" + "\n".join(prior_lines) if prior_lines else ""
    )

    next_str = next_chapter_id if next_chapter_id else "null"

    user_content = CHAPTER_USER.format(
        title=proposal.get("title", ""),
        character_list=character_list,
        chapter_id=chap_info.get("id", ""),
        chapter_title=chap_info.get("title", ""),
        chapter_summary=chap_info.get("summary", ""),
        next_chapter_id=next_str,
        prior_chapter_context=prior_context,
    )
    if feedback:
        user_content += f"\n\nAdditional guidance: {feedback}"

    messages: list[dict] = [
        {"role": "system", "content": CHAPTER_SYSTEM},
        {"role": "user", "content": user_content},
    ]

    MAX_ATTEMPTS = 2
    last_error: YAMLParseError | None = None

    for attempt in range(MAX_ATTEMPTS):
        response_text = await call_llm(client, config, messages)
        try:
            data = extract_yaml(response_text)
            required = {"id", "title", "summary", "beats", "completion"}
            missing = required - set(data.keys())
            if missing:
                raise YAMLParseError(f"Chapter YAML missing required keys: {missing}")
            # Ensure characters list exists
            if "characters" not in data:
                data["characters"] = list(characters.keys())
            # Code-enforce the next pointer
            data["next"] = next_chapter_id
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

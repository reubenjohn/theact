"""Generate world.yaml from a proposal."""

from __future__ import annotations

from openai import AsyncOpenAI

from theact.creator.config import CreatorLLMConfig
from theact.creator.generator import YAMLParseError, call_llm, extract_yaml
from theact.creator.prompts import WORLD_SYSTEM, WORLD_USER


async def generate_world(
    proposal: dict,
    client: AsyncOpenAI,
    config: CreatorLLMConfig,
    feedback: str | None = None,
) -> dict:
    """Generate world.yaml from the proposal.

    Returns:
        dict with keys: "setting", "tone", "rules"
    """
    user_content = WORLD_USER.format(
        title=proposal.get("title", ""),
        setting=proposal.get("setting", ""),
        tone=proposal.get("tone", ""),
        rules=proposal.get("rules", ""),
    )
    if feedback:
        user_content += f"\n\nAdditional guidance: {feedback}"

    messages: list[dict] = [
        {"role": "system", "content": WORLD_SYSTEM},
        {"role": "user", "content": user_content},
    ]

    MAX_ATTEMPTS = 2
    last_error: YAMLParseError | None = None

    for attempt in range(MAX_ATTEMPTS):
        response_text = await call_llm(client, config, messages)
        try:
            data = extract_yaml(response_text)
            # Validate required keys
            required = {"setting", "tone", "rules"}
            missing = required - set(data.keys())
            if missing:
                raise YAMLParseError(f"World YAML missing required keys: {missing}")
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

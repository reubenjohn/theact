"""Generate world.yaml from a proposal."""

from __future__ import annotations

from openai import AsyncOpenAI

from theact.creator.config import CreatorLLMConfig
from theact.creator.generator import call_llm_with_retry
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

    return await call_llm_with_retry(
        client,
        config,
        messages,
        call_type="world",
        required_keys={"setting", "tone", "rules"},
        key_label="World YAML",
    )

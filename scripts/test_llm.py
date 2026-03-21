"""
Smoke test for the LLM client layer.
Run: uv run python scripts/test_llm.py

Requires VENICE_API_KEY in environment or .env file.
"""

import asyncio

from dotenv import load_dotenv

load_dotenv()

from theact.llm import (  # noqa: E402
    AgentLLMConfig,
    LLMResult,
    NARRATOR_CONFIG,
    StructuredResult,
    complete,
    complete_structured,
    estimate_messages_tokens,
    estimate_tokens,
    load_llm_config,
    stream,
)


async def test_complete():
    """Test basic non-streaming completion."""
    print("=== Test: complete() ===")
    config = load_llm_config()
    result = await complete(
        messages=[{"role": "user", "content": "Say hello in exactly 5 words."}],
        llm_config=config,
    )
    assert isinstance(result, LLMResult)
    print(f"  Content: {result.content}")
    print(
        f"  Thinking: {result.thinking[:100]}..."
        if result.thinking
        else "  Thinking: (none)"
    )
    print(f"  Finish reason: {result.finish_reason}")
    print("  PASSED\n")


async def test_stream():
    """Test streaming completion with thinking separation."""
    print("=== Test: stream() ===")
    config = load_llm_config()
    thinking_parts = []
    content_parts = []

    async for chunk in await stream(
        messages=[{"role": "user", "content": "What is 2+2? Explain briefly."}],
        llm_config=config,
    ):
        if chunk.is_thinking:
            thinking_parts.append(chunk.thinking)
        elif chunk.is_content:
            content_parts.append(chunk.content)

    content = "".join(content_parts)
    thinking = "".join(thinking_parts)
    print(f"  Content: {content}")
    print(f"  Thinking: {thinking[:100]}..." if thinking else "  Thinking: (none)")
    print("  PASSED\n")


async def test_structured():
    """Test YAML-parsed structured output."""
    print("=== Test: complete_structured() ===")
    config = load_llm_config()
    result = await complete_structured(
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a narrator for a text RPG. "
                    "Respond with a brief narration and metadata in a YAML block.\n\n"
                    "```yaml\n"
                    "narration: |\n"
                    "  [Your narration here]\n"
                    "responding_characters:\n"
                    "  - character_1\n"
                    "mood: calm\n"
                    "```"
                ),
            },
            {"role": "user", "content": "I enter the tavern."},
        ],
        llm_config=config,
        agent_config=NARRATOR_CONFIG,
        yaml_hint=(
            "narration: |\\n  ...\\nresponding_characters:"
            "\\n  - ...\\nmood: calm|tense|urgent"
        ),
    )
    assert isinstance(result, StructuredResult)
    print(f"  Parsed data: {result.data}")
    print(f"  Attempts: {result.attempts}")
    print(f"  Raw content: {result.raw_content[:200]}...")
    print("  PASSED\n")


async def test_token_estimation():
    """Test token estimation utilities (no API call needed)."""
    print("=== Test: token estimation ===")
    text = "Hello, world! This is a test of token estimation."
    tokens = estimate_tokens(text)
    print(f"  '{text}' -> ~{tokens} tokens")

    messages = [
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "Hello!"},
    ]
    msg_tokens = estimate_messages_tokens(messages)
    print(f"  2-message conversation -> ~{msg_tokens} tokens")
    print("  PASSED\n")


async def test_parallel():
    """Test parallel calls via asyncio.gather (simulates post-turn processing)."""
    print("=== Test: parallel calls ===")
    config = load_llm_config()

    async def call(prompt: str) -> str:
        result = await complete(
            messages=[{"role": "user", "content": prompt}],
            llm_config=config,
            agent_config=AgentLLMConfig(max_tokens=100),
        )
        return result.content

    results = await asyncio.gather(
        call("Say 'alpha' and nothing else."),
        call("Say 'beta' and nothing else."),
        call("Say 'gamma' and nothing else."),
    )

    for i, r in enumerate(results):
        print(f"  Call {i}: {r.strip()}")
    print("  PASSED\n")


async def main():
    await test_token_estimation()  # no API call, always safe
    await test_complete()
    await test_stream()
    await test_structured()
    await test_parallel()
    print("All tests passed.")


if __name__ == "__main__":
    asyncio.run(main())

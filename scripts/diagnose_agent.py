"""Diagnostic tool for agent prompts and model responses.

Usage:
    uv run python scripts/diagnose_agent.py narrator "I open my eyes."
    uv run python scripts/diagnose_agent.py character "I look around." --character maya
    uv run python scripts/diagnose_agent.py memory
    uv run python scripts/diagnose_agent.py game_state
    uv run python scripts/diagnose_agent.py --save-fixture narrator "I open my eyes."

Shows the exact prompt sent and raw response received. Use this to iterate
on prompts in agents/prompts.py. With --save-fixture, saves the response
as a regression test fixture.
"""

import argparse
import asyncio
import json
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from theact.engine.context import (  # noqa: E402
    build_character_messages,
    build_game_state_messages,
    build_memory_messages,
    build_narrator_messages,
)
from theact.io.save_manager import create_save, load_save  # noqa: E402
from theact.llm.config import (  # noqa: E402
    CHARACTER_CONFIG,
    GAME_STATE_CONFIG,
    MEMORY_UPDATE_CONFIG,
    NARRATOR_CONFIG,
    load_llm_config,
)
from theact.llm.inference import complete  # noqa: E402
from theact.llm.parsing import extract_yaml_block, parse_yaml_response  # noqa: E402
from theact.llm.tokens import estimate_tokens  # noqa: E402
from theact.models.conversation import ConversationEntry  # noqa: E402


def ensure_save(save_id: str = "diag-001", player_name: str = "Alex") -> str:
    """Create a diagnostic save if it doesn't exist."""
    save_path = Path("saves") / save_id
    if not save_path.exists():
        create_save("lost-island", save_id, player_name)
    return save_id


def print_messages(messages: list[dict], label: str) -> None:
    """Print formatted messages with token estimates."""
    print(f"\n{'=' * 70}")
    print(f" {label}")
    print(f"{'=' * 70}")
    for msg in messages:
        role = msg["role"].upper()
        content = msg["content"]
        tokens = estimate_tokens(content)
        print(f"\n--- {role} ({tokens} est. tokens, {len(content)} chars) ---")
        print(content)
    total = sum(estimate_tokens(m["content"]) for m in messages)
    print(f"\n--- TOTAL: ~{total} estimated tokens ---")


def print_response(result, agent_name: str) -> dict:
    """Print and return structured response info."""
    print(f"\n{'=' * 70}")
    print(f" RAW RESPONSE ({agent_name})")
    print(f"{'=' * 70}")

    info = {
        "agent": agent_name,
        "content_length": len(result.content),
        "thinking_length": len(result.thinking) if result.thinking else 0,
        "finish_reason": result.finish_reason,
        "content": result.content,
        "thinking": result.thinking or "",
    }

    if result.thinking:
        print(f"\n--- THINKING ({info['thinking_length']} chars) ---")
        print(result.thinking[:1000])
        if len(result.thinking) > 1000:
            print(f"... ({len(result.thinking) - 1000} more chars)")

    print(f"\n--- CONTENT ({info['content_length']} chars) ---")
    print(result.content if result.content else "(empty)")

    print(f"\n--- FINISH REASON: {result.finish_reason} ---")

    # Try YAML parsing
    if result.content:
        yaml_block = extract_yaml_block(result.content)
        if yaml_block:
            print("\n--- EXTRACTED YAML ---")
            print(yaml_block)
            try:
                parsed = parse_yaml_response(result.content)
                print("\n--- PARSED DATA ---")
                print(json.dumps(parsed, indent=2, default=str))
                info["parsed"] = parsed
            except Exception as e:
                print(f"\n--- YAML PARSE ERROR: {e} ---")
                info["parse_error"] = str(e)
        else:
            print("\n--- NO YAML BLOCK FOUND ---")

    if result.finish_reason == "length":
        print(
            "\n⚠ FINISH REASON IS 'length' — model ran out of max_tokens. "
            "Thinking tokens may have consumed the entire budget."
        )

    return info


def save_fixture(info: dict, agent_name: str) -> Path:
    """Save response as a test fixture."""
    fixtures_dir = Path("tests/fixtures")
    fixtures_dir.mkdir(exist_ok=True)

    # Find next available fixture number
    existing = list(fixtures_dir.glob(f"{agent_name}_*.json"))
    n = len(existing) + 1
    path = fixtures_dir / f"{agent_name}_{n:03d}.json"

    with open(path, "w") as f:
        json.dump(info, f, indent=2, default=str)

    print(f"\nFixture saved to {path}")
    return path


async def diagnose_narrator(args, game, llm_config):
    player_input = args.input or "I open my eyes and try to stand up."
    messages = build_narrator_messages(game, player_input, llm_config)
    print_messages(messages, "NARRATOR PROMPT")
    result = await complete(messages, llm_config, NARRATOR_CONFIG)
    return print_response(result, "narrator")


async def diagnose_character(args, game, llm_config):
    char_id = args.character or "maya"
    if char_id in game.characters:
        character = game.characters[char_id]
    else:
        char_id = next(iter(game.characters))
        character = game.characters[char_id]
        print(f"Character not found, using {character.name} ({char_id})")

    memory = game.memories.get(char_id)
    from theact.models.memory import CharacterMemory

    if not memory:
        memory = CharacterMemory(character=character.name, summary="", key_facts=[])

    from theact.engine.types import NarratorOutput

    narrator_output = NarratorOutput(
        narration="You stand on the beach, sand crunching beneath your feet.",
        responding_characters=[char_id],
        mood="tense",
    )
    player_input = args.input or "I look around for anything useful."
    messages = build_character_messages(
        game, character, memory, player_input, narrator_output, [], llm_config
    )
    print_messages(messages, f"CHARACTER PROMPT ({character.name})")
    result = await complete(messages, llm_config, CHARACTER_CONFIG)
    return print_response(result, f"character_{char_id}")


async def diagnose_memory(args, game, llm_config):
    char_id = args.character or "maya"
    if char_id in game.characters:
        character = game.characters[char_id]
    else:
        char_id = next(iter(game.characters))
        character = game.characters[char_id]

    from theact.models.memory import CharacterMemory

    memory = game.memories.get(char_id) or CharacterMemory(
        character=character.name, summary="", key_facts=[]
    )
    turn_entries = [
        ConversationEntry(
            turn=1,
            role="narrator",
            content="You wake on the beach amid scattered wreckage.",
        ),
        ConversationEntry(
            turn=1,
            role="player",
            content="I look around for other survivors.",
        ),
    ]
    messages = build_memory_messages(character, memory, turn_entries)
    print_messages(messages, f"MEMORY UPDATE PROMPT ({character.name})")
    result = await complete(messages, llm_config, MEMORY_UPDATE_CONFIG)
    return print_response(result, f"memory_{char_id}")


async def diagnose_game_state(args, game, llm_config):
    turn_entries = [
        ConversationEntry(
            turn=1,
            role="narrator",
            content="You wake on the beach amid scattered wreckage.",
        ),
        ConversationEntry(
            turn=1,
            role="player",
            content="I stand up and look around the beach.",
        ),
    ]
    messages = build_game_state_messages(game, turn_entries)
    if not messages:
        print("No current chapter — game_state returns empty messages.")
        return {"agent": "game_state", "error": "no chapter"}
    print_messages(messages, "GAME STATE PROMPT")
    result = await complete(messages, llm_config, GAME_STATE_CONFIG)
    return print_response(result, "game_state")


async def main():
    parser = argparse.ArgumentParser(description="Diagnose agent prompts and responses")
    parser.add_argument(
        "agent",
        choices=["narrator", "character", "memory", "game_state", "all"],
        help="Which agent to diagnose",
    )
    parser.add_argument(
        "input", nargs="?", help="Player input (for narrator/character)"
    )
    parser.add_argument("--character", "-c", help="Character ID (for character/memory)")
    parser.add_argument(
        "--save-fixture", action="store_true", help="Save response as test fixture"
    )
    parser.add_argument("--save-id", default="diag-001", help="Save ID to use")
    args = parser.parse_args()

    llm_config = load_llm_config()
    ensure_save(args.save_id)
    game = load_save(args.save_id)

    agents_to_run = (
        ["narrator", "character", "memory", "game_state"]
        if args.agent == "all"
        else [args.agent]
    )

    dispatch = {
        "narrator": diagnose_narrator,
        "character": diagnose_character,
        "memory": diagnose_memory,
        "game_state": diagnose_game_state,
    }

    for agent_name in agents_to_run:
        info = await dispatch[agent_name](args, game, llm_config)
        if args.save_fixture:
            save_fixture(info, agent_name)


if __name__ == "__main__":
    asyncio.run(main())

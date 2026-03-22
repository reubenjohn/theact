"""Diagnostic tool for game creator prompts and model responses.

Usage:
    uv run python scripts/diagnose_creator.py hints "A noir mystery with 2 characters"
    uv run python scripts/diagnose_creator.py setting "A noir mystery..."
    uv run python scripts/diagnose_creator.py characters "A noir mystery..."
    uv run python scripts/diagnose_creator.py chapters "A noir mystery..."
    uv run python scripts/diagnose_creator.py all "A noir mystery with 2 characters named Maya and Joaquin, 8 chapters"

Shows the exact prompts sent and raw responses received. Use this to iterate
on prompts in creator/prompts.py.
"""

import argparse
import asyncio
import json
from pathlib import Path

import yaml
from dotenv import load_dotenv

load_dotenv()

from theact.creator.concept_hints import extract_concept_hints  # noqa: E402
from theact.creator.config import load_creator_config  # noqa: E402
from theact.creator.generator import extract_yaml  # noqa: E402
from theact.creator.prompts import (  # noqa: E402
    SETTING_SYSTEM,
    SETTING_USER,
    characters_system_prompt,
    characters_user_prompt,
    chapters_system_prompt,
    chapters_user_prompt,
)
from theact.creator.proposer import (  # noqa: E402
    generate_chapters_proposal,
    generate_characters_proposal,
    generate_setting,
)


def print_prompt(label: str, text: str) -> None:
    """Print a prompt section with token and character counts."""
    tokens = len(text) // 4
    chars = len(text)
    print(f"\n{'=' * 66}")
    print(f" {label} ({tokens} est. tokens, {chars} chars)")
    print(f"{'=' * 66}")
    print(text)


def print_prompts(system: str, user: str) -> None:
    """Print system and user prompts with a total token estimate."""
    print_prompt("SYSTEM PROMPT", system)
    print_prompt("USER PROMPT", user)
    sys_tokens = len(system) // 4
    usr_tokens = len(user) // 4
    print(f"\n--- TOTAL: ~{sys_tokens + usr_tokens} estimated tokens ---")


def print_response(response_text: str, step_name: str) -> dict:
    """Print and parse a raw LLM response. Returns info dict."""
    print(f"\n{'=' * 66}")
    print(f" RAW RESPONSE ({step_name})")
    print(f"{'=' * 66}")
    print(response_text if response_text else "(empty)")

    info: dict = {
        "step": step_name,
        "content_length": len(response_text),
        "content": response_text,
    }

    # Try YAML extraction
    try:
        parsed = extract_yaml(response_text)
        print(f"\n{'=' * 66}")
        print(f" PARSED YAML ({step_name})")
        print(f"{'=' * 66}")
        print(
            yaml.dump(
                parsed, default_flow_style=False, allow_unicode=True, sort_keys=False
            )
        )
        info["parsed"] = parsed
    except Exception as e:
        print(f"\n{'=' * 66}")
        print(f" YAML PARSE ERROR ({step_name})")
        print(f"{'=' * 66}")
        print(str(e))
        info["parse_error"] = str(e)

    return info


def save_fixture(info: dict, step_name: str) -> Path:
    """Save raw response as a test fixture."""
    fixtures_dir = Path("tests/fixtures/creator")
    fixtures_dir.mkdir(parents=True, exist_ok=True)

    path = fixtures_dir / f"{step_name}.txt"
    with open(path, "w") as f:
        f.write(info.get("content", ""))

    # Also save parsed data as JSON if available
    if "parsed" in info:
        json_path = fixtures_dir / f"{step_name}.json"
        with open(json_path, "w") as f:
            json.dump(info["parsed"], f, indent=2, default=str)
        print(f"\nFixture saved to {path} and {json_path}")
    else:
        print(f"\nFixture saved to {path}")

    return path


def diagnose_hints(concept: str) -> dict:
    """Extract and display concept hints (no LLM call)."""
    hints = extract_concept_hints(concept)

    print(f"\n{'=' * 66}")
    print(" CONCEPT HINTS (pure code, no LLM)")
    print(f"{'=' * 66}")
    print(f"  character_count: {hints.character_count}")
    print(f"  chapter_count:   {hints.chapter_count}")
    print(f"  character_names: {hints.character_names}")
    print(f"  character_stems: {hints.character_stems}")

    return {
        "step": "hints",
        "character_count": hints.character_count,
        "chapter_count": hints.chapter_count,
        "character_names": hints.character_names,
        "character_stems": hints.character_stems,
    }


async def diagnose_setting(concept: str, client, config) -> tuple[dict, dict]:
    """Run the setting step and display prompts + response."""
    # Show the prompts that will be sent
    system = SETTING_SYSTEM
    user = SETTING_USER.format(concept=concept)
    print_prompts(system, user)

    # Call the proposer
    setting_data = await generate_setting(concept, client, config)

    # Reconstruct raw response for display (re-serialize parsed output)
    raw_yaml = yaml.dump(
        setting_data, default_flow_style=False, allow_unicode=True, sort_keys=False
    )
    info = print_response(f"```yaml\n{raw_yaml}```", "setting")
    info["parsed"] = setting_data
    return setting_data, info


async def diagnose_characters(
    concept: str, setting_data: dict, hints, client, config
) -> tuple[dict, dict]:
    """Run the characters step and display prompts + response."""
    # Show the prompts that will be sent (same as what the proposer sends)
    system = characters_system_prompt(hints.character_count if hints else None)
    user = characters_user_prompt(
        title=setting_data.get("title", ""),
        setting=setting_data.get("setting", ""),
        tone=setting_data.get("tone", ""),
        concept=concept,
        character_names=hints.character_names if hints else None,
    )
    print_prompts(system, user)

    # Call the proposer with concept and hints
    characters_data = await generate_characters_proposal(
        setting_data, client, config, concept=concept, hints=hints
    )

    raw_yaml = yaml.dump(
        characters_data, default_flow_style=False, allow_unicode=True, sort_keys=False
    )
    info = print_response(f"```yaml\n{raw_yaml}```", "characters")
    info["parsed"] = characters_data
    return characters_data, info


async def diagnose_chapters(
    concept: str, setting_data: dict, characters_data: dict, hints, client, config
) -> tuple[dict, dict]:
    """Run the chapters step and display prompts + response."""
    # Reconstruct the character_list the same way the proposer does
    char_names = [
        f"{c['name']} ({c['stem']})" for c in characters_data.get("characters", [])
    ]
    character_list = ", ".join(char_names) if char_names else "none"

    # Show the prompts that will be sent (same as what the proposer sends)
    system = chapters_system_prompt(hints.chapter_count if hints else None)
    user = chapters_user_prompt(
        title=setting_data.get("title", ""),
        setting=setting_data.get("setting", ""),
        character_list=character_list,
        concept=concept,
    )
    print_prompts(system, user)

    # Call the proposer with concept and hints
    try:
        chapters_data = await generate_chapters_proposal(
            setting_data, characters_data, client, config, concept=concept, hints=hints
        )
    except Exception as e:
        print(f"\n{'=' * 66}")
        print(f" CHAPTERS GENERATION FAILED: {type(e).__name__}")
        print(f"{'=' * 66}")
        print(str(e))
        return {}, {"step": "chapters", "error": str(e)}

    raw_yaml = yaml.dump(
        chapters_data, default_flow_style=False, allow_unicode=True, sort_keys=False
    )
    info = print_response(f"```yaml\n{raw_yaml}```", "chapters")
    info["parsed"] = chapters_data
    return chapters_data, info


async def main():
    parser = argparse.ArgumentParser(
        description="Diagnose game creator prompts and responses"
    )
    parser.add_argument(
        "step",
        choices=["hints", "setting", "characters", "chapters", "all"],
        help="Which creator step to diagnose",
    )
    parser.add_argument("concept", help="Game concept text")
    parser.add_argument(
        "--setting-file",
        help="Load setting from a YAML file instead of generating it (for characters/chapters)",
    )
    parser.add_argument(
        "--save-fixture",
        action="store_true",
        help="Save raw responses to tests/fixtures/creator/",
    )
    args = parser.parse_args()

    concept = args.concept
    step = args.step

    # Hints is pure code -- no LLM needed
    if step == "hints":
        info = diagnose_hints(concept)
        if args.save_fixture:
            save_fixture(
                {"step": "hints", "content": json.dumps(info, indent=2, default=str)},
                "hints",
            )
        return

    # All other steps need an LLM client
    from openai import AsyncOpenAI  # noqa: E402

    config = load_creator_config()
    client = AsyncOpenAI(base_url=config.base_url, api_key=config.api_key)

    print(f"Model: {config.model}")
    print(f"Base URL: {config.base_url}")
    print(f"Temperature: {config.temperature}")

    # Always extract hints for display
    hints = extract_concept_hints(concept)
    print(
        f"\nConcept hints: characters={hints.character_count}, "
        f"chapters={hints.chapter_count}, names={hints.character_names}"
    )

    setting_data = None
    characters_data = None

    # Load setting from file if provided
    if args.setting_file:
        with open(args.setting_file) as f:
            setting_data = yaml.safe_load(f)
        print(f"\nLoaded setting from {args.setting_file}")

    if step == "setting":
        _, info = await diagnose_setting(concept, client, config)
        if args.save_fixture:
            save_fixture(info, "setting")

    elif step == "characters":
        if not setting_data:
            print("\n--- Running setting step first ---\n")
            setting_data, setting_info = await diagnose_setting(concept, client, config)
            if args.save_fixture:
                save_fixture(setting_info, "setting")
        _, info = await diagnose_characters(
            concept, setting_data, hints, client, config
        )
        if args.save_fixture:
            save_fixture(info, "characters")

    elif step == "chapters":
        if not setting_data:
            print("\n--- Running setting step first ---\n")
            setting_data, setting_info = await diagnose_setting(concept, client, config)
            if args.save_fixture:
                save_fixture(setting_info, "setting")
        print("\n--- Running characters step first ---\n")
        characters_data, chars_info = await diagnose_characters(
            concept, setting_data, hints, client, config
        )
        if args.save_fixture:
            save_fixture(chars_info, "characters")
        _, info = await diagnose_chapters(
            concept, setting_data, characters_data, hints, client, config
        )
        if args.save_fixture:
            save_fixture(info, "chapters")

    elif step == "all":
        print("\n--- Step 1: Setting ---\n")
        setting_data, setting_info = await diagnose_setting(concept, client, config)
        if args.save_fixture:
            save_fixture(setting_info, "setting")

        print("\n--- Step 2: Characters ---\n")
        characters_data, chars_info = await diagnose_characters(
            concept, setting_data, hints, client, config
        )
        if args.save_fixture:
            save_fixture(chars_info, "characters")

        print("\n--- Step 3: Chapters ---\n")
        _, chaps_info = await diagnose_chapters(
            concept, setting_data, characters_data, hints, client, config
        )
        if args.save_fixture:
            save_fixture(chaps_info, "chapters")


if __name__ == "__main__":
    asyncio.run(main())

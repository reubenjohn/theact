"""Interactive game creation session orchestrator."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml
from openai import AsyncOpenAI
from rich.console import Console

from theact.creator.assembler import assemble_game_meta_from_data, enforce_consistency
from theact.creator.chapter_gen import generate_chapter
from theact.creator.character_gen import generate_character
from theact.creator.config import CreatorLLMConfig, load_creator_config
from theact.creator.display import (
    display_game_files,
    display_proposal,
    display_size_warnings,
    display_validation_errors,
)
from theact.creator.fixer import fix_validation_errors
from theact.creator.generator import (
    YAMLParseError,
    call_llm,
    extract_yaml,
    serialize_game_data,
)
from theact.creator.pipeline import run_generation_pipeline
from theact.creator.prompts import (
    CLASSIFY_SYSTEM,
    CLASSIFY_USER,
    GENERATION_SYSTEM,
    TARGETED_REVISION_USER,
)
from theact.creator.proposer import (
    assemble_proposal,
    generate_chapters_proposal,
    generate_characters_proposal,
    generate_setting,
    revise_chapters_proposal,
    revise_characters_proposal,
    revise_setting,
)
from theact.creator.validator import check_size_warnings, validate_game_data
from theact.creator.world_gen import generate_world
from theact.creator.writer import write_game_files

console = Console()


async def create_game(concept: str | None = None) -> Path | None:
    """Run the interactive game creation flow.

    Args:
        concept: Optional pre-supplied concept (from brainstorm or CLI arg).
                 If None, prompts the user for input.

    Returns the path to the created game directory, or None if aborted.
    """
    config = load_creator_config()
    client = _create_client(config)

    # Step 1: Get concept
    if not concept:
        console.print("\n[bold]Creating a new game.[/bold]\n")
        console.print(
            "Describe your game concept in a few sentences. Include the genre, "
            "setting, key characters, and what the player does.\n"
        )
        concept = _get_input()
        if not concept:
            return None

    # Step 2: Decomposed proposal (setting → characters → chapters)
    proposal = await _decomposed_proposal(concept, client, config)
    if proposal is None:
        return None

    display_proposal(proposal)
    console.print("[green]Proposal assembled from all steps.[/green]\n")

    # Step 3: Generate full game files via decomposed pipeline
    console.print("\n[dim]Generating game files...[/dim]\n")
    try:
        data = await run_generation_pipeline(
            proposal,
            client,
            config,
            on_progress=lambda msg: console.print(f"  [dim]{msg}[/dim]"),
        )
    except (YAMLParseError, ValueError) as e:
        console.print(f"[red]Failed to generate game files:[/red]\n{e}")
        console.print("[dim]Please try again with a different concept.[/dim]")
        return None

    # Step 4: Validate
    result = validate_game_data(data)
    if not result.valid:
        console.print("[yellow]Fixing validation errors...[/yellow]\n")
        data, result = await fix_validation_errors(data, result, client, config)

    if not result.valid:
        display_validation_errors(result.errors)
        console.print(
            "[red]Could not fix all errors automatically. "
            "Please adjust your concept and try again.[/red]"
        )
        return None

    # Step 5: Size warnings
    warnings = check_size_warnings(result.world, result.characters, result.chapters)
    if warnings:
        display_size_warnings(warnings)

    # Step 6: User review
    display_game_files(result)

    while True:
        feedback = _get_input(prompt='Type feedback to revise, or "ok" to finalize: ')
        if not feedback:
            return None
        if feedback.strip().lower() in ("ok", "looks good", "good", "yes", "y"):
            break
        console.print("\n[dim]Revising...[/dim]\n")
        data = await revise_targeted(data, feedback, client, config)
        result = validate_game_data(data)
        if not result.valid:
            data, result = await fix_validation_errors(data, result, client, config)
        if result.valid:
            display_game_files(result)
        else:
            display_validation_errors(result.errors)
            console.print(
                "[yellow]Some errors remain. You may continue revising.[/yellow]"
            )

    # Step 7: Write to disk
    game_id = result.game.id
    from theact.io.save_manager import GAMES_DIR

    game_dir = GAMES_DIR / game_id
    if game_dir.exists():
        confirm = _get_input(
            f"Game directory '{game_dir}' already exists. Overwrite? (y/n): "
        )
        if not confirm or confirm.lower() not in ("y", "yes"):
            console.print("[dim]Aborted -- existing game not overwritten.[/dim]")
            return None
        overwrite = True
    else:
        overwrite = False

    game_path = write_game_files(game_id, result, overwrite=overwrite)
    console.print(f"\n[green]Game created at:[/green] {game_path}\n")
    return game_path


async def _decomposed_proposal(
    concept: str,
    client: AsyncOpenAI,
    config: CreatorLLMConfig,
) -> dict | None:
    """Run the 3-step decomposed proposal flow.

    Returns the assembled proposal dict, or None if aborted.
    """
    # Step 1: Setting
    console.print("\n[dim]Generating setting...[/dim]\n")
    setting_data = await generate_setting(concept, client, config)
    _display_yaml("Setting", setting_data)

    while True:
        feedback = _get_input(prompt='Feedback on setting, or "ok" to continue: ')
        if not feedback:
            return None
        if feedback.strip().lower() in ("ok", "looks good", "good", "yes", "y"):
            break
        console.print("\n[dim]Revising setting...[/dim]\n")
        setting_data = await revise_setting(setting_data, feedback, client, config)
        _display_yaml("Setting", setting_data)

    # Step 2: Characters
    console.print("\n[dim]Generating characters...[/dim]\n")
    characters_data = await generate_characters_proposal(setting_data, client, config)
    _display_yaml("Characters", characters_data)

    while True:
        feedback = _get_input(prompt='Feedback on characters, or "ok" to continue: ')
        if not feedback:
            return None
        if feedback.strip().lower() in ("ok", "looks good", "good", "yes", "y"):
            break
        console.print("\n[dim]Revising characters...[/dim]\n")
        characters_data = await revise_characters_proposal(
            characters_data, setting_data, feedback, client, config
        )
        _display_yaml("Characters", characters_data)

    # Step 3: Chapters
    console.print("\n[dim]Generating chapters...[/dim]\n")
    chapters_data = await generate_chapters_proposal(
        setting_data, characters_data, client, config
    )
    _display_yaml("Chapters", chapters_data)

    while True:
        feedback = _get_input(prompt='Feedback on chapters, or "ok" to continue: ')
        if not feedback:
            return None
        if feedback.strip().lower() in ("ok", "looks good", "good", "yes", "y"):
            break
        console.print("\n[dim]Revising chapters...[/dim]\n")
        chapters_data = await revise_chapters_proposal(
            chapters_data, setting_data, characters_data, feedback, client, config
        )
        _display_yaml("Chapters", chapters_data)

    return assemble_proposal(setting_data, characters_data, chapters_data)


def _display_yaml(label: str, data: dict) -> None:
    """Display a YAML block with a label."""
    yaml_str = yaml.dump(
        data, default_flow_style=False, allow_unicode=True, sort_keys=False
    )
    console.print(f"\n[bold]{label}:[/bold]")
    console.print(f"```yaml\n{yaml_str}```\n")


# ---------------------------------------------------------------------------
# Targeted revision
# ---------------------------------------------------------------------------


@dataclass
class RevisionTarget:
    """A single file targeted for revision."""

    file_type: str  # "world", "character", or "chapter"
    stem: str | None  # e.g., "maya" or "01-the-crash"; None for world


async def classify_revision_targets(
    feedback: str,
    data: dict,
    client: AsyncOpenAI,
    config: CreatorLLMConfig,
) -> list[RevisionTarget]:
    """Classify which file(s) the feedback targets."""
    char_list = "\n".join(
        f"- character: {stem} ({data['characters'][stem].get('name', stem)})"
        for stem in data.get("characters", {})
    )
    chap_list = "\n".join(
        f"- chapter: {cid} ({data['chapters'][cid].get('title', cid)})"
        for cid in data.get("chapters", {})
    )

    messages: list[dict] = [
        {"role": "system", "content": CLASSIFY_SYSTEM},
        {
            "role": "user",
            "content": CLASSIFY_USER.format(
                feedback=feedback,
                character_list=char_list,
                chapter_list=chap_list,
            ),
        },
    ]

    try:
        response = await call_llm(client, config, messages)
        result = extract_yaml(response)
        targets = []
        for t in result.get("targets", []):
            targets.append(
                RevisionTarget(
                    file_type=t.get("file_type", ""),
                    stem=t.get("stem"),
                )
            )
        return targets
    except (YAMLParseError, KeyError, TypeError):
        return []  # Fall back to full pipeline on classifier failure


async def revise_targeted(
    data: dict,
    feedback: str,
    client: AsyncOpenAI,
    config: CreatorLLMConfig,
) -> dict:
    """Identify which file(s) the feedback targets and regenerate them."""
    targets = await classify_revision_targets(feedback, data, client, config)

    if not targets:
        # Fallback: use the old monolithic revision approach
        return await _revise_and_validate(data, feedback, client, config)

    proposal = _proposal_from_data(data)

    for target in targets:
        if target.file_type == "world":
            data["world"] = await generate_world(
                proposal=proposal,
                client=client,
                config=config,
                feedback=feedback,
            )
        elif target.file_type == "character" and target.stem:
            char_info = _char_info(data, target.stem)
            if char_info:
                data["characters"][target.stem] = await generate_character(
                    proposal=proposal,
                    char_info=char_info,
                    all_stems=list(data["characters"].keys()),
                    prior_characters={
                        k: v for k, v in data["characters"].items() if k != target.stem
                    },
                    client=client,
                    config=config,
                    feedback=feedback,
                )
        elif target.file_type == "chapter" and target.stem:
            chap_info = _chap_info(data, target.stem)
            if chap_info:
                data["chapters"][target.stem] = await generate_chapter(
                    proposal=proposal,
                    chap_info=chap_info,
                    characters=data["characters"],
                    prior_chapters={
                        k: v for k, v in data["chapters"].items() if k != target.stem
                    },
                    next_chapter_id=_next_chapter_id(data, target.stem),
                    client=client,
                    config=config,
                    feedback=feedback,
                )

    # Re-assemble game.yaml and enforce consistency
    data["game"] = assemble_game_meta_from_data(data)
    data = enforce_consistency(data)

    return data


async def _revise_and_validate(
    data: dict,
    feedback: str,
    client: AsyncOpenAI,
    config: CreatorLLMConfig,
) -> dict:
    """Fallback: monolithic revision using TARGETED_REVISION_USER."""
    from theact.creator.generator import parse_generation_response

    yaml_text = serialize_game_data(data)
    messages: list[dict] = [
        {"role": "system", "content": GENERATION_SYSTEM},
        {
            "role": "user",
            "content": TARGETED_REVISION_USER.format(
                user_feedback=feedback,
                current_output=yaml_text,
            ),
        },
    ]

    for attempt in range(3):
        response = await call_llm(client, config, messages)
        try:
            return parse_generation_response(response)
        except YAMLParseError as e:
            if attempt == 2:
                console.print(f"[red]Failed to parse revised output: {e}[/red]")
                return data
            messages.append({"role": "assistant", "content": response})
            messages.append(
                {
                    "role": "user",
                    "content": f"That output was not valid YAML: {e}\nPlease try again.",
                }
            )

    return data


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


def _proposal_from_data(data: dict) -> dict:
    """Reconstruct a proposal-like dict from current game data."""
    game = data.get("game", {})
    world = data.get("world", {})
    return {
        "title": game.get("title", ""),
        "id": game.get("id", ""),
        "setting": world.get("setting", ""),
        "tone": world.get("tone", ""),
        "rules": world.get("rules", ""),
        "characters": [
            {
                "stem": stem,
                "name": char_data.get("name", stem),
                "role": char_data.get("role", ""),
            }
            for stem, char_data in data.get("characters", {}).items()
        ],
        "chapters": [
            {
                "id": cid,
                "title": chap_data.get("title", cid),
                "summary": chap_data.get("summary", ""),
            }
            for cid, chap_data in data.get("chapters", {}).items()
        ],
    }


def _char_info(data: dict, stem: str) -> dict | None:
    """Get char_info dict for a character stem."""
    char_data = data.get("characters", {}).get(stem)
    if not char_data:
        return None
    return {
        "stem": stem,
        "name": char_data.get("name", stem),
        "role": char_data.get("role", ""),
    }


def _chap_info(data: dict, cid: str) -> dict | None:
    """Get chap_info dict for a chapter id."""
    chap_data = data.get("chapters", {}).get(cid)
    if not chap_data:
        return None
    return {
        "id": cid,
        "title": chap_data.get("title", cid),
        "summary": chap_data.get("summary", ""),
    }


def _next_chapter_id(data: dict, cid: str) -> str | None:
    """Get the next chapter id for a given chapter."""
    chapter_ids = list(data.get("chapters", {}).keys())
    try:
        idx = chapter_ids.index(cid)
        return chapter_ids[idx + 1] if idx + 1 < len(chapter_ids) else None
    except ValueError:
        return None


def _get_input(prompt: str = "> ") -> str | None:
    """Get input from the user. Returns None on EOF/Ctrl-C."""
    try:
        return console.input(prompt).strip()
    except (EOFError, KeyboardInterrupt):
        console.print("\n[dim]Aborted.[/dim]")
        return None


def _create_client(config: CreatorLLMConfig) -> AsyncOpenAI:
    """Create an AsyncOpenAI client from the creator config."""
    return AsyncOpenAI(
        base_url=config.base_url,
        api_key=config.api_key,
    )

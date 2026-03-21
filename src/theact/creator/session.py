"""Interactive game creation session orchestrator."""

from __future__ import annotations

from pathlib import Path

import yaml
from openai import AsyncOpenAI
from rich.console import Console

from theact.creator.config import CreatorLLMConfig, load_creator_config
from theact.creator.display import (
    display_game_files,
    display_proposal,
    display_size_warnings,
    display_validation_errors,
)
from theact.creator.fixer import fix_validation_errors
from theact.creator.generator import YAMLParseError, _parse_generation_response
from theact.creator.generator import generate_game_files
from theact.creator.prompts import GENERATION_SYSTEM, TARGETED_REVISION_USER
from theact.creator.proposer import generate_proposal, revise_proposal
from theact.creator.validator import check_size_warnings, validate_game_data
from theact.creator.writer import write_game_files

console = Console()


async def create_game() -> Path | None:
    """Run the interactive game creation flow.

    Returns the path to the created game directory, or None if aborted.
    """
    config = load_creator_config()
    client = _create_client(config)

    # Step 1: Get concept
    console.print("\n[bold]Creating a new game.[/bold]\n")
    console.print(
        "Describe your game concept in a few sentences. Include the genre, "
        "setting, key characters, and what the player does.\n"
    )
    concept = _get_input()
    if not concept:
        return None

    # Step 2: Generate and iterate on proposal
    console.print("\n[dim]Generating proposal...[/dim]\n")
    proposal = await generate_proposal(concept, client, config)
    display_proposal(proposal)

    while True:
        feedback = _get_input(prompt='Type feedback to revise, or "ok" to proceed: ')
        if not feedback:
            return None
        if feedback.strip().lower() in ("ok", "looks good", "good", "yes", "y"):
            break
        console.print("\n[dim]Revising proposal...[/dim]\n")
        proposal = await revise_proposal(proposal, feedback, client, config)
        display_proposal(proposal)

    # Step 3: Generate full game files
    console.print("\n[dim]Generating game files...[/dim]\n")
    try:
        data = await generate_game_files(proposal, client, config)
    except YAMLParseError as e:
        console.print(f"[red]Failed to generate valid YAML after retries:[/red]\n{e}")
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
        data = await _revise_and_validate(data, feedback, client, config)
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


async def _revise_and_validate(
    data: dict,
    feedback: str,
    client: AsyncOpenAI,
    config: CreatorLLMConfig,
) -> dict:
    """Revise specific files based on user feedback and return updated data.

    Sends the current game data and user feedback to the LLM using
    TARGETED_REVISION_USER, then parses the response. If YAML parsing
    fails, retries up to 2 times. Returns the (possibly revised) data dict.
    """
    yaml_text = _serialize_game_data(data)
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
        response = await _call_llm(client, config, messages)
        try:
            return _parse_generation_response(response)
        except YAMLParseError as e:
            if attempt == 2:
                console.print(f"[red]Failed to parse revised output: {e}[/red]")
                return data  # Return unmodified data on total failure
            messages.append({"role": "assistant", "content": response})
            messages.append(
                {
                    "role": "user",
                    "content": f"That output was not valid YAML: {e}\nPlease try again.",
                }
            )

    return data


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


async def _call_llm(
    client: AsyncOpenAI, config: CreatorLLMConfig, messages: list[dict]
) -> str:
    """Call the LLM and return the response text content."""
    response = await client.chat.completions.create(
        model=config.model,
        messages=messages,
        temperature=config.temperature,
        max_tokens=config.max_tokens,
    )
    return response.choices[0].message.content or ""


def _serialize_game_data(data: dict) -> str:
    """Serialize a game data dict to a YAML string for prompt injection."""
    return yaml.dump(
        data, default_flow_style=False, allow_unicode=True, sort_keys=False
    )

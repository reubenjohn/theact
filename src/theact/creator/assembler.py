"""Code-assembled game metadata and cross-file consistency enforcement.

No LLM calls — game.yaml is an index of generated files,
and consistency fixes are deterministic.
"""

from __future__ import annotations

from copy import deepcopy


def assemble_game_meta(
    proposal: dict,
    characters: dict[str, dict],
    chapters: dict[str, dict],
) -> dict:
    """Assemble game.yaml data from generated components.

    This is pure code -- no LLM call. The game meta is just an index
    of the generated characters and chapters, plus the title from
    the proposal. The description is synthesized from the title
    since proposals don't include a description field.
    """
    return {
        "id": proposal["id"],
        "title": proposal["title"],
        "description": f"{proposal['title']} -- a text-based RPG.",
        "characters": list(characters.keys()),
        "chapters": list(chapters.keys()),
    }


def assemble_game_meta_from_data(data: dict) -> dict:
    """Re-assemble game.yaml from a full data dict.

    Convenience wrapper for use during revision and fixing, where
    the full proposal is not available -- only the data dict with
    game/world/characters/chapters keys.
    """
    return {
        "id": data["game"]["id"],
        "title": data["game"]["title"],
        "description": data["game"].get(
            "description", f"{data['game']['title']} -- a text-based RPG."
        ),
        "characters": list(data.get("characters", {}).keys()),
        "chapters": list(data.get("chapters", {}).keys()),
    }


def enforce_consistency(data: dict) -> dict:
    """Apply code-enforced fixes for cross-file consistency.

    These are deterministic fixes that don't need an LLM:
    - Rebuild game.yaml from actual characters/chapters keys
    - Remove self-referencing relationships
    - Strip invalid character stems from chapter character lists
    - Re-wire chapter next-chain based on game.yaml chapter order
    """
    data = deepcopy(data)

    valid_char_stems = set(data.get("characters", {}).keys())
    chapter_ids = list(data.get("chapters", {}).keys())

    # 1. Rebuild game.yaml from actual data
    data["game"] = assemble_game_meta_from_data(data)

    # 2. Remove self-referencing relationships and strip invalid stems
    for stem, char_data in data.get("characters", {}).items():
        if "relationships" not in char_data or not isinstance(
            char_data["relationships"], dict
        ):
            char_data["relationships"] = {}
            continue
        # Remove self-reference
        char_data["relationships"].pop(stem, None)
        # Strip invalid stems
        char_data["relationships"] = {
            k: v for k, v in char_data["relationships"].items() if k in valid_char_stems
        }

    # 3. Strip invalid character stems from chapter character lists
    for chap_data in data.get("chapters", {}).values():
        if "characters" in chap_data and isinstance(chap_data["characters"], list):
            chap_data["characters"] = [
                s for s in chap_data["characters"] if s in valid_char_stems
            ]

    # 4. Re-wire chapter next-chain based on order in chapters dict
    for i, cid in enumerate(chapter_ids):
        chap_data = data["chapters"].get(cid, {})
        if i + 1 < len(chapter_ids):
            chap_data["next"] = chapter_ids[i + 1]
        else:
            chap_data["next"] = None

    return data

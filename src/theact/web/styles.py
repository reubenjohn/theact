"""Color constants and CSS utilities for the web UI.

Mirrors the CLI's color scheme (src/theact/cli/styles.py) but uses
CSS color values instead of Rich color names.
"""

# --- Narrator ---
NARRATOR_COLOR = "#e0e0e0"
NARRATOR_NAME_COLOR = "#ffffff"

# --- Character palette ---
# Matches CLI's CHARACTER_COLORS order: cyan, magenta, yellow, green, red, blue.
CHARACTER_COLORS = [
    "#00e5ff",  # bright cyan
    "#ff80ff",  # bright magenta
    "#ffff00",  # bright yellow
    "#69f0ae",  # bright green
    "#ff5252",  # bright red
    "#448aff",  # bright blue
]

# --- Player ---
PLAYER_COLOR = "#ffffff"

# --- Thinking ---
THINKING_COLOR = "#888888"

# --- System messages ---
SYSTEM_COLOR = "#9e9e9e"

# --- Status / info ---
ERROR_COLOR = "#ff5252"


def get_character_color(character_name: str, character_list: list[str]) -> str:
    """Return the CSS color for a character based on roster position.

    Args:
        character_name: The character's display name or stem.
        character_list: Ordered list of character names/stems.

    Returns:
        A CSS color string from CHARACTER_COLORS.
    """
    try:
        idx = character_list.index(character_name)
    except ValueError:
        idx = hash(character_name)
    return CHARACTER_COLORS[idx % len(CHARACTER_COLORS)]

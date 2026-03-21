"""Color and style constants for the Rich terminal CLI."""

from rich.style import Style

# --- Narrative styles ---
NARRATOR_STYLE = Style(color="white", italic=True)
NARRATOR_LABEL_STYLE = Style(color="bright_white", bold=True, italic=True)

# --- Character styles ---
# Characters get assigned colors from this palette in order of appearance.
CHARACTER_COLORS = [
    "bright_cyan",
    "bright_magenta",
    "bright_yellow",
    "bright_green",
    "bright_red",
    "bright_blue",
]

CHARACTER_NAME_STYLE = Style(bold=True)  # combined with character color

# --- Player styles ---
PLAYER_STYLE = Style(color="bright_white", bold=True)

# --- Thinking styles ---
THINKING_STYLE = Style(color="bright_black", dim=True)
THINKING_LABEL_STYLE = Style(color="bright_black", bold=True, dim=True)

# --- UI styles ---
STATUS_STYLE = Style(color="bright_black")
ERROR_STYLE = Style(color="red", bold=True)
TURN_HEADER_STYLE = Style(color="bright_black", bold=True)
COMMAND_OUTPUT_STYLE = Style(color="bright_black")

# --- Separators ---
TURN_SEPARATOR = "dim"


def get_character_color(character_name: str, character_list: list[str]) -> str:
    """Return the color for a character based on their position in the roster.

    Args:
        character_name: The character's display name.
        character_list: The ordered list of character names (or stems).

    Returns:
        A Rich color string from CHARACTER_COLORS.
    """
    try:
        idx = character_list.index(character_name)
    except ValueError:
        idx = hash(character_name)  # fallback for unknown characters
    return CHARACTER_COLORS[idx % len(CHARACTER_COLORS)]

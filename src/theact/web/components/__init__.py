"""Web UI components package.

Re-exports for backward compatibility.
"""

from theact.web.components.message_blocks import (
    StreamingTextBlock,
    create_character_block,
    create_narrator_block,
    create_player_block,
)
from theact.web.components.static_turn import render_static_turn
from theact.web.components.system_message import show_system_message
from theact.web.components.thinking_panel import create_thinking_panel
from theact.web.components.turn_card import create_turn_card

__all__ = [
    "StreamingTextBlock",
    "create_character_block",
    "create_narrator_block",
    "create_player_block",
    "create_thinking_panel",
    "create_turn_card",
    "render_static_turn",
    "show_system_message",
]

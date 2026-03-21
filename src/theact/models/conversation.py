"""Conversation entry model."""

from typing import Literal

from pydantic import BaseModel, ConfigDict


class ConversationEntry(BaseModel):
    """Single message in the conversation log. Appended to conversation.yaml."""

    model_config = ConfigDict(extra="forbid")

    turn: int
    role: Literal["narrator", "character", "player"]
    character: str | None = None  # Set when role is "character"
    content: str

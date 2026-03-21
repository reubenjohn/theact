"""Character definition model."""

from pydantic import BaseModel, ConfigDict


class Character(BaseModel):
    """Character definition. Loaded from characters/<name>.yaml. ~60 words total."""

    model_config = ConfigDict(extra="forbid")

    name: str  # Display name
    role: str  # One-line role in the story
    personality: str  # Core traits, speech patterns. 2-3 sentences.
    secret: str  # Hidden motivation or knowledge. 1 sentence.
    relationships: dict[str, str]  # name -> one-line relationship stance

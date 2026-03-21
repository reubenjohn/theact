"""Character memory model."""

from pydantic import BaseModel, ConfigDict


class CharacterMemory(BaseModel):
    """Per-character rolling memory. Written to memory/<name>.yaml."""

    model_config = ConfigDict(extra="forbid")

    character: str  # Character name
    summary: str  # Rolling summary of what this character knows/feels. ~3-5 sentences.
    key_facts: list[str]  # Important discrete facts. Max ~10, oldest pruned.

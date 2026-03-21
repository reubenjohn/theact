"""World definition model."""

from pydantic import BaseModel, ConfigDict


class World(BaseModel):
    """World definition. Loaded from world.yaml. Keep each field to 1-3 sentences."""

    model_config = ConfigDict(extra="forbid")

    setting: str  # Where and when. ~2 sentences.
    tone: str  # Narrative voice and style. ~2 sentences.
    rules: str  # Key constraints the narrator must follow. ~2 sentences.

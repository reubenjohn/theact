"""Chapter definition and summary models."""

from pydantic import BaseModel, ConfigDict


class Chapter(BaseModel):
    """Chapter definition. Loaded from chapters/<id>.yaml."""

    model_config = ConfigDict(extra="forbid")

    id: str  # e.g. "01-the-crash"
    title: str  # e.g. "The Crash"
    summary: str  # What this chapter is about. 2-3 sentences.
    beats: list[str]  # Key events that should happen. Short phrases.
    completion: str  # What must be true for chapter to end. 1 sentence.
    characters: list[str]  # Which characters are active in this chapter.
    next: str | None = None  # Next chapter id, or None if final chapter.


class ChapterSummary(BaseModel):
    """Summary of a completed chapter. Appended to summaries.yaml."""

    model_config = ConfigDict(extra="forbid")

    chapter_id: str
    title: str
    summary: str  # 2-3 sentence summary of what happened.

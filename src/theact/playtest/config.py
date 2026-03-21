"""Configuration for playtest runs."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from theact.llm.config import LLMConfig


@dataclass
class PlaytestConfig:
    """Configuration for a playtest run."""

    game_id: str  # e.g. "lost-island"
    max_turns: int = 20  # stop after N turns
    player_name: str = "Alex"  # default player name
    opening_action: str = "I try to free my arm and look around."
    stop_on_error: bool = False  # keep going through errors
    edge_case_frequency: float = 0.15  # 15% chance of unusual action
    timestamp: str = ""  # auto-filled if empty
    llm_config: LLMConfig = field(default_factory=LLMConfig)
    output_dir: str = "playtests"  # base output directory

    def __post_init__(self) -> None:
        if not self.timestamp:
            self.timestamp = datetime.now().strftime("%Y-%m-%dT%H-%M-%S")

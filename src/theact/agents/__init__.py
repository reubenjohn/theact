"""Agent modules for TheAct: narrator, character, memory, game state, summarizer."""

__all__ = [
    "run_narrator",
    "run_character",
    "run_memory_update",
    "run_game_state",
    "run_chapter_summary",
    "run_rolling_summary",
]

# Lazy imports to avoid circular dependency:
# agents.character -> engine.context -> agents.prompts -> agents.__init__
_AGENT_MAP = {
    "run_narrator": ("theact.agents.narrator", "run_narrator"),
    "run_character": ("theact.agents.character", "run_character"),
    "run_memory_update": ("theact.agents.memory", "run_memory_update"),
    "run_game_state": ("theact.agents.game_state", "run_game_state"),
    "run_chapter_summary": ("theact.agents.summarizer", "run_chapter_summary"),
    "run_rolling_summary": ("theact.agents.summarizer", "run_rolling_summary"),
}


def __getattr__(name: str):
    if name in _AGENT_MAP:
        import importlib

        module_path, attr_name = _AGENT_MAP[name]
        module = importlib.import_module(module_path)
        return getattr(module, attr_name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

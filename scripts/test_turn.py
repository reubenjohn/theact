"""
Integration test for the turn engine.
Run: uv run python scripts/test_turn.py

Requires LLM_API_KEY in environment or .env file.
Runs 3 turns against the live API with the lost-island game.
"""

import asyncio
import shutil

from dotenv import load_dotenv

load_dotenv()

from theact.engine.turn import run_turn  # noqa: E402
from theact.io.save_manager import SAVES_DIR, create_save, load_save  # noqa: E402
from theact.llm.config import load_llm_config  # noqa: E402


async def on_token(source: str, character: str | None, token: str) -> None:
    """Print tokens as they arrive."""
    print(token, end="", flush=True)


async def main() -> None:
    llm_config = load_llm_config()
    save_id = "test-turn-001"

    # Clean up previous test save if it exists
    save_path = SAVES_DIR / save_id
    if save_path.exists():
        shutil.rmtree(save_path)

    # Create a fresh save
    print("Creating save...")
    save_path = create_save("lost-island", save_id, "Alex")
    print(f"Save created at {save_path}\n")

    # Load the game
    game = load_save(save_id)

    # Scripted player inputs
    inputs = [
        "I open my eyes and try to stand up.",
        "I look around for anything useful in the wreckage.",
        "I walk along the beach looking for other survivors.",
    ]

    for i, player_input in enumerate(inputs):
        print(f"\n{'=' * 60}")
        print(f"TURN {i + 1}: Player says: {player_input}")
        print(f"{'=' * 60}\n")

        result = await run_turn(game, player_input, llm_config, on_token)

        print(f"\n\n--- Turn {result.turn} Summary ---")
        print(f"Mood: {result.narrator.mood}")
        print(f"Characters responded: {[c.character for c in result.characters]}")
        print(f"Beats hit: {game.state.beats_hit}")
        print(f"Memory diffs: {len(result.memory_diffs)}")
        if result.chapter_advanced:
            print(f"CHAPTER ADVANCED to: {result.new_chapter}")
        print()

        # Reload game state for next turn
        game = load_save(save_id)

    print("\n=== FINAL STATE ===")
    print(f"Turn: {game.state.turn}")
    print(f"Chapter: {game.state.current_chapter}")
    print(f"Beats hit: {game.state.beats_hit}")
    print(f"Rolling summary: {game.state.rolling_summary}")
    print(f"Memories: {list(game.memories.keys())}")
    for char_id, mem in game.memories.items():
        print(f"  {char_id}: {mem.summary[:100]}...")

    print("\nDone.")


if __name__ == "__main__":
    asyncio.run(main())

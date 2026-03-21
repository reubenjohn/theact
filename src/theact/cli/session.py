"""Gameplay session: input loop, turn dispatch, command handling."""

from __future__ import annotations

import logging

from rich.console import Console
from rich.style import Style
from rich.text import Text

from theact.cli.commands import (
    cmd_conversation,
    cmd_help,
    cmd_history,
    cmd_memory,
    cmd_save,
    cmd_status,
    cmd_think,
    cmd_undo,
    parse_command,
)
from theact.cli.renderer import Renderer
from theact.cli.styles import (
    NARRATOR_STYLE,
    PLAYER_STYLE,
    STATUS_STYLE,
    get_character_color,
)
from theact.engine.turn import run_turn
from theact.io.save_manager import load_save
from theact.llm.config import LLMConfig
from theact.models.game import LoadedGame

logger = logging.getLogger(__name__)


class GameSession:
    """Manages a single gameplay session from load to quit.

    The session is a thin layer: it reads player input, dispatches
    slash commands, and calls run_turn() with a streaming callback
    that drives the renderer.
    """

    def __init__(
        self,
        console: Console,
        game: LoadedGame,
        llm_config: LLMConfig,
    ) -> None:
        self.console = console
        self.game = game
        self.llm_config = llm_config
        self.renderer = Renderer(console, game)
        self.show_thinking = True
        self._last_player_input: str | None = None

    async def run(self) -> None:
        """Main gameplay loop."""
        if self.game.state.turn == 0:
            # Fresh game -- run the opening narration automatically
            await self._play_turn("[game start]")
        else:
            # Resuming -- show recent context
            self._show_recap()

        while True:
            player_input = self._get_input()

            if player_input is None:
                # EOF (Ctrl+D)
                break

            if not player_input.strip():
                continue

            command = parse_command(player_input)
            if command:
                cmd_name, args = command
                should_quit = await self._handle_command(cmd_name, args)
                if should_quit:
                    break
                continue

            await self._play_turn(player_input)

        self._print_exit_message()

    async def _play_turn(self, player_input: str) -> None:
        """Run a turn through the engine, streaming results to the renderer."""
        self._last_player_input = player_input

        chapter_title = self._current_chapter_title()
        self.renderer.begin_turn(self.game.state.turn + 1, chapter_title)

        # Track streaming state for the on_token callback
        streaming_state = {"phase": "idle", "current_char": None}

        async def on_token(source: str, character: str | None, token: str) -> None:
            """Stream callback: route tokens to the renderer.

            The turn engine calls this as tokens arrive from the LLM.
            We determine whether a token is thinking or content by checking
            for <think> tags -- but the streaming layer in turn.py already
            separates them. The source/character tells us who is speaking.

            Actually, the on_token callback from turn.py gets the raw token
            text. The thinking/content split was done in the agents, which
            pass tokens through. We receive the combined stream here.

            For simplicity: we don't get separate thinking vs content tokens
            from the callback -- that split happens inside the agent. The
            callback just gets content tokens. Thinking tokens are consumed
            internally by the agents.
            """
            if source == "narrator":
                if streaming_state["phase"] != "narrator":
                    streaming_state["phase"] = "narrator"
                self.renderer.render_narrator(token)
            elif source == "character":
                char_name = character or "?"
                if (
                    streaming_state["phase"] != "character"
                    or streaming_state["current_char"] != char_name
                ):
                    if streaming_state["phase"] == "narrator":
                        self.renderer.end_narrator()
                    elif streaming_state["phase"] == "character":
                        self.renderer.end_character()
                    streaming_state["phase"] = "character"
                    streaming_state["current_char"] = char_name
                self.renderer.render_character(char_name, token)

        try:
            # Show spinner for post-processing after streaming completes
            await run_turn(
                self.game,
                player_input,
                self.llm_config,
                on_token=on_token,
            )

            # End the final streaming section
            if streaming_state["phase"] == "narrator":
                self.renderer.end_narrator()
            elif streaming_state["phase"] == "character":
                self.renderer.end_character()

            self.renderer.end_turn()

            # Reload game state from disk (the engine committed changes)
            self._reload_game()

        except KeyboardInterrupt:
            self.renderer.show_error("Turn interrupted.")
            self._reload_game()
        except Exception as e:
            logger.exception("Error during turn")
            self.renderer.show_error(f"{e}\nYour turn was not saved. Try again.")
            # Reload from disk to discard partial in-memory mutations
            self._reload_game()

    def _get_input(self) -> str | None:
        """Prompt for player input. Returns None on EOF."""
        try:
            return self.console.input(
                f"[bold bright_white]{self.game.state.player_name} > [/]"
            )
        except EOFError:
            return None

    async def _handle_command(self, cmd: str, args: list[str]) -> bool:
        """Execute a slash command. Returns True if session should end."""
        if cmd == "help":
            cmd_help(self.console)
        elif cmd == "quit":
            return True
        elif cmd == "undo":
            self.game = cmd_undo(self.console, self.game, args)
            self.renderer.game = self.game
        elif cmd == "history":
            cmd_history(self.console, self.game)
        elif cmd == "save":
            cmd_save(self.console, self.game)
        elif cmd == "status":
            cmd_status(self.console, self.game)
        elif cmd == "memory":
            cmd_memory(self.console, self.game, args)
        elif cmd == "think":
            self.show_thinking = cmd_think(self.console, args, self.show_thinking)
        elif cmd == "retry":
            await self._retry()
        elif cmd == "conversation":
            cmd_conversation(self.console, self.game, args)
        else:
            self.console.print(
                f"Unknown command: /{cmd}. Type /help for available commands.",
                style=Style(color="red"),
            )
        return False

    async def _retry(self) -> None:
        """Undo last turn and replay the same player input."""
        if self._last_player_input is None:
            self.console.print("No previous input to retry.", style=STATUS_STYLE)
            return

        previous_input = self._last_player_input
        # Undo last turn
        self.game = cmd_undo(self.console, self.game, [])
        self.renderer.game = self.game

        # Replay the same input
        self.console.print(f"Replaying: {previous_input}", style=STATUS_STYLE)
        await self._play_turn(previous_input)

    def _show_recap(self) -> None:
        """Show the last few conversation entries for context."""
        entries = self.game.conversation[-5:]
        if not entries:
            return
        self.console.print()
        self.console.print("  Previously...", style=Style(dim=True, italic=True))
        self.console.print()
        for entry in entries:
            if entry.role == "narrator":
                text = entry.content[:200] + ("..." if len(entry.content) > 200 else "")
                self.console.print(Text(f"  {text}", style=NARRATOR_STYLE))
            elif entry.role == "player":
                line = Text(f"  {self.game.state.player_name}: ", style=PLAYER_STYLE)
                line.append(entry.content)
                self.console.print(line)
            elif entry.role == "character":
                name = entry.character or "?"
                color = get_character_color(name, list(self.game.characters.keys()))
                self.console.print(
                    Text(
                        f"  {name}: ",
                        style=Style(color=color, bold=True),
                    ),
                    end="",
                )
                text = entry.content[:200] + ("..." if len(entry.content) > 200 else "")
                self.console.print(Text(text, style=Style(color=color)))
        self.console.print()

    def _current_chapter_title(self) -> str:
        """Get the current chapter's display title."""
        chapter_id = self.game.state.current_chapter
        chapter = self.game.chapters.get(chapter_id)
        return chapter.title if chapter else chapter_id

    def _print_exit_message(self) -> None:
        """Print a farewell message with current turn number."""
        turn = self.game.state.turn
        self.console.print(
            f"\nGame saved at turn {turn}. See you next time.\n",
            style=STATUS_STYLE,
        )

    def _reload_game(self) -> None:
        """Reload game from disk, discarding in-memory state."""
        try:
            self.game = load_save(self.game.save_path.name, self.game.save_path.parent)
            self.renderer.game = self.game
        except Exception:
            logger.exception("Failed to reload game from disk")

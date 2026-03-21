"""Top-level CLI application: banner, main menu, session dispatch."""

from __future__ import annotations

from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel

from theact.cli.menu import (
    confirm,
    delete_save_dir,
    prompt_choice,
    prompt_text,
    show_game_list,
    show_save_list,
)
from theact.cli.session import GameSession
from theact.cli.styles import ERROR_STYLE, STATUS_STYLE
from theact.io.save_manager import SAVES_DIR, create_save, load_save, slugify
from theact.llm.config import LLMConfig, load_llm_config
from theact.models.game import LoadedGame


class Application:
    """Top-level CLI application.

    Displays the banner, manages the main menu, and dispatches
    to game sessions. All game logic lives in the engine; this
    is purely presentation and navigation.
    """

    def __init__(self) -> None:
        self.console = Console()
        self.llm_config: LLMConfig | None = None

    async def run(self) -> None:
        """Main entry point. Shows banner, loads config, runs menu loop."""
        load_dotenv()
        self._print_banner()
        self.llm_config = self._load_config()
        if self.llm_config is None:
            return

        while True:
            choice = self._main_menu()
            if choice == "new":
                await self._new_game()
            elif choice == "continue":
                await self._continue_game()
            elif choice == "delete":
                self._delete_save()
            elif choice == "quit":
                self._farewell()
                break

    def _print_banner(self) -> None:
        """Print the title card."""
        banner = Panel(
            "[bold bright_white]T H E   A C T[/]\n[dim]an AI text-based RPG[/]",
            border_style="dim",
            padding=(1, 4),
        )
        self.console.print()
        self.console.print(banner, justify="center")
        self.console.print()

    def _load_config(self) -> LLMConfig | None:
        """Load LLM config from env. Print error and exit if missing."""
        try:
            return load_llm_config()
        except ValueError as e:
            self.console.print(f"\n{e}", style=ERROR_STYLE)
            self.console.print(
                "Create a .env file with LLM_API_KEY=your_key_here",
                style=STATUS_STYLE,
            )
            return None

    def _main_menu(self) -> str:
        """Display menu, return choice string."""
        self.console.print()
        self.console.print("  1. New Game", style="bold")
        self.console.print("  2. Continue Game", style="bold")
        self.console.print("  3. Delete Save", style="bold")
        self.console.print("  4. Quit", style="bold")
        self.console.print()

        while True:
            try:
                raw = self.console.input("> ")
            except (EOFError, KeyboardInterrupt):
                return "quit"
            raw = raw.strip()
            if raw == "1":
                return "new"
            elif raw == "2":
                return "continue"
            elif raw == "3":
                return "delete"
            elif raw == "4" or raw.lower() in ("q", "quit"):
                return "quit"
            else:
                self.console.print("Please enter 1, 2, 3, or 4.", style=ERROR_STYLE)

    async def _new_game(self) -> None:
        """Game selection -> save creation -> enter session."""
        games = show_game_list(self.console)
        if not games:
            return

        idx = prompt_choice(self.console, games, "Select a game")
        if idx is None:
            return
        game_meta = games[idx]

        # Get save name
        save_name = prompt_text(self.console, "Save name", default=game_meta.id)
        save_id = slugify(save_name)
        if not save_id:
            save_id = game_meta.id

        # Get player name
        player_name = prompt_text(self.console, "Your character name")
        if not player_name:
            player_name = "Player"

        try:
            create_save(game_meta.id, save_id, player_name)
            self.console.print(f"\nCreated save: {save_id}", style=STATUS_STYLE)
        except FileExistsError:
            self.console.print(
                f"A save named '{save_id}' already exists. Choose a different name.",
                style=ERROR_STYLE,
            )
            return
        except FileNotFoundError as e:
            self.console.print(f"Error: {e}", style=ERROR_STYLE)
            return

        game = load_save(save_id)
        await self._enter_session(game)

    async def _continue_game(self) -> None:
        """Save selection -> load -> enter session."""
        saves = show_save_list(self.console)
        if not saves:
            return

        idx = prompt_choice(self.console, saves, "Select a save")
        if idx is None:
            return

        save_id = saves[idx]["id"]
        try:
            game = load_save(save_id)
        except Exception as e:
            self.console.print(f"Error loading save: {e}", style=ERROR_STYLE)
            return

        await self._enter_session(game)

    def _delete_save(self) -> None:
        """Save selection -> confirm -> delete."""
        saves = show_save_list(self.console)
        if not saves:
            return

        idx = prompt_choice(self.console, saves, "Select a save to delete")
        if idx is None:
            return

        save_info = saves[idx]
        if not confirm(
            self.console,
            f"Delete save '{save_info['id']}' ({save_info['game_title']}, turn {save_info['turn']})?",
        ):
            self.console.print("Cancelled.", style=STATUS_STYLE)
            return

        save_path = SAVES_DIR / save_info["id"]
        if save_path.exists():
            delete_save_dir(save_path)
            self.console.print(f"Deleted save: {save_info['id']}", style=STATUS_STYLE)
        else:
            self.console.print("Save not found.", style=ERROR_STYLE)

    async def _enter_session(self, game: LoadedGame) -> None:
        """Create a GameSession and run it."""
        session = GameSession(self.console, game, self.llm_config)
        try:
            await session.run()
        except KeyboardInterrupt:
            self.console.print(
                f"\nGame saved at turn {game.state.turn}. See you next time.\n",
                style=STATUS_STYLE,
            )

    def _farewell(self) -> None:
        """Print farewell message."""
        self.console.print("\nUntil next time.\n", style=STATUS_STYLE)

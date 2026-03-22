"""Multi-step game creation wizard for the web UI.

Wraps the existing creator APIs (proposer, pipeline, validator, fixer, writer)
in a NiceGUI stepper interface. No creator logic is duplicated -- every LLM
call goes through src/theact/creator/.
"""

from __future__ import annotations

import logging

import yaml
from openai import AsyncOpenAI

from nicegui import ui

from theact.creator.config import CreatorLLMConfig, load_creator_config
from theact.creator.fixer import fix_validation_errors
from theact.creator.pipeline import run_generation_pipeline
from theact.creator.proposer import (
    assemble_proposal,
    generate_chapters_proposal,
    generate_characters_proposal,
    generate_setting,
    revise_chapters_proposal,
    revise_characters_proposal,
    revise_setting,
)
from theact.creator.validator import check_size_warnings, validate_game_data
from theact.creator.writer import write_game_files

logger = logging.getLogger(__name__)


class CreatorWizard:
    """Multi-step wizard UI for creating a new game.

    Steps:
        1. Concept input
        2. Proposal review (setting, characters, chapters)
        3. Generation with progress
        4. Review and finalize
    """

    def __init__(self, on_complete: callable) -> None:
        self.on_complete = on_complete

        # Creator LLM config and client (initialized in build)
        self._config: CreatorLLMConfig | None = None
        self._client: AsyncOpenAI | None = None

        # State carried between steps
        self._concept: str = ""
        self._setting_data: dict | None = None
        self._characters_data: dict | None = None
        self._chapters_data: dict | None = None
        self._proposal: dict | None = None
        self._generated_data: dict | None = None
        self._validation_result = None

        # UI references
        self._stepper: ui.stepper | None = None
        self._review_container: ui.element | None = None
        self._gen_container: ui.element | None = None
        self._val_container: ui.element | None = None
        self._files_container: ui.element | None = None
        self._gen_trigger = None

    def build(self) -> None:
        """Build the wizard page layout."""
        # Check creator config
        try:
            self._config = load_creator_config()
            self._client = AsyncOpenAI(
                base_url=self._config.base_url,
                api_key=self._config.api_key,
            )
        except ValueError as e:
            self._build_config_error(str(e))
            return

        with ui.column().classes("w-full max-w-4xl mx-auto p-4"):
            # Header
            with ui.row().classes("w-full items-center"):
                ui.button(icon="arrow_back", on_click=self.on_complete).props(
                    "flat"
                ).tooltip("Back to menu")
                ui.label("Create a New Game").style(
                    "font-size: 1.4em; font-weight: bold; color: #ccc;"
                )

            ui.separator()

            # Model info banner
            if self._config.is_small_model:
                ui.label(
                    "Warning: Using a small model for game creation. "
                    "Results may be unreliable. Set CREATOR_MODEL to a "
                    "larger model (e.g., gpt-4o) in your .env file."
                ).classes("w-full").style(
                    "color: #ff9800; background: #332200; padding: 8px; "
                    "border-radius: 4px; font-size: 0.9em;"
                )

            # Stepper
            with ui.stepper().props("vertical").classes("w-full") as stepper:
                self._stepper = stepper
                self._build_step_concept()
                self._build_step_proposal()
                self._build_step_generation()
                self._build_step_finalize()

    # ------------------------------------------------------------------
    # Step 1: Concept Input
    # ------------------------------------------------------------------

    def _build_step_concept(self) -> None:
        with ui.step("Concept"):
            ui.label(
                "Describe your game world, characters, and story. "
                "Include genre, setting, key characters, and what the player does."
            ).style("color: #aaa; font-size: 0.9em;")

            concept_input = (
                ui.textarea(
                    placeholder=(
                        "A noir detective mystery set in 1940s Los Angeles. "
                        "The player is a private eye investigating a missing "
                        "person case. Characters include a femme fatale "
                        "nightclub singer and a corrupt police captain..."
                    )
                )
                .classes("w-full")
                .props("outlined rows=6")
            )

            # Example concepts as clickable chips
            ui.label("Examples:").style(
                "color: #888; font-size: 0.8em; margin-top: 8px;"
            )
            with ui.row().classes("gap-2 flex-wrap"):
                examples = [
                    "A haunted lighthouse on a remote island...",
                    "A space station crew dealing with an alien signal...",
                    "A medieval village facing a dragon threat...",
                ]
                for example in examples:
                    ui.chip(
                        example[:40] + "...",
                        on_click=lambda e=example: concept_input.set_value(e),
                    ).props("outline clickable")

            # Progress display (hidden until "Generate" is clicked)
            progress_container = ui.column().classes("w-full")
            progress_container.set_visibility(False)

            async def on_generate():
                concept = concept_input.value.strip()
                if not concept:
                    ui.notify("Please enter a game concept.", type="warning")
                    return

                self._concept = concept
                progress_container.set_visibility(True)
                progress_container.clear()

                try:
                    await self._run_proposal_phase(progress_container)
                    self._render_proposal(self._review_container)
                    self._stepper.next()
                except Exception as e:
                    logger.exception("Proposal generation failed")
                    with progress_container:
                        ui.label(f"Error: {e}").style("color: #ff5252;")
                        ui.button("Retry", on_click=on_generate, icon="refresh").props(
                            "outline"
                        )

            with ui.stepper_navigation():
                ui.button(
                    "Generate Proposal", on_click=on_generate, icon="auto_awesome"
                ).props("color=primary")

    async def _run_proposal_phase(self, progress_container: ui.element) -> None:
        """Run setting -> characters -> chapters proposal generation."""

        def _progress(msg: str) -> ui.label:
            with progress_container:
                row = ui.row().classes("items-center gap-2")
                with row:
                    ui.spinner("dots", size="sm")
                    label = ui.label(msg).style("color: #aaa;")
            return label

        # Setting
        label = _progress("Generating setting...")
        self._setting_data = await generate_setting(
            self._concept, self._client, self._config
        )
        label.style("color: #69f0ae;")
        label.text = "Setting generated"

        # Characters
        label = _progress("Creating characters...")
        self._characters_data = await generate_characters_proposal(
            self._setting_data, self._client, self._config
        )
        char_count = len(self._characters_data.get("characters", []))
        label.style("color: #69f0ae;")
        label.text = f"Characters generated ({char_count} characters)"

        # Chapters
        label = _progress("Planning chapters...")
        self._chapters_data = await generate_chapters_proposal(
            self._setting_data, self._characters_data, self._client, self._config
        )
        chap_count = len(self._chapters_data.get("chapters", []))
        label.style("color: #69f0ae;")
        label.text = f"Chapters generated ({chap_count} chapters)"

        # Assemble
        self._proposal = assemble_proposal(
            self._setting_data, self._characters_data, self._chapters_data
        )

    # ------------------------------------------------------------------
    # Step 2: Proposal Review
    # ------------------------------------------------------------------

    def _build_step_proposal(self) -> None:
        with ui.step("Proposal Review"):
            review_container = ui.column().classes("w-full")
            self._review_container = review_container

            feedback_input = (
                ui.textarea(placeholder="Suggest changes, or leave blank to accept...")
                .classes("w-full")
                .props("outlined rows=3")
            )

            revise_progress = ui.column().classes("w-full")
            revise_progress.set_visibility(False)

            async def on_revise():
                feedback = feedback_input.value.strip()
                if not feedback:
                    ui.notify(
                        "Enter feedback to revise, or click Accept.",
                        type="info",
                    )
                    return
                await self._revise_proposal(feedback, review_container, revise_progress)
                feedback_input.value = ""

            async def on_accept():
                self._refresh_generation_step()
                self._stepper.next()

            with ui.stepper_navigation():
                ui.button("Back", on_click=self._stepper.previous).props("flat")
                ui.button("Revise", on_click=on_revise, icon="edit").props("outline")
                ui.button("Accept & Generate", on_click=on_accept, icon="check").props(
                    "color=primary"
                )

    def _render_proposal(self, container: ui.element) -> None:
        """Render the current proposal into the given container."""
        container.clear()
        if not self._proposal:
            return

        with container:
            # Setting card
            with ui.card().classes("w-full"):
                ui.label(self._proposal.get("title", "Untitled")).style(
                    "font-size: 1.1em; font-weight: bold; color: #fff;"
                )
                ui.label(f"ID: {self._proposal.get('id', '')}").style(
                    "color: #888; font-size: 0.8em;"
                )
                if self._proposal.get("setting"):
                    ui.label("Setting").style(
                        "font-weight: bold; color: #ccc; margin-top: 8px;"
                    )
                    ui.label(self._proposal["setting"]).style("color: #aaa;")
                if self._proposal.get("tone"):
                    ui.label("Tone").style(
                        "font-weight: bold; color: #ccc; margin-top: 8px;"
                    )
                    ui.label(self._proposal["tone"]).style("color: #aaa;")
                if self._proposal.get("rules"):
                    ui.label("Rules").style(
                        "font-weight: bold; color: #ccc; margin-top: 8px;"
                    )
                    ui.label(self._proposal["rules"]).style("color: #aaa;")

            # Character cards
            for char in self._proposal.get("characters", []):
                with ui.card().classes("w-full"):
                    with ui.row().classes("items-center gap-2"):
                        ui.icon("person").style("color: #69f0ae;")
                        ui.label(char.get("name", "?")).style(
                            "font-weight: bold; color: #fff;"
                        )
                        ui.badge(char.get("role", ""), color="blue").classes("text-xs")
                    ui.label(f"Stem: {char.get('stem', '')}").style(
                        "color: #888; font-size: 0.8em;"
                    )

            # Chapter cards
            for i, chap in enumerate(self._proposal.get("chapters", []), 1):
                with ui.card().classes("w-full"):
                    with ui.row().classes("items-center gap-2"):
                        ui.icon("menu_book").style("color: #ffff00;")
                        ui.label(f"Ch. {i}: {chap.get('title', '?')}").style(
                            "font-weight: bold; color: #fff;"
                        )
                    if chap.get("summary"):
                        ui.label(chap["summary"]).style("color: #aaa;")
                    ui.label(f"ID: {chap.get('id', '')}").style(
                        "color: #888; font-size: 0.8em;"
                    )

    async def _revise_proposal(
        self,
        feedback: str,
        review_container: ui.element,
        progress_container: ui.element,
    ) -> None:
        """Revise the proposal based on user feedback."""
        progress_container.clear()
        progress_container.set_visibility(True)

        def _progress(msg: str) -> ui.label:
            with progress_container:
                row = ui.row().classes("items-center gap-2")
                with row:
                    ui.spinner("dots", size="sm")
                    label = ui.label(msg).style("color: #aaa;")
            return label

        try:
            label = _progress("Revising setting...")
            self._setting_data = await revise_setting(
                self._setting_data, feedback, self._client, self._config
            )
            label.style("color: #69f0ae;")
            label.text = "Setting revised"

            label = _progress("Revising characters...")
            self._characters_data = await revise_characters_proposal(
                self._characters_data,
                self._setting_data,
                feedback,
                self._client,
                self._config,
            )
            label.style("color: #69f0ae;")
            label.text = "Characters revised"

            label = _progress("Revising chapters...")
            self._chapters_data = await revise_chapters_proposal(
                self._chapters_data,
                self._setting_data,
                self._characters_data,
                feedback,
                self._client,
                self._config,
            )
            label.style("color: #69f0ae;")
            label.text = "Chapters revised"

            self._proposal = assemble_proposal(
                self._setting_data, self._characters_data, self._chapters_data
            )
            self._render_proposal(review_container)
            progress_container.clear()
            progress_container.set_visibility(False)
            ui.notify("Proposal revised.", type="positive")
        except Exception as e:
            logger.exception("Proposal revision failed")
            with progress_container:
                ui.label(f"Revision failed: {e}").style("color: #ff5252;")

    # ------------------------------------------------------------------
    # Step 3: Generation
    # ------------------------------------------------------------------

    def _build_step_generation(self) -> None:
        with ui.step("Generation"):
            gen_container = ui.column().classes("w-full")
            validation_container = ui.column().classes("w-full")

            self._gen_container = gen_container
            self._val_container = validation_container

            async def on_generate():
                gen_container.clear()
                validation_container.clear()
                await self._run_generation(gen_container, validation_container)

            self._gen_trigger = on_generate

            with ui.stepper_navigation():
                ui.button("Back", on_click=self._stepper.previous).props("flat")
                ui.button(
                    "Continue to Review",
                    on_click=lambda: self._advance_to_finalize(),
                    icon="arrow_forward",
                ).props("color=primary")

    def _advance_to_finalize(self) -> None:
        """Advance to the finalize step and render generated files."""
        self._render_generated_files(self._files_container)
        self._stepper.next()

    def _refresh_generation_step(self) -> None:
        """Trigger generation when the step is entered."""
        ui.timer(0.2, lambda: self._gen_trigger(), once=True)

    async def _run_generation(
        self,
        gen_container: ui.element,
        val_container: ui.element,
    ) -> None:
        """Run the generation pipeline and display progress."""
        progress_labels: list[ui.label] = []

        def on_progress(msg: str) -> None:
            with gen_container:
                row = ui.row().classes("items-center gap-2")
                with row:
                    ui.spinner("dots", size="sm")
                    label = ui.label(msg).style("color: #aaa;")
                progress_labels.append(label)
            # Mark previous label as complete
            if len(progress_labels) > 1:
                prev = progress_labels[-2]
                prev.style("color: #69f0ae;")

        try:
            self._generated_data = await run_generation_pipeline(
                self._proposal,
                self._client,
                self._config,
                on_progress=on_progress,
            )

            # Mark final progress label as complete
            if progress_labels:
                progress_labels[-1].style("color: #69f0ae;")

            # Validate
            await self._run_validation(val_container)

        except Exception as e:
            logger.exception("Generation failed")
            with gen_container:
                ui.label(f"Generation failed: {e}").style("color: #ff5252;")
                ui.button("Retry", on_click=self._gen_trigger, icon="refresh").props(
                    "outline"
                )

    async def _run_validation(self, container: ui.element) -> None:
        """Validate generated data and attempt auto-fix if needed."""
        container.clear()

        with container:
            ui.label("Validating...").style("color: #aaa;")

        result = validate_game_data(self._generated_data)

        if not result.valid:
            container.clear()
            with container:
                ui.label(
                    f"Validation found {len(result.errors)} error(s). "
                    "Attempting auto-fix..."
                ).style("color: #ff9800;")
                for err in result.errors:
                    ui.label(f"  {err.file}: {err.message}").style(
                        "color: #ff9800; font-size: 0.85em; margin-left: 12px;"
                    )

            self._generated_data, result = await fix_validation_errors(
                self._generated_data, result, self._client, self._config
            )

        self._validation_result = result

        container.clear()
        with container:
            if result.valid:
                ui.label("Validation passed.").style(
                    "color: #69f0ae; font-weight: bold;"
                )
            else:
                ui.label("Validation errors remain after auto-fix:").style(
                    "color: #ff5252; font-weight: bold;"
                )
                for err in result.errors:
                    ui.label(f"  {err.file}: {err.message}").style(
                        "color: #ff5252; font-size: 0.85em; margin-left: 12px;"
                    )

            # Size warnings
            if result.valid:
                warnings = check_size_warnings(
                    result.world, result.characters, result.chapters
                )
                if warnings:
                    ui.label("Size warnings:").style(
                        "color: #ff9800; font-weight: bold; margin-top: 8px;"
                    )
                    for w in warnings:
                        ui.label(f"  {w}").style(
                            "color: #ff9800; font-size: 0.85em; margin-left: 12px;"
                        )

    # ------------------------------------------------------------------
    # Step 4: Review & Finalize
    # ------------------------------------------------------------------

    def _build_step_finalize(self) -> None:
        with ui.step("Review & Finalize"):
            files_container = ui.column().classes("w-full")
            self._files_container = files_container

            feedback_input = (
                ui.textarea(
                    placeholder=("Request changes, or click Create Game to finalize...")
                )
                .classes("w-full")
                .props("outlined rows=3")
            )

            revise_progress = ui.column().classes("w-full")
            revise_progress.set_visibility(False)

            async def on_regenerate():
                feedback = feedback_input.value.strip()
                if not feedback:
                    ui.notify("Enter feedback to revise.", type="info")
                    return
                await self._revise_generated(feedback, revise_progress)
                self._render_generated_files(files_container)
                feedback_input.value = ""

            async def on_create():
                await self._write_game(files_container)

            with ui.stepper_navigation():
                ui.button("Back", on_click=self._stepper.previous).props("flat")
                ui.button("Regenerate", on_click=on_regenerate, icon="edit").props(
                    "outline"
                )
                ui.button("Create Game", on_click=on_create, icon="save").props(
                    "color=primary"
                )

    def _render_generated_files(self, container: ui.element) -> None:
        """Render all generated game files as collapsible YAML blocks."""
        container.clear()
        if not self._generated_data:
            return

        with container:
            # game.yaml
            with ui.expansion("game.yaml", icon="description").classes("w-full"):
                ui.code(
                    yaml.dump(
                        self._generated_data["game"],
                        default_flow_style=False,
                        allow_unicode=True,
                        sort_keys=False,
                    ),
                    language="yaml",
                ).classes("w-full")

            # world.yaml
            with ui.expansion("world.yaml", icon="public").classes("w-full"):
                ui.code(
                    yaml.dump(
                        self._generated_data["world"],
                        default_flow_style=False,
                        allow_unicode=True,
                        sort_keys=False,
                    ),
                    language="yaml",
                ).classes("w-full")

            # Character files
            for stem, char_data in self._generated_data.get("characters", {}).items():
                with ui.expansion(f"characters/{stem}.yaml", icon="person").classes(
                    "w-full"
                ):
                    ui.code(
                        yaml.dump(
                            char_data,
                            default_flow_style=False,
                            allow_unicode=True,
                            sort_keys=False,
                        ),
                        language="yaml",
                    ).classes("w-full")

            # Chapter files
            for cid, chap_data in self._generated_data.get("chapters", {}).items():
                with ui.expansion(f"chapters/{cid}.yaml", icon="menu_book").classes(
                    "w-full"
                ):
                    ui.code(
                        yaml.dump(
                            chap_data,
                            default_flow_style=False,
                            allow_unicode=True,
                            sort_keys=False,
                        ),
                        language="yaml",
                    ).classes("w-full")

    async def _revise_generated(
        self, feedback: str, progress_container: ui.element
    ) -> None:
        """Revise generated files based on feedback."""
        from theact.creator.session import revise_targeted

        progress_container.clear()
        progress_container.set_visibility(True)

        def _progress(msg: str) -> ui.label:
            with progress_container:
                row = ui.row().classes("items-center gap-2")
                with row:
                    ui.spinner("dots", size="sm")
                    label = ui.label(msg).style("color: #aaa;")
            return label

        try:
            label = _progress("Revising game files...")
            self._generated_data = await revise_targeted(
                self._generated_data, feedback, self._client, self._config
            )
            label.style("color: #69f0ae;")
            label.text = "Files revised"

            label = _progress("Validating...")
            result = validate_game_data(self._generated_data)
            if not result.valid:
                label.text = "Validation errors found, auto-fixing..."
                self._generated_data, result = await fix_validation_errors(
                    self._generated_data, result, self._client, self._config
                )
            self._validation_result = result
            label.style("color: #69f0ae;")
            label.text = "Validation complete"

            progress_container.clear()
            progress_container.set_visibility(False)

            if result.valid:
                ui.notify("Revision complete.", type="positive")
            else:
                ui.notify(
                    f"Revision complete but {len(result.errors)} error(s) remain.",
                    type="warning",
                )
        except Exception as e:
            logger.exception("Revision failed")
            with progress_container:
                ui.label(f"Revision failed: {e}").style("color: #ff5252;")

    async def _write_game(self, container: ui.element) -> None:
        """Write the game files to disk."""
        if not self._validation_result or not self._validation_result.valid:
            ui.notify(
                "Cannot create game: validation errors remain.",
                type="negative",
            )
            return

        game_id = self._validation_result.game.id

        try:
            from theact.io.save_manager import GAMES_DIR

            game_dir = GAMES_DIR / game_id
            if game_dir.exists():
                # Show confirmation dialog
                with ui.dialog() as dialog, ui.card():
                    ui.label(f'Game "{game_id}" already exists. Overwrite?').style(
                        "color: #ccc;"
                    )
                    with ui.row().classes("justify-end gap-2"):
                        ui.button("Cancel", on_click=dialog.close).props("flat")

                        async def confirm_overwrite():
                            dialog.close()
                            self._do_write(game_id, overwrite=True)

                        ui.button(
                            "Overwrite",
                            on_click=confirm_overwrite,
                            color="red",
                        ).props("flat")
                dialog.open()
                return

            self._do_write(game_id, overwrite=False)

        except Exception as e:
            logger.exception("Failed to write game files")
            ui.notify(f"Error: {e}", type="negative")

    def _do_write(self, game_id: str, overwrite: bool) -> None:
        """Perform the actual file write and navigate to menu."""
        game_path = write_game_files(
            game_id, self._validation_result, overwrite=overwrite
        )
        ui.notify(
            f"Game created: {game_id} ({game_path})",
            type="positive",
            timeout=5000,
        )
        # Navigate back to menu after a brief delay
        ui.timer(1.0, self.on_complete, once=True)

    # ------------------------------------------------------------------
    # Error / config screens
    # ------------------------------------------------------------------

    def _build_config_error(self, message: str) -> None:
        """Show a helpful message when creator config is missing."""
        with ui.column().classes("w-full max-w-3xl mx-auto p-4 items-center"):
            ui.icon("warning", size="xl").style("color: #ff9800;")
            ui.label("Creator Not Configured").style(
                "font-size: 1.2em; font-weight: bold; color: #ccc;"
            )
            ui.label(message).style("color: #ff9800;")
            ui.label(
                "The game creator requires an LLM API key. "
                "Set CREATOR_API_KEY (or LLM_API_KEY) in your .env file. "
                "Optionally set CREATOR_MODEL to a capable model like gpt-4o."
            ).style("color: #aaa; margin-top: 8px;")
            ui.button(
                "Back to Menu",
                on_click=lambda: ui.navigate.to("/"),
                icon="arrow_back",
            ).props("outline")

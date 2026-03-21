# Step 04: Game Creation Wizard

> **Implementation note:** This step adds a multi-step game creation wizard to the web UI, replacing the need for the `scripts/create_game.py` terminal script. The wizard calls the existing creator APIs (`src/theact/creator/`) -- no creator logic is rewritten. All LLM calls go through the existing proposer, pipeline, validator, fixer, and writer modules. The creator uses a separate (usually larger) model configured via `CREATOR_*` env vars. If no creator config is set, the wizard shows a helpful message directing the user to configure it.

## 1. Overview

The terminal CLI has a full interactive game creation flow via `scripts/create_game.py`, which calls `src/theact/creator/session.py:create_game()`. That function is tightly coupled to terminal I/O (`console.input()`, `console.print()`, Rich formatting) and cannot be reused from the web UI.

This step builds a **browser-native game creation wizard** at the `/create` route. The wizard decomposes the creation flow into four visual steps:

1. **Concept** -- the user describes their game idea
2. **Proposal Review** -- the LLM generates setting, characters, and chapters; the user reviews and revises
3. **Generation** -- the full game files are generated, validated, and auto-fixed
4. **Review & Finalize** -- the user inspects generated YAML files, provides feedback, and writes to disk

The wizard calls the same decomposed creator APIs that the CLI uses:

- `generate_setting()`, `generate_characters_proposal()`, `generate_chapters_proposal()`, `assemble_proposal()` for the proposal phase
- `revise_setting()`, `revise_characters_proposal()`, `revise_chapters_proposal()` for revisions
- `run_generation_pipeline()` for file generation
- `validate_game_data()` and `fix_validation_errors()` for validation
- `check_size_warnings()` for size checks
- `write_game_files()` for finalization

No new LLM prompts, no new agents, no changes to any creator module.

## 2. Page Route

**Modified files:** `src/theact/web/app.py`

### 2.1 New Route

Register a new NiceGUI page at `/create`:

```python
# In setup_app() within src/theact/web/app.py

@ui.page("/create")
async def create_page():
    """Game creation wizard page."""
    from theact.web.creator_wizard import CreatorWizard

    wizard = CreatorWizard(on_complete=lambda: ui.navigate.to("/"))
    wizard.build()
```

### 2.2 Menu Link

Add a "Create Game" button to the main menu in `_build_menu()`, placed between the banner and the "New Game" section:

```python
# In _build_menu(), after the banner and separator:
ui.button(
    "Create Game",
    on_click=lambda: ui.navigate.to("/create"),
    icon="auto_fix_high",
).props("outline").classes("w-full")
```

### 2.3 Navigation Flow

```
Menu (/):
    [Create Game] button  -->  /create
                                  |
                                  v
                          CreatorWizard (4 steps)
                                  |
                            on completion
                                  |
                                  v
                              Menu (/)
                      (new game appears in "New Game" dropdown)
```

The wizard page is self-contained. On completion or cancellation, it navigates back to `/` where the new game will appear in the `list_games()` dropdown.

## 3. Wizard Module

**New file:** `src/theact/web/creator_wizard.py`

### 3.1 Class Structure

```python
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

    def build(self) -> None:
        """Build the wizard page layout."""
        ...
```

### 3.2 Page Layout

The wizard uses NiceGUI's `ui.stepper` component for step navigation:

```python
def build(self) -> None:
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
```

## 4. Step 1: Concept Input

The first step collects the user's game concept as free-form text.

```python
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
                    "The player is a private eye investigating a missing person case. "
                    "Characters include a femme fatale nightclub singer and a "
                    "corrupt police captain..."
                )
            )
            .classes("w-full")
            .props("outlined rows=6")
        )

        # Optional: example concepts as clickable chips
        ui.label("Examples:").style("color: #888; font-size: 0.8em; margin-top: 8px;")
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
                self._stepper.next()  # advance to Step 2
            except Exception as e:
                logger.exception("Proposal generation failed")
                with progress_container:
                    ui.label(f"Error: {e}").style("color: #ff5252;")
                    ui.button(
                        "Retry", on_click=on_generate, icon="refresh"
                    ).props("outline")

        with ui.stepper_navigation():
            ui.button(
                "Generate Proposal", on_click=on_generate, icon="auto_awesome"
            ).props("color=primary")
```

### 4.1 Proposal Generation

The proposal phase makes 3 sequential LLM calls. Show progress for each:

```python
async def _run_proposal_phase(self, progress_container: ui.element) -> None:
    """Run setting -> characters -> chapters proposal generation."""

    def _progress(msg: str) -> ui.label:
        with progress_container:
            row = ui.row().classes("items-center gap-2")
            with row:
                ui.spinner("dots", size="sm")
                label = ui.label(msg).style("color: #aaa;")
        return label

    # Step 1: Setting
    label = _progress("Generating setting...")
    self._setting_data = await generate_setting(
        self._concept, self._client, self._config
    )
    label.style("color: #69f0ae;")
    label.text = "Setting generated"

    # Step 2: Characters
    label = _progress("Creating characters...")
    self._characters_data = await generate_characters_proposal(
        self._setting_data, self._client, self._config
    )
    label.style("color: #69f0ae;")
    label.text = f"Characters generated ({len(self._characters_data.get('characters', []))} characters)"

    # Step 3: Chapters
    label = _progress("Planning chapters...")
    self._chapters_data = await generate_chapters_proposal(
        self._setting_data, self._characters_data, self._client, self._config
    )
    label.style("color: #69f0ae;")
    label.text = f"Chapters generated ({len(self._chapters_data.get('chapters', []))} chapters)"

    # Assemble
    self._proposal = assemble_proposal(
        self._setting_data, self._characters_data, self._chapters_data
    )
```

> **UI update timing:** The `label.text = "..."` and `label.style(...)` assignments inside the `_progress` callback execute during long `await` calls. NiceGUI may not immediately push these changes to the browser. During implementation, test that progress labels update visually in real time. If they batch-update only after all awaits complete, add explicit `.update()` calls on the label or its parent row, or use `await ui.run_javascript("void(0)")` to force a client round-trip between steps.

## 5. Step 2: Proposal Review

Displays the generated proposal in structured cards and allows iterative revision.

```python
def _build_step_proposal(self) -> None:
    with ui.step("Proposal Review"):
        review_container = ui.column().classes("w-full")

        feedback_input = (
            ui.textarea(placeholder="Suggest changes, or leave blank to accept...")
            .classes("w-full")
            .props("outlined rows=3")
        )

        async def on_revise():
            feedback = feedback_input.value.strip()
            if not feedback:
                ui.notify("Enter feedback to revise, or click Accept.", type="info")
                return
            await self._revise_proposal(feedback, review_container)
            feedback_input.value = ""

        async def on_accept():
            self._refresh_generation_step()
            self._stepper.next()

        with ui.stepper_navigation():
            ui.button("Back", on_click=self._stepper.previous).props("flat")
            ui.button("Revise", on_click=on_revise, icon="edit").props("outline")
            ui.button(
                "Accept & Generate", on_click=on_accept, icon="check"
            ).props("color=primary")

    # Initial render is deferred until the step is entered
    # (the proposal data is not available at build time)
```

### 5.1 Proposal Display

Render the proposal as structured cards when the step is entered. The display is refreshed after each revision.

```python
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
            ui.label(f'ID: {self._proposal.get("id", "")}').style(
                "color: #888; font-size: 0.8em;"
            )
            if self._proposal.get("setting"):
                ui.label("Setting").style("font-weight: bold; color: #ccc; margin-top: 8px;")
                ui.label(self._proposal["setting"]).style("color: #aaa;")
            if self._proposal.get("tone"):
                ui.label("Tone").style("font-weight: bold; color: #ccc; margin-top: 8px;")
                ui.label(self._proposal["tone"]).style("color: #aaa;")
            if self._proposal.get("rules"):
                ui.label("Rules").style("font-weight: bold; color: #ccc; margin-top: 8px;")
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
                ui.label(f'Stem: {char.get("stem", "")}').style(
                    "color: #888; font-size: 0.8em;"
                )

        # Chapter cards
        for i, chap in enumerate(self._proposal.get("chapters", []), 1):
            with ui.card().classes("w-full"):
                with ui.row().classes("items-center gap-2"):
                    ui.icon("menu_book").style("color: #ffff00;")
                    ui.label(f'Ch. {i}: {chap.get("title", "?")}').style(
                        "font-weight: bold; color: #fff;"
                    )
                if chap.get("summary"):
                    ui.label(chap["summary"]).style("color: #aaa;")
                ui.label(f'ID: {chap.get("id", "")}').style(
                    "color: #888; font-size: 0.8em;"
                )
```

### 5.2 Proposal Revision

Revision calls the per-section `revise_*` functions from `src/theact/creator/proposer.py`. The wizard revises all three sections using the same feedback text, since the user's feedback may touch any part of the proposal:

```python
async def _revise_proposal(
    self, feedback: str, review_container: ui.element
) -> None:
    """Revise the proposal based on user feedback."""
    ui.notify("Revising proposal...", type="info")

    try:
        self._setting_data = await revise_setting(
            self._setting_data, feedback, self._client, self._config
        )
        self._characters_data = await revise_characters_proposal(
            self._characters_data,
            self._setting_data,
            feedback,
            self._client,
            self._config,
        )
        self._chapters_data = await revise_chapters_proposal(
            self._chapters_data,
            self._setting_data,
            self._characters_data,
            feedback,
            self._client,
            self._config,
        )
        self._proposal = assemble_proposal(
            self._setting_data, self._characters_data, self._chapters_data
        )
        self._render_proposal(review_container)
        ui.notify("Proposal revised.", type="positive")
    except Exception as e:
        logger.exception("Proposal revision failed")
        ui.notify(f"Revision failed: {e}", type="negative")
```

## 6. Step 3: Generation

Runs the full generation pipeline with real-time progress display, then validates and auto-fixes.

```python
def _build_step_generation(self) -> None:
    with ui.step("Generation"):
        gen_container = ui.column().classes("w-full")
        validation_container = ui.column().classes("w-full")

        async def on_generate():
            gen_container.clear()
            validation_container.clear()
            await self._run_generation(gen_container, validation_container)

        # Auto-run generation when this step is entered
        # (triggered by _refresh_generation_step)
        self._gen_container = gen_container
        self._val_container = validation_container
        self._gen_trigger = on_generate

        with ui.stepper_navigation():
            ui.button("Back", on_click=self._stepper.previous).props("flat")
            ui.button(
                "Continue to Review",
                on_click=lambda: self._stepper.next(),
                icon="arrow_forward",
            ).props("color=primary")

def _refresh_generation_step(self) -> None:
    """Trigger generation when the step is entered."""
    ui.timer(0.2, lambda: self._gen_trigger(), once=True)
```

### 6.1 Generation Pipeline

Use `run_generation_pipeline()`'s `on_progress` callback to update the UI in real time:

```python
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
            self._proposal, self._client, self._config, on_progress=on_progress
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
```

### 6.2 Validation and Auto-Fix

```python
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
                f"Validation found {len(result.errors)} error(s). Attempting auto-fix..."
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
            ui.label("Validation passed.").style("color: #69f0ae; font-weight: bold;")
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
```

## 7. Step 4: Review & Finalize

Shows all generated YAML files and allows a final feedback loop before writing to disk.

```python
def _build_step_finalize(self) -> None:
    with ui.step("Review & Finalize"):
        files_container = ui.column().classes("w-full")

        feedback_input = (
            ui.textarea(placeholder="Request changes, or click Create Game to finalize...")
            .classes("w-full")
            .props("outlined rows=3")
        )

        async def on_regenerate():
            feedback = feedback_input.value.strip()
            if not feedback:
                ui.notify("Enter feedback to revise.", type="info")
                return
            # Go back to generation step with feedback applied
            await self._revise_generated(feedback)
            self._render_generated_files(files_container)
            feedback_input.value = ""

        async def on_create():
            await self._write_game(files_container)

        with ui.stepper_navigation():
            ui.button("Back", on_click=self._stepper.previous).props("flat")
            ui.button("Regenerate", on_click=on_regenerate, icon="edit").props(
                "outline"
            )
            ui.button(
                "Create Game", on_click=on_create, icon="save"
            ).props("color=primary")
```

### 7.1 YAML File Display

Show each generated file in a collapsible code block with syntax highlighting:

```python
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
            with ui.expansion(
                f"characters/{stem}.yaml", icon="person"
            ).classes("w-full"):
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
            with ui.expansion(
                f"chapters/{cid}.yaml", icon="menu_book"
            ).classes("w-full"):
                ui.code(
                    yaml.dump(
                        chap_data,
                        default_flow_style=False,
                        allow_unicode=True,
                        sort_keys=False,
                    ),
                    language="yaml",
                ).classes("w-full")
```

### 7.2 Targeted Revision

Feedback at this stage triggers the targeted revision flow from `src/theact/creator/session.py` -- classify which files the feedback targets, regenerate only those files, re-validate:

```python
async def _revise_generated(self, feedback: str) -> None:
    """Revise generated files based on feedback."""
    from theact.creator.session import revise_targeted

    ui.notify("Revising...", type="info")
    try:
        self._generated_data = await revise_targeted(
            self._generated_data, feedback, self._client, self._config
        )
        result = validate_game_data(self._generated_data)
        if not result.valid:
            self._generated_data, result = await fix_validation_errors(
                self._generated_data, result, self._client, self._config
            )
        self._validation_result = result

        if result.valid:
            ui.notify("Revision complete.", type="positive")
        else:
            ui.notify(
                f"Revision complete but {len(result.errors)} error(s) remain.",
                type="warning",
            )
    except Exception as e:
        logger.exception("Revision failed")
        ui.notify(f"Revision failed: {e}", type="negative")
```

**Action required:** `_revise_targeted` is a private function in `src/theact/creator/session.py`. Rename it to `revise_targeted` (remove the leading underscore) as a minimal change to make it importable. This is the preferred approach -- it is a one-line rename in `session.py` plus updating the one internal call site. Do NOT reimplement the logic in the wizard or create a wrapper; that would duplicate code.

### 7.3 Write to Disk

```python
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
        overwrite = False
        if game_dir.exists():
            # Show confirmation dialog
            with ui.dialog() as dialog, ui.card():
                ui.label(
                    f'Game "{game_id}" already exists. Overwrite?'
                ).style("color: #ccc;")
                with ui.row().classes("justify-end gap-2"):
                    ui.button("Cancel", on_click=dialog.close).props("flat")

                    async def confirm_overwrite():
                        dialog.close()
                        self._do_write(game_id, overwrite=True)

                    ui.button("Overwrite", on_click=confirm_overwrite, color="red").props(
                        "flat"
                    )
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
```

## 8. Error Handling

### 8.1 LLM API Errors

All LLM calls are wrapped in try/except blocks. On failure:
- Show the error message in red text within the current step
- Provide a "Retry" button that re-runs the failed operation
- Do not advance to the next step

```python
except Exception as e:
    logger.exception("LLM call failed")
    with container:
        ui.label(f"Error: {e}").style("color: #ff5252;")
        ui.button("Retry", on_click=retry_handler, icon="refresh").props("outline")
```

### 8.2 Validation Errors That Cannot Be Auto-Fixed

If `fix_validation_errors()` fails to resolve all errors:
- Display remaining errors in the validation container
- Allow the user to proceed to Step 4 and provide manual feedback
- The "Create Game" button in Step 4 is disabled while validation errors remain

### 8.3 Creator Config Missing

If `load_creator_config()` raises `ValueError` (no API key):

```python
def _build_config_error(self, message: str) -> None:
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
```

## 9. Creator Config

The game creator uses a **different model** than gameplay. Key points:

- `load_creator_config()` from `src/theact/creator/config.py` checks `CREATOR_*` env vars first, then falls back to `LLM_*` env vars
- If the resolved model is the small 7B gameplay model (`is_small_model`), the wizard shows a warning banner (see Section 3.2)
- The wizard does NOT provide in-UI config editing -- that is Step 05 (Settings). The wizard simply reads from env and reports if something is missing

### 9.1 Config Resolution Order

```
CREATOR_API_KEY  ->  LLM_API_KEY  ->  ValueError (no key)
CREATOR_MODEL    ->  LLM_MODEL    ->  fallback (small gameplay model + warning)
CREATOR_BASE_URL ->  LLM_BASE_URL ->  https://api.openai.com/v1
```

## 10. Tests

**New file:** `tests/web/test_creator_wizard.py`

Browser integration tests using the Playwright pattern from `tests/web/conftest.py`.

```python
"""Browser tests for the game creation wizard.

Run with:  uv run pytest tests/web/test_creator_wizard.py -v
"""

from playwright.sync_api import expect


class TestCreatePageAccess:
    """Tests for the /create route and navigation."""

    def test_create_page_accessible(self, page, web_server):
        """The /create page loads without error."""
        page.goto(f"{web_server}/create")
        expect(page.get_by_text("Create a New Game")).to_be_visible()

    def test_create_button_on_menu(self, page, web_server):
        """The menu has a 'Create Game' button."""
        page.goto(web_server)
        expect(page.get_by_role("button", name="Create Game")).to_be_visible()

    def test_create_button_navigates(self, page, web_server):
        """Clicking 'Create Game' navigates to /create."""
        page.goto(web_server)
        page.get_by_role("button", name="Create Game").click()
        page.wait_for_url(f"{web_server}/create")
        expect(page.get_by_text("Create a New Game")).to_be_visible()


class TestWizardSteps:
    """Tests for the wizard step structure."""

    def test_stepper_visible(self, page, web_server):
        """The step indicator is visible on the create page."""
        page.goto(f"{web_server}/create")
        expect(page.get_by_text("Concept")).to_be_visible()

    def test_concept_textarea_present(self, page, web_server):
        """Step 1 has a textarea for concept input."""
        page.goto(f"{web_server}/create")
        textarea = page.locator("textarea")
        expect(textarea).to_be_visible()

    def test_generate_button_present(self, page, web_server):
        """Step 1 has a 'Generate Proposal' button."""
        page.goto(f"{web_server}/create")
        expect(
            page.get_by_role("button", name="Generate Proposal")
        ).to_be_visible()

    def test_back_button_returns_to_menu(self, page, web_server):
        """The back arrow button navigates to the menu."""
        page.goto(f"{web_server}/create")
        page.get_by_role("button", name="").first.click()  # back arrow
        page.wait_for_url(web_server + "/")


class TestConfigError:
    """Tests for missing creator config handling.

    These tests require a test environment where CREATOR_API_KEY
    and LLM_API_KEY are both unset, which is difficult to arrange
    in the standard test fixture. Mark as manual or conditional.
    """

    pass  # Conditional tests based on env availability
```

## 11. What This Step Does NOT Do

- **No new LLM prompts or agents.** Every LLM call goes through existing creator modules. The wizard is purely a UI wrapper.
- **No changes to `src/theact/creator/`.** The creator modules are used as-is. The one exception is potentially making `_revise_targeted` public (a rename, not a logic change).
- **No in-browser YAML editing.** The review step shows YAML as read-only code blocks. Direct editing of game files is out of scope.
- **No streaming of LLM responses.** The creator calls return complete responses (not streamed). Progress is shown at the call level ("Generating world...", "Generating character: Maya..."), not at the token level.
- **No brainstorm mode.** The terminal CLI has a brainstorm tool (`scripts/brainstorm.py`) for freeform ideation. Bringing this to the web is a future enhancement.
- **No settings editing.** If the creator model is misconfigured, the wizard tells the user to edit `.env`. In-UI settings editing is Step 05.
- **No auto-save of wizard state.** If the user navigates away mid-wizard, all progress is lost. Session persistence for the wizard is a Step 08 concern.
- **No changes to the terminal CLI.** `scripts/create_game.py` continues to work independently.

## 12. Verification

After implementation, confirm:

1. **Menu navigation** -- "Create Game" button is visible on the menu page at `/` and navigates to `/create`.
2. **Step indicator** -- The stepper component shows all four step labels: Concept, Proposal Review, Generation, Review & Finalize.
3. **Concept input** -- Textarea accepts text. Example chips populate the textarea when clicked. "Generate Proposal" button is clickable.
4. **Proposal generation** -- Clicking "Generate Proposal" shows progressive status messages ("Generating setting...", "Creating characters...", "Planning chapters..."). On completion, the wizard advances to Step 2.
5. **Proposal review** -- Setting, characters, and chapters display in structured cards with correct data. Feedback textarea and "Revise" button are present. Revisions update the displayed cards.
6. **Accept & Generate** -- Clicking "Accept & Generate" advances to Step 3 and triggers the generation pipeline.
7. **Generation progress** -- Per-file progress messages appear ("Generating world...", "Generating character: Maya...", etc.). Each message turns green on completion.
8. **Validation display** -- After generation, validation results appear. If errors exist, auto-fix is attempted and results are shown. Size warnings display in orange.
9. **File review** -- Step 4 shows all generated YAML files in collapsible, syntax-highlighted code blocks.
10. **Feedback loop** -- Entering feedback and clicking "Regenerate" revises the targeted files, re-validates, and updates the display.
11. **Create Game** -- Clicking "Create Game" writes files to `games/<id>/`. A success notification appears and the user is navigated back to the menu. The new game appears in the "New Game" dropdown.
12. **Overwrite dialog** -- If a game with the same ID exists, a confirmation dialog appears before overwriting.
13. **Error recovery** -- LLM API errors show an error message and a "Retry" button. Missing creator config shows a helpful message with setup instructions.
14. **Small model warning** -- If the creator resolves to the 7B gameplay model, a visible warning banner appears at the top of the wizard.
15. **No regressions** -- Existing web UI tests (`tests/web/test_menu.py`, `tests/web/test_gameplay.py`) continue to pass.

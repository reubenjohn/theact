# Step 06: Playtest Dashboard

> **Implementation note:** This step adds a dedicated `/playtest` page to the web UI for launching, monitoring, and reviewing automated playtests. It wraps the existing `PlaytestRunner` from `src/theact/playtest/runner.py` with no changes to playtest logic. The only engine-side addition is an optional `on_turn_complete` callback parameter on `PlaytestRunner.run()` to enable real-time progress updates. This step depends on Step 05 (Settings) for LLM configuration access.

## 1. Overview

The terminal has a playtest script (`scripts/playtest.py`) that runs autonomous N-turn playtests with quality scoring, and a playtest framework in `src/theact/playtest/` with `PlaytestConfig`, `PlaytestRunner`, and `PlaytestReport`. The web UI currently has no playtest capabilities at all -- users must drop to the terminal to run playtests.

This step adds a new page at `/playtest` that provides:

- **Configuration form** -- select a game, set turn count, edge case frequency, and other parameters
- **Live progress monitoring** -- watch the playtest execute in real-time with turn counter, quality scores, and running averages
- **Results display** -- view the completed report with summary stats, per-turn details, LLM call statistics, and quality score charts
- **Past reports browser** -- browse, load, and compare previous playtest reports from the `playtests/` directory

All playtest logic uses the existing `PlaytestRunner` -- no changes to scoring, logging, or report generation.

## 2. Page Route and Navigation

**Modified file:** `src/theact/web/app.py`

Register a new page route and add a navigation link from the main menu.

```python
from theact.web.playtest_dashboard import playtest_page

@ui.page("/playtest")
async def playtest():
    await playtest_page()
```

Add a "Playtest" button to the main menu, placed after the existing game management sections:

```python
# In _build_menu(), after the delete section:
ui.separator()
with ui.row().classes("w-full items-center gap-2"):
    ui.label("Tools").style(
        "font-size: 1.2em; font-weight: bold; color: #ccc; margin-top: 12px;"
    )
ui.button(
    "Playtest Dashboard",
    on_click=lambda: ui.navigate.to("/playtest"),
    icon="science",
).props("dense")
```

The playtest page should include a "Back to Menu" button that navigates to `/`.

## 3. Dashboard Layout

**New file:** `src/theact/web/playtest_dashboard.py`

The page uses a three-panel layout:

```python
async def playtest_page() -> None:
    """Build the playtest dashboard page."""
    with ui.column().classes("w-full items-center"):
        # Header with back button
        with ui.row().classes("w-full max-w-6xl items-center p-4"):
            ui.button(icon="arrow_back", on_click=lambda: ui.navigate.to("/")).props(
                "flat dense"
            )
            ui.label("Playtest Dashboard").style(
                "font-size: 1.4em; font-weight: bold; color: #ccc;"
            )

        # Three-panel layout
        with ui.row().classes("w-full max-w-6xl gap-4 p-4"):
            # Left: Configuration form
            with ui.column().classes("w-80 min-w-[320px]"):
                _build_config_panel()

            # Center: Live progress / results
            with ui.column().classes("flex-grow min-w-[400px]"):
                _build_progress_panel()

            # Right: Past reports browser
            with ui.column().classes("w-80 min-w-[320px]"):
                _build_reports_panel()
```

Each panel is built by a dedicated function, keeping the module well-organized.

## 4. Configuration Panel

The left panel contains a form for configuring playtest parameters.

```python
def _build_config_panel() -> None:
    """Build the playtest configuration form."""
    ui.label("Configuration").style("font-size: 1.1em; font-weight: bold; color: #ccc;")

    # Game selector -- populated from save_manager.list_games()
    games = list_games()
    game_options = {g.id: g.title for g in games}
    game_select = ui.select(
        options=game_options,
        label="Game",
        value=games[0].id if games else None,
    ).classes("w-full")

    # Max turns
    max_turns_input = ui.number(
        label="Max Turns",
        value=20,
        min=1,
        max=100,
        step=1,
    ).classes("w-full").props("outlined dense dark")

    # Player name
    player_name_input = ui.input(
        label="Player Name",
        value="Alex",
    ).classes("w-full").props("outlined dense dark")

    # Edge case frequency -- slider with label
    ui.label("Edge Case Frequency").classes("text-sm text-gray-400 mt-2")
    edge_case_slider = ui.slider(
        min=0.0, max=0.5, step=0.05, value=0.15,
    ).classes("w-full")
    ui.label().bind_text_from(edge_case_slider, "value", backward=lambda v: f"{v:.0%}")

    # Stop on error
    stop_on_error_check = ui.checkbox("Stop on error", value=False)

    # Start button
    ui.button(
        "Start Playtest",
        on_click=lambda: _start_playtest(
            game_id=game_select.value,
            max_turns=int(max_turns_input.value),
            player_name=player_name_input.value,
            edge_case_frequency=edge_case_slider.value,
            stop_on_error=stop_on_error_check.value,
        ),
        icon="play_arrow",
    ).props("dense").classes("mt-4")
```

Field defaults match `PlaytestConfig` defaults: `max_turns=20`, `player_name="Alex"`, `edge_case_frequency=0.15`, `stop_on_error=False`.

If no games are found in `games/`, show a message: "No games found. Create a game first."

## 5. Live Progress Panel

The center panel shows real-time progress during playtest execution and the final results once complete.

### Progress display during execution

```python
# Module-level state — see note below about per-page scoping
_progress_state = {
    "running": False,
    "current_turn": 0,
    "max_turns": 0,
    "turn_logs": [],       # list of TurnLog-like dicts for display
    "quality_scores": [],  # running list of composite scores
    "report": None,        # set when complete
}
```

> **Note:** `_progress_state` as a module-level dict is shared across all browser sessions/tabs. If two users open `/playtest` simultaneously, they see and mutate the same state. During implementation, use per-page closures (following `app.py`'s `page_state = {}` pattern) or `app.storage.tab` to scope state to each browser tab.

During execution, the panel shows:

- **Progress bar:** current turn / max turns, using `ui.linear_progress`
- **Turn counter label:** "Turn 7 / 20"
- **Current action:** the player input for the current turn
- **Running quality score:** average composite score so far
- **Running parse success rate:** percentage of turns without parse issues
- **Running character response rate:** percentage of turns with >= 1 character responding
- **Turn log feed:** scrolling list of completed turns with turn number, player input, and composite score

```python
@ui.refreshable
def _render_progress() -> None:
    if not _progress_state["running"] and _progress_state["report"] is None:
        ui.label("Configure and start a playtest to see results here.").classes(
            "text-gray-500 italic"
        )
        return

    if _progress_state["running"]:
        current = _progress_state["current_turn"]
        total = _progress_state["max_turns"]
        ui.label(f"Turn {current} / {total}").classes("font-bold text-lg")
        ui.linear_progress(
            value=current / total if total else 0, show_value=False
        ).classes("w-full")

        # Running averages
        scores = _progress_state["quality_scores"]
        if scores:
            avg = sum(scores) / len(scores)
            ui.label(f"Avg quality score: {avg:.2f}").classes("text-sm")

        # Turn log feed
        with ui.scroll_area().classes("w-full h-64 border border-gray-700 rounded mt-2"):
            for log in reversed(_progress_state["turn_logs"]):
                with ui.row().classes("w-full items-center gap-2 py-1 px-2"):
                    ui.label(f"T{log['turn']}").classes("text-xs text-gray-500 w-8")
                    ui.label(log["player_input"][:60]).classes("text-sm flex-grow")
                    score = log.get("composite", 0)
                    color = "text-green-400" if score >= 0.7 else "text-yellow-400" if score >= 0.4 else "text-red-400"
                    ui.label(f"{score:.2f}").classes(f"text-sm font-mono {color}")
```

### Update mechanism

Updates are pushed to the UI using NiceGUI's async model. Since `PlaytestRunner.run()` is async and runs in the same event loop as NiceGUI, progress updates can be pushed directly via a callback (see Section 6).

After each turn callback fires:
1. Update `_progress_state` with the new turn data
2. Call `_render_progress.refresh()` to re-render the panel

## 6. Playtest Execution Strategy

### The challenge

`PlaytestRunner.run()` is a long-running async coroutine that blocks the caller until all turns complete. Running it directly from a button click handler would freeze the UI.

### The solution

Run the playtest as a background task using `asyncio.create_task()`, and add an optional progress callback to `PlaytestRunner.run()`.

**Minimal engine change** in `src/theact/playtest/runner.py`:

Add an optional `on_turn_complete` callback parameter to `PlaytestRunner.run()`. This is a small, backward-compatible addition -- the callback defaults to `None` and existing callers are unaffected.

The callback receives three arguments: `(turn_number, turn_log, quality_score_dict)`. The third argument is the quality score dict for the turn (or `None` if scoring is unavailable), so the web UI does not need to access private attributes like `runner._quality_scores`.

```python
from typing import Callable

class PlaytestRunner:
    async def run(
        self,
        on_turn_complete: Callable[[int, TurnLog, dict | None], None] | None = None,
    ) -> PlaytestReport:
        """Execute a full playtest. Returns a PlaytestReport.

        Args:
            on_turn_complete: Optional callback invoked after each turn completes.
                Receives (turn_number, turn_log, quality_score_dict). The quality
                score dict contains at minimum a "composite" key, or is None if
                scoring is unavailable. Used by the web UI for progress updates.
        """
        # ... existing setup code ...

        for turn_num in range(1, self.config.max_turns + 1):
            # ... existing turn logic ...

            # After logging the turn result and computing quality score:
            if on_turn_complete is not None:
                turn_log = self.logger.turns[-1] if self.logger.turns else None
                quality_score = self._quality_scores[-1] if self._quality_scores else None
                if turn_log is not None:
                    on_turn_complete(turn_num, turn_log, quality_score)

            # ... rest of loop ...
```

**Web UI side** in `src/theact/web/playtest_dashboard.py`:

```python
async def _start_playtest(
    game_id: str,
    max_turns: int,
    player_name: str,
    edge_case_frequency: float,
    stop_on_error: bool,
) -> None:
    """Launch a playtest as a background task."""
    if _progress_state["running"]:
        ui.notify("A playtest is already running.", type="warning")
        return

    llm_config = load_llm_config()

    config = PlaytestConfig(
        game_id=game_id,
        max_turns=max_turns,
        player_name=player_name,
        edge_case_frequency=edge_case_frequency,
        stop_on_error=stop_on_error,
        llm_config=llm_config,
    )

    # Reset progress state
    _progress_state.update({
        "running": True,
        "current_turn": 0,
        "max_turns": max_turns,
        "turn_logs": [],
        "quality_scores": [],
        "report": None,
    })
    _render_progress.refresh()

    def on_turn_complete(turn_num: int, turn_log: TurnLog, quality_score: dict | None) -> None:
        """Callback invoked after each turn -- updates progress state."""
        _progress_state["current_turn"] = turn_num
        composite = quality_score.get("composite", 0.0) if quality_score else 0.0
        _progress_state["turn_logs"].append({
            "turn": turn_num,
            "player_input": turn_log.player_input,
            "composite": composite,
            "characters_responded": turn_log.characters_responded,
            "issues": turn_log.issues,
        })
        _progress_state["quality_scores"].append(composite)
        _render_progress.refresh()

    runner = PlaytestRunner(config)

    async def _run_task():
        try:
            report = await runner.run(on_turn_complete=on_turn_complete)
            _progress_state["running"] = False
            _progress_state["report"] = report
            _render_progress.refresh()
            _render_results.refresh()
            _refresh_past_reports.refresh()
            ui.notify("Playtest complete!", type="positive")
        except Exception as e:
            _progress_state["running"] = False
            _render_progress.refresh()
            ui.notify(f"Playtest failed: {e}", type="negative")

    asyncio.create_task(_run_task())
```

Key points:
- `asyncio.create_task()` lets the playtest run without blocking the UI event loop
- The `on_turn_complete` callback fires after each turn, updating the shared progress state
- `_render_progress.refresh()` triggers NiceGUI to re-render the progress panel
- The `_start_playtest` function checks `_progress_state["running"]` to prevent concurrent playtests

> **Note:** The `asyncio.create_task()` approach runs the task detached from the NiceGUI page handler's client context. Calls to `_render_progress.refresh()` and `ui.notify()` from the background task may silently fail because there is no active client. During implementation, either (a) capture the client context before creating the task and restore it inside the task using `with client`, or (b) use a `ui.timer` that polls `_progress_state` at a short interval (e.g., 0.5s) instead of pushing refreshes from the background task.

## 7. Results Display

After the playtest completes, the center panel switches from the progress view to a full results view.

```python
@ui.refreshable
def _render_results() -> None:
    """Render the completed playtest report."""
    report = _progress_state.get("report")
    if report is None:
        return

    ui.label("Playtest Results").style("font-size: 1.2em; font-weight: bold; color: #ccc;")

    # Summary card
    with ui.card().classes("w-full"):
        with ui.row().classes("gap-4 flex-wrap"):
            _stat_chip("Turns", f"{report.turns_played} / {report.max_turns}")
            _stat_chip("Duration", f"{int(report.total_duration_seconds)}s")
            _stat_chip("Issues", str(report.issue_count))
            _stat_chip("Errors", str(report.error_count))

        # Quality averages
        if report.quality_scores:
            composites = [qs.get("composite", 0) for qs in report.quality_scores]
            avg_composite = sum(composites) / len(composites) if composites else 0
            with ui.row().classes("gap-4 flex-wrap mt-2"):
                _stat_chip("Avg Quality", f"{avg_composite:.2f}")
                _stat_chip("Parse Success", f"{report.yaml_parse_success_rate:.0%}")
                _stat_chip("Char Response", f"{report.character_response_rate:.0%}")

    # Quality score distribution chart (Apache ECharts via NiceGUI)
    if report.quality_scores:
        composites = [qs.get("composite", 0) for qs in report.quality_scores]
        turns = [qs.get("turn", i + 1) for i, qs in enumerate(report.quality_scores)]
        ui.echart({
            "title": {"text": "Quality Score by Turn"},
            "xAxis": {"type": "category", "data": turns, "name": "Turn"},
            "yAxis": {"type": "value", "min": 0, "max": 1, "name": "Score"},
            "series": [{
                "data": composites,
                "type": "line",
                "smooth": True,
                "areaStyle": {},
            }],
        }).classes("w-full h-64")

    # Per-turn table (expandable rows)
    ui.label("Per-Turn Detail").classes("font-bold mt-4")
    columns = [
        {"name": "turn", "label": "Turn", "field": "turn", "align": "left"},
        {"name": "elapsed", "label": "Time (s)", "field": "elapsed", "align": "right"},
        {"name": "chars", "label": "Characters", "field": "chars", "align": "left"},
        {"name": "issues", "label": "Issues", "field": "issues", "align": "left"},
    ]
    rows = []
    for pt in report.per_turn:
        rows.append({
            "turn": pt["turn"],
            "elapsed": pt["elapsed"],
            "chars": ", ".join(pt["characters_responded"]) if pt["characters_responded"] else "(none)",
            "issues": ", ".join(pt["issues"]) if pt["issues"] else "",
        })
    ui.table(columns=columns, rows=rows, row_key="turn").classes("w-full")

    # LLM call statistics
    if report.call_log_totals:
        ui.label("LLM Call Statistics").classes("font-bold mt-4")
        totals = report.call_log_totals
        with ui.card().classes("w-full"):
            with ui.row().classes("gap-4 flex-wrap"):
                _stat_chip("Total Calls", str(totals.get("total_calls", 0)))
                _stat_chip("Mean Latency", f"{totals.get('mean_latency_ms', 0)}ms")
                _stat_chip("Parse Rate", f"{totals.get('parse_success_rate', 0):.0%}")
                _stat_chip("Prompt Tokens", str(totals.get("total_prompt_tokens", 0)))
                _stat_chip("Retries", str(totals.get("total_retries", 0)))

        # Per-agent breakdown
        if report.call_log_summary:
            agent_columns = [
                {"name": "agent", "label": "Agent", "field": "agent", "align": "left"},
                {"name": "calls", "label": "Calls", "field": "calls", "align": "right"},
                {"name": "latency", "label": "Mean Latency", "field": "latency", "align": "right"},
                {"name": "parse_rate", "label": "Parse Rate", "field": "parse_rate", "align": "right"},
                {"name": "retries", "label": "Retries", "field": "retries", "align": "right"},
            ]
            agent_rows = []
            for agent, stats in report.call_log_summary.items():
                agent_rows.append({
                    "agent": agent,
                    "calls": stats["total_calls"],
                    "latency": f"{stats['mean_latency_ms']}ms",
                    "parse_rate": f"{stats['parse_success_rate']:.0%}",
                    "retries": stats["total_retries"],
                })
            ui.table(columns=agent_columns, rows=agent_rows, row_key="agent").classes("w-full mt-2")


def _stat_chip(label: str, value: str) -> None:
    """Render a small label+value stat display."""
    with ui.column().classes("items-center"):
        ui.label(value).classes("font-bold text-lg")
        ui.label(label).classes("text-xs text-gray-500")
```

The results display includes:

1. **Summary card** -- turns completed, duration, issues, errors, average quality, parse success rate, character response rate
2. **Quality score chart** -- line chart of composite scores per turn using NiceGUI's `ui.echart` (Apache ECharts)
3. **Per-turn table** -- turn number, elapsed time, characters responded, issues (uses `ui.table`)
4. **LLM call statistics** -- total calls, mean latency, parse success rate, prompt tokens, retries
5. **Per-agent breakdown table** -- agent name, calls, mean latency, parse rate, retries

## 8. Past Reports Browser

The right panel lists previous playtest reports from the `playtests/` directory.

### Report discovery

Each playtest writes its report to `playtests/<timestamp>/`. The directory contains `report.md`, `config.yaml`, `conversation.yaml`, and optionally `memory_final.yaml` and `llm_calls.yaml`.

```python
def _discover_past_reports() -> list[dict]:
    """Scan playtests/ directory for past reports. Returns metadata dicts."""
    playtests_dir = Path("playtests")
    if not playtests_dir.exists():
        return []

    reports = []
    for report_dir in sorted(playtests_dir.iterdir(), reverse=True):
        if not report_dir.is_dir():
            continue

        config_path = report_dir / "config.yaml"
        if not config_path.exists():
            continue

        with open(config_path) as f:
            config_data = yaml.safe_load(f) or {}

        reports.append({
            "timestamp": config_data.get("timestamp", report_dir.name),
            "game_id": config_data.get("game_id", "unknown"),
            "max_turns": config_data.get("max_turns", 0),
            "model": config_data.get("model", "unknown"),
            "path": str(report_dir),
        })

    return reports
```

### Report list UI

```python
@ui.refreshable
def _refresh_past_reports() -> None:
    """Render the past reports list."""
    ui.label("Past Reports").style("font-size: 1.1em; font-weight: bold; color: #ccc;")

    reports = _discover_past_reports()
    if not reports:
        ui.label("No past reports found.").classes("text-gray-500 italic")
        return

    for rpt in reports:
        with ui.card().classes("w-full cursor-pointer").on(
            "click", lambda r=rpt: _load_past_report(r)
        ):
            ui.label(rpt["game_id"]).classes("font-bold")
            ui.label(rpt["timestamp"]).classes("text-xs text-gray-500")
            ui.label(f"{rpt['max_turns']} turns - {rpt['model']}").classes("text-xs text-gray-400")
```

### Loading a past report

Clicking a report card loads the `report.md` content and attempts to reconstruct a `PlaytestReport` from the YAML files for display in the center panel:

```python
def _load_past_report(report_meta: dict) -> None:
    """Load a past report and display it in the results panel."""
    report_dir = Path(report_meta["path"])

    # Try to load the markdown report for raw display
    report_md_path = report_dir / "report.md"
    if report_md_path.exists():
        md_content = report_md_path.read_text()
        _progress_state["report_markdown"] = md_content

    # Try to load config.yaml for structured data
    config_path = report_dir / "config.yaml"
    if config_path.exists():
        with open(config_path) as f:
            config_data = yaml.safe_load(f)
        _progress_state["loaded_config"] = config_data

    _render_results.refresh()
```

For past reports where we only have the markdown file (not a live `PlaytestReport` object), the results panel falls back to rendering the markdown content using `ui.markdown()`.

### Compare mode

Select two reports from the past reports list to see a side-by-side comparison. This is implemented with checkboxes next to each report card:

```python
_compare_selection: list[dict] = []  # max 2

def _toggle_compare(report_meta: dict) -> None:
    if report_meta in _compare_selection:
        _compare_selection.remove(report_meta)
    elif len(_compare_selection) < 2:
        _compare_selection.append(report_meta)
    else:
        ui.notify("Select at most 2 reports to compare.", type="warning")
    _refresh_past_reports.refresh()
```

When two reports are selected, a "Compare" button appears. Clicking it shows a side-by-side view in the center panel with:
- Game ID, timestamp, model for each report
- Turn count, duration, issue count for each
- If both have `config.yaml` data, show a diff table of configuration differences

## 9. Tests

**New file:** `tests/web/test_playtest_dashboard.py`

All tests use the Playwright-based browser testing pattern from the existing `tests/web/conftest.py` -- synchronous Playwright with the `page` and `web_server` session fixtures.

```python
"""Browser integration tests for the playtest dashboard.

Run with:  uv run pytest tests/web/test_playtest_dashboard.py -v
"""

from playwright.sync_api import expect


class TestPlaytestPageAccess:
    """Tests that the playtest page is accessible."""

    def test_playtest_page_loads(self, page, web_server):
        """Playtest page is accessible at /playtest."""
        page.goto(f"{web_server}/playtest")
        expect(page.get_by_text("Playtest Dashboard")).to_be_visible()

    def test_back_button_present(self, page, web_server):
        """Back button navigates to main menu."""
        page.goto(f"{web_server}/playtest")
        back_btn = page.locator("button:has(i:text('arrow_back'))")
        expect(back_btn).to_be_visible()


class TestPlaytestConfigForm:
    """Tests for the configuration panel."""

    def test_game_selector_present(self, page, web_server):
        """Game selector dropdown is present."""
        page.goto(f"{web_server}/playtest")
        expect(page.get_by_label("Game")).to_be_visible()

    def test_max_turns_input_present(self, page, web_server):
        """Max turns number input is present with default value."""
        page.goto(f"{web_server}/playtest")
        expect(page.get_by_label("Max Turns")).to_be_visible()

    def test_player_name_input_present(self, page, web_server):
        """Player name text input is present."""
        page.goto(f"{web_server}/playtest")
        expect(page.get_by_label("Player Name")).to_be_visible()

    def test_edge_case_slider_present(self, page, web_server):
        """Edge case frequency slider is present."""
        page.goto(f"{web_server}/playtest")
        expect(page.get_by_text("Edge Case Frequency")).to_be_visible()

    def test_stop_on_error_checkbox_present(self, page, web_server):
        """Stop on error checkbox is present."""
        page.goto(f"{web_server}/playtest")
        expect(page.get_by_text("Stop on error")).to_be_visible()

    def test_start_button_present(self, page, web_server):
        """Start Playtest button is present."""
        page.goto(f"{web_server}/playtest")
        expect(page.get_by_role("button", name="Start Playtest")).to_be_visible()

    def test_game_selector_populated(self, page, web_server):
        """Game selector has at least one option (requires games/ to have a game)."""
        page.goto(f"{web_server}/playtest")
        game_select = page.get_by_label("Game")
        # Click to open dropdown; if games exist, options will appear
        game_select.click()
        # At minimum, the select should be interactable
        expect(game_select).to_be_enabled()


class TestPlaytestPastReports:
    """Tests for the past reports browser section."""

    def test_past_reports_section_exists(self, page, web_server):
        """Past Reports section header is visible."""
        page.goto(f"{web_server}/playtest")
        expect(page.get_by_text("Past Reports")).to_be_visible()
```

## 10. What This Step Does NOT Do

- **No changes to playtest scoring or report generation.** All scoring logic remains in `src/theact/playtest/scoring.py` and report generation in `src/theact/playtest/report.py`.
- **No golden scenario or A/B test UI.** This step only covers playtests via `PlaytestRunner`. Golden scenarios (`scripts/run_golden.py`) and A/B tests (`scripts/ab_test.py`) remain terminal-only.
- **No concurrent playtest execution.** Only one playtest can run at a time. The start button is disabled while a playtest is in progress.
- **No playtest cancellation.** Once started, a playtest runs to completion (or until `stop_on_error` triggers). Adding a cancel button (which would require cooperative cancellation in `PlaytestRunner`) is a future refinement.
- **No report deletion.** Past reports can be viewed but not deleted from the UI. Users can delete report directories manually.
- **No custom opening action.** The `opening_action` field from `PlaytestConfig` uses the default value. Exposing it in the form is a minor future addition.
- **No advanced frequency tuning.** Only `edge_case_frequency` is exposed. The `direct_edge_case_frequency`, `nonsense_frequency`, and `repeat_frequency` fields use defaults.
- **No playtest report export.** Reports are already written to `playtests/` on disk. There is no additional download/export button.

## 11. Verification

After implementation, confirm:

1. **Page accessible** -- Navigating to `/playtest` shows the dashboard with three panels. A "Playtest" link or button on the main menu page navigates to `/playtest`.
2. **Configuration form** -- Game selector is populated with available games from `games/`. Max turns, player name, edge case frequency slider, and stop-on-error checkbox are all present and interactive. Defaults match `PlaytestConfig` defaults.
3. **Start playtest** -- Clicking "Start Playtest" with valid configuration launches a playtest. The button is disabled (or shows a warning) if a playtest is already running.
4. **Live progress** -- During execution, the progress bar advances after each turn. The turn counter updates. Turn logs appear in the scrolling feed with player input and quality score. Running averages (quality, parse success) update incrementally.
5. **Results display** -- After completion, the center panel shows the full report: summary card with key metrics, quality score chart, per-turn detail table, and LLM call statistics with per-agent breakdown.
6. **Past reports** -- The right panel lists previous playtest reports from `playtests/` directory, sorted newest first. Each card shows game ID, timestamp, turn count, and model.
7. **Load past report** -- Clicking a past report card loads it into the center panel for viewing.
8. **Compare mode** -- Selecting two past reports and clicking "Compare" shows a side-by-side comparison of key metrics.
9. **No regressions** -- Existing web UI tests (`tests/web/test_menu.py`, `tests/web/test_gameplay.py`) continue to pass. The playtest framework's own tests are unaffected.
10. **Back navigation** -- The back button on the playtest page returns to the main menu.

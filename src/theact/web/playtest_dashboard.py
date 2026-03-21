"""Playtest dashboard page: configure, launch, monitor, and review playtests."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import yaml
from nicegui import ui

from theact.io.save_manager import list_games
from theact.llm.config import load_llm_config
from theact.playtest.config import PlaytestConfig
from theact.playtest.logger import TurnLog

logger = logging.getLogger(__name__)


async def playtest_page() -> None:
    """Build the playtest dashboard page.

    All mutable state is scoped to this function via closures so that
    each browser tab gets its own independent state.
    """
    # --- Per-page state (closure-scoped, not module-level) ---
    state = {
        "running": False,
        "current_turn": 0,
        "max_turns": 0,
        "turn_logs": [],  # list of dicts for display
        "quality_scores": [],  # running list of composite scores
        "report": None,  # PlaytestReport when complete
        "report_markdown": None,  # markdown from a loaded past report
        "loaded_config": None,  # config dict from a loaded past report
        "error_message": None,  # error message if playtest failed
        "start_btn": None,  # reference to start button for enable/disable
    }

    # --- Header ---
    with ui.column().classes("w-full items-center"):
        with ui.row().classes("w-full max-w-6xl items-center p-4"):
            ui.button(icon="arrow_back", on_click=lambda: ui.navigate.to("/")).props(
                "flat dense"
            )
            ui.label("Playtest Dashboard").style(
                "font-size: 1.4em; font-weight: bold; color: #ccc;"
            )

        # --- Three-panel layout ---
        with ui.row().classes("w-full max-w-6xl gap-4 p-4 items-start"):
            # Left: Configuration form
            with ui.column().classes("w-80 min-w-[320px]"):
                _build_config_panel(
                    state, _render_progress, _render_results, _refresh_past_reports
                )

            # Center: Live progress / results
            with ui.column().classes("flex-grow min-w-[400px]"):
                _render_progress(state)
                _render_results(state)

            # Right: Past reports browser
            with ui.column().classes("w-80 min-w-[320px]"):
                _refresh_past_reports(state, _render_results)

    # Set up a timer to poll state and refresh UI during playtest execution.
    # asyncio.create_task() detaches from the NiceGUI client context, so
    # refreshable calls from the background task would silently fail.
    # Instead, the background task only mutates `state` and this timer
    # drives UI updates.
    poll_state = {"was_running": False}

    def _poll_progress():
        if state["running"]:
            poll_state["was_running"] = True
            _render_progress.refresh(state)
        elif poll_state["was_running"]:
            # Playtest just finished -- do final refresh
            poll_state["was_running"] = False
            _render_progress.refresh(state)
            _render_results.refresh(state)
            _refresh_past_reports.refresh(state, _render_results)
            if state.get("start_btn"):
                state["start_btn"].enable()
            if state.get("error_message"):
                ui.notify(f"Playtest failed: {state['error_message']}", type="negative")
            elif state.get("report"):
                ui.notify("Playtest complete!", type="positive")

    ui.timer(0.5, _poll_progress)


def _build_config_panel(
    state: dict,
    render_progress_fn,
    render_results_fn,
    refresh_reports_fn,
) -> None:
    """Build the playtest configuration form."""
    ui.label("Configuration").style("font-size: 1.1em; font-weight: bold; color: #ccc;")

    games = list_games()

    if not games:
        ui.label("No games found. Create a game first.").classes("text-gray-500 italic")
        return

    game_options = {g.id: g.title for g in games}
    game_select = ui.select(
        options=game_options,
        label="Game",
        value=games[0].id if games else None,
    ).classes("w-full")

    max_turns_input = (
        ui.number(
            label="Max Turns",
            value=20,
            min=1,
            max=100,
            step=1,
        )
        .classes("w-full")
        .props("outlined dense dark")
    )

    player_name_input = (
        ui.input(
            label="Player Name",
            value="Alex",
        )
        .classes("w-full")
        .props("outlined dense dark")
    )

    ui.label("Edge Case Frequency").classes("text-sm text-gray-400 mt-2")
    edge_case_slider = ui.slider(
        min=0.0,
        max=0.5,
        step=0.05,
        value=0.15,
    ).classes("w-full")
    ui.label().bind_text_from(edge_case_slider, "value", backward=lambda v: f"{v:.0%}")

    stop_on_error_check = ui.checkbox("Stop on error", value=False)

    start_btn = (
        ui.button(
            "Start Playtest",
            on_click=lambda: _start_playtest(
                state=state,
                game_id=game_select.value,
                max_turns=int(max_turns_input.value or 20),
                player_name=player_name_input.value or "Alex",
                edge_case_frequency=edge_case_slider.value,
                stop_on_error=stop_on_error_check.value,
                render_progress_fn=render_progress_fn,
                render_results_fn=render_results_fn,
                refresh_reports_fn=refresh_reports_fn,
            ),
            icon="play_arrow",
        )
        .props("dense")
        .classes("mt-4")
    )
    state["start_btn"] = start_btn


async def _start_playtest(
    *,
    state: dict,
    game_id: str,
    max_turns: int,
    player_name: str,
    edge_case_frequency: float,
    stop_on_error: bool,
    render_progress_fn,
    render_results_fn,
    refresh_reports_fn,
) -> None:
    """Launch a playtest as a background task."""
    if state["running"]:
        ui.notify("A playtest is already running.", type="warning")
        return

    if not game_id:
        ui.notify("Please select a game.", type="warning")
        return

    try:
        llm_config = load_llm_config()
    except ValueError as e:
        ui.notify(f"LLM not configured: {e}", type="negative")
        return

    config = PlaytestConfig(
        game_id=game_id,
        max_turns=max_turns,
        player_name=player_name,
        edge_case_frequency=edge_case_frequency,
        stop_on_error=stop_on_error,
        llm_config=llm_config,
    )

    # Reset state
    state.update(
        {
            "running": True,
            "current_turn": 0,
            "max_turns": max_turns,
            "turn_logs": [],
            "quality_scores": [],
            "report": None,
            "report_markdown": None,
            "loaded_config": None,
            "error_message": None,
        }
    )

    if state.get("start_btn"):
        state["start_btn"].disable()
    render_progress_fn.refresh(state)
    render_results_fn.refresh(state)

    def on_turn_complete(
        turn_num: int, turn_log: TurnLog, quality_score: dict | None
    ) -> None:
        """Callback invoked after each turn -- updates state dict only."""
        composite = quality_score.get("composite", 0.0) if quality_score else 0.0
        state["current_turn"] = turn_num
        state["turn_logs"].append(
            {
                "turn": turn_num,
                "player_input": turn_log.player_input,
                "composite": composite,
                "characters_responded": turn_log.characters_responded,
                "issues": turn_log.issues,
            }
        )
        state["quality_scores"].append(composite)

    from theact.playtest.runner import PlaytestRunner

    runner = PlaytestRunner(config)

    async def _run_task():
        try:
            report = await runner.run(on_turn_complete=on_turn_complete)
            state["running"] = False
            state["report"] = report
        except Exception as e:
            logger.exception("Playtest failed")
            state["running"] = False
            state["error_message"] = str(e)

    asyncio.create_task(_run_task())


@ui.refreshable
def _render_progress(state: dict) -> None:
    """Render the live progress panel."""
    if (
        not state["running"]
        and state["report"] is None
        and state.get("report_markdown") is None
    ):
        if state.get("error_message"):
            ui.label(f"Playtest failed: {state['error_message']}").classes(
                "text-red-400"
            )
            return
        ui.label("Configure and start a playtest to see results here.").classes(
            "text-gray-500 italic"
        )
        return

    if state["running"]:
        current = state["current_turn"]
        total = state["max_turns"]
        ui.label(f"Turn {current} / {total}").classes("font-bold text-lg")
        ui.linear_progress(
            value=current / total if total else 0, show_value=False
        ).classes("w-full")

        # Running averages
        scores = state["quality_scores"]
        if scores:
            avg = sum(scores) / len(scores)
            ui.label(f"Avg quality score: {avg:.2f}").classes("text-sm")

            # Parse success rate (turns without parse-related issues)
            turns_with_parse = sum(
                1
                for tl in state["turn_logs"]
                if any(
                    "yaml" in i.lower() or "parse" in i.lower()
                    for i in tl.get("issues", [])
                )
            )
            total_logged = len(state["turn_logs"])
            if total_logged:
                parse_rate = (total_logged - turns_with_parse) / total_logged
                ui.label(f"Parse success: {parse_rate:.0%}").classes("text-sm")

            # Character response rate
            turns_with_chars = sum(
                1 for tl in state["turn_logs"] if tl.get("characters_responded")
            )
            if total_logged:
                char_rate = turns_with_chars / total_logged
                ui.label(f"Char response: {char_rate:.0%}").classes("text-sm")

        # Turn log feed
        with ui.scroll_area().classes(
            "w-full h-64 border border-gray-700 rounded mt-2"
        ):
            for log in reversed(state["turn_logs"]):
                with ui.row().classes("w-full items-center gap-2 py-1 px-2"):
                    ui.label(f"T{log['turn']}").classes("text-xs text-gray-500 w-8")
                    ui.label(log["player_input"][:60]).classes("text-sm flex-grow")
                    score = log.get("composite", 0)
                    color = (
                        "text-green-400"
                        if score >= 0.7
                        else "text-yellow-400"
                        if score >= 0.4
                        else "text-red-400"
                    )
                    ui.label(f"{score:.2f}").classes(f"text-sm font-mono {color}")


@ui.refreshable
def _render_results(state: dict) -> None:
    """Render the completed playtest report or a loaded past report."""
    report = state.get("report")

    # If we have a loaded markdown from a past report but no live report
    if report is None and state.get("report_markdown"):
        ui.label("Past Report").style(
            "font-size: 1.2em; font-weight: bold; color: #ccc;"
        )
        ui.markdown(state["report_markdown"]).classes("w-full")
        return

    if report is None:
        return

    ui.label("Playtest Results").style(
        "font-size: 1.2em; font-weight: bold; color: #ccc;"
    )

    # Summary card
    with ui.card().classes("w-full"):
        with ui.row().classes("gap-4 flex-wrap"):
            _stat_chip("Turns", f"{report.turns_played} / {report.max_turns}")
            _stat_chip("Duration", f"{int(report.total_duration_seconds)}s")
            _stat_chip("Issues", str(report.issue_count))
            _stat_chip("Errors", str(report.error_count))

        if report.quality_scores:
            composites = [qs.get("composite", 0) for qs in report.quality_scores]
            avg_composite = sum(composites) / len(composites) if composites else 0
            with ui.row().classes("gap-4 flex-wrap mt-2"):
                _stat_chip("Avg Quality", f"{avg_composite:.2f}")
                _stat_chip("Parse Success", f"{report.yaml_parse_success_rate:.0%}")
                _stat_chip("Char Response", f"{report.character_response_rate:.0%}")

    # Quality score chart
    if report.quality_scores:
        composites = [qs.get("composite", 0) for qs in report.quality_scores]
        turns = [qs.get("turn", i + 1) for i, qs in enumerate(report.quality_scores)]
        ui.echart(
            {
                "title": {
                    "text": "Quality Score by Turn",
                    "textStyle": {"color": "#ccc"},
                },
                "xAxis": {
                    "type": "category",
                    "data": turns,
                    "name": "Turn",
                    "nameTextStyle": {"color": "#999"},
                    "axisLabel": {"color": "#999"},
                },
                "yAxis": {
                    "type": "value",
                    "min": 0,
                    "max": 1,
                    "name": "Score",
                    "nameTextStyle": {"color": "#999"},
                    "axisLabel": {"color": "#999"},
                },
                "series": [
                    {
                        "data": composites,
                        "type": "line",
                        "smooth": True,
                        "areaStyle": {},
                    }
                ],
                "backgroundColor": "transparent",
            }
        ).classes("w-full h-64")

    # Per-turn table
    ui.label("Per-Turn Detail").classes("font-bold mt-4")
    columns = [
        {"name": "turn", "label": "Turn", "field": "turn", "align": "left"},
        {
            "name": "elapsed",
            "label": "Time (s)",
            "field": "elapsed",
            "align": "right",
        },
        {"name": "chars", "label": "Characters", "field": "chars", "align": "left"},
        {
            "name": "issues",
            "label": "Issues",
            "field": "issues",
            "align": "left",
        },
    ]
    rows = []
    for pt in report.per_turn:
        rows.append(
            {
                "turn": pt["turn"],
                "elapsed": pt["elapsed"],
                "chars": (
                    ", ".join(pt["characters_responded"])
                    if pt["characters_responded"]
                    else "(none)"
                ),
                "issues": ", ".join(pt["issues"]) if pt["issues"] else "",
            }
        )
    ui.table(columns=columns, rows=rows, row_key="turn").classes("w-full")

    # LLM call statistics
    if report.call_log_totals:
        ui.label("LLM Call Statistics").classes("font-bold mt-4")
        totals = report.call_log_totals
        with ui.card().classes("w-full"):
            with ui.row().classes("gap-4 flex-wrap"):
                _stat_chip("Total Calls", str(totals.get("total_calls", 0)))
                _stat_chip(
                    "Mean Latency",
                    f"{totals.get('mean_latency_ms', 0)}ms",
                )
                _stat_chip(
                    "Parse Rate",
                    f"{totals.get('parse_success_rate', 0):.0%}",
                )
                _stat_chip(
                    "Prompt Tokens",
                    str(totals.get("total_prompt_tokens", 0)),
                )
                _stat_chip("Retries", str(totals.get("total_retries", 0)))

        # Per-agent breakdown
        if report.call_log_summary:
            agent_columns = [
                {
                    "name": "agent",
                    "label": "Agent",
                    "field": "agent",
                    "align": "left",
                },
                {
                    "name": "calls",
                    "label": "Calls",
                    "field": "calls",
                    "align": "right",
                },
                {
                    "name": "latency",
                    "label": "Mean Latency",
                    "field": "latency",
                    "align": "right",
                },
                {
                    "name": "parse_rate",
                    "label": "Parse Rate",
                    "field": "parse_rate",
                    "align": "right",
                },
                {
                    "name": "retries",
                    "label": "Retries",
                    "field": "retries",
                    "align": "right",
                },
            ]
            agent_rows = []
            for agent, stats in report.call_log_summary.items():
                agent_rows.append(
                    {
                        "agent": agent,
                        "calls": stats["total_calls"],
                        "latency": f"{stats['mean_latency_ms']}ms",
                        "parse_rate": f"{stats['parse_success_rate']:.0%}",
                        "retries": stats["total_retries"],
                    }
                )
            ui.table(columns=agent_columns, rows=agent_rows, row_key="agent").classes(
                "w-full mt-2"
            )


def _stat_chip(label: str, value: str) -> None:
    """Render a small label+value stat display."""
    with ui.column().classes("items-center"):
        ui.label(value).classes("font-bold text-lg")
        ui.label(label).classes("text-xs text-gray-500")


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

        try:
            with open(config_path) as f:
                config_data = yaml.safe_load(f) or {}
        except Exception:
            continue

        reports.append(
            {
                "timestamp": config_data.get("timestamp", report_dir.name),
                "game_id": config_data.get("game_id", "unknown"),
                "max_turns": config_data.get("max_turns", 0),
                "model": config_data.get("model", "unknown"),
                "path": str(report_dir),
            }
        )

    return reports


@ui.refreshable
def _refresh_past_reports(state: dict, render_results_fn) -> None:
    """Render the past reports list."""
    ui.label("Past Reports").style("font-size: 1.1em; font-weight: bold; color: #ccc;")

    reports = _discover_past_reports()
    if not reports:
        ui.label("No past reports found.").classes("text-gray-500 italic")
        return

    for rpt in reports:

        def make_click_handler(report_meta):
            def handler():
                _load_past_report(state, report_meta, render_results_fn)

            return handler

        with (
            ui.card()
            .classes("w-full cursor-pointer")
            .on("click", make_click_handler(rpt))
        ):
            ui.label(rpt["game_id"]).classes("font-bold")
            ui.label(rpt["timestamp"]).classes("text-xs text-gray-500")
            ui.label(f"{rpt['max_turns']} turns - {rpt['model']}").classes(
                "text-xs text-gray-400"
            )


def _load_past_report(state: dict, report_meta: dict, render_results_fn) -> None:
    """Load a past report and display it in the results panel."""
    report_dir = Path(report_meta["path"])

    # Reset live report so the markdown view takes over
    state["report"] = None

    # Try to load the markdown report for raw display
    report_md_path = report_dir / "report.md"
    if report_md_path.exists():
        state["report_markdown"] = report_md_path.read_text()
    else:
        state["report_markdown"] = f"*No report.md found in {report_dir}.*"

    # Try to load config.yaml for structured data
    config_path = report_dir / "config.yaml"
    if config_path.exists():
        try:
            with open(config_path) as f:
                state["loaded_config"] = yaml.safe_load(f)
        except Exception:
            state["loaded_config"] = None

    render_results_fn.refresh(state)

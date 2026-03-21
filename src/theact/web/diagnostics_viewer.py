"""Diagnostics & Observability viewer page.

Read-only viewer for LLM call logs, token usage charts, parse error
browsing, and per-turn diagnostic file artifacts. Data comes from
LLMCallLog (loaded from disk) and DiagnosticsWriter output files.
"""

from __future__ import annotations

import logging
from pathlib import Path

import yaml
from nicegui import ui

from theact.io.save_manager import SAVES_DIR
from theact.llm.call_log import LLMCallLog, LLMCallRecord

logger = logging.getLogger(__name__)


def build_diagnostics_page(save_id: str = "") -> None:
    """Build the diagnostics page with tabbed interface.

    Args:
        save_id: The save directory name. Used to load call_log.yaml
                 from disk and to locate diagnostics artifacts.
    """
    # Load call log from disk if a save_id is provided
    call_log = None
    save_path = None
    if save_id:
        save_path = SAVES_DIR / save_id
        log_path = save_path / "call_log.yaml"
        if log_path.exists():
            call_log = _load_call_log_from_disk(log_path)

    with ui.column().classes("w-full max-w-6xl mx-auto p-4"):
        # Header
        with ui.row().classes("w-full items-center"):
            ui.button(icon="arrow_back", on_click=lambda: ui.navigate.to("/")).props(
                "flat dense"
            )
            ui.label("Diagnostics & Observability").style(
                "font-size: 1.4em; font-weight: bold; color: #ccc;"
            )

        # Save selector when no save_id provided
        if not save_id:
            _build_save_selector()

        if call_log is None or not call_log.records:
            ui.label("No LLM call data available. Play some turns first.").style(
                "color: #888; margin-top: 20px;"
            )
            return

        # Tabbed interface
        with ui.tabs().classes("w-full") as tabs:
            tab_calls = ui.tab("Call Log", icon="list")
            tab_tokens = ui.tab("Token Usage", icon="bar_chart")
            tab_errors = ui.tab("Error Browser", icon="error_outline")
            tab_files = ui.tab("Diagnostics Files", icon="folder_open")

        with ui.tab_panels(tabs, value=tab_calls).classes("w-full"):
            with ui.tab_panel(tab_calls):
                _build_call_log_tab(call_log)
            with ui.tab_panel(tab_tokens):
                _build_token_usage_tab(call_log)
            with ui.tab_panel(tab_errors):
                _build_error_browser_tab(call_log)
            with ui.tab_panel(tab_files):
                _build_diagnostics_files_tab(save_path)


# ---------------------------------------------------------------------------
# Save selector
# ---------------------------------------------------------------------------


def _build_save_selector() -> None:
    """Show a dropdown to select a save and navigate to its diagnostics."""
    from theact.io.save_manager import list_saves

    saves = list_saves()
    if not saves:
        ui.label("No saves found.").style("color: #888; margin-top: 12px;")
        return

    save_options = {s["id"]: f"{s['id']} (Turn {s['turn']})" for s in saves}

    with ui.row().classes("items-center gap-4 mt-4"):
        ui.label("Select a save to view diagnostics:").style("color: #aaa;")
        save_select = ui.select(
            options=save_options,
            label="Save",
            value=None,
        ).classes("w-64")

        def on_go():
            if save_select.value:
                ui.navigate.to(f"/diagnostics?save={save_select.value}")

        ui.button("View", on_click=on_go, icon="visibility").props("dense")


# ---------------------------------------------------------------------------
# Tab 1: Call Log
# ---------------------------------------------------------------------------


def _build_call_log_tab(call_log: LLMCallLog) -> None:
    """Build the call log table with filters and summary."""
    agents = sorted(set(r.agent for r in call_log.records))
    turns = sorted(set(r.turn for r in call_log.records))

    # Filters
    with ui.row().classes("w-full items-center gap-4 mb-4"):
        agent_filter = ui.select(
            options=["All"] + agents, value="All", label="Agent"
        ).classes("w-48")
        turn_min = ui.number(
            label="From turn", value=min(turns) if turns else 0
        ).classes("w-24")
        turn_max = ui.number(label="To turn", value=max(turns) if turns else 0).classes(
            "w-24"
        )
        result_filter = ui.select(
            options=["All", "success", "failure"],
            value="All",
            label="Parse Result",
        ).classes("w-32")

    # Table columns
    columns = [
        {"name": "turn", "label": "Turn", "field": "turn", "sortable": True},
        {"name": "agent", "label": "Agent", "field": "agent", "sortable": True},
        {
            "name": "prompt_tokens",
            "label": "Prompt Tok",
            "field": "prompt_tokens",
            "sortable": True,
        },
        {
            "name": "thinking_tokens",
            "label": "Think Tok",
            "field": "thinking_tokens",
            "sortable": True,
        },
        {
            "name": "content_tokens",
            "label": "Content Tok",
            "field": "content_tokens",
            "sortable": True,
        },
        {
            "name": "latency_ms",
            "label": "Latency (ms)",
            "field": "latency_ms",
            "sortable": True,
        },
        {
            "name": "parse_result",
            "label": "Parse Result",
            "field": "parse_result",
            "sortable": True,
        },
        {
            "name": "parse_attempts",
            "label": "Attempts",
            "field": "parse_attempts",
            "sortable": True,
        },
    ]

    def get_rows():
        rows = []
        for i, r in enumerate(call_log.records):
            if agent_filter.value != "All" and r.agent != agent_filter.value:
                continue
            if r.turn < (turn_min.value or 0) or r.turn > (turn_max.value or 9999):
                continue
            if result_filter.value == "success" and r.parse_result != "success":
                continue
            if result_filter.value == "failure" and r.parse_result == "success":
                continue
            rows.append(
                {
                    "id": i,
                    "turn": r.turn,
                    "agent": r.agent,
                    "prompt_tokens": r.prompt_tokens,
                    "thinking_tokens": r.thinking_tokens,
                    "content_tokens": r.content_tokens,
                    "latency_ms": r.latency_ms,
                    "parse_result": r.parse_result,
                    "parse_attempts": r.parse_attempts,
                    # Extra fields for expansion
                    "temperature": r.temperature,
                    "max_tokens": r.max_tokens,
                    "finish_reason": r.finish_reason,
                    "retry_count": r.retry_count,
                    "timestamp": r.timestamp,
                }
            )
        return rows

    table = ui.table(columns=columns, rows=get_rows(), row_key="id").classes("w-full")

    # Expandable rows with color-coded parse result
    table.add_slot(
        "body",
        r"""
        <q-tr :props="props" @click="props.expand = !props.expand"
              style="cursor: pointer;">
            <q-td v-for="col in props.cols" :key="col.name" :props="props">
                <q-badge v-if="col.name === 'parse_result'"
                         :color="col.value === 'success' ? 'green' : 'red'">
                    {{ col.value }}
                </q-badge>
                <span v-else>{{ col.value }}</span>
            </q-td>
        </q-tr>
        <q-tr v-show="props.expand" :props="props">
            <q-td colspan="100%">
                <div class="text-left q-pa-sm"
                     style="color: #aaa; font-size: 0.85em;">
                    <div>Temperature: {{ props.row.temperature }}</div>
                    <div>Max Tokens: {{ props.row.max_tokens }}</div>
                    <div>Finish Reason: {{ props.row.finish_reason }}</div>
                    <div>Retry Count: {{ props.row.retry_count }}</div>
                    <div>Timestamp: {{ props.row.timestamp }}</div>
                </div>
            </q-td>
        </q-tr>
    """,
    )

    # Re-filter on change
    def refresh_table():
        table.rows = get_rows()
        table.update()

    agent_filter.on_value_change(lambda _: refresh_table())
    turn_min.on_value_change(lambda _: refresh_table())
    turn_max.on_value_change(lambda _: refresh_table())
    result_filter.on_value_change(lambda _: refresh_table())

    # Summary row
    summary = call_log.summary()
    with ui.row().classes("w-full gap-6 mt-4 text-sm").style("color: #aaa;"):
        ui.label(f"Total calls: {summary['total_calls']}")
        ui.label(f"Mean latency: {summary['mean_latency_ms']}ms")
        ui.label(f"Parse success: {summary['parse_success_rate']:.1%}")
        ui.label(f"Total prompt tokens: {summary['total_prompt_tokens']:,}")
        ui.label(f"Total retries: {summary['total_retries']}")
        if summary["length_finishes"] > 0:
            ui.label(f"Length finishes: {summary['length_finishes']}").style(
                "color: #ffa726;"
            )


# ---------------------------------------------------------------------------
# Tab 2: Token Usage
# ---------------------------------------------------------------------------


def _build_token_usage_tab(call_log: LLMCallLog) -> None:
    """Build token usage charts using ui.echart."""
    turns = sorted(set(r.turn for r in call_log.records))

    # --- Tokens per turn (stacked bar chart) ---
    prompt_by_turn = []
    thinking_by_turn = []
    content_by_turn = []
    for t in turns:
        recs = call_log.records_for_turn(t)
        prompt_by_turn.append(sum(r.prompt_tokens for r in recs))
        thinking_by_turn.append(sum(r.thinking_tokens for r in recs))
        content_by_turn.append(sum(r.content_tokens for r in recs))

    ui.label("Tokens per Turn").classes("font-bold text-lg mt-2")
    ui.echart(
        {
            "tooltip": {"trigger": "axis"},
            "legend": {"data": ["Prompt", "Thinking", "Content"]},
            "xAxis": {
                "type": "category",
                "data": [str(t) for t in turns],
                "name": "Turn",
            },
            "yAxis": {"type": "value", "name": "Tokens"},
            "series": [
                {
                    "name": "Prompt",
                    "type": "bar",
                    "stack": "total",
                    "data": prompt_by_turn,
                    "color": "#42a5f5",
                },
                {
                    "name": "Thinking",
                    "type": "bar",
                    "stack": "total",
                    "data": thinking_by_turn,
                    "color": "#ab47bc",
                },
                {
                    "name": "Content",
                    "type": "bar",
                    "stack": "total",
                    "data": content_by_turn,
                    "color": "#66bb6a",
                },
            ],
        }
    ).classes("w-full h-80")

    # --- Tokens by agent (pie chart) ---
    agent_data = call_log.agent_summary()

    ui.label("Token Consumption by Agent").classes("font-bold text-lg mt-6")
    pie_data = [
        {
            "name": agent,
            "value": (
                stats["total_prompt_tokens"]
                + stats["total_thinking_tokens"]
                + stats["total_content_tokens"]
            ),
        }
        for agent, stats in agent_data.items()
    ]
    ui.echart(
        {
            "tooltip": {"trigger": "item"},
            "series": [
                {
                    "name": "Tokens",
                    "type": "pie",
                    "data": pie_data,
                    "radius": "60%",
                }
            ],
        }
    ).classes("w-full h-80")

    # --- Latency trend (line chart) ---
    latency_by_turn = []
    for t in turns:
        recs = call_log.records_for_turn(t)
        avg = sum(r.latency_ms for r in recs) / len(recs) if recs else 0
        latency_by_turn.append(round(avg))

    ui.label("Average Latency per Turn").classes("font-bold text-lg mt-6")
    ui.echart(
        {
            "tooltip": {"trigger": "axis"},
            "xAxis": {
                "type": "category",
                "data": [str(t) for t in turns],
                "name": "Turn",
            },
            "yAxis": {"type": "value", "name": "Latency (ms)"},
            "series": [
                {
                    "name": "Avg Latency",
                    "type": "line",
                    "data": latency_by_turn,
                    "color": "#ffa726",
                }
            ],
        }
    ).classes("w-full h-64")

    # --- Parse success rate by agent (bar chart) ---
    ui.label("Parse Success Rate by Agent").classes("font-bold text-lg mt-6")
    agent_names = list(agent_data.keys())
    success_rates = [agent_data[a]["parse_success_rate"] * 100 for a in agent_names]
    ui.echart(
        {
            "tooltip": {"trigger": "axis"},
            "xAxis": {"type": "category", "data": agent_names},
            "yAxis": {"type": "value", "name": "Success Rate (%)", "max": 100},
            "series": [
                {
                    "name": "Success %",
                    "type": "bar",
                    "data": success_rates,
                    "color": "#66bb6a",
                }
            ],
        }
    ).classes("w-full h-64")


# ---------------------------------------------------------------------------
# Tab 3: Error Browser
# ---------------------------------------------------------------------------


def _build_error_browser_tab(call_log: LLMCallLog) -> None:
    """Browse parse failures grouped by error category."""
    failures = [r for r in call_log.records if r.parse_result != "success"]

    if not failures:
        ui.label("No parse failures recorded.").style("color: #66bb6a;")
        ui.label("All LLM calls parsed successfully.").style(
            "color: #888; font-size: 0.9em;"
        )
        return

    # Group by category
    categories: dict[str, list[LLMCallRecord]] = {}
    for r in failures:
        categories.setdefault(r.parse_result, []).append(r)

    ui.label(
        f"Total failures: {len(failures)} out of {len(call_log.records)} calls"
    ).style("color: #aaa; margin-bottom: 12px;")

    # Category descriptions
    category_descriptions = {
        "no_yaml_block": "Model response did not contain a YAML code block",
        "invalid_yaml": "YAML code block present but could not be parsed",
        "wrong_schema": "YAML parsed but did not match expected schema",
        "empty_response": "Model returned an empty response",
        "echo_prompt": "Model echoed back the prompt instead of responding",
        "json_instead": "Model returned JSON instead of YAML",
    }

    for category, records in sorted(categories.items(), key=lambda x: -len(x[1])):
        desc = category_descriptions.get(category, "Unknown failure type")
        with ui.expansion(f"{category} ({len(records)} failures)").classes("w-full"):
            ui.label(desc).style("color: #888; font-size: 0.85em; margin-bottom: 8px;")

            for r in records:
                with (
                    ui.card()
                    .classes("w-full mb-2")
                    .style("background: #1a1a2e; border: 1px solid #333;")
                ):
                    with ui.row().classes("gap-4 text-sm").style("color: #aaa;"):
                        ui.label(f"Turn {r.turn}")
                        ui.label(f"Agent: {r.agent}")
                        ui.label(f"Latency: {r.latency_ms}ms")
                        ui.label(f"Attempts: {r.parse_attempts}")
                        ui.label(f"Retries: {r.retry_count}")


# ---------------------------------------------------------------------------
# Tab 4: Diagnostics Files
# ---------------------------------------------------------------------------


def _build_diagnostics_files_tab(save_path: Path | None) -> None:
    """Browse per-turn diagnostic artifacts on disk."""
    if save_path is None:
        ui.label("No active save. Start a game to generate diagnostics.").style(
            "color: #888;"
        )
        return

    diag_dir = save_path / "diagnostics"
    if not diag_dir.exists():
        ui.label(
            "No diagnostics files found. Enable debug mode to generate "
            "per-turn diagnostic artifacts."
        ).style("color: #888;")
        ui.label("Toggle 'Diagnostics' in the gameplay toolbar or settings.").style(
            "color: #666; font-size: 0.85em;"
        )
        return

    # Find available turns
    turn_dirs = sorted(diag_dir.iterdir())
    turn_dirs = [d for d in turn_dirs if d.is_dir() and d.name.startswith("turn-")]

    if not turn_dirs:
        ui.label("No diagnostic turns available.").style("color: #888;")
        return

    # State
    selected_turn = {"dir": turn_dirs[-1]}

    with ui.row().classes("w-full gap-4"):
        # Left panel: turn selector
        with ui.column().classes("w-48 border-r border-gray-700 pr-2"):
            ui.label("Turns").classes("font-bold text-sm mb-2")
            for td in turn_dirs:
                turn_label = td.name

                def make_select_handler(d=td):
                    def handler():
                        selected_turn["dir"] = d
                        _refresh_file_viewer(d, file_viewer_container)

                    return handler

                ui.button(turn_label, on_click=make_select_handler()).props(
                    "flat dense no-caps"
                ).classes("w-full text-left")

        # Right panel: file viewer
        with ui.column().classes("flex-grow") as file_viewer_container:
            _refresh_file_viewer(selected_turn["dir"], file_viewer_container)


def _refresh_file_viewer(turn_dir: Path, container: ui.element | None) -> None:
    """Render the file viewer for a given turn directory."""
    if container is None:
        return
    container.clear()

    with container:
        ui.label(f"Turn: {turn_dir.name}").classes("font-bold mb-2")

        # Show summary.yaml if present
        summary_path = turn_dir / "summary.yaml"
        if summary_path.exists():
            with ui.expansion("summary.yaml").classes("w-full"):
                content = summary_path.read_text(encoding="utf-8")
                ui.code(content, language="yaml").classes("w-full")

        # Find agent subdirectories
        agent_dirs = sorted([d for d in turn_dir.iterdir() if d.is_dir()])

        for agent_dir in agent_dirs:
            with ui.expansion(agent_dir.name).classes("w-full"):
                files = sorted(agent_dir.iterdir())
                for f in files:
                    if not f.is_file():
                        continue
                    lang = "yaml" if f.suffix == ".yaml" else "text"
                    with ui.expansion(f.name).classes("w-full ml-4"):
                        content = f.read_text(encoding="utf-8")
                        ui.code(content, language=lang).classes(
                            "w-full max-h-96 overflow-auto"
                        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_call_log_from_disk(path: Path) -> LLMCallLog | None:
    """Load an LLMCallLog from a YAML file on disk.

    Returns None if the file cannot be parsed or is empty.
    """
    try:
        with open(path) as f:
            data = yaml.safe_load(f)
        if not data:
            return None

        call_log = LLMCallLog()
        for entry in data:
            call_log.log(LLMCallRecord(**entry))
        return call_log
    except Exception:
        logger.exception("Failed to load call log from %s", path)
        return None

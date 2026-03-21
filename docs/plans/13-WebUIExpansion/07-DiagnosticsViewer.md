# Step 07: Diagnostics & Observability Viewer

> **Implementation note:** This step adds a dedicated `/diagnostics` page to the web UI that surfaces the project's existing observability infrastructure (Phase 09) in a browser-based interface. It reads from `LLMCallLog` (in-memory call records), `DiagnosticsWriter` artifacts on disk, and `ParseFailureType` error categories. No engine changes are required — the viewer is a read-only consumer of data already produced by the turn engine, call logger, and diagnostics writer.
>
> **Step 00 refactoring:** After Step 00, the web architecture has changed. `app.py` is slim routing only. `GameplaySession` is a thin orchestrator delegating to `GameSessionState`, `TurnRunner`, `StreamRenderer`, and `CommandRouter`. The `components/` package provides reusable building blocks: `html_utils.py` (table rendering, `relative_time()`) and `dialogs.py`. The debug mode toggle should update `GameSessionState.debug_mode`, which is read by `TurnRunner` when executing turns. Charts use `ui.echart` (Apache ECharts via NiceGUI).

## 1. Overview

The project has rich observability tooling built in Phase 09:

- **Call logging** (`src/theact/llm/call_log.py`): `LLMCallLog` accumulates `LLMCallRecord` entries with token counts, latency, parse results, agent names, and turn numbers. Provides `summary()`, `agent_summary()`, `records_for_turn()`, and `dump_yaml()`.
- **Diagnostics writer** (`src/theact/engine/diagnostics.py`): When `run_turn(debug=True)`, writes per-agent artifacts to `diagnostics/turn-NNN/` — `system_prompt.txt`, `user_message.txt`, `raw_response.txt`, `thinking.txt`, `parsed.yaml`, `call_record.yaml`, plus a `summary.yaml` per turn.
- **Error taxonomy** (`src/theact/llm/errors.py`): 7-category `ParseFailureType` enum — `success`, `no_yaml_block`, `invalid_yaml`, `wrong_schema`, `empty_response`, `echo_prompt`, `json_instead`.
- **Context profiler** (`src/theact/llm/profiler.py`): `profile_messages()` returns `AgentProfile` with token budget allocation per agent.

Currently these are only accessible via terminal scripts (`scripts/diagnose_agent.py`, `scripts/debug_turn.py`) or by manually reading files on disk. The web UI has no diagnostics view.

This step adds a new page at `/diagnostics` with a tabbed interface for viewing LLM call logs, token usage charts, diagnostic file artifacts, and parse failure patterns. It provides visibility into model behavior without touching the terminal and supports prompt debugging and performance monitoring directly from the browser.

## 2. Page Route

**Modified file:** `src/theact/web/app.py`

> **Note:** After Step 00, `app.py` is slim routing only — it registers page routes and delegates to page-building functions. Add the `/diagnostics` route following the same pattern as existing routes.

Register a new page route:

```python
@ui.page("/diagnostics")
async def diagnostics_page():
    """Diagnostics and observability viewer."""
    from theact.web.diagnostics_viewer import build_diagnostics_page
    build_diagnostics_page()
```

Navigation entry points:

- **Menu link** — Add a "Diagnostics" button or link to the main menu page (alongside "New Game" and "Continue Game" sections). Use a `ui.button` with `icon='analytics'` that navigates to `/diagnostics`.
- **Gameplay toolbar link** — Add a button to the gameplay header bar that opens `/diagnostics` in a new tab via `ui.button(..., on_click=lambda: ui.navigate.to('/diagnostics', new_tab=True))`. Opening in a new tab ensures gameplay is not disrupted.
- **Back navigation** — The diagnostics page includes a "Back to Menu" link at the top.

```python
# In MenuBuilder (menu.py):
ui.button("Diagnostics", icon="analytics",
          on_click=lambda: ui.navigate.to("/diagnostics")).props("flat dense")

# In GameplaySession.build() (session.py):
ui.button(icon="analytics",
          on_click=lambda: ui.navigate.to("/diagnostics", new_tab=True)
          ).tooltip("Open diagnostics").props("flat dense")
```

## 3. Diagnostics Viewer Layout

**New file:** `src/theact/web/diagnostics_viewer.py`

The page uses a tabbed interface with four tabs. The `LLMCallLog` instance is obtained from the application-level state (see Section 9 for how it persists across sessions).

```python
from nicegui import ui

from theact.llm.call_log import LLMCallLog


def build_diagnostics_page(save_id: str = "") -> None:
    """Build the diagnostics page with tabbed interface.

    Args:
        save_id: The save directory name. Used to load call_log.yaml from
                 disk and to locate diagnostics artifacts. Passed via query
                 parameter from the /diagnostics route (see Section 9).
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
            ui.button(icon="arrow_back",
                      on_click=lambda: ui.navigate.to("/")).props("flat")
            ui.label("Diagnostics & Observability").style(
                "font-size: 1.4em; font-weight: bold; color: #ccc;"
            )

        if call_log is None or not call_log.records:
            ui.label("No LLM call data available. Play some turns first.").style(
                "color: #888; margin-top: 20px;"
            )
            return

        # Tabbed interface
        with ui.tabs().classes("w-full") as tabs:
            tab_calls = ui.tab("Call Log", icon="list")
            tab_tokens = ui.tab("Token Usage", icon="bar_chart")
            tab_files = ui.tab("Diagnostics Files", icon="folder_open")
            tab_errors = ui.tab("Error Browser", icon="error_outline")

        with ui.tab_panels(tabs, value=tab_calls).classes("w-full"):
            with ui.tab_panel(tab_calls):
                _build_call_log_tab(call_log)
            with ui.tab_panel(tab_tokens):
                _build_token_usage_tab(call_log)
            with ui.tab_panel(tab_files):
                _build_diagnostics_files_tab(save_path)
            with ui.tab_panel(tab_errors):
                _build_error_browser_tab(call_log)
```

## 4. Call Log Tab

> **Note:** `components/html_utils.py` from Step 00 provides table rendering utilities. Use these for the call log table and summary row rather than reimplementing formatting helpers.

Displays all `LLMCallRecord` entries in a filterable, sortable table.

### Table columns

| Column | Source field | Format |
|---|---|---|
| Turn | `record.turn` | Integer |
| Agent | `record.agent` | String (e.g. "narrator", "character:maya") |
| Prompt Tokens | `record.prompt_tokens` | Integer |
| Thinking Tokens | `record.thinking_tokens` | Integer |
| Content Tokens | `record.content_tokens` | Integer |
| Latency | `record.latency_ms` | Integer, suffixed with "ms" |
| Parse Result | `record.parse_result` | String, color-coded (green for "success", red otherwise) |
| Attempts | `record.parse_attempts` | Integer |

### Filters

Place filters in a row above the table:

```python
def _build_call_log_tab(call_log: LLMCallLog) -> None:
    # Collect unique agents and turn range
    agents = sorted(set(r.agent for r in call_log.records))
    turns = sorted(set(r.turn for r in call_log.records))

    with ui.row().classes("w-full items-center gap-4 mb-4"):
        agent_filter = ui.select(
            options=["All"] + agents, value="All", label="Agent"
        ).classes("w-48")
        turn_min = ui.number(
            label="From turn", value=min(turns) if turns else 0
        ).classes("w-24")
        turn_max = ui.number(
            label="To turn", value=max(turns) if turns else 0
        ).classes("w-24")
        result_filter = ui.select(
            options=["All", "success", "failure"], value="All", label="Parse Result"
        ).classes("w-32")

    # Table data
    columns = [
        {"name": "turn", "label": "Turn", "field": "turn", "sortable": True},
        {"name": "agent", "label": "Agent", "field": "agent", "sortable": True},
        {"name": "prompt_tokens", "label": "Prompt Tok", "field": "prompt_tokens", "sortable": True},
        {"name": "thinking_tokens", "label": "Think Tok", "field": "thinking_tokens", "sortable": True},
        {"name": "content_tokens", "label": "Content Tok", "field": "content_tokens", "sortable": True},
        {"name": "latency_ms", "label": "Latency (ms)", "field": "latency_ms", "sortable": True},
        {"name": "parse_result", "label": "Parse Result", "field": "parse_result", "sortable": True},
        {"name": "parse_attempts", "label": "Attempts", "field": "parse_attempts", "sortable": True},
    ]

    def get_rows():
        rows = []
        for i, r in enumerate(call_log.records):
            # Apply filters
            if agent_filter.value != "All" and r.agent != agent_filter.value:
                continue
            if r.turn < (turn_min.value or 0) or r.turn > (turn_max.value or 9999):
                continue
            if result_filter.value == "success" and r.parse_result != "success":
                continue
            if result_filter.value == "failure" and r.parse_result == "success":
                continue
            rows.append({
                "id": i,
                "turn": r.turn,
                "agent": r.agent,
                "prompt_tokens": r.prompt_tokens,
                "thinking_tokens": r.thinking_tokens,
                "content_tokens": r.content_tokens,
                "latency_ms": r.latency_ms,
                "parse_result": r.parse_result,
                "parse_attempts": r.parse_attempts,
            })
        return rows

    table = ui.table(columns=columns, rows=get_rows(), row_key="id").classes("w-full")
    table.add_slot("body-cell-parse_result", r'''
        <q-td :props="props">
            <q-badge :color="props.value === 'success' ? 'green' : 'red'">
                {{ props.value }}
            </q-badge>
        </q-td>
    ''')

    # Re-filter on change
    def refresh_table():
        table.rows = get_rows()
        table.update()

    agent_filter.on_value_change(lambda _: refresh_table())
    turn_min.on_value_change(lambda _: refresh_table())
    turn_max.on_value_change(lambda _: refresh_table())
    result_filter.on_value_change(lambda _: refresh_table())
```

### Row expansion

When a row is clicked, expand to show full `LLMCallRecord` details:

```python
    # Expandable rows for detail view
    table.add_slot("body", r'''
        <q-tr :props="props" @click="props.expand = !props.expand" style="cursor: pointer;">
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
                <div class="text-left q-pa-sm" style="color: #aaa; font-size: 0.85em;">
                    <div>Temperature: {{ props.row.temperature }}</div>
                    <div>Max Tokens: {{ props.row.max_tokens }}</div>
                    <div>Finish Reason: {{ props.row.finish_reason }}</div>
                    <div>Retry Count: {{ props.row.retry_count }}</div>
                    <div>Timestamp: {{ props.row.timestamp }}</div>
                </div>
            </q-td>
        </q-tr>
    ''')
```

To support expansion, include the extra fields in the row data:

```python
rows.append({
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
})
```

### Summary row

Below the table, show aggregate statistics from `call_log.summary()`:

```python
    summary = call_log.summary()
    with ui.row().classes("w-full gap-6 mt-4 text-sm").style("color: #aaa;"):
        ui.label(f"Total calls: {summary['total_calls']}")
        ui.label(f"Mean latency: {summary['mean_latency_ms']}ms")
        ui.label(f"Parse success: {summary['parse_success_rate']:.1%}")
        ui.label(f"Total prompt tokens: {summary['total_prompt_tokens']:,}")
        ui.label(f"Total retries: {summary['total_retries']}")
        if summary['length_finishes'] > 0:
            ui.label(f"Length finishes: {summary['length_finishes']}").style("color: #ffa726;")
```

## 5. Token Usage Tab

Charts using NiceGUI's `ui.echart` component (which wraps Apache ECharts). Data is derived from `LLMCallLog.summary()`, `LLMCallLog.agent_summary()`, and per-turn aggregation of `records_for_turn()`.

```python
def _build_token_usage_tab(call_log: LLMCallLog) -> None:
    # --- Tokens per turn (stacked bar chart) ---
    turns = sorted(set(r.turn for r in call_log.records))
    prompt_by_turn = []
    thinking_by_turn = []
    content_by_turn = []
    for t in turns:
        recs = call_log.records_for_turn(t)
        prompt_by_turn.append(sum(r.prompt_tokens for r in recs))
        thinking_by_turn.append(sum(r.thinking_tokens for r in recs))
        content_by_turn.append(sum(r.content_tokens for r in recs))

    ui.label("Tokens per Turn").classes("font-bold text-lg mt-2")
    # Note: verify exact ECharts options against the ECharts documentation during implementation.
    ui.echart({
        "xAxis": {"type": "category", "data": [str(t) for t in turns], "name": "Turn"},
        "yAxis": {"type": "value", "name": "Tokens"},
        "series": [
            {"name": "Prompt", "type": "bar", "stack": "total", "data": prompt_by_turn, "color": "#42a5f5"},
            {"name": "Thinking", "type": "bar", "stack": "total", "data": thinking_by_turn, "color": "#ab47bc"},
            {"name": "Content", "type": "bar", "stack": "total", "data": content_by_turn, "color": "#66bb6a"},
        ],
    }).classes("w-full h-80")

    # --- Tokens by agent (pie chart) ---
    agent_data = call_log.agent_summary()

    ui.label("Token Consumption by Agent").classes("font-bold text-lg mt-6")
    # Note: verify exact ECharts options against the ECharts documentation during implementation.
    pie_data = [
        {"name": agent, "value": stats["total_prompt_tokens"] + stats["total_thinking_tokens"] + stats["total_content_tokens"]}
        for agent, stats in agent_data.items()
    ]
    ui.echart({
        "series": [{"name": "Tokens", "type": "pie", "data": pie_data}],
    }).classes("w-full h-80")

    # --- Latency trend (line chart) ---
    latency_by_turn = []
    for t in turns:
        recs = call_log.records_for_turn(t)
        avg = sum(r.latency_ms for r in recs) / len(recs) if recs else 0
        latency_by_turn.append(round(avg))

    ui.label("Average Latency per Turn").classes("font-bold text-lg mt-6")
    # Note: verify exact ECharts options against the ECharts documentation during implementation.
    ui.echart({
        "xAxis": {"type": "category", "data": [str(t) for t in turns], "name": "Turn"},
        "yAxis": {"type": "value", "name": "Latency (ms)"},
        "series": [{"name": "Avg Latency", "type": "line", "data": latency_by_turn, "color": "#ffa726"}],
    }).classes("w-full h-64")

    # --- Parse success rate by agent (bar chart) ---
    ui.label("Parse Success Rate by Agent").classes("font-bold text-lg mt-6")
    # Note: verify exact ECharts options against the ECharts documentation during implementation.
    agent_names = list(agent_data.keys())
    success_rates = [agent_data[a]["parse_success_rate"] * 100 for a in agent_names]
    ui.echart({
        "xAxis": {"type": "category", "data": agent_names},
        "yAxis": {"type": "value", "name": "Success Rate (%)", "max": 100},
        "series": [{"name": "Success %", "type": "bar", "data": success_rates, "color": "#66bb6a"}],
    }).classes("w-full h-64")
```

## 6. Diagnostics Files Tab

Browses the `diagnostics/turn-NNN/` directories written by `DiagnosticsWriter` when turns are run with `debug=True`.

### Layout

Two-panel layout:
- **Left panel** (~200px): List of available diagnostic turns, derived by scanning the `diagnostics/` directory under the current save path.
- **Right panel** (remaining width): File viewer showing the selected artifact.

```python
def _build_diagnostics_files_tab(save_path: Path | None) -> None:
    """Browse per-turn diagnostic artifacts.

    Args:
        save_path: Path to the save directory, derived from the save_id
                   parameter passed to build_diagnostics_page (see Section 9).
    """
    if save_path is None:
        ui.label("No active save. Start a game to generate diagnostics.").style("color: #888;")
        return

    diag_dir = save_path / "diagnostics"
    if not diag_dir.exists():
        ui.label(
            "No diagnostics files found. Enable debug mode to generate "
            "per-turn diagnostic artifacts."
        ).style("color: #888;")
        ui.label(
            "Toggle 'Enable Diagnostics' in the gameplay toolbar or settings."
        ).style("color: #666; font-size: 0.85em;")
        return

    # Find available turns
    turn_dirs = sorted(diag_dir.iterdir())
    turn_dirs = [d for d in turn_dirs if d.is_dir() and d.name.startswith("turn-")]

    if not turn_dirs:
        ui.label("No diagnostic turns available.").style("color: #888;")
        return

    # State
    selected_turn = {"dir": turn_dirs[-1]}  # default to latest
    file_viewer_container = None

    with ui.row().classes("w-full gap-4"):
        # Left panel: turn selector
        with ui.column().classes("w-48 border-r border-gray-700 pr-2"):
            ui.label("Turns").classes("font-bold text-sm mb-2")
            for td in turn_dirs:
                turn_label = td.name  # e.g. "turn-001"

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


def _refresh_file_viewer(turn_dir, container) -> None:
    """Render the file viewer for a given turn directory."""
    if container is None:
        return
    container.clear()

    with container:
        ui.label(f"Turn: {turn_dir.name}").classes("font-bold mb-2")

        # Find agent subdirectories
        agent_dirs = sorted([d for d in turn_dir.iterdir() if d.is_dir()])

        # Also show summary.yaml if present
        summary_path = turn_dir / "summary.yaml"
        if summary_path.exists():
            with ui.expansion("summary.yaml").classes("w-full"):
                content = summary_path.read_text(encoding="utf-8")
                ui.code(content, language="yaml").classes("w-full")

        for agent_dir in agent_dirs:
            with ui.expansion(agent_dir.name).classes("w-full"):
                # List files in agent directory
                files = sorted(agent_dir.iterdir())
                for f in files:
                    if not f.is_file():
                        continue
                    lang = "yaml" if f.suffix == ".yaml" else "text"
                    with ui.expansion(f.name).classes("w-full ml-4"):
                        content = f.read_text(encoding="utf-8")
                        ui.code(content, language=lang).classes("w-full max-h-96 overflow-auto")
```

### File types and rendering

| File | Language | Notes |
|---|---|---|
| `system_prompt.txt` | `text` | The system prompt sent to the LLM |
| `user_message.txt` | `text` | The assembled user message |
| `raw_response.txt` | `text` | The raw LLM response text |
| `thinking.txt` | `text` | Model's thinking/reasoning (if present) |
| `parsed.yaml` | `yaml` | Parsed structured output |
| `call_record.yaml` | `yaml` | Full `LLMCallRecord` as YAML |
| `summary.yaml` | `yaml` | Turn-level aggregate (at turn root, not per agent) |

## 7. Error Browser Tab

Filters `LLMCallRecord` entries where `parse_result` is not `"success"` and groups them by `ParseFailureType` category.

```python
def _build_error_browser_tab(call_log: LLMCallLog) -> None:
    """Browse parse failures grouped by error category."""
    from theact.llm.errors import ParseFailureType

    # Collect failures
    failures = [r for r in call_log.records if r.parse_result != "success"]

    if not failures:
        ui.label("No parse failures recorded.").style("color: #66bb6a;")
        ui.label("All LLM calls parsed successfully.").style("color: #888; font-size: 0.9em;")
        return

    # Group by category
    categories: dict[str, list] = {}
    for r in failures:
        categories.setdefault(r.parse_result, []).append(r)

    # Summary cards
    ui.label(f"Total failures: {len(failures)} out of {len(call_log.records)} calls").style(
        "color: #aaa; margin-bottom: 12px;"
    )

    # Category descriptions for context
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
        with ui.expansion(
            f"{category} ({len(records)} failures)"
        ).classes("w-full"):
            ui.label(desc).style("color: #888; font-size: 0.85em; margin-bottom: 8px;")

            for r in records:
                with ui.card().classes("w-full mb-2").style(
                    "background: #1a1a2e; border: 1px solid #333;"
                ):
                    with ui.row().classes("gap-4 text-sm").style("color: #aaa;"):
                        ui.label(f"Turn {r.turn}")
                        ui.label(f"Agent: {r.agent}")
                        ui.label(f"Latency: {r.latency_ms}ms")
                        ui.label(f"Attempts: {r.parse_attempts}")
                        ui.label(f"Retries: {r.retry_count}")
```

The error browser helps identify patterns: e.g., if `no_yaml_block` failures cluster on a specific agent, that agent's prompt may need adjustment. If `wrong_schema` failures spike after a prompt change, the new prompt may be confusing the model.

## 8. Debug Mode Toggle

Add an option in the gameplay session to enable debug mode, which causes `run_turn()` to be called with `debug=True` and triggers `DiagnosticsWriter` to write per-turn artifacts.

### Toggle location

**Modified file:** `src/theact/web/state.py` and `src/theact/web/session.py`

> **Note:** After Step 00, `GameplaySession` is a thin orchestrator. Observable state lives in `GameSessionState` (in `state.py`), and turn execution is handled by `TurnRunner`. The debug mode flag should be stored in `GameSessionState` so that `TurnRunner` can read it when executing turns.

Add a `debug_mode` field to `GameSessionState`:

```python
class GameSessionState:
    def __init__(self, ...) -> None:
        ...
        self.debug_mode = False
```

> **Note:** `debug_mode` is already a field on the `GameSessionState` dataclass from Step 00 — no additional `state.py` changes are needed. The snippet above is shown for context only.

Add a toggle in the gameplay header bar (alongside the existing "Thinking" switch). The toggle updates `GameSessionState.debug_mode`:

```python
def _build_header(self) -> None:
    with ui.row().classes("w-full items-center p-2").style("border-bottom: 1px solid #444;"):
        # ... existing header label ...

        self._debug_switch = ui.switch("Diagnostics", value=self.state.debug_mode).style(
            "color: #999;"
        )
        self._debug_switch.on_value_change(self._on_debug_toggle)

        # ... existing thinking switch, menu button ...


def _on_debug_toggle(self, e) -> None:
    self.state.debug_mode = e.value
    state_label = "enabled" if e.value else "disabled"
    ui.notify(f"Debug diagnostics {state_label}.", type="info")
```

### Passing debug to run_turn

`TurnRunner` reads `state.debug_mode` when executing turns:

```python
# In TurnRunner.run():
result = await run_turn(
    self.state.game,
    player_input,
    self.state.llm_config,
    on_token=on_token,
    call_log=self._call_log,     # see Section 9
    debug=self.state.debug_mode,
)
```

### Note on disk usage

When debug mode is enabled, `DiagnosticsWriter` writes files for every agent on every turn. For a turn with 5 agents, that is roughly 30 files per turn. Over a long session this adds up. The toggle defaults to off and the UI should include a brief note:

```python
self._debug_switch.tooltip(
    "Write per-turn diagnostic files to disk. Increases disk usage."
)
```

## 9. Call Log Persistence

### In-session accumulation

Add an `LLMCallLog` instance to `TurnRunner` and pass it to `run_turn()`:

> **Note:** `LLMCallLog` lives on `TurnRunner` (as `self._turn_runner.call_log`), not on the session directly. `GameplaySession` accesses it via `self._turn_runner.call_log` when needed (e.g., for persistence or passing to the diagnostics page).

```python
from theact.llm.call_log import LLMCallLog

class TurnRunner:
    def __init__(self, ...) -> None:
        ...
        self.call_log = LLMCallLog()
```

`TurnRunner.run()` passes the call log to `run_turn`:

```python
result = await run_turn(
    self._state.game,
    player_input,
    self._state.llm_config,
    on_token=on_token,
    call_log=self.call_log,
    debug=self._state.debug_mode,
)
```

### Persistence across sessions

To survive page reloads and session restarts, dump the call log to disk periodically:

- **On turn completion:** After each successful turn, call `self._turn_runner.call_log.dump_yaml(self._state.game.save_path / "call_log.yaml")`.
- **On session load:** When loading a save, check for `saves/{save-id}/call_log.yaml`. If present, load it to restore the call log on `TurnRunner`.

```python
from dataclasses import fields as dataclass_fields

def _load_call_log(self) -> None:
    """Load persisted call log if available."""
    log_path = self._state.game.save_path / "call_log.yaml"
    if log_path.exists():
        import yaml
        from theact.llm.call_log import LLMCallRecord
        with open(log_path) as f:
            data = yaml.safe_load(f) or []
        for entry in data:
            self._turn_runner.call_log.log(LLMCallRecord(**entry))

def _persist_call_log(self) -> None:
    """Save call log to disk."""
    self._turn_runner.call_log.dump_yaml(self._state.game.save_path / "call_log.yaml")
```

Call `_load_call_log()` at the end of `__init__` and `_persist_call_log()` at the end of each successful `_play_turn()`.

### Passing call log to diagnostics page

The diagnostics page needs access to the call log. Options:

1. **Read from disk:** The `/diagnostics` page reads `saves/{save-id}/call_log.yaml` directly. This works even if the gameplay session is not active.
2. **App-level storage:** Store the call log reference in `app.storage.general` keyed by save ID. The diagnostics page retrieves it by save ID from a query parameter (`/diagnostics?save=my-save`).

Option 1 is simpler and recommended for the initial implementation. The diagnostics page accepts a `save_id` query parameter:

```python
@ui.page("/diagnostics")
async def diagnostics_page(save: str = ""):
    from theact.web.diagnostics_viewer import build_diagnostics_page
    build_diagnostics_page(save_id=save)
```

```python
def build_diagnostics_page(save_id: str = "") -> None:
    call_log = None
    if save_id:
        log_path = SAVES_DIR / save_id / "call_log.yaml"
        if log_path.exists():
            call_log = _load_call_log_from_disk(log_path)
    # ... build UI with call_log ...
```

## 10. Tests

**New file:** `tests/web/test_diagnostics.py`

Tests use the same Playwright-based browser testing pattern as existing web tests (see `tests/web/conftest.py`).

```python
import pytest
from pathlib import Path
from playwright.sync_api import expect


def test_diagnostics_page_accessible(page, web_server):
    """Diagnostics page loads at /diagnostics."""
    page.goto(f"{web_server}/diagnostics")
    # Page should load without error
    heading = page.locator("text=Diagnostics & Observability")
    expect(heading).to_be_visible()


def test_diagnostics_empty_state(page, web_server):
    """With no call data, shows an appropriate message."""
    page.goto(f"{web_server}/diagnostics")
    empty_msg = page.locator("text=No LLM call data available")
    expect(empty_msg).to_be_visible()


def test_diagnostics_tabs_present(page, web_server, tmp_path):
    """All four tabs are rendered when call log data exists.

    Note: The test fixture must provide a save with a call_log.yaml file,
    because build_diagnostics_page returns early (before rendering tabs)
    when there is no call log data. The fixture creates a minimal
    call_log.yaml so that the tabs are rendered.
    """
    # Create a minimal save with call log data for the test
    save_dir = tmp_path / "test-save"
    save_dir.mkdir(parents=True)
    call_log_path = save_dir / "call_log.yaml"
    call_log_path.write_text(
        "- turn: 1\n  agent: narrator\n  prompt_tokens: 100\n"
        "  thinking_tokens: 0\n  content_tokens: 50\n  latency_ms: 200\n"
        "  parse_result: success\n  parse_attempts: 1\n"
    )

    page.goto(f"{web_server}/diagnostics?save=test-save")
    for tab_name in ["Call Log", "Token Usage", "Diagnostics Files", "Error Browser"]:
        tab = page.locator(f"text={tab_name}")
        expect(tab).to_be_visible()


def test_diagnostics_link_in_menu(page, web_server):
    """Menu page has a link/button to diagnostics."""
    page.goto(web_server)
    diag_button = page.locator("text=Diagnostics")
    expect(diag_button).to_be_visible()
```

Additional tests to add once the full implementation is in place:

- **Call log table renders with data:** Create a save with a persisted `call_log.yaml`, navigate to `/diagnostics?save=<id>`, verify the table has rows.
- **Tab switching:** Click each tab and verify its panel content appears.
- **Error browser empty state:** With all-success call log, verify "No parse failures recorded" message.
- **Diagnostics files empty state:** Without debug artifacts, verify the "No diagnostics files found" message and the suggestion to enable debug mode.

## 11. What This Step Does NOT Do

- **Live streaming of diagnostics.** The diagnostics page shows a snapshot of call log data at page load time. It does not update in real time as turns are played. A manual refresh (page reload) is needed to see new data.
- **Editing prompts from the viewer.** The diagnostics files tab is read-only. It does not provide a prompt editor or re-run capability. Use `scripts/debug_turn.py` for interactive prompt editing.
- **Comparing across sessions.** There is no A/B comparison view or diff between two call logs. Use `scripts/ab_test.py` for that.
- **Context profiler integration.** The context profiler (`src/theact/llm/profiler.py`) provides per-call token budget analysis, but integrating it into the viewer requires capturing `AgentProfile` data during turns. This can be added as a follow-up enhancement.
- **Export or download.** No CSV/JSON export of call log data. The persisted `call_log.yaml` file serves as the export format.
- **Alerts or thresholds.** No automatic warnings when latency exceeds a threshold or parse failure rate degrades. This could be a future enhancement.
- **Multi-save comparison.** The viewer shows data for one save at a time. Cross-save analysis is out of scope.

## 12. Verification

After implementation, confirm:

1. **Diagnostics page accessible from menu** — The main menu (`/`) includes a "Diagnostics" button or link that navigates to `/diagnostics`. The page loads with a header and back-navigation.
2. **Diagnostics page accessible from gameplay** — The gameplay toolbar has a diagnostics button that opens `/diagnostics` in a new tab without disrupting the active game session.
3. **Call log tab shows LLM call records** — After playing several turns with a call log, the Call Log tab displays a table with one row per LLM call. Columns include Turn, Agent, Prompt Tokens, Thinking Tokens, Content Tokens, Latency, Parse Result, and Attempts. Filters by agent, turn range, and parse result work correctly. Clicking a row expands to show temperature, max_tokens, finish_reason, retry_count, and timestamp. Summary row shows totals and averages.
4. **Token usage tab shows charts** — The Token Usage tab renders at least four charts: tokens per turn (stacked bar), tokens by agent (pie), latency trend (line), and parse success rate by agent (bar). Charts use data from `LLMCallLog.summary()` and `LLMCallLog.agent_summary()`.
5. **Diagnostics files tab browses artifacts** — After running turns with debug mode enabled, the Diagnostics Files tab shows a list of available diagnostic turns. Selecting a turn displays agent subdirectories. Expanding an agent shows its artifact files (`system_prompt.txt`, `raw_response.txt`, `parsed.yaml`, etc.) with syntax highlighting for YAML files.
6. **Error browser groups failures** — The Error Browser tab groups parse failures by `ParseFailureType` category (e.g., `no_yaml_block`, `invalid_yaml`, `wrong_schema`). Each category shows a count and is expandable to reveal individual failure records with turn, agent, latency, and attempt count. When there are no failures, shows a success message.
7. **Debug mode toggle enables diagnostics** — The gameplay toolbar has a "Diagnostics" switch defaulting to off. When toggled on, subsequent turns call `run_turn(debug=True)` and diagnostic files appear in `diagnostics/turn-NNN/`. When toggled off, no diagnostic files are written.
8. **Call log persists across sessions** — After playing turns, `call_log.yaml` is written to the save directory. Reloading the save (or navigating to `/diagnostics?save=<id>`) restores the full call history. The file uses `LLMCallLog.dump_yaml()` format.
9. **Empty states handled gracefully** — The diagnostics page with no call data shows "No LLM call data available." The diagnostics files tab with no debug artifacts shows a message suggesting to enable debug mode. The error browser with no failures shows a success message.
10. **No regressions** — Existing web UI tests (`tests/web/`) continue to pass. The gameplay session works normally with and without the debug toggle. The call log does not affect turn performance.

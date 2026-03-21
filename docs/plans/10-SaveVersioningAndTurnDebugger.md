# Phase 10: Save Versioning & Turn Debugger

## 1. Overview

This phase adds two capabilities that serve different users with a shared foundation:

**Part A -- Save Versioning Enhancements.** Players and developers can fork saves non-destructively, peek at historical turn state without modifying HEAD, and diff any two turns. The existing `git_save.py` already provides `init_repo`, `commit_turn`, `undo`, `get_history`, and `get_turn_count`. This phase adds `save_as`, `peek_at_turn`, and `diff_turns` on top of that foundation.

**Part B -- Turn Debugger.** An interactive script for prompt engineers to step through a turn agent-by-agent, inspect prompts and responses, replay with edited prompts, and capture test fixtures. This is the single most impactful tool for prompt iteration -- it turns "change, re-run full playtest, hope" into "change, replay one agent, see immediately."

### What This Phase Does NOT Do

- No changes to the turn engine flow. The debugger wraps agent calls; it does not modify `run_turn()`.
- No changes to agent prompts. This phase builds tooling, not prompt improvements.
- No new game mechanics or features.

### Dependencies

- **Phase 01** (data models, git versioning) -- the foundation this phase extends.
- **Phase 03** (turn engine, agents, context assembly) -- the debugger wraps these.
- **Phase 09** (observability) -- the debugger uses `LLMCallRecord` and `LLMCallLog` for stats display if available, but degrades gracefully without them.

---

## 2. Part A: Save Versioning Enhancements

### 2.1 `save_as(save_path, new_save_id, saves_dir) -> Path`

Copy an entire save (including `.git/` history) to a new location. This enables non-destructive forking: copy first, then undo on the copy. The original timeline is preserved.

**File:** `src/theact/versioning/git_save.py`

```python
def save_as(save_path: Path, new_save_id: str, saves_dir: Path | None = None) -> Path:
    """Fork a save by copying the entire directory (including .git history).

    Args:
        save_path: Path to the existing save directory.
        new_save_id: Name for the new save directory.
        saves_dir: Parent directory for saves. Defaults to save_path.parent.

    Returns:
        Path to the new save directory.

    Raises:
        FileExistsError: If a save with new_save_id already exists.
        FileNotFoundError: If save_path does not exist.
    """
    if not save_path.exists():
        raise FileNotFoundError(f"Save not found: {save_path}")

    target_dir = (saves_dir or save_path.parent) / new_save_id
    if target_dir.exists():
        raise FileExistsError(f"Save already exists: {target_dir}")

    shutil.copytree(save_path, target_dir)
    return target_dir
```

**Import:** Add `import shutil` at the top of `git_save.py`.

### 2.2 `peek_at_turn(save_path, turn_number) -> dict[str, str]`

Read-only access to any historical turn's state WITHOUT modifying HEAD. Uses `git show` to read file contents at a specific commit. No checkout, no modification to the working tree.

**File:** `src/theact/versioning/git_save.py`

```python
def peek_at_turn(save_path: Path, turn_number: int) -> dict[str, str]:
    """Read file contents at a specific turn without modifying HEAD.

    Uses `git show <ref>:<path>` to read files at the commit for the
    given turn number. Returns a dict of {filename: content} for the
    key game state files.

    Args:
        save_path: Path to the save directory (must be a git repo).
        turn_number: The turn to peek at (0 = initial state before any turns).

    Returns:
        Dict mapping filenames to their contents at that turn.
        Keys include: "state.yaml", "conversation.yaml", and any
        "memory/<name>.yaml" files that existed at that turn.

    Raises:
        ValueError: If the turn_number is out of range.
    """
    repo = Repo(save_path)
    history = get_history(save_path)

    if turn_number == 0:
        # Initial commit: find it by walking past all turn commits
        all_commits = list(repo.iter_commits())
        ref = all_commits[-1].hexsha  # oldest commit
    else:
        # Find the commit for this turn
        match = [h for h in history if h.turn == turn_number]
        if not match:
            available = sorted(h.turn for h in history)
            raise ValueError(
                f"Turn {turn_number} not found. Available turns: {available}"
            )
        ref = match[0].commit_hash

    # Files to retrieve
    target_files = ["state.yaml", "conversation.yaml", "summaries.yaml"]

    result: dict[str, str] = {}
    for fname in target_files:
        try:
            content = repo.git.show(f"{ref}:{fname}")
            result[fname] = content
        except Exception:
            pass  # File may not exist at this commit

    # Memory files: list tree at ref to find them
    try:
        tree_output = repo.git.ls_tree("-r", "--name-only", ref)
        for line in tree_output.splitlines():
            if line.startswith("memory/") and line.endswith(".yaml"):
                content = repo.git.show(f"{ref}:{line}")
                result[line] = content
    except Exception:
        pass

    return result
```

### 2.3 `diff_turns(save_path, turn_a, turn_b) -> str`

Show what changed between two turns. Uses `git diff` between the two commits. Returns human-readable diff text.

**File:** `src/theact/versioning/git_save.py`

```python
def diff_turns(save_path: Path, turn_a: int, turn_b: int) -> str:
    """Show what changed between two turns as a unified diff.

    Args:
        save_path: Path to the save directory.
        turn_a: First turn number (0 = initial state).
        turn_b: Second turn number.

    Returns:
        Human-readable unified diff text. Empty string if no differences.

    Raises:
        ValueError: If either turn number is out of range.
    """
    repo = Repo(save_path)
    history = get_history(save_path)

    def _resolve_ref(turn: int) -> str:
        if turn == 0:
            all_commits = list(repo.iter_commits())
            return all_commits[-1].hexsha
        match = [h for h in history if h.turn == turn]
        if not match:
            available = [0] + sorted(h.turn for h in history)
            raise ValueError(
                f"Turn {turn} not found. Available: {available}"
            )
        return match[0].commit_hash

    ref_a = _resolve_ref(turn_a)
    ref_b = _resolve_ref(turn_b)

    # Diff key state files (not game definition files, which are immutable)
    diff_paths = ["state.yaml", "conversation.yaml", "summaries.yaml", "memory/"]

    diff_text = repo.git.diff(ref_a, ref_b, "--", *diff_paths)
    return diff_text
```

### 2.4 `list_saves()` Compatibility

The existing `list_saves()` in `src/theact/io/save_manager.py` scans all subdirectories of the saves directory. Saves created by `save_as()` are structurally identical to originals, so `list_saves()` already works with them -- no code change needed.

**Verification:** Write a test that calls `save_as()`, then calls `list_saves()`, and confirms the forked save appears in the list.

### 2.5 CLI Integration: `/save-as <name>`

**File:** `src/theact/cli/commands.py`

Add to the `COMMANDS` dict:

```python
"save-as": {"args": "<name>", "desc": "Fork the current save to a new name"},
```

Add the command handler:

```python
def cmd_save_as(console: Console, game: LoadedGame, args: list[str]) -> None:
    """Fork the current save to a new save directory."""
    if not args:
        console.print("Usage: /save-as <name>", style=ERROR_STYLE)
        return

    new_save_id = args[0]
    try:
        new_path = git_save.save_as(game.save_path, new_save_id)
        console.print(
            f"Save forked to: {new_path.name}",
            style=STATUS_STYLE,
        )
    except FileExistsError:
        console.print(
            f"Save '{new_save_id}' already exists.",
            style=ERROR_STYLE,
        )
    except FileNotFoundError as e:
        console.print(f"Error: {e}", style=ERROR_STYLE)
```

Wire the command in the session's command dispatch (in `src/theact/cli/session.py`).

### 2.6 Web UI Integration: `/save-as <name>`

**File:** `src/theact/web/commands.py`

Add `cmd_save_as_web()` following the same pattern as `cmd_save_web()`:

```python
def cmd_save_as_web(
    chat_area: ui.element, game: LoadedGame, args: list[str]
) -> None:
    """Fork the current save to a new directory."""
    if not args:
        ui.notify("Usage: /save-as <name>", type="warning")
        return

    new_save_id = args[0]
    try:
        new_path = git_save.save_as(game.save_path, new_save_id)
        show_system_message(
            chat_area,
            html_lib.escape(f"Save forked to: {new_path.name}"),
        )
    except FileExistsError:
        ui.notify(f"Save '{new_save_id}' already exists.", type="warning")
    except FileNotFoundError as e:
        ui.notify(str(e), type="negative")
```

Update the `COMMANDS_HELP` table and the web session's command dispatch to include `/save-as`.

---

## 3. Part A: Tests

### 3.1 Test File

**File:** `tests/test_save_versioning.py`

All tests use `tmp_path` fixtures and the same `games_dir` / `saves_dir` / `save_path` pattern from the existing `test_git_save.py`.

### 3.2 Test Cases

```python
class TestSaveAs:
    def test_creates_copy(self, save_path: Path, saves_dir: Path):
        """save_as creates a new directory with all files including .git."""
        new_path = save_as(save_path, "forked-save", saves_dir)
        assert new_path.exists()
        assert (new_path / ".git").is_dir()
        assert (new_path / "game.yaml").exists()
        assert (new_path / "state.yaml").exists()

    def test_preserves_history(self, save_path: Path, saves_dir: Path):
        """Forked save has the same git history as the original."""
        # Make some turns first
        for i in range(1, 4):
            _make_turn(save_path, i)
        new_path = save_as(save_path, "fork-history", saves_dir)
        assert get_turn_count(new_path) == 3
        assert get_turn_count(save_path) == 3  # original unchanged

    def test_independent_after_fork(self, save_path: Path, saves_dir: Path):
        """Changes to forked save do not affect original."""
        _make_turn(save_path, 1)
        new_path = save_as(save_path, "fork-independent", saves_dir)
        _make_turn(new_path, 2)
        assert get_turn_count(new_path) == 2
        assert get_turn_count(save_path) == 1  # original unaffected

    def test_undo_on_fork_preserves_original(self, save_path, saves_dir):
        """Undo on forked save leaves original intact."""
        for i in range(1, 4):
            _make_turn(save_path, i)
        new_path = save_as(save_path, "fork-undo", saves_dir)
        undo(new_path, 2)
        assert get_turn_count(new_path) == 1
        assert get_turn_count(save_path) == 3

    def test_duplicate_name_raises(self, save_path: Path, saves_dir: Path):
        """save_as raises FileExistsError if target exists."""
        save_as(save_path, "existing", saves_dir)
        with pytest.raises(FileExistsError):
            save_as(save_path, "existing", saves_dir)

    def test_missing_source_raises(self, saves_dir: Path):
        """save_as raises FileNotFoundError if source does not exist."""
        with pytest.raises(FileNotFoundError):
            save_as(saves_dir / "nonexistent", "target", saves_dir)

    def test_list_saves_includes_fork(self, save_path, saves_dir):
        """list_saves returns both original and forked saves."""
        save_as(save_path, "forked-listed", saves_dir)
        saves = list_saves(saves_dir)
        ids = [s["id"] for s in saves]
        assert save_path.name in ids
        assert "forked-listed" in ids


class TestPeekAtTurn:
    def test_peek_at_turn_zero(self, save_path: Path):
        """peek_at_turn(0) returns initial state before any turns."""
        _make_turn(save_path, 1)
        data = peek_at_turn(save_path, 0)
        assert "state.yaml" in data
        # Initial state has turn: 0
        assert "turn: 0" in data["state.yaml"]

    def test_peek_at_specific_turn(self, save_path: Path):
        """peek_at_turn(N) returns state at turn N."""
        for i in range(1, 4):
            _make_turn(save_path, i)
        data = peek_at_turn(save_path, 2)
        assert "state.yaml" in data
        assert "turn: 2" in data["state.yaml"]

    def test_peek_does_not_modify_head(self, save_path: Path):
        """peek_at_turn does not change the working directory or HEAD."""
        for i in range(1, 4):
            _make_turn(save_path, i)
        peek_at_turn(save_path, 1)
        # HEAD should still be at turn 3
        assert get_turn_count(save_path) == 3
        game = load_save(save_path.name, save_path.parent)
        assert game.state.turn == 3

    def test_peek_includes_memory_files(self, save_path: Path):
        """peek_at_turn returns memory files if they existed at that turn."""
        _make_turn(save_path, 1)
        _make_turn_with_memory(save_path, 2)
        data = peek_at_turn(save_path, 2)
        assert any(k.startswith("memory/") for k in data)

    def test_peek_invalid_turn_raises(self, save_path: Path):
        """peek_at_turn raises ValueError for nonexistent turn."""
        _make_turn(save_path, 1)
        with pytest.raises(ValueError, match="not found"):
            peek_at_turn(save_path, 99)

    def test_peek_returns_conversation(self, save_path: Path):
        """peek_at_turn includes conversation.yaml content."""
        _make_turn(save_path, 1)
        _make_turn(save_path, 2)
        data = peek_at_turn(save_path, 1)
        assert "conversation.yaml" in data


class TestDiffTurns:
    def test_diff_shows_state_changes(self, save_path: Path):
        """diff_turns shows changes to state.yaml between turns."""
        for i in range(1, 4):
            _make_turn(save_path, i)
        diff = diff_turns(save_path, 1, 3)
        assert "state.yaml" in diff
        # Should show turn number change
        assert "-turn: 1" in diff or "+turn: 3" in diff

    def test_diff_from_initial(self, save_path: Path):
        """diff_turns(0, N) shows changes from initial state."""
        _make_turn(save_path, 1)
        diff = diff_turns(save_path, 0, 1)
        assert "state.yaml" in diff

    def test_diff_same_turn_empty(self, save_path: Path):
        """diff_turns(N, N) returns empty string."""
        _make_turn(save_path, 1)
        diff = diff_turns(save_path, 1, 1)
        assert diff == ""

    def test_diff_invalid_turn_raises(self, save_path: Path):
        """diff_turns raises ValueError for nonexistent turn."""
        _make_turn(save_path, 1)
        with pytest.raises(ValueError, match="not found"):
            diff_turns(save_path, 1, 99)
```

**Test helpers** (`_make_turn`, `_make_turn_with_memory`) follow the same pattern as `TestUndo._make_turns` in `test_git_save.py`.

---

## 4. Part B: Turn Debugger Architecture

### 4.1 Core Data Structures

**File:** `src/theact/debugger/types.py`

```python
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class AgentResult:
    """Result of a single agent call during debugging."""

    agent: str                          # e.g. "narrator", "character:maya", "memory:maya", "game_state"
    messages: list[dict[str, str]]      # the prompt messages sent to the model
    raw_response: str                   # full raw response text (including thinking)
    thinking: str                       # thinking/reasoning content
    content: str                        # actual response content
    parsed_data: dict[str, Any] | None  # parsed YAML data (None for unstructured agents)
    prompt_tokens: int                  # estimated tokens in prompt
    thinking_tokens: int                # estimated tokens in thinking
    content_tokens: int                 # estimated tokens in content
    latency_ms: int                     # wall-clock time for the call
    finish_reason: str                  # "stop", "length", or "error"
    parse_success: bool                 # True if YAML parsed on first attempt
    parse_attempts: int                 # total parse attempts (1 = first try worked)


@dataclass
class DebugStep:
    """One step in the debugger's execution history."""

    agent: str
    result: AgentResult
    skipped: bool = False


@dataclass
class DebugSession:
    """Full state of a debugging session."""

    game_id: str
    save_id: str
    player_input: str
    steps: list[DebugStep] = field(default_factory=list)
    history: dict[str, list[AgentResult]] = field(default_factory=dict)
    # Intermediate state built up as agents run
    narrator_output: Any = None         # NarratorOutput once narrator completes
    character_responses: list[Any] = field(default_factory=list)  # CharacterResponse list
```

### 4.2 TurnDebugger Class

**File:** `src/theact/debugger/debugger.py`

```python
"""Interactive turn debugger for prompt iteration."""

from __future__ import annotations

import importlib
import time
from pathlib import Path
from typing import Any

from theact.agents import character, game_state, memory, narrator
from theact.agents import prompts
from theact.debugger.types import AgentResult, DebugSession, DebugStep
from theact.engine.context import (
    build_character_messages,
    build_game_state_messages,
    build_memory_messages,
    build_narrator_messages,
)
from theact.engine.types import (
    CharacterResponse,
    GameStateResult,
    NarratorOutput,
)
from theact.io.save_manager import load_save
from theact.llm.config import (
    CHARACTER_CONFIG,
    GAME_STATE_CONFIG,
    LLMConfig,
    MEMORY_UPDATE_CONFIG,
    NARRATOR_CONFIG,
    load_llm_config,
)
from theact.llm.tokens import estimate_tokens


class TurnDebugger:
    """Interactive turn debugger.

    Runs agents one at a time, pausing between each for user inspection.
    Stores full prompt/response data for every call, enabling replay,
    comparison, and fixture capture.
    """

    def __init__(
        self,
        game_id: str,
        save_id: str,
        player_input: str,
        llm_config: LLMConfig | None = None,
        saves_dir: Path | None = None,
    ):
        self.session = DebugSession(
            game_id=game_id,
            save_id=save_id,
            player_input=player_input,
        )
        self.game = load_save(save_id, saves_dir=saves_dir)
        self.llm_config = llm_config or load_llm_config()
        self.pending: list[str] = []  # Agent names still to run

    def plan_turn(self) -> list[str]:
        """Plan the agent execution order for this turn.

        Returns the list of agent names that will run, in order.
        Must be called before stepping through agents.
        The narrator always runs first. Character agents depend on
        narrator output (responding_characters). Post-turn agents
        (memory, game_state) run after all characters.
        """
        self.pending = ["narrator"]
        # Characters and post-turn agents are added after narrator completes
        return list(self.pending)

    async def step(self) -> DebugStep:
        """Execute the next pending agent and return its result."""
        if not self.pending:
            raise StopIteration("No more agents to run.")

        agent_name = self.pending.pop(0)
        result = await self._run_agent(agent_name)
        step = DebugStep(agent=agent_name, result=result)
        self.session.steps.append(step)
        self.session.history.setdefault(agent_name, []).append(result)

        # After narrator completes, populate the pending queue
        if agent_name == "narrator" and self.session.narrator_output:
            for char_id in self.session.narrator_output.responding_characters:
                if char_id in self.game.characters:
                    self.pending.append(f"character:{char_id}")
            # Post-turn agents go after all characters
            for char_id in self.session.narrator_output.responding_characters:
                if char_id in self.game.characters:
                    self.pending.append(f"memory:{char_id}")
            self.pending.append("game_state")

        return step

    def skip(self) -> str | None:
        """Skip the next pending agent. Returns the skipped agent name."""
        if not self.pending:
            return None
        skipped = self.pending.pop(0)
        step = DebugStep(
            agent=skipped,
            result=AgentResult(
                agent=skipped, messages=[], raw_response="",
                thinking="", content="(skipped)", parsed_data=None,
                prompt_tokens=0, thinking_tokens=0, content_tokens=0,
                latency_ms=0, finish_reason="skipped",
                parse_success=True, parse_attempts=0,
            ),
            skipped=True,
        )
        self.session.steps.append(step)
        return skipped

    async def replay(self, agent_name: str) -> DebugStep:
        """Re-run an agent with the same prompt (fresh model call)."""
        result = await self._run_agent(agent_name)
        step = DebugStep(agent=agent_name, result=result)
        self.session.history.setdefault(agent_name, []).append(result)
        return step

    async def edit_and_replay(self, agent_name: str) -> DebugStep:
        """Reload prompts.py and context.py from disk, then replay the agent.

        Note: context.py uses `from theact.agents.prompts import ...` which
        copies values at import time. Reloading prompts alone won't propagate
        changes to the context builders -- context must be reloaded too.
        """
        importlib.reload(prompts)
        from theact.engine import context
        importlib.reload(context)
        return await self.replay(agent_name)

    def inspect(self, agent_name: str, field: str = "all") -> str:
        """Return formatted inspection of an agent's last result."""
        runs = self.session.history.get(agent_name, [])
        if not runs:
            return f"No results for agent '{agent_name}'."
        result = runs[-1]
        return _format_inspection(result, field)

    def compare(self, agent_name: str) -> str:
        """Side-by-side diff of the last two runs of an agent."""
        runs = self.session.history.get(agent_name, [])
        if len(runs) < 2:
            return f"Need at least 2 runs of '{agent_name}' to compare."
        return _format_comparison(runs[-2], runs[-1])

    def capture_fixture(self, agent_name: str, fixture_name: str) -> Path:
        """Save the last agent result as a YAML test fixture."""
        runs = self.session.history.get(agent_name, [])
        if not runs:
            raise ValueError(f"No results for agent '{agent_name}'.")
        result = runs[-1]
        return _save_fixture(result, fixture_name)

    def get_pending(self) -> list[str]:
        """Return the remaining agents to run."""
        return list(self.pending)

    async def run_remaining(self) -> list[DebugStep]:
        """Run all remaining agents without stopping."""
        steps = []
        while self.pending:
            step = await self.step()
            steps.append(step)
        return steps

    # --- Private agent runners ---

    async def _run_agent(self, agent_name: str) -> AgentResult:
        """Run a single agent and capture full diagnostics."""
        if agent_name == "narrator":
            return await self._run_narrator()
        elif agent_name.startswith("character:"):
            char_id = agent_name.split(":", 1)[1]
            return await self._run_character(char_id)
        elif agent_name.startswith("memory:"):
            char_id = agent_name.split(":", 1)[1]
            return await self._run_memory(char_id)
        elif agent_name == "game_state":
            return await self._run_game_state()
        else:
            raise ValueError(f"Unknown agent: {agent_name}")

    async def _run_narrator(self) -> AgentResult:
        """Run narrator agent with full instrumentation."""
        messages = build_narrator_messages(
            self.game, self.session.player_input, self.llm_config
        )
        prompt_tokens = sum(estimate_tokens(m.get("content", "")) for m in messages)

        start = time.monotonic()
        narrator_output = await narrator.run_narrator(
            self.game, self.session.player_input, self.llm_config
        )
        latency_ms = int((time.monotonic() - start) * 1000)

        self.session.narrator_output = narrator_output

        return AgentResult(
            agent="narrator",
            messages=messages,
            raw_response=narrator_output.narration,
            thinking="",  # not captured in current narrator agent
            content=narrator_output.narration,
            parsed_data={
                "narration": narrator_output.narration,
                "responding_characters": narrator_output.responding_characters,
                "mood": narrator_output.mood,
            },
            prompt_tokens=prompt_tokens,
            thinking_tokens=0,
            content_tokens=estimate_tokens(narrator_output.narration),
            latency_ms=latency_ms,
            finish_reason="stop",
            parse_success=True,
            parse_attempts=1,
        )

    async def _run_character(self, char_id: str) -> AgentResult:
        """Run character agent with full instrumentation."""
        char = self.game.characters[char_id]
        char_memory = self.game.memories.get(char_id)

        messages = build_character_messages(
            game=self.game,
            character=char,
            memory=char_memory,
            player_input=self.session.player_input,
            narrator_output=self.session.narrator_output,
            prior_responses=self.session.character_responses,
            llm_config=self.llm_config,
        )
        prompt_tokens = sum(estimate_tokens(m.get("content", "")) for m in messages)

        start = time.monotonic()
        response = await character.run_character(
            game=self.game,
            character=char,
            memory=char_memory,
            player_input=self.session.player_input,
            narrator_output=self.session.narrator_output,
            prior_responses=self.session.character_responses,
            llm_config=self.llm_config,
        )
        latency_ms = int((time.monotonic() - start) * 1000)

        self.session.character_responses.append(response)

        return AgentResult(
            agent=f"character:{char_id}",
            messages=messages,
            raw_response=response.response,
            thinking=response.thinking or "",
            content=response.response,
            parsed_data=None,  # character agent is unstructured
            prompt_tokens=prompt_tokens,
            thinking_tokens=estimate_tokens(response.thinking or ""),
            content_tokens=estimate_tokens(response.response),
            latency_ms=latency_ms,
            finish_reason="stop",
            parse_success=True,
            parse_attempts=1,
        )

    async def _run_memory(self, char_id: str) -> AgentResult:
        """Run memory update agent with full instrumentation."""
        char = self.game.characters[char_id]
        char_memory = self.game.memories.get(char_id)

        # Build the conversation entries for this turn (from session steps)
        turn_entries = _extract_turn_entries(self.session)

        messages = build_memory_messages(char, char_memory, turn_entries)
        prompt_tokens = sum(estimate_tokens(m.get("content", "")) for m in messages)

        start = time.monotonic()
        diff = await memory.run_memory_update(
            char, char_memory, turn_entries, self.llm_config
        )
        latency_ms = int((time.monotonic() - start) * 1000)

        return AgentResult(
            agent=f"memory:{char_id}",
            messages=messages,
            raw_response="",
            thinking="",
            content=diff.new_summary,
            parsed_data={
                "old_summary": diff.old_summary,
                "new_summary": diff.new_summary,
                "old_facts": diff.old_facts,
                "new_facts": diff.new_facts,
            },
            prompt_tokens=prompt_tokens,
            thinking_tokens=0,
            content_tokens=estimate_tokens(diff.new_summary),
            latency_ms=latency_ms,
            finish_reason="stop",
            parse_success=True,
            parse_attempts=1,
        )

    async def _run_game_state(self) -> AgentResult:
        """Run game state check agent with full instrumentation."""
        turn_entries = _extract_turn_entries(self.session)
        messages = build_game_state_messages(self.game, turn_entries)
        prompt_tokens = sum(
            estimate_tokens(m.get("content", "")) for m in messages
        ) if messages else 0

        start = time.monotonic()
        gs_result = await game_state.run_game_state(
            self.game, turn_entries, self.llm_config
        )
        latency_ms = int((time.monotonic() - start) * 1000)

        return AgentResult(
            agent="game_state",
            messages=messages or [],
            raw_response="",
            thinking="",
            content=gs_result.reasoning or "",
            parsed_data={
                "beats_hit": gs_result.beats_hit,
                "completed": gs_result.completed,
                "reasoning": gs_result.reasoning,
            },
            prompt_tokens=prompt_tokens,
            thinking_tokens=0,
            content_tokens=estimate_tokens(gs_result.reasoning or ""),
            latency_ms=latency_ms,
            finish_reason="stop",
            parse_success=True,
            parse_attempts=1,
        )
```

### 4.3 Helper Functions

**File:** `src/theact/debugger/helpers.py`

```python
"""Helper functions for the turn debugger."""

from __future__ import annotations

import difflib
from pathlib import Path

import yaml

from theact.debugger.types import AgentResult, DebugSession
from theact.llm.tokens import estimate_tokens
from theact.models.conversation import ConversationEntry


def _extract_turn_entries(session: DebugSession) -> list[ConversationEntry]:
    """Build ConversationEntry list from the debugger's completed steps.

    Mirrors the entries list built by run_turn() in the turn engine.
    """
    new_turn = (
        session.steps[0].result.parsed_data.get("narration", "")
        if session.steps
        else ""
    )
    entries: list[ConversationEntry] = []

    # Find narrator step
    for step in session.steps:
        if step.agent == "narrator" and not step.skipped:
            entries.append(
                ConversationEntry(
                    turn=session.game.state.turn,
                    role="narrator",
                    content=step.result.content,
                )
            )
            break

    # Player entry
    turn = session.game.state.turn
    entries.append(
        ConversationEntry(
            turn=turn,
            role="player",
            content=session.player_input,
        )
    )

    # Character entries
    for step in session.steps:
        if step.agent.startswith("character:") and not step.skipped:
            entries.append(
                ConversationEntry(
                    turn=turn,
                    role="character",
                    character=step.agent.split(":", 1)[1],
                    content=step.result.content,
                )
            )

    return entries


def _format_inspection(result: AgentResult, field: str = "all") -> str:
    """Format an AgentResult for display."""
    sections = []

    if field in ("all", "prompt"):
        sections.append("=== PROMPT ===")
        for msg in result.messages:
            role = msg.get("role", "?")
            content = msg.get("content", "")
            tokens = estimate_tokens(content)
            sections.append(f"[{role}] ({tokens} tokens)")
            sections.append(content)
            sections.append("")

    if field in ("all", "response"):
        sections.append("=== RESPONSE ===")
        if result.thinking:
            sections.append(f"[thinking] ({result.thinking_tokens} tokens)")
            sections.append(result.thinking[:500])
            if len(result.thinking) > 500:
                sections.append(f"... ({len(result.thinking)} chars total)")
            sections.append("")
        sections.append(f"[content] ({result.content_tokens} tokens)")
        sections.append(result.content)
        sections.append("")

    if field in ("all", "parsed"):
        sections.append("=== PARSED DATA ===")
        if result.parsed_data:
            sections.append(yaml.dump(result.parsed_data, default_flow_style=False))
        else:
            sections.append("(no structured data)")
        sections.append("")

    if field in ("all", "stats"):
        sections.append("=== STATS ===")
        sections.append(f"Prompt tokens:   {result.prompt_tokens}")
        sections.append(f"Thinking tokens: {result.thinking_tokens}")
        sections.append(f"Content tokens:  {result.content_tokens}")
        sections.append(f"Latency:         {result.latency_ms}ms")
        sections.append(f"Finish reason:   {result.finish_reason}")
        sections.append(f"Parse success:   {result.parse_success}")
        sections.append(f"Parse attempts:  {result.parse_attempts}")
        sections.append("")

    return "\n".join(sections)


def _format_comparison(a: AgentResult, b: AgentResult) -> str:
    """Show a word-level diff between two agent results."""
    lines_a = a.content.splitlines()
    lines_b = b.content.splitlines()

    diff = difflib.unified_diff(
        lines_a, lines_b,
        fromfile=f"run {1} ({a.latency_ms}ms)",
        tofile=f"run {2} ({b.latency_ms}ms)",
        lineterm="",
    )
    diff_text = "\n".join(diff)

    # Add stats comparison
    stats = [
        "",
        "=== STATS COMPARISON ===",
        f"{'Metric':<20} {'Run 1':>10} {'Run 2':>10} {'Delta':>10}",
        f"{'Prompt tokens':<20} {a.prompt_tokens:>10} {b.prompt_tokens:>10} {b.prompt_tokens - a.prompt_tokens:>+10}",
        f"{'Thinking tokens':<20} {a.thinking_tokens:>10} {b.thinking_tokens:>10} {b.thinking_tokens - a.thinking_tokens:>+10}",
        f"{'Content tokens':<20} {a.content_tokens:>10} {b.content_tokens:>10} {b.content_tokens - a.content_tokens:>+10}",
        f"{'Latency (ms)':<20} {a.latency_ms:>10} {b.latency_ms:>10} {b.latency_ms - a.latency_ms:>+10}",
    ]

    return diff_text + "\n".join(stats)


def _save_fixture(result: AgentResult, fixture_name: str) -> Path:
    """Save an AgentResult as a YAML fixture file."""
    fixture_dir = Path("tests/fixtures")
    fixture_dir.mkdir(parents=True, exist_ok=True)

    fixture_path = fixture_dir / f"{fixture_name}.yaml"

    data = {
        "agent": result.agent,
        "messages": result.messages,
        "raw_response": result.raw_response,
        "thinking": result.thinking,
        "content": result.content,
        "parsed_data": result.parsed_data,
        "prompt_tokens": result.prompt_tokens,
        "thinking_tokens": result.thinking_tokens,
        "content_tokens": result.content_tokens,
        "finish_reason": result.finish_reason,
        "parse_success": result.parse_success,
        "parse_attempts": result.parse_attempts,
    }

    with open(fixture_path, "w") as f:
        yaml.dump(data, f, default_flow_style=False, allow_unicode=True)

    return fixture_path
```

---

## 5. Interactive Debugger Script

### 5.1 Script Entry Point

**File:** `scripts/debug_turn.py`

```python
#!/usr/bin/env python
"""Interactive turn debugger for prompt iteration.

Usage:
    # Step through a single turn interactively
    uv run python scripts/debug_turn.py --game lost-island --save debug-001 --input "I look for survivors"

    # Replay mode: walk through a saved game's history (no API calls)
    uv run python scripts/debug_turn.py --replay --save my-save

    # Step through using an existing save without creating a new one
    uv run python scripts/debug_turn.py --save existing-save --input "I search the wreckage"
"""

import argparse
import asyncio
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from dotenv import load_dotenv
load_dotenv()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Interactive turn debugger")
    parser.add_argument("--game", help="Game ID (e.g. lost-island)")
    parser.add_argument("--save", required=True, help="Save ID to use or create")
    parser.add_argument("--input", help="Player input for the turn")
    parser.add_argument("--replay", action="store_true", help="Replay mode: walk through git history")
    parser.add_argument("--saves-dir", type=Path, default=None, help="Override saves directory")
    parser.add_argument("--games-dir", type=Path, default=None, help="Override games directory")
    return parser.parse_args()


async def run_interactive(args: argparse.Namespace) -> None:
    """Run the interactive step-through debugger."""
    from theact.debugger.debugger import TurnDebugger
    from theact.io.save_manager import create_save, load_save
    from theact.llm.config import load_llm_config

    saves_dir = args.saves_dir
    games_dir = args.games_dir

    # Create save if it doesn't exist
    save_path = (saves_dir or Path("saves")) / args.save
    if not save_path.exists():
        if not args.game:
            print("Error: --game is required when the save does not exist.")
            sys.exit(1)
        create_save(
            args.game, args.save, "Debugger",
            games_dir=games_dir, saves_dir=saves_dir,
        )
        print(f"Created save: {args.save}")

    player_input = args.input or input("Player input> ")

    debugger = TurnDebugger(
        game_id=args.game or "",
        save_id=args.save,
        player_input=player_input,
        saves_dir=saves_dir,
    )
    debugger.plan_turn()

    print(f"\nDebugging turn for: \"{player_input}\"")
    print(f"Agents planned: {debugger.get_pending()}")
    print()

    while debugger.get_pending():
        next_agent = debugger.get_pending()[0]
        total = len(debugger.session.steps) + len(debugger.get_pending())
        current = len(debugger.session.steps) + 1
        print(f"[{current}/{total}] {next_agent.upper()}")

        action = input("  [s]tep  [r]eplay  [e]dit  [i]nspect  [k]skip  [c]ontinue all  [q]uit > ").strip().lower()

        if action in ("s", "step", ""):
            step = await debugger.step()
            _print_step_summary(step)

        elif action in ("r", "replay"):
            # Replay the last completed agent
            last_agents = list(debugger.session.history.keys())
            if last_agents:
                agent = last_agents[-1]
                print(f"  Replaying {agent}...")
                step = await debugger.replay(agent)
                _print_step_summary(step)
            else:
                print("  No agent to replay yet. Step first.")

        elif action in ("e", "edit"):
            last_agents = list(debugger.session.history.keys())
            if last_agents:
                agent = last_agents[-1]
                print("  Reloading prompts.py...")
                step = await debugger.edit_and_replay(agent)
                _print_step_summary(step)
            else:
                print("  No agent to edit-replay yet. Step first.")

        elif action in ("i", "inspect"):
            last_agents = list(debugger.session.history.keys())
            if last_agents:
                agent = last_agents[-1]
                sub = input("  Inspect [a]ll [p]rompt [r]esponse [d]ata [s]tats > ").strip().lower()
                field_map = {"a": "all", "p": "prompt", "r": "response", "d": "parsed", "s": "stats"}
                field = field_map.get(sub, "all")
                print(debugger.inspect(agent, field))
            else:
                print("  No agent to inspect yet. Step first.")

        elif action in ("k", "skip"):
            skipped = debugger.skip()
            print(f"  Skipped: {skipped}")

        elif action in ("c", "continue"):
            print("  Running all remaining agents...")
            steps = await debugger.run_remaining()
            for s in steps:
                _print_step_summary(s)

        elif action in ("q", "quit"):
            print("Exiting debugger.")
            return

        # After step, offer capture
        if action in ("s", "step", "") and debugger.session.steps:
            last = debugger.session.steps[-1]
            cap = input("  [f]ixture  [m]compare  [enter] continue > ").strip().lower()
            if cap in ("f", "fixture"):
                name = input("  Fixture name> ").strip()
                if name:
                    path = debugger.capture_fixture(last.agent, name)
                    print(f"  Saved to: {path}")
            elif cap in ("m", "compare"):
                print(debugger.compare(last.agent))

    print("\nAll agents complete.")


def run_replay(args: argparse.Namespace) -> None:
    """Replay mode: walk through git history showing conversation at each turn."""
    from theact.versioning.git_save import get_history, peek_at_turn

    import yaml

    saves_dir = args.saves_dir or Path("saves")
    save_path = saves_dir / args.save

    if not save_path.exists():
        print(f"Error: Save '{args.save}' not found at {save_path}")
        sys.exit(1)

    history = get_history(save_path)
    if not history:
        print("No turn history in this save.")
        return

    # Sort by turn number (ascending)
    history.sort(key=lambda h: h.turn)

    current_idx = 0
    while True:
        entry = history[current_idx]
        data = peek_at_turn(save_path, entry.turn)

        print(f"\n{'='*60}")
        print(f"Turn {entry.turn}: {entry.message}")
        print(f"{'='*60}")

        # Parse and display conversation
        if "conversation.yaml" in data:
            try:
                entries = yaml.safe_load(data["conversation.yaml"])
                if entries:
                    # Show only this turn's entries
                    turn_entries = [e for e in entries if e.get("turn") == entry.turn]
                    for e in turn_entries:
                        role = e.get("role", "?")
                        char = e.get("character", "")
                        content = e.get("content", "")
                        if role == "narrator":
                            print(f"  Narrator: {content[:300]}...")
                        elif role == "player":
                            print(f"  Player: {content}")
                        elif role == "character":
                            print(f"  {char}: {content[:200]}")
            except Exception:
                print("  (could not parse conversation)")

        # Show state summary
        if "state.yaml" in data:
            try:
                state = yaml.safe_load(data["state.yaml"])
                beats = state.get("beats_hit", [])
                chapter = state.get("current_chapter", "?")
                print(f"\n  Chapter: {chapter} | Beats: {len(beats)}")
            except Exception:
                pass

        print()
        action = input(
            f"[enter] next  [p]rev  [N] jump to turn  [d]iff  [i]nspect  [q]uit > "
        ).strip().lower()

        if action == "" or action == "n":
            if current_idx < len(history) - 1:
                current_idx += 1
            else:
                print("  (last turn)")
        elif action == "p":
            if current_idx > 0:
                current_idx -= 1
            else:
                print("  (first turn)")
        elif action == "d":
            # Diff with previous turn
            if current_idx > 0:
                from theact.versioning.git_save import diff_turns
                prev_turn = history[current_idx - 1].turn
                curr_turn = history[current_idx].turn
                diff = diff_turns(save_path, prev_turn, curr_turn)
                print(diff[:2000] if len(diff) > 2000 else diff)
            else:
                print("  (no previous turn to diff against)")
        elif action == "i":
            # Full state inspection
            for fname, content in sorted(data.items()):
                print(f"\n--- {fname} ---")
                print(content[:1000])
                if len(content) > 1000:
                    print(f"... ({len(content)} chars total)")
        elif action == "q":
            return
        elif action.isdigit():
            target = int(action)
            matches = [i for i, h in enumerate(history) if h.turn == target]
            if matches:
                current_idx = matches[0]
            else:
                print(f"  Turn {target} not found.")


def _print_step_summary(step) -> None:
    """Print a one-line summary of a completed step."""
    r = step.result
    print(f"  Prompt: {r.prompt_tokens} tokens")
    print(f"  Thinking: {r.thinking_tokens} tokens")
    print(f"  Content: {r.content_tokens} tokens ({r.latency_ms / 1000:.1f}s)")
    if r.parsed_data:
        for key, val in r.parsed_data.items():
            if isinstance(val, list):
                print(f"  {key}: {val}")
            elif isinstance(val, str) and len(val) > 80:
                print(f"  {key}: {val[:80]}...")
            else:
                print(f"  {key}: {val}")
    if r.finish_reason != "stop":
        print(f"  WARNING: finish_reason={r.finish_reason}")
    print()


def main():
    args = parse_args()
    if args.replay:
        run_replay(args)
    else:
        asyncio.run(run_interactive(args))


if __name__ == "__main__":
    main()
```

---

## 6. Module Layout

### 6.1 New Files

```
src/theact/debugger/
    __init__.py             # Empty or re-exports TurnDebugger
    types.py                # AgentResult, DebugStep, DebugSession dataclasses
    debugger.py             # TurnDebugger class
    helpers.py              # _format_inspection, _format_comparison, _save_fixture, _extract_turn_entries

scripts/
    debug_turn.py           # Interactive CLI script (Section 5)

tests/
    test_save_versioning.py # Tests for save_as, peek_at_turn, diff_turns (Section 3)
    test_debugger.py        # Tests for TurnDebugger internals (Section 7)
```

### 6.2 Modified Files

```
src/theact/versioning/git_save.py  # Add save_as, peek_at_turn, diff_turns
src/theact/cli/commands.py         # Add /save-as command
src/theact/cli/session.py          # Wire /save-as dispatch
src/theact/web/commands.py         # Add /save-as for web UI
```

---

## 7. Debugger Tests

**File:** `tests/test_debugger.py`

The debugger makes real LLM calls, so full integration tests require `VENICE_API_KEY`. Unit tests verify the non-LLM parts: session planning, step tracking, fixture saving, comparison formatting.

### 7.1 Unit Tests (No LLM Calls)

```python
class TestDebugSession:
    def test_extract_turn_entries_empty(self):
        """_extract_turn_entries returns player entry even with no steps."""
        session = DebugSession(game_id="test", save_id="test", player_input="hello")
        entries = _extract_turn_entries(session)
        assert len(entries) == 1
        assert entries[0].role == "player"

    def test_format_inspection_all(self):
        """_format_inspection includes all sections when field='all'."""
        result = _make_mock_result()
        text = _format_inspection(result, "all")
        assert "PROMPT" in text
        assert "RESPONSE" in text
        assert "PARSED DATA" in text
        assert "STATS" in text

    def test_format_inspection_prompt_only(self):
        """_format_inspection shows only prompt when field='prompt'."""
        result = _make_mock_result()
        text = _format_inspection(result, "prompt")
        assert "PROMPT" in text
        assert "STATS" not in text

    def test_format_comparison(self):
        """_format_comparison shows diff and stats."""
        a = _make_mock_result(content="The sun rises over the ocean.")
        b = _make_mock_result(content="The moon hangs over the dark ocean.")
        text = _format_comparison(a, b)
        assert "STATS COMPARISON" in text
        assert "Delta" in text

    def test_save_fixture_creates_file(self, tmp_path):
        """_save_fixture writes a YAML file."""
        result = _make_mock_result()
        # Patch fixture_dir
        path = _save_fixture(result, "test_fixture")
        assert path.exists()
        assert path.suffix == ".yaml"


class TestTurnDebuggerPlan:
    def test_plan_starts_with_narrator(self):
        """plan_turn always starts with narrator."""
        # This test requires a valid save, use a fixture
        # Just test that plan_turn sets pending correctly
        debugger = _make_debugger_with_mock_save()
        agents = debugger.plan_turn()
        assert agents == ["narrator"]

    def test_skip_removes_from_pending(self):
        """skip() pops the first pending agent."""
        debugger = _make_debugger_with_mock_save()
        debugger.plan_turn()
        skipped = debugger.skip()
        assert skipped == "narrator"
        assert debugger.get_pending() == []

    def test_get_pending_returns_copy(self):
        """get_pending returns a copy, not the internal list."""
        debugger = _make_debugger_with_mock_save()
        debugger.plan_turn()
        pending = debugger.get_pending()
        pending.clear()
        assert debugger.get_pending() == ["narrator"]
```

### 7.2 Integration Tests (Requires LLM)

These tests are marked with `@pytest.mark.skipif` if `VENICE_API_KEY` is not set. They verify the full debugger workflow against the live model.

```python
@pytest.mark.skipif(
    not os.environ.get("VENICE_API_KEY"),
    reason="Requires VENICE_API_KEY",
)
class TestTurnDebuggerIntegration:
    @pytest.fixture
    def debugger(self, games_dir, saves_dir):
        save_path = create_save(
            "lost-island", "debug-test", "Tester",
            games_dir=games_dir, saves_dir=saves_dir,
        )
        return TurnDebugger(
            game_id="lost-island",
            save_id="debug-test",
            player_input="I open my eyes.",
            saves_dir=saves_dir,
        )

    async def test_step_through_narrator(self, debugger):
        """Step through narrator agent and get a result."""
        debugger.plan_turn()
        step = await debugger.step()
        assert step.agent == "narrator"
        assert step.result.content  # non-empty narration
        assert step.result.latency_ms > 0
        # After narrator, pending should include characters and post-turn
        assert len(debugger.get_pending()) > 0

    async def test_replay_produces_different_result(self, debugger):
        """Replay the same agent and verify we get a fresh result."""
        debugger.plan_turn()
        step1 = await debugger.step()
        step2 = await debugger.replay("narrator")
        # Results should exist (content may or may not differ)
        assert step2.result.content
        # History should have 2 entries
        assert len(debugger.session.history["narrator"]) == 2

    async def test_capture_fixture(self, debugger, tmp_path):
        """Capture a fixture after running narrator."""
        debugger.plan_turn()
        await debugger.step()
        path = debugger.capture_fixture("narrator", "test_capture")
        assert path.exists()
```

---

## 8. Implementation Steps

### Step 1: Save Versioning Functions

1. Add `import shutil` to `src/theact/versioning/git_save.py`.
2. Implement `save_as()` as specified in Section 2.1.
3. Implement `peek_at_turn()` as specified in Section 2.2.
4. Implement `diff_turns()` as specified in Section 2.3.
5. Write tests in `tests/test_save_versioning.py` (Section 3).
6. Run `uv run pytest tests/test_save_versioning.py -v`.

### Step 2: CLI and Web UI Integration

1. Add `/save-as` to `COMMANDS` dict in `src/theact/cli/commands.py`.
2. Implement `cmd_save_as()` in `src/theact/cli/commands.py`.
3. Wire `/save-as` dispatch in `src/theact/cli/session.py`.
4. Implement `cmd_save_as_web()` in `src/theact/web/commands.py`.
5. Update `COMMANDS_HELP` HTML table in `src/theact/web/commands.py`.
6. Wire `/save-as` dispatch in the web session handler.
7. Test manually by running the CLI and web UI.

### Step 3: Debugger Data Types

1. Create `src/theact/debugger/__init__.py`.
2. Create `src/theact/debugger/types.py` with `AgentResult`, `DebugStep`, `DebugSession` (Section 4.1).
3. Create `src/theact/debugger/helpers.py` with helper functions (Section 4.3).

### Step 4: TurnDebugger Class

1. Create `src/theact/debugger/debugger.py` with `TurnDebugger` (Section 4.2).
2. Implement `plan_turn()`, `step()`, `skip()`, `replay()`, `edit_and_replay()`, `inspect()`, `compare()`, `capture_fixture()`, `run_remaining()`.
3. Implement private agent runners: `_run_narrator()`, `_run_character()`, `_run_memory()`, `_run_game_state()`.
4. Write unit tests in `tests/test_debugger.py` (Section 7.1).
5. Run `uv run pytest tests/test_debugger.py -v`.

### Step 5: Debug Script

1. Create `scripts/debug_turn.py` (Section 5.1).
2. Implement interactive mode with the step/replay/edit/inspect/skip/continue/quit command loop.
3. Implement replay mode using `peek_at_turn()` and `get_history()`.
4. Test manually:
   ```bash
   uv run python scripts/debug_turn.py --game lost-island --save debug-test --input "I open my eyes"
   uv run python scripts/debug_turn.py --replay --save debug-test
   ```

### Step 6: Final Verification

1. Run the full test suite: `uv run pytest tests/ -v`.
2. Run lint: `uv run prek run --all-files`.
3. Manual smoke test of the interactive debugger with the lost-island game.
4. Manual smoke test of replay mode on a save with several turns of history.
5. Verify `/save-as` works in both CLI and web UI.

---

## 9. Verification Criteria

### Part A: Save Versioning

- `save_as()` creates an independent copy with full git history.
- Changes to the fork do not affect the original (and vice versa).
- `peek_at_turn()` returns file contents at any historical turn without modifying HEAD.
- `diff_turns()` shows meaningful diffs between two turns.
- `/save-as` command works in both CLI and web UI.
- `list_saves()` includes forked saves.
- All tests in `test_save_versioning.py` pass.

### Part B: Turn Debugger

- `scripts/debug_turn.py` runs successfully with a live game save.
- The debugger steps through narrator, character, memory, and game state agents in order.
- `replay` re-runs an agent and shows (potentially different) output.
- `edit` reloads `prompts.py` from disk without restarting the script.
- `inspect` shows full prompt, response, parsed data, and stats.
- `compare` shows a diff between two runs of the same agent.
- `capture` saves a fixture file to `tests/fixtures/`.
- `skip` skips an agent and proceeds to the next.
- Replay mode walks through git history turn by turn without API calls.
- All unit tests in `test_debugger.py` pass.

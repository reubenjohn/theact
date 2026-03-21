"""Turn debugger: step through agents, replay, edit prompts, capture fixtures."""

from __future__ import annotations

import importlib
import time
from pathlib import Path

from theact.debugger.helpers import (
    _extract_turn_entries,
    _format_comparison,
    _format_inspection,
    _save_fixture,
)
from theact.debugger.types import AgentResult, DebugSession, DebugStep
from theact.io.save_manager import load_save
from theact.llm.config import LLMConfig
from theact.models.game import LoadedGame
from theact.llm.tokens import estimate_messages_tokens, estimate_tokens


class TurnDebugger:
    """Interactive turn debugger for prompt engineering.

    Wraps individual agent calls (does NOT modify run_turn). Allows
    stepping through agents one at a time, replaying with modified
    prompts, inspecting results, and capturing test fixtures.
    """

    def __init__(
        self,
        game_id: str,
        save_id: str,
        player_input: str,
        llm_config: LLMConfig | None = None,
        saves_dir: Path | None = None,
    ) -> None:
        self.game: LoadedGame = load_save(save_id, saves_dir=saves_dir)
        self.player_input = player_input
        self.llm_config = llm_config or LLMConfig()
        self.session = DebugSession(
            game_id=game_id,
            save_id=save_id,
            player_input=player_input,
        )
        self._pending: list[str] = []

    def plan_turn(self) -> list[str]:
        """Plan the initial turn steps. Always starts with narrator."""
        self._pending = ["narrator"]
        return list(self._pending)

    async def step(self) -> DebugStep:
        """Execute the next pending agent.

        After the narrator completes, populates pending with character
        agents, memory agents, and game_state based on the narrator's
        responding_characters list.

        Raises RuntimeError if no pending agents remain.
        """
        if not self._pending:
            raise RuntimeError("No pending agents")

        agent_name = self._pending.pop(0)
        result = await self._run_agent(agent_name)

        debug_step = DebugStep(agent=agent_name, result=result)
        self.session.steps.append(debug_step)

        # Track in history
        self.session.history.setdefault(agent_name, []).append(result)

        # After narrator: populate remaining agents
        if agent_name == "narrator" and self.session.narrator_output is not None:
            chars = self.session.narrator_output.responding_characters
            for char_id in chars:
                self._pending.append(f"character:{char_id}")
            for char_id in chars:
                self._pending.append(f"memory:{char_id}")
            self._pending.append("game_state")

        return debug_step

    def skip(self) -> str | None:
        """Skip the next pending agent. Returns the skipped agent name, or None."""
        if not self._pending:
            return None

        agent_name = self._pending.pop(0)

        # Create a skipped step with empty result
        empty_result = AgentResult(
            agent=agent_name,
            messages=[],
            raw_response="",
            thinking="",
            content="",
            parsed_data=None,
            prompt_tokens=0,
            thinking_tokens=0,
            content_tokens=0,
            latency_ms=0,
            finish_reason="skipped",
            parse_success=False,
            parse_attempts=0,
        )
        debug_step = DebugStep(agent=agent_name, result=empty_result, skipped=True)
        self.session.steps.append(debug_step)

        return agent_name

    async def replay(self, agent_name: str) -> DebugStep:
        """Re-run an agent with the same context. Appends to history, not steps."""
        result = await self._run_agent(agent_name)
        self.session.history.setdefault(agent_name, []).append(result)
        return DebugStep(agent=agent_name, result=result)

    async def edit_and_replay(self, agent_name: str) -> DebugStep:
        """Reload prompt and context modules, then replay the agent.

        CRITICAL: reloads both prompts.py AND context.py because context.py
        imports from prompts at module level.
        """
        import theact.agents.prompts as prompts_module
        import theact.engine.context as context_module

        importlib.reload(prompts_module)
        importlib.reload(context_module)

        return await self.replay(agent_name)

    def inspect(self, agent_name: str, field: str = "all") -> str:
        """Return formatted inspection of the last result for an agent."""
        history = self.session.history.get(agent_name, [])
        if not history:
            return f"No results for agent '{agent_name}'"
        return _format_inspection(history[-1], field)

    def compare(self, agent_name: str) -> str:
        """Diff the last two runs of an agent."""
        history = self.session.history.get(agent_name, [])
        if len(history) < 2:
            return f"Need at least 2 runs of '{agent_name}' to compare (have {len(history)})"
        return _format_comparison(history[-2], history[-1])

    def capture_fixture(self, agent_name: str, fixture_name: str) -> Path:
        """Save the last result for an agent as a test fixture."""
        history = self.session.history.get(agent_name, [])
        if not history:
            raise ValueError(f"No results for agent '{agent_name}'")
        return _save_fixture(history[-1], fixture_name)

    def get_pending(self) -> list[str]:
        """Return a copy of the pending agent list."""
        return list(self._pending)

    async def run_remaining(self) -> list[DebugStep]:
        """Run all remaining pending agents."""
        steps: list[DebugStep] = []
        while self._pending:
            step = await self.step()
            steps.append(step)
        return steps

    # ----- Private agent runners -----

    async def _run_agent(self, agent_name: str) -> AgentResult:
        """Dispatch to the correct agent runner."""
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
        """Run the narrator agent and capture results."""
        from theact.agents.narrator import run_narrator
        from theact.engine.context import build_narrator_messages

        messages = build_narrator_messages(
            self.game, self.player_input, self.llm_config
        )
        prompt_tokens = estimate_messages_tokens(messages)

        content_parts: list[str] = []

        async def capture_token(token: str, is_thinking: bool = False) -> None:
            if not is_thinking:
                content_parts.append(token)

        t0 = time.monotonic()
        narrator_output = await run_narrator(
            game=self.game,
            player_input=self.player_input,
            llm_config=self.llm_config,
            on_token=capture_token,
        )
        latency_ms = int((time.monotonic() - t0) * 1000)

        self.session.narrator_output = narrator_output

        raw_response = "".join(content_parts)
        content = narrator_output.narration

        parsed_data = {
            "narration": narrator_output.narration,
            "responding_characters": narrator_output.responding_characters,
            "mood": narrator_output.mood,
        }

        return AgentResult(
            agent="narrator",
            messages=messages,
            raw_response=raw_response,
            thinking="",
            content=content,
            parsed_data=parsed_data,
            prompt_tokens=prompt_tokens,
            thinking_tokens=0,
            content_tokens=estimate_tokens(content),
            latency_ms=latency_ms,
            finish_reason="stop",
            parse_success=True,
            parse_attempts=1,
        )

    async def _run_character(self, char_id: str) -> AgentResult:
        """Run a character agent and capture results."""
        from theact.agents.character import run_character
        from theact.engine.context import build_character_messages

        if self.session.narrator_output is None:
            raise RuntimeError("Cannot run character agent before narrator")

        character = self.game.characters.get(char_id)
        if character is None:
            raise ValueError(f"Character '{char_id}' not found in game")

        memory = self.game.memories.get(char_id)

        messages = build_character_messages(
            game=self.game,
            character=character,
            memory=memory,
            player_input=self.player_input,
            narrator_output=self.session.narrator_output,
            prior_responses=self.session.character_responses,
            llm_config=self.llm_config,
        )
        prompt_tokens = estimate_messages_tokens(messages)

        t0 = time.monotonic()
        char_response = await run_character(
            game=self.game,
            character=character,
            memory=memory,
            player_input=self.player_input,
            narrator_output=self.session.narrator_output,
            prior_responses=self.session.character_responses,
            llm_config=self.llm_config,
        )
        latency_ms = int((time.monotonic() - t0) * 1000)

        self.session.character_responses.append(char_response)

        return AgentResult(
            agent=f"character:{char_id}",
            messages=messages,
            raw_response=char_response.response,
            thinking=char_response.thinking or "",
            content=char_response.response,
            parsed_data=None,
            prompt_tokens=prompt_tokens,
            thinking_tokens=estimate_tokens(char_response.thinking or ""),
            content_tokens=estimate_tokens(char_response.response),
            latency_ms=latency_ms,
            finish_reason="stop",
            parse_success=True,
            parse_attempts=1,
        )

    async def _run_memory(self, char_id: str) -> AgentResult:
        """Run the memory update agent for a character."""
        from theact.agents.memory import run_memory_update
        from theact.engine.context import build_memory_messages

        character = self.game.characters.get(char_id)
        if character is None:
            raise ValueError(f"Character '{char_id}' not found in game")

        memory = self.game.memories.get(char_id)
        turn_entries = _extract_turn_entries(self.session)

        messages = build_memory_messages(character, memory, turn_entries)
        prompt_tokens = estimate_messages_tokens(messages)

        t0 = time.monotonic()
        memory_diff = await run_memory_update(
            character=character,
            memory=memory,
            turn_entries=turn_entries,
            llm_config=self.llm_config,
        )
        latency_ms = int((time.monotonic() - t0) * 1000)

        parsed_data = {
            "old_summary": memory_diff.old_summary,
            "new_summary": memory_diff.new_summary,
            "old_facts": memory_diff.old_facts,
            "new_facts": memory_diff.new_facts,
        }

        return AgentResult(
            agent=f"memory:{char_id}",
            messages=messages,
            raw_response=memory_diff.new_summary,
            thinking="",
            content=memory_diff.new_summary,
            parsed_data=parsed_data,
            prompt_tokens=prompt_tokens,
            thinking_tokens=0,
            content_tokens=estimate_tokens(memory_diff.new_summary),
            latency_ms=latency_ms,
            finish_reason="stop",
            parse_success=True,
            parse_attempts=1,
        )

    async def _run_game_state(self) -> AgentResult:
        """Run the game state check agent."""
        from theact.agents.game_state import run_game_state
        from theact.engine.context import build_game_state_messages

        turn_entries = _extract_turn_entries(self.session)

        messages = build_game_state_messages(self.game, turn_entries)
        prompt_tokens = estimate_messages_tokens(messages) if messages else 0

        t0 = time.monotonic()
        game_state_result = await run_game_state(
            game=self.game,
            turn_entries=turn_entries,
            llm_config=self.llm_config,
        )
        latency_ms = int((time.monotonic() - t0) * 1000)

        parsed_data = {
            "beats_hit": game_state_result.beats_hit,
            "completed": game_state_result.completed,
            "reasoning": game_state_result.reasoning,
        }

        reasoning_text = game_state_result.reasoning or ""

        return AgentResult(
            agent="game_state",
            messages=messages,
            raw_response=reasoning_text,
            thinking="",
            content=reasoning_text,
            parsed_data=parsed_data,
            prompt_tokens=prompt_tokens,
            thinking_tokens=0,
            content_tokens=estimate_tokens(reasoning_text),
            latency_ms=latency_ms,
            finish_reason="stop",
            parse_success=True,
            parse_attempts=1,
        )

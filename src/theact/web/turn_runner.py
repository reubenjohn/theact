"""Turn execution wrapper.

Calls engine.turn.run_turn() and processes the result. Does NOT
handle UI updates -- returns the TurnResult for the caller to render.
"""

from __future__ import annotations

from theact.engine.turn import StreamCallback, run_turn
from theact.engine.types import TurnResult
from theact.llm.call_log import LLMCallLog
from theact.web.state import GameSessionState


class TurnRunner:
    """Executes turns via the engine and returns results."""

    def __init__(self, state: GameSessionState) -> None:
        self._state = state
        self.call_log: LLMCallLog | None = None

    async def run(
        self,
        player_input: str,
        on_token: StreamCallback | None = None,
    ) -> TurnResult:
        """Run a turn and return the result.

        The caller is responsible for UI updates (streaming is handled
        via the on_token callback). After this returns, the caller
        should call state.reload_game() to get the persisted state.
        """
        return await run_turn(
            game=self._state.game,
            player_input=player_input,
            llm_config=self._state.llm_config,
            on_token=on_token,
            call_log=self.call_log,
            debug=self._state.debug_mode,
        )

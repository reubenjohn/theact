"""Freeform brainstorm conversation loop for exploring game ideas."""

from __future__ import annotations

from rich.console import Console

from openai import AsyncOpenAI

from theact.creator.config import CreatorLLMConfig
from theact.creator.generator import call_llm
from theact.creator.prompts import BRAINSTORM_SUMMARIZE_SYSTEM, BRAINSTORM_SYSTEM
from theact.llm.tokens import estimate_tokens

console = Console()


def _get_input(prompt: str = "> ") -> str | None:
    """Get input from the user. Returns None on EOF/Ctrl-C."""
    try:
        return console.input(prompt).strip()
    except (EOFError, KeyboardInterrupt):
        console.print("\n[dim]Aborted.[/dim]")
        return None


class BrainstormSession:
    """Freeform brainstorm conversation loop."""

    MAX_CONTEXT_TOKENS = 3000
    KEEP_EXCHANGES = 6  # keep last N user/assistant pairs when truncating

    def __init__(self, client: AsyncOpenAI, config: CreatorLLMConfig):
        self.client = client
        self.config = config
        self.messages: list[dict] = [
            {"role": "system", "content": BRAINSTORM_SYSTEM},
        ]

    async def run(self) -> str | None:
        """Run the brainstorm loop.

        Returns a concept summary string, or None if aborted.
        """
        console.print(
            "\n[bold]Brainstorm mode.[/bold] "
            "Describe your game idea and I'll help you develop it.\n"
            'Type [bold]"done"[/bold] when ready to create, '
            "or Ctrl-C to quit.\n"
        )

        while True:
            user_input = _get_input()
            if not user_input:
                return None
            if user_input.strip().lower() in ("done", "ok", "let's make this"):
                break

            self.messages.append({"role": "user", "content": user_input})
            self._truncate_if_needed()

            response = await call_llm(self.client, self.config, self.messages)
            self.messages.append({"role": "assistant", "content": response})
            console.print(f"\n{response}\n")

        # Summarize the brainstorm into a concept
        if len(self.messages) <= 1:
            return None  # No conversation happened

        return await self._summarize()

    async def _summarize(self) -> str:
        """Compress the brainstorm conversation into a concept paragraph."""
        summary_messages = [
            {"role": "system", "content": BRAINSTORM_SUMMARIZE_SYSTEM},
            {
                "role": "user",
                "content": self._format_conversation(),
            },
        ]
        return await call_llm(self.client, self.config, summary_messages)

    def _format_conversation(self) -> str:
        """Format the brainstorm messages for the summarizer."""
        lines = []
        for msg in self.messages[1:]:  # skip system prompt
            role = "Designer" if msg["role"] == "assistant" else "User"
            lines.append(f"{role}: {msg['content']}")
        return "\n".join(lines)

    def _truncate_if_needed(self) -> None:
        """Sliding window truncation if context exceeds token budget."""
        total = sum(estimate_tokens(m["content"]) for m in self.messages)
        if total <= self.MAX_CONTEXT_TOKENS:
            return

        # Keep system prompt + last KEEP_EXCHANGES pairs
        system = self.messages[:1]
        # Non-system messages
        rest = self.messages[1:]
        keep_count = self.KEEP_EXCHANGES * 2  # pairs of user/assistant
        if len(rest) > keep_count:
            rest = rest[-keep_count:]
        self.messages = system + rest

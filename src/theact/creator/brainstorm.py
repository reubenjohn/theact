"""Freeform brainstorm conversation management and CLI loop.

BrainstormConversation is the shared conversation engine used by both the CLI
(BrainstormSession) and web (CreatorChatPanel) brainstorm interfaces. It
handles message history, sliding-window truncation, and summarization.
"""

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


class BrainstormConversation:
    """Shared brainstorm conversation engine (no UI).

    Manages the message list, context-window truncation, and summarization
    logic that is common to both CLI and web brainstorm UIs.
    """

    MAX_CONTEXT_TOKENS = 3000
    KEEP_EXCHANGES = 6  # keep last N user/assistant pairs when truncating

    def __init__(self, client: AsyncOpenAI, config: CreatorLLMConfig) -> None:
        self.client = client
        self.config = config
        self.messages: list[dict] = [
            {"role": "system", "content": BRAINSTORM_SYSTEM},
        ]

    @property
    def has_conversation(self) -> bool:
        """True if there are any user/assistant messages beyond the system prompt."""
        return len(self.messages) > 1

    async def send(self, user_text: str) -> str:
        """Add a user message, truncate, call LLM, and return the response."""
        self.messages.append({"role": "user", "content": user_text})
        self.truncate_if_needed()
        response = await call_llm(self.client, self.config, self.messages)
        self.messages.append({"role": "assistant", "content": response})
        return response

    def undo_last(self) -> int:
        """Remove the last user+assistant exchange. Returns messages removed."""
        removed = 0
        while len(self.messages) > 1 and removed < 2:
            role = self.messages[-1]["role"]
            self.messages.pop()
            removed += 1
            if role == "user":
                break
        return removed

    def clear(self) -> None:
        """Reset to just the system prompt."""
        self.messages = [self.messages[0]]

    async def summarize(self) -> str:
        """Compress the conversation into a concept paragraph."""
        summary_messages = [
            {"role": "system", "content": BRAINSTORM_SUMMARIZE_SYSTEM},
            {"role": "user", "content": self.format_conversation()},
        ]
        return await call_llm(self.client, self.config, summary_messages)

    def format_conversation(self) -> str:
        """Format the brainstorm messages for the summarizer."""
        lines = []
        for msg in self.messages[1:]:  # skip system prompt
            role = "Designer" if msg["role"] == "assistant" else "User"
            lines.append(f"{role}: {msg['content']}")
        return "\n".join(lines)

    def truncate_if_needed(self) -> int:
        """Sliding window truncation if context exceeds token budget.

        Returns the number of messages dropped.
        """
        total = sum(estimate_tokens(m["content"]) for m in self.messages)
        if total <= self.MAX_CONTEXT_TOKENS:
            return 0

        system = self.messages[:1]
        rest = self.messages[1:]
        keep_count = self.KEEP_EXCHANGES * 2
        if len(rest) > keep_count:
            drop_count = len(rest) - keep_count
            rest = rest[-keep_count:]
            self.messages = system + rest
            return drop_count
        self.messages = system + rest
        return 0


class BrainstormSession:
    """CLI brainstorm loop wrapping BrainstormConversation."""

    def __init__(self, client: AsyncOpenAI, config: CreatorLLMConfig):
        self.conversation = BrainstormConversation(client, config)

    # Forward constants and message access through to the conversation
    MAX_CONTEXT_TOKENS = BrainstormConversation.MAX_CONTEXT_TOKENS
    KEEP_EXCHANGES = BrainstormConversation.KEEP_EXCHANGES

    @property
    def messages(self) -> list[dict]:
        return self.conversation.messages

    @messages.setter
    def messages(self, value: list[dict]) -> None:
        self.conversation.messages = value

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

            response = await self.conversation.send(user_input)
            console.print(f"\n{response}\n")

        if not self.conversation.has_conversation:
            return None

        return await self.conversation.summarize()

    # Keep these as forwarding methods for tests
    async def _summarize(self) -> str:
        return await self.conversation.summarize()

    def _format_conversation(self) -> str:
        return self.conversation.format_conversation()

    def _truncate_if_needed(self) -> None:
        self.conversation.truncate_if_needed()

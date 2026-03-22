"""Brainstorm chat side panel for the creator wizard.

A free-form conversation panel that lets users chat with the LLM for
inspiration before and during game creation. Reuses the brainstorm
prompts from the creator module. The panel can optionally inject a
summary of the conversation into the concept or feedback fields.
"""

from __future__ import annotations

import logging

from openai import AsyncOpenAI

from nicegui import ui

from theact.creator.config import CreatorLLMConfig
from theact.creator.generator import call_llm
from theact.creator.prompts import BRAINSTORM_SUMMARIZE_SYSTEM, BRAINSTORM_SYSTEM
from theact.llm.inference import extract_think_tags
from theact.llm.tokens import estimate_tokens

logger = logging.getLogger(__name__)


class CreatorChatPanel:
    """Collapsible side panel for brainstorming with the LLM."""

    MAX_CONTEXT_TOKENS = 3000
    KEEP_EXCHANGES = 6

    def __init__(
        self,
        client: AsyncOpenAI,
        config: CreatorLLMConfig,
        on_use_text: callable | None = None,
    ) -> None:
        self._client = client
        self._config = config
        self._on_use_text = on_use_text
        self._messages: list[dict] = [
            {"role": "system", "content": BRAINSTORM_SYSTEM},
        ]
        self._visible = False
        self._drawer: ui.right_drawer | None = None
        self._chat_container: ui.column | None = None
        self._input: ui.input | None = None
        self._sending = False
        # Track UI bubble containers so we can remove them on undo/clear.
        self._bubble_elements: list[ui.column] = []

    def build(self) -> None:
        """Build the right-drawer chat panel."""
        self._drawer = (
            ui.right_drawer(value=False, fixed=False, bordered=True)
            .classes("bg-[#0d1117]")
            .props(':width="540" data-testid="creator-chat-drawer"')
        )

        with self._drawer:
            # Header
            with ui.row().classes("w-full items-center justify-between p-3 pb-0"):
                ui.label("Brainstorm").style(
                    "font-size: 1.1em; font-weight: bold; color: #ccc;"
                )
                with ui.row().classes("gap-1"):
                    ui.button(
                        icon="content_paste",
                        on_click=self._use_as_concept,
                    ).props("flat dense").tooltip("Use summary as concept")
                    ui.button(
                        icon="undo",
                        on_click=self._undo_last,
                    ).props("flat dense").tooltip("Undo last message")
                    ui.button(
                        icon="delete_sweep",
                        on_click=self._clear_chat,
                    ).props("flat dense").tooltip("Clear chat")
                    ui.button(
                        icon="close",
                        on_click=self.toggle,
                    ).props("flat dense")

            ui.label(
                "Chat freely about game ideas. Click paste to use a summary."
            ).style("color: #666; font-size: 0.8em; padding: 0 12px;")

            ui.separator()

            # Chat message area
            self._chat_container = (
                ui.column()
                .classes("w-full flex-grow overflow-y-auto p-3 gap-2")
                .style("min-height: 0;")
            )

            # Input area at bottom
            with ui.row().classes("w-full p-3 pt-0 gap-1 items-end"):
                self._input = (
                    ui.input(placeholder="Type a message...")
                    .classes("flex-grow")
                    .props("outlined dense")
                    .on("keydown.enter", self._send_message)
                )
                ui.button(
                    icon="send",
                    on_click=self._send_message,
                ).props("flat dense color=primary")

    def toggle(self) -> None:
        """Show or hide the chat drawer."""
        if self._drawer:
            self._visible = not self._visible
            self._drawer.toggle()

    @property
    def visible(self) -> bool:
        return self._visible

    async def _send_message(self) -> None:
        """Send the user's message and get an LLM response."""
        if self._sending or not self._input:
            return
        text = (self._input.value or "").strip()
        if not text:
            return

        self._sending = True
        self._input.value = ""

        # Show user message
        self._render_message("You", text, user=True)

        # Add to history and truncate
        self._messages.append({"role": "user", "content": text})
        self._truncate_if_needed()

        # Show thinking indicator
        with self._chat_container:
            thinking = ui.row().classes("items-center gap-2")
            with thinking:
                ui.spinner("dots", size="sm")
                ui.label("Thinking...").style("color: #666; font-size: 0.85em;")

        try:
            response = await call_llm(self._client, self._config, self._messages)
            self._messages.append({"role": "assistant", "content": response})
            thinking.delete()
            reply_text, think_text = extract_think_tags(response)
            self._render_message(
                "Designer",
                reply_text,
                user=False,
                thinking=think_text or None,
            )
        except Exception as e:
            logger.exception("Chat message failed")
            thinking.delete()
            with self._chat_container:
                ui.label(f"Error: {e}").style("color: #ff5252; font-size: 0.85em;")
        finally:
            self._sending = False

    def _render_message(
        self, sender: str, text: str, *, user: bool, thinking: str | None = None
    ) -> None:
        """Render a single chat message bubble."""
        with self._chat_container:
            align = "items-end" if user else "items-start"
            bg = "#1a2233" if user else "#1a1a2e"
            color = "#90caf9" if user else "#c5e1a5"

            bubble = ui.column().classes(f"w-full {align}")
            self._bubble_elements.append(bubble)
            with bubble:
                ui.label(sender).style(
                    f"color: {color}; font-size: 0.75em; font-weight: bold;"
                )
                if thinking:
                    with (
                        ui.expansion("Thinking", icon="psychology")
                        .classes("w-full")
                        .style("color: #888; font-size: 0.8em; max-width: 95%;")
                    ):
                        ui.label(thinking).style(
                            "color: #999; font-size: 0.85em; white-space: pre-wrap;"
                        )
                ui.label(text).style(
                    f"color: #ddd; font-size: 0.9em; background: {bg}; "
                    f"padding: 8px 12px; border-radius: 8px; max-width: 95%; "
                    f"white-space: pre-wrap;"
                )

        # Auto-scroll to bottom
        if self._chat_container:
            ui.run_javascript(
                'document.querySelector("[data-testid=creator-chat-drawer] '
                '.overflow-y-auto").scrollTop = 999999;'
            )

    def _undo_last(self) -> None:
        """Remove the last user+assistant exchange from history and UI."""
        if self._sending or len(self._messages) <= 1:
            return
        # Remove last assistant reply (if present) then user message.
        removed = 0
        while len(self._messages) > 1 and removed < 2:
            role = self._messages[-1]["role"]
            self._messages.pop()
            if self._bubble_elements:
                self._bubble_elements.pop().delete()
            removed += 1
            if role == "user":
                break
        ui.notify("Last message undone.", type="info")

    def _clear_chat(self) -> None:
        """Reset conversation to a blank slate."""
        if self._sending:
            return
        self._messages = [self._messages[0]]  # keep system prompt
        self._bubble_elements.clear()
        if self._chat_container:
            self._chat_container.clear()
        ui.notify("Chat cleared.", type="info")

    async def _use_as_concept(self) -> None:
        """Summarize the conversation and pass it to the wizard."""
        if len(self._messages) <= 1:
            ui.notify("No conversation to summarize yet.", type="info")
            return

        if not self._on_use_text:
            ui.notify("No target field connected.", type="warning")
            return

        try:
            summary = await self._summarize()
            self._on_use_text(summary)
            ui.notify("Summary copied to concept field.", type="positive")
        except Exception as e:
            logger.exception("Failed to summarize brainstorm")
            ui.notify(f"Summarization failed: {e}", type="negative")

    async def _summarize(self) -> str:
        """Compress conversation into a concept paragraph."""
        lines = []
        for msg in self._messages[1:]:
            role = "Designer" if msg["role"] == "assistant" else "User"
            lines.append(f"{role}: {msg['content']}")

        summary_messages = [
            {"role": "system", "content": BRAINSTORM_SUMMARIZE_SYSTEM},
            {"role": "user", "content": "\n".join(lines)},
        ]
        return await call_llm(self._client, self._config, summary_messages)

    def _truncate_if_needed(self) -> None:
        """Sliding window truncation when context exceeds budget."""
        total = sum(estimate_tokens(m["content"]) for m in self._messages)
        if total <= self.MAX_CONTEXT_TOKENS:
            return
        system = self._messages[:1]
        rest = self._messages[1:]
        keep_count = self.KEEP_EXCHANGES * 2
        if len(rest) > keep_count:
            drop_count = len(rest) - keep_count
            rest = rest[-keep_count:]
            # Keep bubble list in sync — drop the oldest UI elements.
            self._bubble_elements = self._bubble_elements[drop_count:]
        self._messages = system + rest

"""Brainstorm chat side panel for the creator wizard.

A free-form conversation panel that lets users chat with the LLM for
inspiration before and during game creation. Uses BrainstormConversation
from the creator module for message management, truncation, and summarization.
"""

from __future__ import annotations

import logging

from openai import AsyncOpenAI

from nicegui import ui

from theact.creator.brainstorm import BrainstormConversation
from theact.creator.config import CreatorLLMConfig
from theact.llm.inference import extract_think_tags

logger = logging.getLogger(__name__)


class CreatorChatPanel:
    """Collapsible side panel for brainstorming with the LLM."""

    KEEP_EXCHANGES = BrainstormConversation.KEEP_EXCHANGES

    def __init__(
        self,
        client: AsyncOpenAI,
        config: CreatorLLMConfig,
        on_use_text: callable | None = None,
    ) -> None:
        self._conversation = BrainstormConversation(client, config)
        self._on_use_text = on_use_text
        self._visible = False
        self._drawer: ui.right_drawer | None = None
        self._chat_container: ui.column | None = None
        self._input: ui.input | None = None
        self._sending = False
        # Track UI bubble containers so we can remove them on undo/clear.
        self._bubble_elements: list[ui.column] = []

    # Backward-compatible access for tests that reach into _messages
    @property
    def _messages(self) -> list[dict]:
        return self._conversation.messages

    @_messages.setter
    def _messages(self, value: list[dict]) -> None:
        self._conversation.messages = value

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

        # Show thinking indicator
        with self._chat_container:
            thinking = ui.row().classes("items-center gap-2")
            with thinking:
                ui.spinner("dots", size="sm")
                ui.label("Thinking...").style("color: #666; font-size: 0.85em;")

        try:
            response = await self._conversation.send(text)
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
        if self._sending or not self._conversation.has_conversation:
            return
        removed = self._conversation.undo_last()
        # Keep bubble list in sync
        for _ in range(removed):
            if self._bubble_elements:
                self._bubble_elements.pop().delete()
        ui.notify("Last message undone.", type="info")

    def _clear_chat(self) -> None:
        """Reset conversation to a blank slate."""
        if self._sending:
            return
        self._conversation.clear()
        self._bubble_elements.clear()
        if self._chat_container:
            self._chat_container.clear()
        ui.notify("Chat cleared.", type="info")

    async def _use_as_concept(self) -> None:
        """Summarize the conversation and pass it to the wizard."""
        if not self._conversation.has_conversation:
            ui.notify("No conversation to summarize yet.", type="info")
            return

        if not self._on_use_text:
            ui.notify("No target field connected.", type="warning")
            return

        try:
            summary = await self._conversation.summarize()
            self._on_use_text(summary)
            ui.notify("Summary copied to concept field.", type="positive")
        except Exception as e:
            logger.exception("Failed to summarize brainstorm")
            ui.notify(f"Summarization failed: {e}", type="negative")

    async def _summarize(self) -> str:
        """Compress conversation into a concept paragraph."""
        return await self._conversation.summarize()

    def _truncate_if_needed(self) -> None:
        """Sliding window truncation when context exceeds budget."""
        drop_count = self._conversation.truncate_if_needed()
        if drop_count > 0:
            self._bubble_elements = self._bubble_elements[drop_count:]

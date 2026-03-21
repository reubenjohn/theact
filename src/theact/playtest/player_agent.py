"""Automated player agent for playtest sessions."""

from __future__ import annotations

import random

from theact.llm.config import AgentLLMConfig, LLMConfig
from theact.llm.inference import complete
from theact.models.chapter import Chapter
from theact.models.conversation import ConversationEntry

PLAYER_SYSTEM_PROMPT = """\
You are a player in a text-based RPG. You are playing a crash survivor
on a mysterious island. Read the narrator and character dialogue, then
respond with a short action or statement (1-2 sentences).

Guidelines:
- Stay in character as a crash survivor
- React naturally to what just happened
- Alternate between: exploring, talking to characters, investigating mysteries
- Be curious about strange details
- Sometimes push back on character suggestions
- Keep responses to 1-2 sentences
- IMPORTANT: Do NOT repeat actions you have already taken. If you already
  looked around, try something new. Vary your approach each turn."""

EDGE_CASE_PROMPTS = [
    "Do something unexpected -- try to go somewhere unusual or off-script.",
    "Ask a character a very direct, uncomfortable question.",
    "Try to do something silly or out of character to test the narrator.",
    "Reference something from much earlier in the conversation.",
    "Try to leave the current area or refuse to cooperate with the characters.",
    "Give a very short, minimal response -- just one or two words like 'ok' or 'sure'.",
    "Try to break the fourth wall -- ask about game mechanics, stats, or the narrator.",
    "Attempt something violent or aggressive toward a character.",
    "Say something that doesn't make sense -- gibberish or a non sequitur.",
    "Try to use or interact with an object that hasn't been mentioned.",
]

PLAYER_AGENT_CONFIG = AgentLLMConfig(
    temperature=0.9,
    max_tokens=150,
    structured=False,
)


class PlayerAgent:
    """Generates automated player inputs for playtesting."""

    def __init__(
        self,
        llm_config: LLMConfig,
        edge_case_frequency: float = 0.15,
    ) -> None:
        self.llm_config = llm_config
        self.edge_case_frequency = edge_case_frequency

    async def decide(
        self,
        conversation_tail: list[ConversationEntry],
        chapter: Chapter,
        turn_number: int,
    ) -> str:
        """Generate the next player action based on recent conversation."""
        system = PLAYER_SYSTEM_PROMPT
        is_edge_case = random.random() < self.edge_case_frequency

        if is_edge_case:
            system += "\n\n" + random.choice(EDGE_CASE_PROMPTS)

        messages: list[dict[str, str]] = [
            {"role": "system", "content": system},
        ]

        # Add chapter context (just the title and summary)
        messages.append(
            {
                "role": "user",
                "content": f"Current chapter: {chapter.title}\n{chapter.summary}",
            }
        )

        # Add recent conversation turns
        for entry in conversation_tail:
            role = "assistant" if entry.role != "player" else "user"
            speaker = entry.character or entry.role.capitalize()
            messages.append(
                {
                    "role": role,
                    "content": f"[{speaker}] {entry.content}",
                }
            )

        # Add action request
        messages.append(
            {
                "role": "user",
                "content": "What do you do? (1-2 sentences)",
            }
        )

        result = await complete(
            messages=messages,
            llm_config=self.llm_config,
            agent_config=PLAYER_AGENT_CONFIG,
        )

        return result.content.strip()

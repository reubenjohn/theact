"""Automated player agent for playtest sessions."""

from __future__ import annotations

import random
from dataclasses import dataclass

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

# Pre-defined strings for direct injection (bypass LLM entirely)
DIRECT_INJECTION_SHORT = [
    "ok",
    "sure",
    "yes",
    "no",
    ".",
    "I wait.",
]

DIRECT_INJECTION_NONSENSE = [
    "asdf jkl;",
    "THE QUICK BROWN FOX THE QUICK BROWN FOX",
    "sudo rm -rf /",
]

DIRECT_INJECTION_FOURTH_WALL = [
    "I know this is a game",
    "What's my hit points?",
    "Can I see the map?",
]

DIRECT_INJECTION_CONTRADICTORY = [
    "I both leave and stay at the same time",
]

# Combined pool for direct injection
DIRECT_INJECTION_ALL = (
    DIRECT_INJECTION_SHORT
    + DIRECT_INJECTION_NONSENSE
    + DIRECT_INJECTION_FOURTH_WALL
    + DIRECT_INJECTION_CONTRADICTORY
)

PLAYER_AGENT_CONFIG = AgentLLMConfig(
    temperature=0.9,
    max_tokens=1500,
    structured=False,
)


@dataclass
class PlayerDecision:
    """Result of a player agent decision, with metadata about edge case type."""

    action: str
    edge_case_type: str = "normal"
    # Possible types: "normal", "llm_edge_case", "direct_injection",
    # "nonsense_injection", "repeat_injection"


class PlayerAgent:
    """Generates automated player inputs for playtesting."""

    def __init__(
        self,
        llm_config: LLMConfig,
        edge_case_frequency: float = 0.15,
        direct_edge_case_frequency: float = 0.05,
        nonsense_frequency: float = 0.03,
        repeat_frequency: float = 0.03,
    ) -> None:
        self.llm_config = llm_config
        self.edge_case_frequency = edge_case_frequency
        self.direct_edge_case_frequency = direct_edge_case_frequency
        self.nonsense_frequency = nonsense_frequency
        self.repeat_frequency = repeat_frequency
        self._last_action: str | None = None

    async def decide(
        self,
        conversation_tail: list[ConversationEntry],
        chapter: Chapter,
        turn_number: int,
    ) -> str:
        """Generate the next player action based on recent conversation.

        Returns the action string. Use decide_with_metadata() to also
        get the edge case type label.
        """
        decision = await self.decide_with_metadata(
            conversation_tail, chapter, turn_number
        )
        return decision.action

    async def decide_with_metadata(
        self,
        conversation_tail: list[ConversationEntry],
        chapter: Chapter,
        turn_number: int,
    ) -> PlayerDecision:
        """Generate the next player action with edge case metadata.

        Checks injection types in order:
        1. Direct string injection (bypass LLM)
        2. Nonsense injection (subset of direct)
        3. Repeat injection (repeat previous action)
        4. Normal LLM generation (with possible edge case prompt)
        """
        # 1. Direct string injection — bypass LLM entirely
        if random.random() < self.direct_edge_case_frequency:
            action = random.choice(DIRECT_INJECTION_ALL)
            self._last_action = action
            return PlayerDecision(action=action, edge_case_type="direct_injection")

        # 2. Nonsense injection
        if random.random() < self.nonsense_frequency:
            action = random.choice(DIRECT_INJECTION_NONSENSE)
            self._last_action = action
            return PlayerDecision(action=action, edge_case_type="nonsense_injection")

        # 3. Repeat injection — return the same action as previous turn
        if self._last_action and random.random() < self.repeat_frequency:
            return PlayerDecision(
                action=self._last_action, edge_case_type="repeat_injection"
            )

        # 4. Normal LLM generation (with possible edge case prompt)
        system = PLAYER_SYSTEM_PROMPT
        is_edge_case = random.random() < self.edge_case_frequency
        edge_case_type = "llm_edge_case" if is_edge_case else "normal"

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

        action = result.content.strip()

        # Fallback: if thinking model consumed all tokens, use a generic action
        if not action:
            action = random.choice(
                [
                    "I look around for anything useful.",
                    "I try talking to the nearest person.",
                    "I explore the area more carefully.",
                    "I search for supplies.",
                    "I investigate the strange detail I noticed.",
                ]
            )

        self._last_action = action
        return PlayerDecision(action=action, edge_case_type=edge_case_type)

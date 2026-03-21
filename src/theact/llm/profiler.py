"""Context window profiler for agent prompts.

Provides tools to measure how much of the context window each agent uses,
diagnose headroom issues, and produce human-readable profiles.
"""

from __future__ import annotations

from dataclasses import dataclass

from theact.llm.tokens import estimate_tokens


@dataclass
class AgentProfile:
    """Token usage profile for a single agent call."""

    agent: str
    system_prompt_tokens: int
    user_message_tokens: int
    total_prompt_tokens: int
    max_tokens_budget: int
    context_limit: int = 8192
    headroom: int = 0  # context_limit - total_prompt - max_tokens_budget

    # Optional breakdown fields
    conversation_tokens: int = 0
    chapter_context_tokens: int = 0
    memory_tokens: int = 0


def profile_messages(
    agent: str,
    messages: list[dict],
    max_tokens_budget: int,
    context_limit: int = 8192,
) -> AgentProfile:
    """Profile token usage for a set of agent messages.

    Args:
        agent: Agent identifier (e.g. "narrator", "character:maya").
        messages: The full message list sent to the LLM.
        max_tokens_budget: The max_tokens parameter for the completion.
        context_limit: The model's total context window size.

    Returns:
        AgentProfile with token counts and headroom calculation.
    """
    system_tokens = 0
    user_tokens = 0

    for msg in messages:
        content = msg.get("content", "")
        tokens = estimate_tokens(content)
        role = msg.get("role", "")
        if role == "system":
            system_tokens += tokens
        elif role == "user":
            user_tokens += tokens
        else:
            # assistant or other roles count toward user
            user_tokens += tokens

    # Include per-message overhead (rough estimate: 4 tokens per message + 3 base)
    overhead = len(messages) * 4 + 3
    total_prompt = system_tokens + user_tokens + overhead
    headroom = context_limit - total_prompt - max_tokens_budget

    return AgentProfile(
        agent=agent,
        system_prompt_tokens=system_tokens,
        user_message_tokens=user_tokens,
        total_prompt_tokens=total_prompt,
        max_tokens_budget=max_tokens_budget,
        context_limit=context_limit,
        headroom=headroom,
    )


def format_profile(profile: AgentProfile) -> str:
    """Format a single agent profile as a human-readable string."""
    lines = [
        f"Agent: {profile.agent}",
        f"  System prompt:  {profile.system_prompt_tokens:>5} tokens",
        f"  User message:   {profile.user_message_tokens:>5} tokens",
        f"  Total prompt:   {profile.total_prompt_tokens:>5} tokens",
        f"  Max tokens:     {profile.max_tokens_budget:>5} tokens",
        f"  Context limit:  {profile.context_limit:>5} tokens",
        f"  Headroom:       {profile.headroom:>5} tokens",
    ]
    if profile.headroom < 0:
        lines.append("  ** OVER BUDGET **")
    return "\n".join(lines)


def format_turn_profile(profiles: list[AgentProfile]) -> str:
    """Format all agent profiles for a turn as a summary table."""
    if not profiles:
        return "No agent profiles."

    lines = [
        "Turn Context Profile",
        "=" * 70,
        f"{'Agent':<25} {'System':>7} {'User':>7} {'Total':>7} {'Max':>7} {'Room':>7}",
        "-" * 70,
    ]

    for p in profiles:
        flag = " (!)" if p.headroom < 0 else ""
        lines.append(
            f"{p.agent:<25} {p.system_prompt_tokens:>7} "
            f"{p.user_message_tokens:>7} {p.total_prompt_tokens:>7} "
            f"{p.max_tokens_budget:>7} {p.headroom:>7}{flag}"
        )

    lines.append("-" * 70)

    # Summary row
    total_prompt = sum(p.total_prompt_tokens for p in profiles)
    total_max = sum(p.max_tokens_budget for p in profiles)
    min_headroom = min(p.headroom for p in profiles)
    lines.append(
        f"{'TOTAL':<25} {'':>7} {'':>7} {total_prompt:>7} "
        f"{total_max:>7} {min_headroom:>7}"
    )
    lines.append(f"Min headroom: {min_headroom} tokens")

    return "\n".join(lines)

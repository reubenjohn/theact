"""Token estimation utilities.

Uses a simple character-based heuristic (no tiktoken dependency).
Sufficient for context budget decisions — not exact counts.
"""

from __future__ import annotations

# Approximate characters-per-token ratio for English text.
# Real tokenizers vary (3.5-4.5 chars/token).
CHARS_PER_TOKEN = 4

# Overhead per message in a chat completion (role, formatting, separators).
# OpenAI charges ~4 tokens per message for formatting.
MESSAGE_OVERHEAD_TOKENS = 4


def estimate_tokens(text: str) -> int:
    """Estimate the token count for a string of text."""
    if not text:
        return 0
    return max(1, len(text) // CHARS_PER_TOKEN)


def estimate_messages_tokens(messages: list[dict[str, str]]) -> int:
    """Estimate total token count for a list of chat messages.

    Accounts for per-message overhead (role, separators).
    """
    total = 0
    for msg in messages:
        total += MESSAGE_OVERHEAD_TOKENS
        total += estimate_tokens(msg.get("content", ""))
        total += estimate_tokens(msg.get("role", ""))
    # Every conversation has a base overhead of ~3 tokens
    total += 3
    return total


def tokens_remaining(
    messages: list[dict[str, str]],
    context_limit: int,
    max_completion_tokens: int,
) -> int:
    """Estimate how many tokens are available for additional context.

    Used by context assembly (Phase 03) to decide when to summarize
    and how much history to include.

    Returns negative if already over budget.
    """
    used = estimate_messages_tokens(messages)
    return context_limit - used - max_completion_tokens

# Memory & Summarization

A 7B model has ~8K context tokens. A game can last 50+ turns, generating ~25K tokens of raw conversation. The memory and summarization systems keep context within budget without losing important story details.

## Character Memory

Each character has a private memory file (`memories/<name>.yaml`) with two components:

- **Summary** — 3-5 sentences describing what the character knows, feels, and has experienced.
- **Key facts** — Up to 10 discrete statements like "Found a radio in the wreckage" or "Maya revealed she has a dying mother."

Memory is updated by the **memory agent** after every turn. The agent sees the current memory and the current turn's events, then outputs a YAML diff: facts to add, remove, or update, plus a new summary that merges the old one with new information.

Critical rule: memories are never cross-contaminated between characters. Each character's memory agent only sees what that character witnessed. If Maya wasn't present when something happened, her memory doesn't include it.

The memory model lives in [`src/theact/models/memory.py`](../../src/theact/models/memory.py). The memory agent is in [`src/theact/agents/memory.py`](../../src/theact/agents/memory.py). The prompt template is `MEMORY_UPDATE_SYSTEM` in [`src/theact/agents/prompts.py`](../../src/theact/agents/prompts.py).

## Rolling Summary

As the conversation grows, older turns are compressed into a running summary. This is **incremental merge**, not full re-summarization:

1. When unsummarized conversation exceeds ~1500 tokens, summarization triggers
2. The oldest turns (everything except the last 4 turns) are fed to the summarizer along with the existing summary
3. The summarizer merges new events into the existing summary, keeping it under 5 sentences
4. The summarized turns are tracked by `last_summarized_turn` in the game state — they remain in the conversation log but are not counted toward the threshold again

The rolling summary is injected at the top of the narrator's context as "Story so far." This gives the narrator long-range memory without consuming the full conversation history.

See `_maybe_update_rolling_summary()` in [`src/theact/engine/turn.py`](../../src/theact/engine/turn.py) and `ROLLING_SUMMARY_SYSTEM` in [`src/theact/agents/prompts.py`](../../src/theact/agents/prompts.py).

## Chapter Summaries

When a chapter completes, a dedicated summarizer creates a 2-3 sentence recap. Chapter summaries are:

- Stored in `summaries.yaml` in the save directory
- Injected into the narrator's context as "COMPLETED CHAPTERS" so the narrator maintains continuity across chapters

See [`src/theact/agents/summarizer.py`](../../src/theact/agents/summarizer.py) for the implementation and `_advance_chapter()` in [`turn.py`](../../src/theact/engine/turn.py) for where it's triggered.

## Context Budgeting

Each agent's context is assembled in [`src/theact/engine/context.py`](../../src/theact/engine/context.py). The `build_*_messages()` functions follow this pattern:

1. Build the system prompt with all required data (world, chapter, character, memory)
2. Add the user message with conversation history and the current turn
3. Estimate total tokens via [`src/theact/llm/tokens.py`](../../src/theact/llm/tokens.py) (a simple `len(text) // 4` heuristic — no tiktoken dependency)
4. If over budget, trim conversation history (reduce from 4 recent turns to 2, or drop history entirely)

The narrator gets the most context: rolling summary + chapter summaries + recent conversation + current input. Character agents get less: their memory + recent conversation + the current turn. Post-turn agents (memory, game state) get the minimum: just the current turn's events.

## How It All Fits Together

On a typical turn 30:

- The **rolling summary** covers turns 1-26 in ~5 sentences
- The **narrator** sees: rolling summary + chapter summaries + turns 27-29 + current input
- Each **character** sees: their memory (summary + facts) + turns 28-29 + current turn
- The **memory agent** sees: character's current memory + current turn → outputs updated memory
- The **game state agent** sees: chapter beats + current turn → checks completion

This layered approach means a 50-turn game uses roughly the same context as a 5-turn game.

## Further Reading

- [Agents](agents.md) — details on each agent, including the memory and summarizer agents
- [Data Model](data-model.md) — memory file format and save structure
- [Architecture](architecture.md) — where memory fits in the turn pipeline

# Agents

Each agent in TheAct makes exactly one LLM call to do exactly one task. The code decides which agents run and in what order — the model never decides "what to do next."

## Agent Inventory

| Agent | Purpose | Output Format | Source |
|-------|---------|---------------|--------|
| Narrator | Describes what happens, picks responding characters | YAML: `narration`, `responding_characters`, `mood` | [`agents/narrator.py`](../../src/theact/agents/narrator.py) |
| Character | Responds in-character with dialogue and actions | Plain text (50-150 words) | [`agents/character.py`](../../src/theact/agents/character.py) |
| Memory | Updates a character's memory after a turn | YAML: `add`, `remove`, `update`, `summary` | [`agents/memory.py`](../../src/theact/agents/memory.py) |
| Game State | Checks chapter beat progress and completion | YAML: `chapter_complete`, `reason`, `new_beats` | [`agents/game_state.py`](../../src/theact/agents/game_state.py) |
| Chapter Summary | Summarizes a completed chapter | Plain text (2-3 sentences) | [`agents/summarizer.py`](../../src/theact/agents/summarizer.py) |
| Rolling Summary | Merges old conversation into running summary | Plain text (under 5 sentences) | [`agents/summarizer.py`](../../src/theact/agents/summarizer.py) |

All agents run during gameplay using the small model (`olafangensan-glm-4.7-flash-heretic`). The game **creator agent** is a separate multi-step pipeline that uses a larger model — see [Creator Agent](creator.md) for its design.

## Prompt Design for Small Models

All prompt templates live in a single file: [`src/theact/agents/prompts.py`](../../src/theact/agents/prompts.py). This is deliberate — when a prompt needs tuning, it's a one-line edit in one file.

The rules for writing prompts that 7B models can follow:

1. **One task per call.** The narrator narrates. The memory agent updates memory. Never combine tasks.
2. **~300 token system prompts.** Every token competes with reasoning space. Cut ruthlessly.
3. **Imperative mood.** "Write narration" not "You should write narration." "Do NOT skip beats" not "Please try to avoid skipping beats."
4. **Concrete examples.** Show the exact output format with realistic content. Small models learn more from examples than instructions.
5. **State constraints as rules.** "Only list characters from ACTIVE CHARACTERS" not "It would be best to only include characters that are active."

See [Prompt Iteration](../guides/prompt-iteration.md) for how to modify these prompts when the model misbehaves.

## Structured Output

Agents that return structured data use YAML in fenced code blocks. The parsing pipeline:

1. The prompt includes a concrete YAML example showing the exact format
2. A YAML hint is appended to the user message as a reminder (see `YAML_HINT_*` constants in [`prompts.py`](../../src/theact/agents/prompts.py))
3. The model's response is passed to `extract_yaml_block()` in [`src/theact/llm/parsing.py`](../../src/theact/llm/parsing.py), which finds the last fenced `yaml` block via regex
4. The extracted text is parsed with `yaml.safe_load()`
5. On parse failure, the system retries with the error message fed back to the model

Why YAML instead of JSON? Small models produce more reliable YAML — they can use multiline strings with `|`, don't need to escape quotes, and the format is more forgiving of whitespace issues.

## Context Assembly

Each agent's message list is built by a dedicated function in [`src/theact/engine/context.py`](../../src/theact/engine/context.py):

| Function | Agent | Key inputs |
|----------|-------|------------|
| `build_narrator_messages()` | Narrator | World, chapter context, rolling summary, recent conversation, player input |
| `build_character_messages()` | Character | Character definition, memory, recent conversation, narrator output, prior character responses |
| `build_memory_messages()` | Memory | Character definition, current memory, current turn entries |
| `build_game_state_messages()` | Game State | Chapter beats with hit status, current turn entries |
| `build_summary_messages()` | Chapter Summary | Chapter definition, recent conversation |
| `build_rolling_summary_messages()` | Rolling Summary | Existing summary, old conversation entries |

Each builder checks token budgets and trims conversation history if needed. See [Memory & Summarization](memory-and-summarization.md) for the context budgeting strategy.

## Further Reading

- [Architecture](architecture.md) — where agents fit in the turn pipeline
- [Memory & Summarization](memory-and-summarization.md) — how memory and summary agents manage context
- [Prompt Iteration](../guides/prompt-iteration.md) — how to tune prompts when things go wrong

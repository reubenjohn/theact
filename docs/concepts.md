# Core Concepts

TheAct is a text RPG engine where code orchestrates every turn. The LLM never decides what to do next — it only responds to specific tasks. This makes it reliable with small (7B-class) language models.

## System Overview

The turn pipeline diagram in the project [README](../README.md) shows the high-level flow. In short: each turn, the engine feeds player input through a sequence of agents — narrator first, then characters, then memory and game state — before saving everything to disk with a git commit.

## Glossary

### Game Structure

- **Game Definition** — A set of YAML files describing a game: world, characters, and chapters. Lives in `games/<game-id>/`. Think of it as a template.
- **Save** — An active playthrough. Created from a game definition with added mutable state (conversation log, memories, game progress). Lives in `saves/`. Each save is its own git repository.
- **World** — The setting, tone, and narrative rules (~6 sentences). Injected into every narrator prompt.
- **Character** — An NPC with name, role, personality, secret, and relationships (~60 words total). Each character has its own memory and responds via a dedicated LLM call.
- **Chapter** — A narrative segment with story beats and a completion condition. Chapters advance automatically when the game state agent determines the condition is met.
- **Beat** — A short-phrase plot point within a chapter (e.g. "Player finds radio in wreckage"). Beats are tracked and guide the narrator toward story progression.

### Turn Pipeline

- **Turn** — One complete cycle: player input → narrator → character responses → memory updates → game state check → save. The engine runs 6-8 LLM calls per turn.
- **Agent** — A single LLM call with one specific task. The narrator describes what happens. A character agent speaks in-character. A memory agent updates one character's memory. The code decides which agents run and in what order.
- **Context Assembly** — The code that builds each agent's prompt by combining game data (world, characters, chapters), conversation history, and memory into a message array. Lives in `src/theact/engine/context.py`.
- **Structured Output** — Agents that return data (narrator, memory, game state) output YAML in fenced code blocks. The engine parses this with `yaml.safe_load()` and retries with error feedback on failure. YAML is used instead of JSON because small models produce more reliable YAML.

### Memory & Context

- **Character Memory** — Per-character state: a 3-5 sentence summary plus up to 10 key facts. Updated by a dedicated memory agent after each turn. Never cross-contaminated between characters.
- **Rolling Summary** — An incremental summary of older conversation turns. When unsummarized conversation exceeds ~1500 tokens, the oldest turns are merged into the existing summary (not re-summarized from scratch). Keeps context within the model's ~8K token window.
- **Chapter Summary** — A 2-3 sentence recap of a completed chapter. Injected into narrator context so the narrator maintains story continuity across chapters.

### Tools

- **Playtest** — An autonomous multi-turn test run where an AI player agent generates inputs and the system scores quality across dimensions like narration length, YAML parse success, and character voice consistency.
- **Turn Debugger** — An interactive tool for stepping through a turn's agent calls one at a time, inspecting prompts/responses, editing prompts, and replaying without restarting.
- **Golden Scenario** — A scripted multi-turn behavioral test with structural assertions (not text matching). Catches regressions in specific behaviors.

## Design Principles

- **One task per LLM call.** Never combine tasks. The narrator narrates. The memory agent updates memory.
- **Tiny prompts.** System prompts stay under ~300 tokens. A 7B model with 8K context cannot afford waste.
- **Code drives the loop.** The turn engine is deterministic code. The model never decides "what to do next."
- **YAML everywhere.** All data files and structured LLM output use YAML for human readability and small-model reliability.

## See Also

- [Architecture](architecture/overview.md)
- [Getting Started](getting-started.md)

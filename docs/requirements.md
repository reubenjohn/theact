# TheAct — Requirements & Design Rationale

This document captures the requirements, constraints, and design decisions for TheAct, with the reasoning behind each. It serves as the "why" behind the plan documents.

---

## 1. Problem Statement

TheAct is a rebuild of an earlier project called "xplore" (`~/workspace/token_world/token_world/llm/xplore`). Xplore was a working AI text RPG built with Streamlit, SQLAlchemy, and the Swarm SDK. It worked, but had problems:

- **Goal system unreliability.** Xplore used structured goals (short-term, long-term) for character memory. Small models frequently made wrong decisions — deleting goals that weren't complete, creating duplicates, failing to recognize completion. The structured decision-per-goal approach was too many sequential decisions for a small model.
- **Context window pressure.** As conversations grew, the small model's performance degraded. Summarization helped but was a full re-summarization pass, which was expensive and lossy.
- **Architectural coupling.** SQLAlchemy + Streamlit + Swarm SDK created tight coupling that made iteration difficult.
- **Model dependency.** The system relied on model capabilities (tool calls, complex instruction following) that small models can't reliably provide.

TheAct addresses all of these by designing from the ground up for small model constraints.

---

## 2. Core Requirements

### 2.1 Small Model First

**Requirement:** Must work with 7B-class thinking models (specifically `olafangensan-glm-4.7-flash-heretic` via Venice AI).

**Rationale:** The user wants games that can run on local hardware or cheap inference endpoints. This rules out relying on GPT-4-class capabilities.

**Implications:**
- No tool calls — small models can't reliably execute multi-step tool use
- No complex structured output — use YAML in fenced blocks, not JSON schema mode
- One task per LLM call — never ask the model to do two things at once
- Tiny prompts — every token in the system prompt is precious
- Aggressive context management — the model has ~8K context, most of which is needed for reasoning

### 2.2 Programmatic Turn Driving

**Requirement:** Turns are orchestrated by code, not by the model deciding what to do next.

**Rationale:** Agent frameworks like Goose let the model drive the loop — deciding what tools to call, when to respond, etc. Small models can't do this reliably. The code must decide: first narrator, then these characters in this order, then memory updates, then state check.

**Implications:**
- The turn engine is deterministic code, not an agent loop
- Each LLM call has a specific purpose with a specific output format
- The model never decides "what to do next" — only "what to say/output given this specific task"

### 2.3 Multiple AI Characters

**Requirement:** Support 1-3 AI characters per game, each with distinct personalities and memories.

**Rationale:** Multiple characters create richer narrative dynamics. But more than 3 overwhelms a small model's ability to maintain distinct voices.

**Design decision — Sequential character responses:** Each character sees prior characters' responses before generating their own. This creates natural conversation flow (Maya says X, then Joaquin responds to X). Parallel character generation would produce disconnected monologues.

**Design decision — Separate memory per character:** Each character has their own memory file updated by a dedicated LLM call. A single call trying to update multiple characters' memories cross-contaminates — the model confuses whose memory is whose.

### 2.4 Unlimited Undo

**Requirement:** Players can undo an unlimited number of turns. Critical for development and playtesting.

**Rationale:** When iterating on prompts and game design, the ability to rewind and replay is essential. Also a good player feature.

**Design decision — Git for versioning:** Each save is a git repository. One commit per turn. Undo = `git reset --hard HEAD~N`. This scales to hundreds of turns because git stores diffs, not full copies. The conversation file grows linearly but git only stores the appended portion as a diff.

**Alternative considered:** tar.gz snapshots. Rejected because they grow linearly with game size — turn 200 stores all prior state. Git stores diffs.

### 2.5 Autonomous Playtesting

**Requirement:** An AI agent must be able to playtest the game without human intervention.

**Rationale:** Without automated playtesting, prompt engineering is guesswork. The playtest framework lets us run 20-turn sessions, detect failures (empty responses, memory corruption, stuck loops), and iterate on prompts empirically.

**Implications:**
- The turn engine must be fully API-driven (no interactive UI dependency)
- A "player agent" generates reasonable inputs using the same LLM
- Everything is logged: turns, timing, thinking tokens, errors, memory state

### 2.6 Game Creation Agent

**Requirement:** An interactive agent helps users create new games by generating all game definition files from a concept description.

**Rationale:** Manually writing YAML game files is tedious and error-prone. A capable model can generate them from natural language.

**Design decision — Use a larger model:** Game creation is a one-time task that needs strong instruction following and creative writing. The 7B model can't do this well. A larger model (Claude, GPT-4) generates the files, but the output must be tiny enough for the 7B to consume during gameplay.

---

## 3. Data Format Decisions

### 3.1 YAML Everywhere

**Decision:** All game files, save state, conversation history, and memories use YAML.

**Rationale:** YAML is human-readable and hand-editable. During development, being able to open a character file and tweak the personality in a text editor is invaluable. JSON is harder to read and edit. Markdown is unstructured.

**Library:** `pyyaml` (simple, widely used). Not `ruamel.yaml` — we don't need comment preservation and pyyaml is simpler.

### 3.2 Tiny Game Files

**Decision:** Character files ~60 words. World file ~6 sentences. Chapter beats are short phrases.

**Rationale:** These files are injected into LLM prompts. A 500-word character backstory consumed 125 tokens — 1.5% of an 8K context window per character. With 2 characters, world context, chapter context, conversation history, and completion tokens, every token matters. The original Lost Island game had 500+ word character files and 2000+ word chapter files — far too large.

**What a 7B model actually needs to play a character:**
- Name and role (who they are in the story)
- Personality in 2-3 sentences (how they talk and behave)
- A secret (hidden motivation — creates depth cheaply)
- Relationships (one line per other character)

That's ~60 words. Enough for a small model to produce distinct, consistent character responses.

### 3.3 Conversation as YAML List

**Decision:** `conversation.yaml` is a YAML list of entries, each with turn/role/character/content.

**Rationale:** Consistent with the YAML-everywhere approach. Each entry is a few lines. For git, diffs are clean (appended entries). For undo, the file reverts to the prior state. For context assembly, we load and filter by turn number.

**Performance note:** `append_yaml_entry` rewrites the full file on each append. At 2000 entries (~500 turns × 4 messages), this is ~50KB of YAML — fast to parse and write. Not a bottleneck.

---

## 4. Memory System Decisions

### 4.1 Per-Character Memory Files

**Decision:** Each character has `memory/<name>.yaml` with a rolling summary (3-5 sentences) and key facts (max 10).

**Rationale:** Xplore's goal-based memory required the model to make multiple sequential decisions (is this goal complete? should I add a new goal? is this a duplicate?). Small models failed at this regularly. TheAct's approach is simpler: here's what happened this turn, update the memory. One decision, one output.

### 4.2 Separate Memory Update Calls

**Decision:** Each character's memory is updated by a separate, parallel LLM call.

**Rationale:** A single call updating multiple characters' memories cross-contaminates. The model confuses whose memory is whose. Separate calls are clean — each sees only one character's memory and this turn's events.

### 4.3 Rolling Summary (Incremental)

**Decision:** When conversation exceeds ~1500 tokens, older turns are compressed into a rolling summary via incremental merge.

**Rationale:** Full re-summarization is expensive and lossy. Incremental merge (existing summary + the 3 turns being trimmed → updated summary) keeps the summary call cheap and prevents quality degradation over time. The summary is stored in `state.yaml` and included in narrator/character prompts.

**Accepted tradeoff:** After 200+ turns, early events will be compressed and some detail will be lost. Character memories partially compensate, but narrative amnesia is an accepted feature of the format.

---

## 5. Turn Engine Decisions

### 5.1 Turn Flow

```
Player Input → Context Assembly (code) → Narrator (streaming)
→ Characters (sequential, streaming) → Post-Turn (parallel)
→ Persist + Git Commit
```

### 5.2 Narrator Determines Responding Characters

**Decision:** The narrator agent decides which characters respond and in what order.

**Rationale:** Not every character needs to speak every turn. The narrator has the context to decide: if the player asks Maya a direct question, only Maya should respond. If a dramatic event occurs, both characters might react. This keeps the turn focused and reduces unnecessary LLM calls.

### 5.3 Chapter Completion via Dedicated Agent

**Decision:** Each chapter has explicit completion criteria. A dedicated game state agent evaluates whether the criteria are met after each turn.

**Rationale:** Having the narrator judge completion conflates two tasks in one prompt. The game state agent does one thing: compare this turn's events against the chapter's completion criteria and beats. Simple, focused, reliable.

### 5.4 Chapter Summaries for Narrator Context

**Decision:** Completed chapters have 2-3 line summaries. The narrator sees: completed chapter summaries + current chapter (full) + upcoming chapter titles.

**Rationale:** The narrator needs to know "Chapter 1 complete (player established camp), Chapter 2 active, Chapter 3 upcoming" to steer the story. Without this, the narrator has no sense of narrative arc. Chapter summaries are cheap (~50 tokens for all completed chapters) and invaluable for coherence.

---

## 6. UI Decisions

### 6.1 Rich CLI First

**Decision:** Terminal CLI using the Rich library, not a TUI framework like Textual.

**Rationale:** A TUI app is over-engineered for a text game. We need: streaming text display, character-distinct styling, and simple commands. Rich provides all of this with minimal code. The CLI is a thin layer over the turn engine.

### 6.2 NiceGUI for Web UI

**Decision:** NiceGUI is the recommended web framework (Phase 07).

**Rationale:** NiceGUI's WebSocket-native architecture is the correct fit for token-by-token streaming. Its `ui.chat_message` component maps directly to our narrator/character/player messages. Async handlers work natively with the engine's async interface. Gradio's opinionated chat model doesn't support our multi-agent-per-turn pattern. Streamlit's rerun model fights streaming.

### 6.3 Thinking Token Visibility

**Decision:** Thinking tokens are visible by default (dimmed/collapsible).

**Rationale:** The user wants to understand model behavior. Seeing the model's reasoning helps diagnose prompt issues and builds intuition about what the model understands.

---

## 7. Prior Art Reference

### 7.1 Xplore (predecessor)

Location: `~/workspace/token_world/token_world/llm/xplore`

Key lessons learned:
- Goal-based memory doesn't work well with small models (too many sequential decisions)
- Streamlit's rerun model fights streaming
- SQLAlchemy adds unnecessary complexity for file-based game state
- Swarm SDK couples to OpenAI's agent patterns, which small models can't leverage

### 7.2 Example Game (original Lost Island)

Location: `~/workspace/nottheact/saves/playtest-001/`

This is the original verbose game definition. Character files are 500+ words, chapter files 2000+ words. It demonstrates the game concept but is far too large for small model prompts. TheAct's simplified version compresses this to ~60 words per character and ~150 words per chapter while preserving the narrative essence.

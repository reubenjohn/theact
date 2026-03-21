# Phase 12: Creator Agent Small Model Hardening

> **Prerequisite:** Phase 06 (Game Creation Agent) must be complete. Phase 11 (Small Model Hardening) should be complete or in progress -- the prompt engineering methodology and YAML parsing improvements from Phase 11 apply directly here. The creator module currently works with large models (GPT-4, Claude) but cannot run on the 7B gameplay model. This phase makes it work with small models by decomposing monolithic LLM calls into focused, single-task calls -- the same orchestration philosophy that makes gameplay reliable.

## 1. Overview

Phase 06 built the game creation agent with a critical assumption: it runs on a large, capable model. Every design decision reflects this -- a single LLM call generates the entire proposal, another single call generates ALL game files (world + characters + chapters) in one massive YAML block, and a single fix call attempts to repair all validation errors at once.

This works with GPT-4 class models. It will not work with a 7B model. The problems are:

1. **Monolithic generation is too much output.** The `GENERATION_USER` prompt asks the model to produce game.yaml + world.yaml + all characters + all chapters in a single YAML block. For a 3-character, 4-chapter game, that's 800-1200 tokens of structured YAML output. A 7B model with an 8K context window will run out of tokens, produce malformed YAML, or lose coherence between the first and last file.

2. **Prompts are too long.** `GENERATION_SYSTEM` is 121 lines (~700 tokens) of constraints, style guides, and structural rules. The 7B model cannot hold all of these in working memory simultaneously. It will follow some rules and ignore others unpredictably.

3. **Monolithic fixing is fragile.** When validation fails, the fixer sends ALL errors plus the ENTIRE generated YAML back to the model and asks it to fix everything. The model must understand the error, locate the relevant section in a large YAML block, fix it without breaking anything else, and reproduce the entire block. This is beyond 7B capability.

4. **Cross-file coherence in one shot.** Generating characters and chapters in a single call requires the model to maintain consistency across relationship keys, chapter character lists, and next-chain pointers -- all while respecting per-file size constraints. Large models handle this; small models don't.

### The Fix: Code-Orchestrated Decomposition

Apply the same principle that makes gameplay work: **one task per LLM call, orchestrated by code.**

Instead of one call that generates everything, the creator becomes a pipeline of focused calls:

```
(Optional) Brainstorm → Concept → Setting/Tone (1 call, iterate)
→ Characters (1 call each, iterate) → Chapter Arc (1 call each, iterate)
→ Full File Generation: World (1 call) → Characters (1 call each)
→ Chapters (1 call each) → game.yaml (code-assembled, no LLM)
→ Per-file validation + per-file fix (1 call per broken file)
```

Each call has a tiny prompt, produces a small output, and does exactly one thing. Code handles all cross-file consistency (assembling game.yaml, wiring chapter next-chains, injecting character stems into relationship keys).

Additionally, this phase adds a **standalone brainstorm tool** -- a freeform conversational loop where the user can bounce ideas off the LLM before entering the structured creation pipeline. No YAML, no structure, just creative back-and-forth. The brainstorm output can optionally be passed into the creator as a starting concept.

### What This Phase Does NOT Do

- No changes to the web UI. The brainstorm and decomposed proposal are CLI-only in this phase.
- No new file writer or validator logic -- the existing `validator.py` and `writer.py` work on the decomposed output identically.
- No changes to the gameplay engine, agents, or turn flow.

---

## 2. Architecture: Before and After

### 2.1 Current Architecture (Phase 06)

```
User Concept
    │
    ▼
┌─────────────────────────┐
│  generate_proposal()    │  1 LLM call → full proposal YAML
│  (proposer.py)          │  (~700 token prompt, ~500 token output)
└────────────┬────────────┘
             │
             ▼
┌─────────────────────────┐
│  generate_game_files()  │  1 LLM call → ALL files in 1 YAML block
│  (generator.py)         │  (~700 token prompt, ~1000 token output)
└────────────┬────────────┘
             │
             ▼
┌─────────────────────────┐
│  fix_validation_errors()│  1 LLM call per attempt → ALL files rewritten
│  (fixer.py)             │  (errors + full YAML in prompt)
└────────────┬────────────┘
             │
             ▼
        Write to disk
```

**Problem:** Each LLM call does too many things. The generation call must simultaneously:
- Understand 6+ size constraints
- Generate 4+ distinct file types
- Maintain cross-file consistency
- Produce valid YAML for the entire block

### 2.2 New Architecture (Phase 12)

```
┌──────────────────────────┐
│  brainstorm              │  Freeform conversation loop (optional)
│  (brainstorm.py)         │  No structure, just creative discussion
│  scripts/brainstorm.py   │  Outputs a concept summary when done
└────────────┬─────────────┘
             │ (concept text, or user types one directly)
             ▼
┌──────────────────────────┐
│  Decomposed Proposal     │  3 focused steps, each with its own
│  (proposer.py)           │  iteration loop:
│                          │
│  1. Setting/Tone         │  1 LLM call → setting + tone + rules
│     user iterates ↕      │
│  2. Characters           │  1 LLM call → character sketches
│     user iterates ↕      │
│  3. Chapter Arc          │  1 LLM call → chapter outline
│     user iterates ↕      │
└────────────┬─────────────┘
             │ (approved proposal)
             ▼
┌──────────────────────────┐
│  Generation Pipeline     │  Per-file generation:
│  (pipeline.py)           │
│  ┌─ generate_world()     │  1 call → world.yaml
│  ├─ generate_character() │  1 call per character (sequential)
│  ├─ generate_chapter()   │  1 call per chapter (sequential)
│  └─ assemble_game_meta() │  Pure code, no LLM
└────────────┬─────────────┘
             │
             ▼
┌──────────────────────────┐
│  validate + fix          │  1 LLM call per broken FILE (not all at once)
│  (fixer.py, updated)     │  Tiny prompt: 1 file + its errors
└────────────┬─────────────┘
             │
             ▼
        Write to disk
```

**Key differences from Phase 06:**
- New optional brainstorm step before structured creation
- Proposal decomposed into 3 iterable steps (setting → characters → chapters)
- Generation is 1 + N_chars + N_chapters calls instead of 1 monolithic call
- Each call has a prompt under 300 tokens (matching gameplay agent budgets)
- Each call produces a single small YAML block (~60-120 tokens)
- Cross-file consistency is enforced by code, not hoped for from the model
- Fixing targets individual files, not the entire game

---

## 3. Decomposed Generation Pipeline

### 3.1 Module Layout Changes

The current `generator.py` is replaced by focused generators. The shared utilities (`call_llm`, `serialize_game_data`) already live in `generator.py` as public functions after cleanup. The `extract_yaml` function also lives there but needs to be renamed to `extract_yaml` (dropping the leading underscore) since the new per-file generators will import it. Additionally, `extract_yaml` must be updated to strip `<think>...</think>` tags from model responses, since the 7B thinking model wraps its reasoning in these tags before producing content (see Phase 11 Section 2.2). New files:

```
src/theact/creator/
    __init__.py
    brainstorm.py         # NEW: freeform brainstorm conversation loop
    session.py            # Updated orchestrator -- calls pipeline steps
    proposer.py           # Rewritten: decomposed proposal (setting → chars → chapters)
    pipeline.py           # NEW: orchestrates world → chars → chapters → assemble
    world_gen.py          # NEW: generate world.yaml
    character_gen.py      # NEW: generate one character at a time
    chapter_gen.py        # NEW: generate one chapter at a time
    assembler.py          # NEW: code-assemble game.yaml (no LLM)
    generator.py          # Shared utilities (call_llm, serialize_game_data, extract_yaml) + monolithic fallback
    validator.py          # Unchanged
    fixer.py              # Updated: per-file fixing
    prompts.py            # Rewritten: small, focused prompts
    config.py             # Updated: small-model-aware defaults
    writer.py             # Unchanged
    display.py            # Unchanged (progress handled via on_progress callback)
    __main__.py           # Unchanged
```

### 3.2 Pipeline Orchestrator (`pipeline.py`)

The pipeline replaces `generate_game_files()` as the main generation entry point. It calls each generator in sequence, passing forward context from prior steps.

```python
async def run_generation_pipeline(
    proposal: dict,
    client: AsyncOpenAI,
    config: CreatorLLMConfig,
    on_progress: Callable[[str], None] | None = None,
) -> dict:
    """Generate all game files through a decomposed pipeline.

    Calls each generator in sequence:
    1. World (1 call)
    2. Characters (1 call each, sequential -- each sees prior characters)
    3. Chapters (1 call each, sequential -- each sees characters + prior chapters)
    4. game.yaml (code-assembled, no LLM call)

    Args:
        proposal: Approved proposal dict.
        client: AsyncOpenAI client.
        config: Creator LLM configuration.
        on_progress: Optional callback for status updates (e.g., "Generating maya...")

    Returns:
        dict with keys: "game", "world", "characters", "chapters"
    """
    # Guard: proposal must have at least 1 character
    if not proposal.get("characters"):
        raise ValueError("Proposal has no characters. At least 1 is required.")

    if on_progress:
        on_progress("Generating world...")
    world_data = await generate_world(proposal, client, config)

    characters_data = {}
    char_stems = [c["stem"] for c in proposal["characters"]]
    for i, char_info in enumerate(proposal["characters"]):
        stem = char_info["stem"]
        if on_progress:
            on_progress(f"Generating character: {char_info['name']}...")
        # Each character sees the proposal + all prior characters
        # so it can write relationship entries that reference them
        characters_data[stem] = await generate_character(
            proposal=proposal,
            char_info=char_info,
            all_stems=char_stems,
            prior_characters=characters_data,
            client=client,
            config=config,
        )

    chapters_data = {}
    for i, chap_info in enumerate(proposal["chapters"]):
        cid = chap_info["id"]
        if on_progress:
            on_progress(f"Generating chapter: {chap_info['title']}...")
        # Each chapter sees the characters + all prior chapters
        # so it can reference the right character stems and maintain
        # narrative continuity
        next_id = (
            proposal["chapters"][i + 1]["id"]
            if i + 1 < len(proposal["chapters"])
            else None
        )
        chapters_data[cid] = await generate_chapter(
            proposal=proposal,
            chap_info=chap_info,
            characters=characters_data,
            prior_chapters=chapters_data,
            next_chapter_id=next_id,
            client=client,
            config=config,
        )

    # Assemble game.yaml from the generated data -- pure code, no LLM
    game_data = assemble_game_meta(proposal, characters_data, chapters_data)

    result = {
        "game": game_data,
        "world": world_data,
        "characters": characters_data,
        "chapters": chapters_data,
    }

    # Apply code-enforced consistency fixes (remove self-references,
    # strip invalid stems, re-wire chapter chain)
    return enforce_consistency(result)
```

### 3.3 World Generator (`world_gen.py`)

One focused call. Produces only `world.yaml` content.

```python
async def generate_world(
    proposal: dict,
    client: AsyncOpenAI,
    config: CreatorLLMConfig,
) -> dict:
    """Generate world.yaml from the proposal.

    Returns:
        dict with keys: "setting", "tone", "rules"
    """
```

**Prompt (under 200 tokens):**

```python
WORLD_SYSTEM = """\
Generate a world definition for a text RPG.

Output YAML with exactly these keys:

```yaml
setting: |
  Where and when. 2 sentences. Concrete sensory details.
tone: |
  Narrative voice. Second person, present tense, 100-250 words per turn.
rules: |
  2 hard constraints for the narrator. What it must/must not do.
```

HARD LIMIT: ~6 sentences total across all three fields. Under 80 words.
Every word is injected into a small model's prompt. Brevity is critical."""


WORLD_USER = """\
Game concept:
Title: {title}
Setting: {setting}
Tone: {tone}
Rules: {rules}

Generate the world.yaml content."""
```

### 3.4 Character Generator (`character_gen.py`)

One call per character. Sequential so each character can have accurate relationship entries referencing prior characters.

```python
async def generate_character(
    proposal: dict,
    char_info: dict,
    all_stems: list[str],
    prior_characters: dict[str, dict],
    client: AsyncOpenAI,
    config: CreatorLLMConfig,
) -> dict:
    """Generate one character's YAML data.

    Args:
        char_info: This character's proposal entry (stem, name, role).
        all_stems: All character stems in the game.
        prior_characters: Already-generated character data dicts.

    Returns:
        dict with keys: "name", "role", "personality", "secret", "relationships"
    """
```

**Prompt (under 250 tokens):**

```python
CHARACTER_SYSTEM = """\
Generate a character definition for a text RPG.

Output YAML with exactly these keys:

```yaml
name: "Display Name"
role: "One sentence, under 12 words"
personality: |
  2-3 short sentences defining speech patterns and behavior. Under 40 words.
secret: "One sentence hidden motivation. Under 15 words."
relationships:
  other_stem: "One-line stance toward them. Under 12 words."
```

HARD LIMIT: ~60 words total. Personality defines HOW they speak, not backstory.
Relationship keys are the other characters' file stems (lowercase).
Do NOT include a relationship entry for the character itself."""


CHARACTER_USER = """\
Game: {title}
Setting: {setting_summary}

This character:
  Name: {name}
  Role: {role}

Other characters in the game: {other_characters}

{prior_character_context}

Generate this character's YAML."""
```

The `prior_character_context` block is empty for the first character and contains the already-generated characters' names and relationship stances for subsequent ones. This lets each character's relationships be informed by (and potentially reciprocate) prior characters' stances.

### 3.5 Chapter Generator (`chapter_gen.py`)

One call per chapter. Sequential so each chapter can maintain narrative continuity with prior chapters and correctly reference character stems.

```python
async def generate_chapter(
    proposal: dict,
    chap_info: dict,
    characters: dict[str, dict],
    prior_chapters: dict[str, dict],
    next_chapter_id: str | None,
    client: AsyncOpenAI,
    config: CreatorLLMConfig,
) -> dict:
    """Generate one chapter's YAML data.

    Args:
        chap_info: This chapter's proposal entry (id, title, summary).
        characters: All generated character data dicts.
        prior_chapters: Already-generated chapter data dicts.
        next_chapter_id: The ID of the next chapter, or None for the last.

    Returns:
        dict with keys: "id", "title", "summary", "beats", "completion",
                        "characters", "next"
    """
```

**Prompt (under 250 tokens):**

```python
CHAPTER_SYSTEM = """\
Generate a chapter definition for a text RPG.

Output YAML with exactly these keys:

```yaml
id: "chapter-slug"
title: "Chapter Title"
summary: |
  2-3 sentences about what happens.
beats:
  - "Short phrase milestone"
  - "Short phrase milestone"
  - "Short phrase milestone"
  - "Short phrase milestone"
completion: "One sentence testable condition for chapter end."
characters:
  - "char_stem"
next: "next-chapter-id-or-null"
```

RULES:
- 4-6 beats. Beats are SHORT PHRASES (under 15 words each), not sentences.
- Completion is a clear, testable state, not a feeling.
- Characters list uses file stems (lowercase).
- `next` is the next chapter's ID, or null for the last chapter."""


CHAPTER_USER = """\
Game: {title}
Characters: {character_list}

This chapter:
  ID: {chapter_id}
  Title: {chapter_title}
  Summary from proposal: {chapter_summary}
  Next chapter: {next_chapter_id}

{prior_chapter_context}

Generate this chapter's YAML."""
```

The `next` field is injected by code from `next_chapter_id`, not left to the model. This prevents broken chapter chains -- the most common cross-file consistency failure. The `prior_chapter_context` gives the model the previous chapter's summary and beats so it can maintain narrative progression.

### 3.6 Game Meta Assembler (`assembler.py`)

Pure code. No LLM call needed -- game.yaml is just an index of what was generated.

```python
def assemble_game_meta(
    proposal: dict,
    characters: dict[str, dict],
    chapters: dict[str, dict],
) -> dict:
    """Assemble game.yaml data from generated components.

    This is pure code -- no LLM call. The game meta is just an index
    of the generated characters and chapters, plus the title from
    the proposal. The description is synthesized from the title
    since proposals don't include a description field.
    """
    return {
        "id": proposal["id"],
        "title": proposal["title"],
        "description": f"{proposal['title']} -- a text-based RPG.",
        "characters": list(characters.keys()),
        "chapters": list(chapters.keys()),
    }


def assemble_game_meta_from_data(data: dict) -> dict:
    """Re-assemble game.yaml from a full data dict.

    Convenience wrapper for use during revision and fixing, where
    the full proposal is not available -- only the data dict with
    game/world/characters/chapters keys.
    """
    return {
        "id": data["game"]["id"],
        "title": data["game"]["title"],
        "description": data["game"].get(
            "description", f"{data['game']['title']} -- a text-based RPG."
        ),
        "characters": list(data.get("characters", {}).keys()),
        "chapters": list(data.get("chapters", {}).keys()),
    }
```

---

## 4. Prompt Rewrite Strategy

### 4.1 Principles (from Phase 11)

All prompts in this phase follow the same principles validated during Phase 11's gameplay hardening:

1. **Under 300 tokens per system prompt.** Each generator has one job -- its prompt should be tiny.
2. **Concrete examples beat abstract rules.** Show the exact YAML structure, don't describe it in prose.
3. **Position matters.** Output format and hard limits go at the END of the system prompt.
4. **Positive phrasing.** "Write 2 sentences" not "Do not write more than 2 sentences."
5. **One-shot example IS the format spec.** The YAML block in the system prompt is both the example and the schema definition.

### 4.2 Brainstorm Tool (`brainstorm.py`)

A standalone freeform conversation loop for exploring game ideas before entering the structured creation flow. No YAML, no structure -- just the user and the LLM trading ideas.

**Why this helps with small models:** Brainstorming is the easiest possible LLM task -- short conversational responses with no formatting constraints. Even a 7B model can do this well. It also means the user arrives at the creation pipeline with a much clearer concept, which produces better structured output downstream.

#### Module and Script

```
src/theact/creator/
    brainstorm.py           # BrainstormSession class

scripts/
    brainstorm.py           # CLI entry point
```

#### How It Works

```
User: "I want to make a game about..."
LLM: "That's interesting -- have you considered..."
User: "Yeah, and maybe there's a character who..."
LLM: "A betrayer character could work well if..."
  ... (any number of exchanges) ...
User: "ok" / "done" / "let's make this"
  ↓
System summarizes the conversation into a concept paragraph
  ↓
Hands off to create_game(concept=summary) -- or prints it for the user to copy
```

#### Brainstorm System Prompt (under 150 tokens)

```python
BRAINSTORM_SYSTEM = """\
You are a game designer brainstorming text RPG ideas with a collaborator.

Help them explore concepts: settings, characters, tone, plot hooks, themes.
Be creative but concise. Ask questions to draw out their vision.
Suggest concrete details -- names, places, conflicts -- not abstractions.
Keep responses to 2-4 sentences. Build on their ideas, don't overwrite them."""
```

#### Conversation Summary

When the user ends the brainstorm, the system makes one final LLM call to compress the conversation into a concept paragraph suitable for the proposal pipeline:

```python
BRAINSTORM_SUMMARIZE_SYSTEM = """\
Summarize this game brainstorm into a concept paragraph.
Include: genre, setting, key characters, what the player does, and tone.
3-5 sentences. This will be the input to a game creation tool."""
```

The summary is passed as the `concept` argument to `create_game()`, or printed for the user to copy if they want to run the creator separately.

#### BrainstormSession

```python
class BrainstormSession:
    """Freeform brainstorm conversation loop."""

    def __init__(self, client: AsyncOpenAI, config: CreatorLLMConfig):
        self.client = client
        self.config = config
        self.messages: list[dict] = [
            {"role": "system", "content": BRAINSTORM_SYSTEM},
        ]

    async def run(self) -> str | None:
        """Run the brainstorm loop.

        Returns a concept summary string, or None if aborted.
        """
        console.print(
            "\n[bold]Brainstorm mode.[/bold] "
            "Describe your game idea and I'll help you develop it.\n"
            'Type [bold]"done"[/bold] when ready to create, '
            "or Ctrl-C to quit.\n"
        )

        while True:
            user_input = _get_input()
            if not user_input:
                return None
            if user_input.strip().lower() in ("done", "ok", "let's make this"):
                break

            self.messages.append({"role": "user", "content": user_input})

            response = await call_llm(
                self.client, self.config, self.messages
            )
            self.messages.append({"role": "assistant", "content": response})
            console.print(f"\n{response}\n")

        # Summarize the brainstorm into a concept
        if len(self.messages) <= 1:
            return None  # No conversation happened

        return await self._summarize()

    async def _summarize(self) -> str:
        """Compress the brainstorm conversation into a concept paragraph."""
        summary_messages = [
            {"role": "system", "content": BRAINSTORM_SUMMARIZE_SYSTEM},
            {
                "role": "user",
                "content": self._format_conversation(),
            },
        ]
        return await call_llm(self.client, self.config, summary_messages)

    def _format_conversation(self) -> str:
        """Format the brainstorm messages for the summarizer."""
        lines = []
        for msg in self.messages[1:]:  # skip system prompt
            role = "Designer" if msg["role"] == "assistant" else "User"
            lines.append(f"{role}: {msg['content']}")
        return "\n".join(lines)
```

#### CLI Entry Point (`scripts/brainstorm.py`)

```python
#!/usr/bin/env python
"""Brainstorm game ideas with the LLM.

Usage:
    uv run python scripts/brainstorm.py
    uv run python scripts/brainstorm.py --create  # launch creator after
"""

import argparse
import asyncio

from theact.creator.brainstorm import BrainstormSession
from theact.creator.config import load_creator_config
from theact.creator.generator import call_llm  # noqa: reuse
from openai import AsyncOpenAI
from rich.console import Console

console = Console()


def main():
    parser = argparse.ArgumentParser(description="Brainstorm game ideas")
    parser.add_argument(
        "--create", action="store_true",
        help="Launch the game creator after brainstorming",
    )
    args = parser.parse_args()

    config = load_creator_config()
    client = AsyncOpenAI(base_url=config.base_url, api_key=config.api_key)

    concept = asyncio.run(_run(client, config))

    if concept:
        console.print(f"\n[bold]Concept summary:[/bold]\n{concept}\n")
        if args.create:
            from theact.creator.session import create_game
            asyncio.run(create_game(concept=concept))
    else:
        console.print("[dim]No concept generated.[/dim]")


async def _run(client, config):
    session = BrainstormSession(client, config)
    return await session.run()


if __name__ == "__main__":
    main()
```

#### Context Window Management

The brainstorm conversation accumulates in `self.messages`. For a small model with an 8K context window, this can become a problem after many exchanges. If the total conversation exceeds ~3000 tokens (estimated via `len(text) // 4`), truncate the oldest user/assistant messages, keeping the system prompt and the last 6 exchanges. This is simple sliding-window truncation, not summarization -- the brainstorm is informal, so losing early messages is acceptable.

### 4.3 Decomposed Proposal Flow

The current `PROPOSAL_SYSTEM` asks the model to produce title + setting + tone + rules + characters + chapters all at once. For a small model, decompose this into 3 focused steps, each with its own iteration loop.

#### Step 1: Setting and Tone

```python
SETTING_SYSTEM = """\
You are a game designer. Given a concept, define the game's identity.

Output YAML:

```yaml
title: "Display Title"
id: "url-safe-slug"
setting: "Where and when. 2 sentences."
tone: "Narrative voice. Second person, present tense. 2 sentences."
rules: "2 hard constraints for the narrator."
```

Every word must earn its place. The runtime model has an 8K context."""
```

The user reviews and iterates: "make it darker", "change the setting to the 1920s". Each revision regenerates only this block.

#### Step 2: Characters

Once setting is approved, generate character sketches:

```python
PROPOSAL_CHARACTERS_SYSTEM = """\
You are a game designer. Given a game setting, propose characters.

Output YAML:

```yaml
characters:
  - stem: "lowercase-stem"
    name: "Display Name"
    role: "One-line role in the story"
```

1-3 characters. Each role is one sentence. Stems are lowercase, no spaces.
Characters must have distinct personalities and conflicting goals."""
```

The user sees the character list and iterates: "add a villain", "change the doctor to a nurse", "only 2 characters". The setting context is injected into the user message so the model keeps characters consistent with the world.

#### Step 3: Chapter Arc

Once characters are approved, generate the chapter outline:

```python
PROPOSAL_CHAPTERS_SYSTEM = """\
You are a game designer. Given a game setting and characters, outline the chapters.

Output YAML:

```yaml
chapters:
  - id: "01-slug"
    title: "Chapter Title"
    summary: "One sentence about what happens"
```

3-5 chapters. Each covers 5-10 turns of gameplay. Summaries are one sentence.
Chapter IDs are numbered slugs (e.g., "01-the-crash")."""
```

The user sees the arc and iterates: "add a twist in chapter 2", "the final chapter should be a confrontation". Setting + characters are injected into the user message.

#### Assembled Proposal

After all 3 steps are approved, code assembles them into the proposal dict that the generation pipeline expects:

```python
def assemble_proposal(
    setting_data: dict,
    characters_data: dict,
    chapters_data: dict,
) -> dict:
    """Assemble a proposal dict from the 3 decomposed steps."""
    return {
        "title": setting_data["title"],
        "id": setting_data["id"],
        "setting": setting_data["setting"],
        "tone": setting_data["tone"],
        "rules": setting_data["rules"],
        "characters": characters_data["characters"],
        "chapters": chapters_data["chapters"],
    }
```

#### Session Flow Update

The `session.py` orchestrator changes from:

```
concept → generate_proposal() → iterate → generate files
```

To:

```
concept (from brainstorm or typed directly)
  → generate_setting() → iterate
  → generate_characters() → iterate
  → generate_chapters() → iterate
  → assemble_proposal()
  → run_generation_pipeline()
```

Each step shows the user just that piece and lets them refine it before moving on. The user can also go back: "actually change the setting" re-enters step 1, keeping existing character and chapter data as context for when those steps re-run.

### 4.4 Revision Prompt for Small Models

For per-step revisions during the proposal phase, each step has a simple revision prompt:

```python
SETTING_REVISION_USER = """\
Current setting:

```yaml
{current_setting}
```

Requested changes: {user_feedback}

Output the revised YAML. Same format."""
```

The same pattern applies to `CHARACTERS_REVISION_USER` and `CHAPTERS_REVISION_USER`.

---

## 5. Per-File Validation and Fixing

### 5.1 Problem with Monolithic Fixing

The current `fixer.py` sends ALL validation errors plus the ENTIRE game YAML to the model and asks it to fix everything at once. For a small model:
- The prompt is too long (full game YAML can be 800+ tokens)
- The model must understand which parts of a large block to modify
- Fixing one file may break another

### 5.2 Per-File Fix Strategy

Replace the monolithic fixer with a per-file approach. For each file that has validation errors, send only that file's data and its specific errors:

```python
async def fix_file(
    file_type: str,         # "world", "character", or "chapter"
    file_key: str,          # e.g., "maya" or "01-the-crash"
    file_data: dict,        # the current (broken) data for this file
    errors: list[ValidationError],  # only this file's errors
    context: dict,          # minimal context (proposal title, character stems)
    client: AsyncOpenAI,
    config: CreatorLLMConfig,
) -> dict:
    """Fix validation errors in a single file.

    Returns the corrected data dict for this one file.
    """
```

**Fix prompt (under 200 tokens):**

```python
FIX_SYSTEM = """\
Fix the errors in this game file. Change ONLY what is broken.
Output the corrected YAML. Same structure, same keys."""


FIX_USER = """\
File: {file_type}/{file_key}.yaml

Errors:
{error_list}

Current content:
```yaml
{file_yaml}
```

Fix the errors. Output corrected YAML only."""
```

### 5.3 Updated Fix Loop

The new fix loop iterates per-file instead of per-game:

```python
async def fix_validation_errors(
    data: dict,
    validation_result: ValidationResult,
    client: AsyncOpenAI,
    config: CreatorLLMConfig,
) -> tuple[dict, ValidationResult]:
    """Fix validation errors file-by-file.

    Groups errors by file, fixes each broken file individually,
    then re-validates the whole game. Repeats up to MAX_FIX_ATTEMPTS.
    """
    current_data = data

    for _attempt in range(MAX_FIX_ATTEMPTS):
        current_result = validate_game_data(current_data)
        if current_result.valid:
            return current_data, current_result

        # Group errors by file
        errors_by_file = _group_errors_by_file(current_result.errors)

        # Fix each broken file individually
        for file_key, file_errors in errors_by_file.items():
            file_type, stem = _parse_file_key(file_key)
            if file_type == "world":
                file_data = current_data.get("world", {})
            elif file_type == "characters":
                file_data = current_data.get("characters", {}).get(stem, {})
            elif file_type == "chapters":
                file_data = current_data.get("chapters", {}).get(stem, {})
            else:
                # game.yaml errors: cross-reference errors are fixed by
                # reassembly below. Pydantic errors (missing description,
                # wrong types) are fixed by reassembly too, since
                # assemble_game_meta_from_data always produces a valid
                # structure from the current data.
                continue

            fixed = await fix_file(
                file_type, stem, file_data, file_errors,
                context={"title": current_data.get("game", {}).get("title", "")},
                client=client, config=config,
            )
            _update_data(current_data, file_type, stem, fixed)

        # Always re-assemble game.yaml after fixes -- this fixes both
        # cross-reference errors and Pydantic errors (missing fields, etc.)
        current_data["game"] = assemble_game_meta_from_data(current_data)

        # Apply code-enforced consistency fixes
        current_data = enforce_consistency(current_data)

    current_result = validate_game_data(current_data)
    return current_data, current_result
```

### 5.4 Code-Enforced Consistency

Many cross-file validation errors don't need an LLM fix at all. Code can enforce:

1. **Chapter next-chain:** Injected by `generate_chapter()` via the `next_chapter_id` parameter. If somehow wrong after fixing, `assembler.py` can re-wire it.
2. **game.yaml character/chapter lists:** Always assembled by code from the keys of `characters` and `chapters` dicts.
3. **Relationship keys:** The character generator receives `all_stems` and the prompt specifies which stems to use. If a relationship key doesn't match, code can strip it or remap it.
4. **Character self-references:** Code can detect and remove a character's relationship entry that references itself.
5. **Chapter character lists:** Code can validate that referenced character stems exist and strip invalid ones.

Add a `enforce_consistency()` function in `assembler.py` that runs after generation and after each fix round:

```python
def enforce_consistency(data: dict) -> dict:
    """Apply code-enforced fixes for cross-file consistency.

    These are deterministic fixes that don't need an LLM:
    - Rebuild game.yaml from actual characters/chapters keys
    - Remove self-referencing relationships
    - Strip invalid character stems from chapter character lists
    - Re-wire chapter next-chain based on game.yaml chapter order
    """
```

---

## 6. Config Changes for Small Models

### 6.1 Updated Defaults

The `CreatorLLMConfig` needs small-model-aware defaults when running on the 7B model:

```python
@dataclass(frozen=True)
class CreatorLLMConfig:
    base_url: str = "https://api.openai.com/v1"
    api_key: str = ""
    model: str = "olafangensan-glm-4.7-flash-heretic"
    temperature: float = 0.7
    max_tokens: int = 4096        # large model default
    proposal_max_tokens: int = 1500

    # Small model overrides (applied when is_small_model is True)
    small_model_world_max_tokens: int = 800       # world generation
    small_model_character_max_tokens: int = 800    # character generation
    small_model_chapter_max_tokens: int = 1000     # chapter generation (more output)
    small_model_fix_max_tokens: int = 600          # per-file fixing
    small_model_temperature: float = 0.5           # less creative, more reliable

    def max_tokens_for(self, call_type: str) -> int:
        """Return max_tokens for the given call type.

        call_type: "world", "character", "chapter", "fix", or "proposal"
        """
        if not self.is_small_model:
            return self.max_tokens if call_type != "proposal" else self.proposal_max_tokens
        return {
            "world": self.small_model_world_max_tokens,
            "character": self.small_model_character_max_tokens,
            "chapter": self.small_model_chapter_max_tokens,
            "fix": self.small_model_fix_max_tokens,
            "proposal": self.proposal_max_tokens,
        }.get(call_type, self.small_model_world_max_tokens)

    @property
    def generation_temperature(self) -> float:
        return self.small_model_temperature if self.is_small_model else self.temperature
```

### 6.2 Thinking Token Budget

The 7B thinking model spends tokens in `<think>` tags. For creative generation tasks (world, characters), this is acceptable and often beneficial. For structural tasks (chapters with specific fields), thinking overhead is wasteful.

Budget per call type:
- **World generation:** 800 max_tokens (thinking ~200, content ~80, margin ~520)
- **Character generation:** 800 max_tokens (thinking ~200, content ~80, margin ~520)
- **Chapter generation:** 1000 max_tokens (thinking ~300, content ~120, margin ~580)
- **Proposal:** 1500 max_tokens (thinking ~400, content ~300, margin ~800)
- **Per-file fix:** 600 max_tokens (thinking ~100, content ~80, margin ~420)

---

## 7. Session Orchestrator Updates

### 7.1 Updated Flow

The `session.py` orchestrator changes minimally. The user-facing flow is identical. The internal change is swapping `generate_game_files()` for `run_generation_pipeline()`:

```python
# Step 3: Generate full game files (CHANGED)
# Old: data = await generate_game_files(proposal, client, config)
# New:
console.print("\n[dim]Generating game files...[/dim]\n")
try:
    data = await run_generation_pipeline(
        proposal, client, config,
        on_progress=lambda msg: console.print(f"  [dim]{msg}[/dim]"),
    )
except YAMLParseError as e:
    console.print(f"[red]Failed to generate valid YAML:[/red]\n{e}")
    return None
```

### 7.2 Progress Display

The decomposed pipeline naturally supports per-file progress updates. The `on_progress` callback shows the user which file is being generated:

```
Generating game files...
  Generating world...
  Generating character: Maya Chen...
  Generating character: Father Joaquin Reyes...
  Generating chapter: The Crash...
  Generating chapter: The Discovery...
  Generating chapter: The Heart...
```

### 7.3 Targeted Revision (Updated)

The current `_revise_and_validate()` sends the entire game YAML and asks the model to rewrite everything. For a small model, identify which file(s) the feedback targets and regenerate only those:

```python
async def _revise_targeted(
    data: dict,
    feedback: str,
    client: AsyncOpenAI,
    config: CreatorLLMConfig,
) -> dict:
    """Identify which file(s) the feedback targets and regenerate them.

    Uses a small classifier call to determine which file(s) to regenerate,
    then calls the appropriate per-file generator with the feedback
    incorporated into the prompt.
    """
    # Step 1: Classify which file(s) to change
    targets = await classify_revision_targets(feedback, data, client, config)

    # Step 2: Regenerate each target using the per-file generators.
    # Each generator accepts an optional `feedback: str | None` parameter
    # that is appended to the user prompt when provided.
    for target in targets:
        if target.file_type == "world":
            data["world"] = await generate_world(
                proposal=_proposal_from_data(data),
                client=client, config=config,
                feedback=feedback,
            )
        elif target.file_type == "character":
            data["characters"][target.stem] = await generate_character(
                proposal=_proposal_from_data(data),
                char_info=_char_info(data, target.stem),
                all_stems=list(data["characters"].keys()),
                prior_characters={
                    k: v for k, v in data["characters"].items()
                    if k != target.stem
                },
                client=client, config=config,
                feedback=feedback,
            )
        elif target.file_type == "chapter":
            data["chapters"][target.stem] = await generate_chapter(
                proposal=_proposal_from_data(data),
                chap_info=_chap_info(data, target.stem),
                characters=data["characters"],
                prior_chapters={
                    k: v for k, v in data["chapters"].items()
                    if k != target.stem
                },
                next_chapter_id=_next_chapter_id(data, target.stem),
                client=client, config=config,
                feedback=feedback,
            )

    # Step 3: Re-assemble game.yaml and enforce consistency
    data["game"] = assemble_game_meta_from_data(data)
    data = enforce_consistency(data)

    return data
```

The classifier call is a tiny LLM call (~100 token prompt):

```python
@dataclass
class RevisionTarget:
    """A single file targeted for revision."""
    file_type: str   # "world", "character", or "chapter"
    stem: str | None # e.g., "maya" or "01-the-crash"; None for world


CLASSIFY_SYSTEM = """\
Given user feedback about a game, identify which file(s) need changes.
Output YAML:

```yaml
targets:
  - file_type: "world|character|chapter"
    stem: "file-stem-or-null"
```

Only list files that the feedback explicitly mentions or clearly implies."""


CLASSIFY_USER = """\
User feedback: {feedback}

Available files:
- world (setting, tone, rules)
{character_list}
{chapter_list}

Which files need changes?"""
```

`classify_revision_targets()` parses the YAML response into a list of `RevisionTarget`. If the classifier fails (YAML parse error, empty response, or ambiguous results), fall back to regenerating all files through the full pipeline.

---

## 8. Backward Compatibility

### 8.1 Large Model Path Preserved

The decomposed pipeline works for both large and small models. For large models, the per-file approach produces equivalent results with slightly more LLM calls but better reliability. There is no separate code path -- the same pipeline handles both.

The only behavioral difference is `max_tokens` and `temperature` values, which are selected based on `config.is_small_model`.

### 8.2 Old `generate_game_files()` Retained as Fallback

The monolithic `generate_game_files()` function in `generator.py` is retained but no longer called by the session. It remains available for testing or as a fallback if the pipeline approach has issues with a specific model. The session always uses `run_generation_pipeline()`.

---

## 9. Implementation Steps

Build in this order. Each step should produce working, tested code before moving on.

### Step 1: Brainstorm Tool

Implement `brainstorm.py` and `scripts/brainstorm.py`:
- `BrainstormSession` class with conversational loop
- Conversation summary via `BRAINSTORM_SUMMARIZE_SYSTEM`
- Context window management (sliding window at ~3000 tokens)
- `--create` flag to launch creator after brainstorming
- CLI menu integration: add "Brainstorm" option before "Create Game"

Write tests:
- Session handles empty conversation (returns None)
- Session handles normal conversation flow (mock LLM)
- Context window truncation kicks in at token limit
- Summary prompt includes conversation content
- `--create` flag passes concept to `create_game()`

### Step 2: Decomposed Proposal

Rewrite `proposer.py` to use 3 focused steps instead of 1 monolithic proposal:
- `generate_setting()` -- setting, tone, rules (Section 4.3 Step 1)
- `generate_characters_proposal()` -- character sketches (Section 4.3 Step 2)
- `generate_chapters_proposal()` -- chapter arc (Section 4.3 Step 3)
- `assemble_proposal()` -- code-assembled proposal dict
- Revision prompts for each step (`SETTING_REVISION_USER`, etc.)
- Accept optional `concept` parameter in `create_game()` from brainstorm

Write tests (mock LLM):
- Each step produces a dict with the correct keys
- Assembly produces a complete proposal dict
- Revision re-generates only the targeted step
- Going back to an earlier step works

### Step 3: Prompt Rewrite

Rewrite all prompts in `prompts.py` for the decomposed pipeline:
- `BRAINSTORM_SYSTEM` / `BRAINSTORM_SUMMARIZE_SYSTEM` -- new (Section 4.2)
- `SETTING_SYSTEM` / `PROPOSAL_CHARACTERS_SYSTEM` / `PROPOSAL_CHAPTERS_SYSTEM` -- new (Section 4.3)
- `SETTING_REVISION_USER` / `CHARACTERS_REVISION_USER` / `CHAPTERS_REVISION_USER` -- new (Section 4.4)
- `WORLD_SYSTEM` / `WORLD_USER` -- new (Section 3.3)
- `CHARACTER_SYSTEM` / `CHARACTER_USER` -- new (Section 3.4)
- `CHAPTER_SYSTEM` / `CHAPTER_USER` -- new (Section 3.5)
- `FIX_SYSTEM` / `FIX_USER` -- updated for per-file fixing (Section 5.2)
- `CLASSIFY_SYSTEM` / `CLASSIFY_USER` -- new (Section 7.3)
- Retain old monolithic prompts: rename `GENERATION_SYSTEM` / `GENERATION_USER` to `LEGACY_GENERATION_SYSTEM` / `LEGACY_GENERATION_USER` in `prompts.py` so `generate_game_files()` in `generator.py` can still import them as a fallback path
- Update existing tests that import the old prompt names

Write tests:
- All prompts are non-empty strings with correct placeholders
- Each system prompt is under 300 tokens (using `len(text) // 4` heuristic)
- Each prompt's YAML example is valid YAML when extracted

### Step 4: Per-File Generators

Implement the individual generators:
- `world_gen.py` -- `generate_world()`
- `character_gen.py` -- `generate_character()`
- `chapter_gen.py` -- `generate_chapter()`

Each generator:
1. Builds a focused prompt from the system template + user template
2. Calls the LLM with appropriate `max_tokens` for the file type
3. Extracts YAML using `extract_yaml()` from `generator.py` (renamed from `_extract_yaml`; also rename `_parse_proposal_response` to `parse_proposal_response` and `_parse_generation_response` to `parse_generation_response` since these are now shared across modules)
4. Validates the extracted dict has the required keys
5. Retries once on YAML parse failure with error feedback

Write tests (mock LLM):
- Each generator produces a dict with the correct keys
- YAML extraction handles fenced and unfenced blocks
- Retry behavior works when first attempt fails
- Character generator includes relationship entries for all other stems
- Chapter generator includes the correct `next` value

### Step 5: Assembler

Implement `assembler.py`:
- `assemble_game_meta()` -- builds game.yaml from generated data
- `assemble_game_meta_from_data()` -- convenience wrapper for revision/fix contexts
- `enforce_consistency()` -- code-enforced cross-file fixes

Write tests:
- `assemble_game_meta()` produces correct character and chapter lists
- `enforce_consistency()` removes self-referencing relationships
- `enforce_consistency()` strips invalid character stems from chapters
- `enforce_consistency()` re-wires broken chapter next-chains

### Step 6: Pipeline Orchestrator

Implement `pipeline.py`:
- `run_generation_pipeline()` -- calls generators in sequence

Write tests (mock LLM):
- Pipeline produces a complete game data dict with all required keys
- Progress callback is invoked for each generation step
- Pipeline handles YAML parse failure in one generator gracefully
- Character generation is sequential (each sees prior characters)
- Chapter generation is sequential (each sees prior chapters)

### Step 7: Per-File Fixer

Update `fixer.py`:
- `fix_file()` -- fix errors in a single file
- `fix_validation_errors()` -- updated to iterate per-file
- `_group_errors_by_file()` -- helper to group errors

Write tests:
- Per-file fix sends only the relevant file data and errors
- Fix loop terminates after `MAX_FIX_ATTEMPTS`
- Cross-reference errors trigger `enforce_consistency()` instead of LLM fix
- Already-valid data passes through without LLM calls

### Step 8: Config Updates

Update `config.py`:
- Add small-model-aware token limits and temperature
- Add `generation_max_tokens`, `generation_temperature`, `fix_max_tokens` properties

Write tests:
- `is_small_model` returns True for 7B model
- Small model properties return lower values
- Large model properties return original values

### Step 9: Session Integration

Update `session.py`:
- `create_game()` accepts optional `concept: str | None` parameter (from brainstorm or typed directly). If provided, skip the concept input prompt.
- Replace monolithic `generate_proposal()` with decomposed 3-step flow (setting → characters → chapters)
- Replace `generate_game_files()` call with `run_generation_pipeline()`
- Replace `_revise_and_validate()` with `_revise_targeted()`
- Add per-file progress display
- CLI menu: add "Brainstorm" as a menu option before "Create Game"

Write tests (mock LLM + mock input):
- Full flow works with decomposed proposal + pipeline
- `concept` parameter skips the input prompt
- 3-step proposal allows iteration at each step
- Progress messages are displayed
- Targeted revision regenerates only the relevant file(s)
- Fallback to full pipeline on classifier failure

### Step 10: Display and Test Updates

- Per-file progress display is handled via the `on_progress` callback in the session orchestrator (Section 7.1), not in `display.py`. No changes needed in `display.py` itself.
- Update existing `tests/test_creator_prompts.py` to import renamed prompt constants (`LEGACY_GENERATION_SYSTEM`, etc.) and add tests for the new per-file prompts.
- Manual testing of the interactive flow is sufficient for display verification.

### Step 11: Live Testing with 7B Model

This is the iterative validation step, following Phase 11's methodology:

**Step 11a -- Test brainstorm.** Run the brainstorm script with the 7B model:
```bash
CREATOR_MODEL=olafangensan-glm-4.7-flash-heretic uv run python scripts/brainstorm.py
```
Have a 5-6 exchange conversation about a noir detective game. Verify:
- Responses are coherent, short, and build on the user's ideas
- The summary at the end captures the key details
- `--create` flag successfully passes the concept to the creator

**Step 11b -- Test decomposed proposal.** Run the full creation flow:
```bash
CREATOR_MODEL=olafangensan-glm-4.7-flash-heretic uv run python -m theact.creator
```
Concept: "A noir detective story in 1940s Los Angeles with a femme fatale and a corrupt cop."
Test the 3-step proposal: iterate on setting, then characters, then chapters separately.

Record:
- How many calls succeed on the first attempt vs. retry
- Which prompts produce malformed YAML
- Whether file sizes are within constraints
- Whether cross-file references are correct
- Total generation time

**Step 11c -- Iterate on prompts.** For each failure:
1. Diagnose: Which prompt produced bad output? What specifically went wrong?
2. Hypothesize: Why did the model fail? Too much in the prompt? Missing example? Wrong temperature?
3. Fix: Modify the prompt in `prompts.py`
4. Re-test: Run the creation flow again
5. Capture: Save problematic model responses as fixtures

**Step 11d -- Playtest the created game.** After successful creation:
```bash
uv run python scripts/playtest.py --game <created-game-id> --turns 10
```
Verify the created game is playable by the 7B gameplay model. Check:
- File sizes don't overwhelm gameplay prompts
- Character personalities produce distinct voices
- Chapter beats give the narrator enough to work with
- Completion conditions are testable by the game state agent

**Step 11e -- Test with 3 different concepts.** Create games from varied concepts:
1. "Survival horror in an abandoned space station with an engineer and a doctor."
2. "A fantasy quest to find a lost artifact, with a wizard mentor and a rogue companion."
3. "A courtroom drama where the player is a lawyer defending an innocent person."

Each should produce valid, playable games.

### Step 12: Regression Tests

Capture fixtures from Step 11 and write regression tests:
- `tests/test_creator_pipeline.py` -- end-to-end pipeline with mocked LLM responses from fixtures
- `tests/test_creator_world_gen.py` -- world generation from real model responses
- `tests/test_creator_character_gen.py` -- character generation with relationship consistency
- `tests/test_creator_chapter_gen.py` -- chapter generation with narrative continuity

---

## 10. Verification

Phase 12 is complete when all of the following pass:

1. **Unit tests pass:** `uv run pytest tests/test_creator_*.py` -- all green
2. **Brainstorm works:** `uv run python scripts/brainstorm.py` runs a multi-turn conversation with the 7B model and produces a usable concept summary. `--create` flag launches the creator with the summary.
3. **Decomposed proposal works:** The 3-step proposal flow (setting → characters → chapters) works with the 7B model. Each step can be independently iterated. Going back to an earlier step works.
4. **Small model generation works:** The 7B model can create a complete game through the decomposed pipeline. Run:
   ```bash
   CREATOR_MODEL=olafangensan-glm-4.7-flash-heretic uv run python -m theact.creator
   ```
   The flow completes without crashing. Generated files pass validation.
5. **Per-file prompts are under 300 tokens:** Each system prompt (BRAINSTORM_SYSTEM, SETTING_SYSTEM, PROPOSAL_CHARACTERS_SYSTEM, PROPOSAL_CHAPTERS_SYSTEM, WORLD_SYSTEM, CHARACTER_SYSTEM, CHAPTER_SYSTEM) is verified under budget by `tests/test_creator_prompts.py`.
6. **Size compliance:** Games created by the 7B model pass the same size checks as Phase 06:
   - `world.yaml` under 150 words
   - Each character YAML under 80 words
   - Each chapter has 4-6 beats, each under 15 words
7. **Cross-file consistency enforced by code:** `enforce_consistency()` is called after generation and after each fix round. No cross-file errors depend on the LLM to fix.
8. **Per-file fixing works:** When a single file has validation errors, only that file is sent to the fixer (not the entire game). Verified by checking LLM call arguments in tests.
9. **Playability:** At least 2 games created by the 7B model can be played for 10 turns via the playtest framework without crashes.
10. **Large model still works:** The decomposed pipeline produces equivalent results when run with a large model. Existing Phase 06 tests still pass.
11. **Backward compatibility:** The old `generate_game_files()` function still exists and works (retained as fallback, tested).

---

## 11. Dependencies

No new packages required. The decomposed pipeline uses the same infrastructure as Phase 06:

- `openai` -- LLM calls (AsyncOpenAI)
- `pydantic` -- validation (via `theact.models`)
- `pyyaml` -- YAML parsing and serialization
- `rich` -- terminal display

New files: the brainstorm tool (`brainstorm.py` + `scripts/brainstorm.py`), per-file generators (`world_gen.py`, `character_gen.py`, `chapter_gen.py`), the pipeline orchestrator (`pipeline.py`), and the assembler (`assembler.py`). All are pure Python with no new dependencies.

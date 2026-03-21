# Phase 06: Game Creation Agent

> **Implementation note:** This agent uses a DIFFERENT, larger model than gameplay. It needs its own LLM configuration (`CreatorLLMConfig`) pointing to a capable model (Claude, GPT-4, etc.). All generated output must pass Pydantic validation from Phase 01 models and respect the tiny file size constraints (~60 words per character, ~6 sentences world).

## 1. Overview

This phase builds an interactive agent that helps users create new games from a concept description. The user describes their idea, the agent proposes a structure, the user iterates on it, and the agent generates all the game definition files -- validated, tiny, and ready for a 7B model to consume during gameplay.

After this phase is complete, we can:
- Run a `create` command from the CLI (or standalone script) that starts an interactive game creation session
- Describe a game concept in natural language and receive a structured proposal (title, characters, chapter outline)
- Iterate on the proposal with feedback before committing to full generation
- Generate all game definition files (`game.yaml`, `world.yaml`, `characters/*.yaml`, `chapters/*.yaml`)
- Validate every generated file against the Phase 01 Pydantic models
- Automatically fix validation failures without user intervention
- Review the final output and request changes before files are written to disk

### Key Design Decision: Model Selection

This agent does NOT use the small 7B gameplay model. Game creation is a one-time creative task that demands strong instruction following, long-range coherence, and the ability to produce precisely formatted output under tight size constraints. It uses a larger, more capable model (Claude, GPT-4, or equivalent) configured separately from the gameplay LLM.

However, everything the agent *produces* must be optimized for a 7B model to consume. Character files must be ~60 words. World files must be ~6 sentences. Chapter beats must be short phrases, not paragraphs. The creative model's job is to compress rich ideas into tiny, precise definitions.

---

## 2. Architecture

### 2.1 Module Layout

All code lives under `src/theact/creator/`:

```
src/theact/creator/
    __init__.py           # Public API: create_game()
    session.py            # CreationSession -- the interactive orchestrator
    proposer.py           # Generate and revise the game proposal
    generator.py          # Generate full game definition files from a proposal
    validator.py          # Validate generated content against Pydantic models, report errors
    fixer.py              # Feed validation errors back to the LLM for correction
    prompts.py            # All prompt templates for the creation agent
    config.py             # CreatorLLMConfig -- model configuration for the creation agent
    writer.py             # Write validated game files to disk
    display.py            # Rich-formatted display helpers for proposals, game files, errors, and warnings
```

### 2.2 Module Relationships

```
           CLI (Phase 04)  or  standalone script
                    |
                    v
         +--------------------+
         |  session.py        |  <-- CreationSession: the orchestrator
         |  create_game()     |
         +--------------------+
            |       |       |
   +--------+   +---+---+  +--------+
   |             |       |          |
   v             v       v          v
proposer.py  generator.py  validator.py  writer.py
(proposal)   (full gen)    (pydantic)    (disk I/O)
   |             |             |
   |             v             |
   |         fixer.py   <------+
   |         (fix errors)
   |             |
   +------+------+
          |
          v
      prompts.py
      config.py
          |
          v
   openai.AsyncOpenAI  (or anthropic client)
```

### 2.3 Dependency Direction

The creator module depends on:
- `theact.models` -- `GameMeta`, `World`, `Character`, `Chapter` for validation
- `theact.io.yaml_io` -- `dump_yaml` for writing files to disk
- `theact.io.save_manager` -- `GAMES_DIR` for the output path
- `rich` -- Console for interactive display (optional, graceful fallback to plain input/output)

The creator module does NOT depend on:
- `theact.llm` -- it uses its own LLM client configuration since it talks to a different model
- `theact.engine` or `theact.agents` -- game creation is independent of gameplay

### 2.4 LLM Client Strategy

The creation agent needs its own OpenAI-compatible client because it uses a different model, endpoint, and API key than the gameplay agents. Two supported configurations:

1. **OpenAI-compatible API** (default) -- any provider exposing the `/v1/chat/completions` endpoint (OpenAI, Anthropic via proxy, local models via vLLM/Ollama, etc.)
2. **Environment-driven** -- configured via `CREATOR_API_KEY`, `CREATOR_BASE_URL`, `CREATOR_MODEL` env vars, falling back to `LLM_API_KEY` / `LLM_*` defaults if not set

This keeps the creation agent decoupled from the gameplay LLM infrastructure while reusing the same OpenAI Python library.

---

## 3. Creation Flow

The creation process is a multi-step interactive loop. Each step either gathers user input or generates content. The user can go backward or request changes at any point.

### 3.1 Flow Diagram

```
[1] User runs create command
         |
         v
[2] Agent asks for game concept
         |
         v
[3] User describes concept (free text)
         |
         v
[4] Agent generates PROPOSAL
    (title, setting summary, character sketches, chapter outline)
         |
         v
[5] User reviews proposal
    - "looks good" --> proceed to [6]
    - "change X"   --> agent revises proposal, back to [5]
    - "quit"       --> abort
         |
         v
[6] Agent generates FULL game files
    (game.yaml, world.yaml, all characters, all chapters)
         |
         v
[7] System validates all files against Pydantic models
    - All pass   --> proceed to [8]
    - Failures   --> agent fixes errors, back to [7] (max 3 attempts)
         |
         v
[8] User reviews final output
    - "looks good" --> proceed to [9]
    - "change X"   --> agent revises specific files, back to [7]
    - "quit"       --> abort
         |
         v
[9] Files written to games/<game-id>/
    Confirmation printed.
```

### 3.2 Step Details

**Step 1-2: Initiation**

The session starts with a simple prompt. No preamble, no menu -- just a question.

```
Creating a new game.

Describe your game concept in a few sentences. Include the genre, setting,
key characters, and what the player does.

>
```

**Step 3: Concept Input**

The user types 1-5 sentences. The agent does not require a specific format. Examples:

- "A noir detective story in 1940s Los Angeles. The player is a private eye investigating a missing person case. There's a femme fatale, a corrupt cop, and a nervous nightclub owner."
- "Sci-fi survival on a space station. Something is picking off the crew one by one. The player is the engineer."

**Step 4: Proposal Generation**

The agent generates a structured proposal. This is displayed to the user in a readable format, not raw YAML. The proposal contains:

- **Title** and **game ID** (slug)
- **Setting** (2-3 sentences)
- **Tone** (2 sentences)
- **Rules** (2 sentences)
- **Characters** (name + one-line role for each)
- **Chapters** (title + one-line summary for each)

Display format:

```
--- GAME PROPOSAL ---

Title: Midnight on Vine
ID: midnight-on-vine

Setting: Los Angeles, 1947. Rain-slicked boulevards, neon signs, and the smell
of cigarette smoke. The war is over but its ghosts linger in every dark alley.

Tone: Second person, present tense. Hard-boiled narration -- short sentences,
sharp observations, moral ambiguity. 100-250 words per turn.

Rules: Every character has an alibi and a lie. The player can miss clues but
never be blocked from progress. Never reveal a character's secret directly.

Characters:
  1. Dolores Vane -- Nightclub singer, the missing person's sister, knows more than she says.
  2. Sergeant Kowalski -- Homicide cop, friendly on the surface, protecting someone.
  3. Eddie Lim -- Nightclub owner, nervous, in debt to dangerous people.

Chapters:
  1. The Office (01-the-office) -- A woman walks into the player's office with
     a photo and a story that doesn't add up.
  2. The Nightclub (02-the-nightclub) -- The player visits the Blue Moon to ask
     questions. Everyone has an answer, none of them match.
  3. The Truth (03-the-truth) -- The threads converge. Someone is lying about
     the night of the disappearance.

---------------------

What do you think? Type feedback to revise, or "ok" to proceed.

>
```

**Step 5: Iteration**

The user can request any number of changes. Each revision re-generates the full proposal (not a patch). The agent sees the previous proposal plus the user's feedback.

Examples of valid feedback:
- "Add a fourth character -- a journalist who's been investigating the same case"
- "Change the tone to be more literary, less hard-boiled"
- "The third chapter should be about a car chase, not a conversation"
- "Make it 4 chapters instead of 3"
- "The setting should be San Francisco, not LA"

**Step 6: Full Generation**

Once the user approves the proposal, the agent generates every file. This is done in a single LLM call that produces all content at once. The prompt includes the approved proposal plus explicit size constraints and format examples.

The output is a structured block containing all file contents: `game.yaml`, `world.yaml`, each character YAML, and each chapter YAML.

**Step 7: Validation**

Every generated file is parsed through the corresponding Pydantic model:
- `game.yaml` -> `GameMeta`
- `world.yaml` -> `World`
- `characters/<name>.yaml` -> `Character`
- `chapters/<id>.yaml` -> `Chapter`

Additionally, cross-file consistency checks:
- All characters listed in `game.yaml` have corresponding character files
- All chapters listed in `game.yaml` have corresponding chapter files
- Chapter `characters` lists reference valid character file stems
- Chapter `next` fields form a valid chain ending in `None`
- Character `relationships` keys reference other character file stems

If validation fails, the errors are fed back to the LLM with the original output and a request to fix specifically the broken fields. Up to 3 fix attempts. If all fail, the user is shown the errors and asked to provide guidance.

**Step 8: User Review**

The final generated content is displayed file-by-file. The user can request targeted changes ("make Maya's personality more sarcastic", "the second chapter needs a beat about finding a weapon"). Targeted changes re-generate only the affected file(s) and re-validate.

**Step 9: Write to Disk**

Once approved, files are written to `games/<game-id>/`. If the directory already exists, the user is warned and must confirm overwrite.

---

## 4. Prompt Design

All prompts live in `src/theact/creator/prompts.py`. These prompts are for a capable model (Claude/GPT-4 class), so they can be more detailed than the 7B gameplay prompts. However, they must be ruthlessly specific about the output size constraints.

### 4.1 Proposal Prompt

```python
PROPOSAL_SYSTEM = """\
You are a game designer creating a text-based RPG for an AI-driven engine.

The engine uses a SMALL language model (7B parameters) to run the game at
runtime. This means every game definition file must be TINY and PRECISE.
The small model has an 8K token context window. Verbose descriptions will
overwhelm it.

Your task: given a user's game concept, create a structured game proposal.

OUTPUT FORMAT -- respond with exactly this YAML structure:

```yaml
title: "Display Title"
id: "url-safe-slug"
setting: |
  Where and when. 2-3 sentences max. Concrete sensory details.
tone: |
  Narrative voice and style. 2 sentences max.
  Must specify: person (second), tense (present), word count per turn (100-250).
rules: |
  Key narrative constraints. 2 sentences max. What the narrator must
  and must not do.
characters:
  - stem: "file-stem"
    name: "Display Name"
    role: "One-line role in the story"
  - stem: "another-character"
    name: "Another Name"
    role: "One-line role"
chapters:
  - id: "01-slug"
    title: "Chapter Title"
    summary: "One sentence about what happens"
  - id: "02-slug"
    title: "Chapter Title"
    summary: "One sentence about what happens"
```

CONSTRAINTS:
- 1-3 characters. The runtime model supports a maximum of 3 AI characters.
  More than 3 overwhelms the small model's ability to maintain distinct voices.
  If the user's concept implies more, consolidate or cut.
- 3-5 chapters. Each chapter should cover 5-10 turns of gameplay.
- Character stems are lowercase, no spaces (e.g., "maya", "father-joaquin").
  These stems are used as relationship keys and chapter character references.
- Chapter IDs are numbered with slug (e.g., "01-the-crash", "02-survival").
- Setting, tone, and rules: 2-3 sentences EACH. Not paragraphs. Sentences.
- Every word must earn its place. The runtime model sees these verbatim."""
```

### 4.2 Proposal Revision Prompt

```python
PROPOSAL_REVISION_USER = """\
Here is the current proposal:

```yaml
{current_proposal}
```

The user wants changes:
{user_feedback}

Generate a revised proposal. Same YAML format. Apply the requested changes
while keeping everything else consistent. If adding characters or chapters,
update all cross-references."""
```

### 4.3 Full Generation Prompt

This is the most critical prompt. It must produce all game files in one response with strict size constraints.

```python
GENERATION_SYSTEM = """\
You are generating game definition files for a text-based RPG engine.

CRITICAL SIZE CONSTRAINTS:
The runtime engine uses a 7B-parameter model with an 8K token context.
Every file you produce is injected verbatim into the model's prompt.
Files that are too large will cause the runtime model to fail.

HARD LIMITS:
- world.yaml: setting ~2 sentences, tone ~2 sentences, rules ~2 sentences.
  Total file: ~6 sentences. Under 120 words.
- Each character YAML: ~60 words TOTAL across all fields.
  - role: 1 short sentence (under 12 words)
  - personality: 2-3 SHORT sentences (under 40 words)
  - secret: 1 sentence (under 15 words)
  - relationships: one-line per relationship (under 12 words each)
- Each chapter YAML: under 120 words total.
  - summary: 2-3 sentences
  - beats: 4-6 SHORT PHRASES (not sentences, not paragraphs -- phrases
    like "Player finds the locked door" or "Maya reveals her secret")
  - completion: 1 sentence stating what must be true for the chapter to end

STYLE GUIDE FOR CHARACTERS:
- Personality should define speech patterns and behavior, not backstory.
- Secrets are hidden motivations or knowledge -- one punchy sentence.
- Relationships are one character's stance toward another -- terse and opinionated.
- Relationship KEYS must be the OTHER character's file stem (e.g., "maya",
  not "Maya Chen"). Each character must have a relationship entry for every
  other character, and must NOT have an entry for themselves.

STYLE GUIDE FOR CHAPTERS:
- Beats are milestones the narrator steers toward, not a script.
- The completion condition is a clear, testable state ("Player and Maya have
  reached the cave entrance" not "the chapter feels complete").
- The last chapter's `next` field must be null.

STRUCTURAL LIMITS:
- Maximum 3 characters. The runtime model cannot maintain distinct voices
  for more than 3 AI characters.
- 3-5 chapters. Each chapter should cover 5-10 turns of gameplay.
- The last chapter's `next` field must be null. All others must chain forward.

STYLE GUIDE FOR WORLD:
- Setting is WHERE and WHEN. Concrete. Sensory.
- Tone defines the narrative voice. Must specify person, tense, word count.
- Rules are hard constraints for the narrator. Things it must/must not do."""


GENERATION_USER = """\
Generate all game definition files for this approved proposal:

```yaml
{proposal}
```

Output ALL files in a single YAML block with this exact structure:

```yaml
game:
  id: "{game_id}"
  title: "{title}"
  description: "One-sentence pitch"
  characters:
    - "{char_stem_1}"
    - "{char_stem_2}"
  chapters:
    - "{chapter_id_1}"
    - "{chapter_id_2}"

world:
  setting: |
    2-3 sentences.
  tone: |
    2 sentences.
  rules: |
    2 sentences.

characters:
  {char_stem_1}:
    name: "Display Name"
    role: "One-line role"
    personality: |
      2-3 short sentences.
    secret: "One sentence."
    relationships:
      {other_char_stem}: "One-line stance"

  {char_stem_2}:
    name: "Display Name"
    role: "One-line role"
    personality: |
      2-3 short sentences.
    secret: "One sentence."
    relationships:
      {other_char_stem}: "One-line stance"

chapters:
  {chapter_id_1}:
    id: "{chapter_id_1}"
    title: "Chapter Title"
    summary: |
      2-3 sentences.
    beats:
      - "Short phrase"
      - "Short phrase"
      - "Short phrase"
      - "Short phrase"
    completion: "One sentence condition"
    characters:
      - "{char_stem}"
    next: "{chapter_id_2}"

  {chapter_id_2}:
    id: "{chapter_id_2}"
    title: "Chapter Title"
    summary: |
      2-3 sentences.
    beats:
      - "Short phrase"
      - "Short phrase"
      - "Short phrase"
      - "Short phrase"
    completion: "One sentence condition"
    characters:
      - "{char_stem}"
    next: null
```

Remember: CHARACTER FILES ~60 WORDS. WORLD FILE ~6 SENTENCES. BEATS ARE
SHORT PHRASES. This is not creative writing -- it is compressed game data
that a small model will parse."""
```

### 4.4 Fix Prompt

```python
FIX_SYSTEM = """\
You are fixing validation errors in game definition files for a text RPG engine.
You will receive the generated content and a list of errors.
Fix ONLY the errors. Do not change anything else.
Output the complete corrected YAML in the same format as the input."""


FIX_USER = """\
The following game files failed validation:

ERRORS:
{errors}

ORIGINAL OUTPUT:
```yaml
{original_output}
```

Fix the errors and output the complete corrected YAML. Same format."""
```

### 4.5 Targeted Revision Prompt

```python
TARGETED_REVISION_USER = """\
The user wants changes to specific parts of the generated game:

USER REQUEST:
{user_feedback}

CURRENT FILES:
```yaml
{current_output}
```

Apply the requested changes. Output the COMPLETE YAML (all files), not just
the changed parts. Maintain all size constraints:
- Character files: ~60 words total
- World file: ~6 sentences
- Chapter beats: 4-6 short phrases
- Chapter summaries: 2-3 sentences"""
```

---

## 5. Validation

### 5.0 YAML Parsing (`generator.py` — `_parse_generation_response`)

Before Pydantic validation can run, the raw LLM response text must be parsed into a Python dict. This is a distinct failure mode from Pydantic validation — the model may produce malformed YAML, omit the fenced code block delimiters, or return partial output.

```python
# In src/theact/creator/generator.py

import re
import yaml


class YAMLParseError(Exception):
    """Raised when the LLM response cannot be parsed as YAML."""
    pass


def _parse_generation_response(response_text: str) -> dict:
    """
    Extract and parse YAML from the LLM's response.

    Handles three cases:
    1. YAML inside a fenced code block (```yaml ... ```)
    2. Raw YAML (no fencing)
    3. Malformed output (raises YAMLParseError)

    Returns:
        dict with keys: "game", "world", "characters", "chapters"

    Raises:
        YAMLParseError: if YAML cannot be extracted or parsed
    """
    # Try to extract from fenced code block first
    match = re.search(r"```(?:yaml)?\s*\n(.*?)```", response_text, re.DOTALL)
    yaml_text = match.group(1) if match else response_text

    try:
        data = yaml.safe_load(yaml_text)
    except yaml.YAMLError as e:
        raise YAMLParseError(
            f"LLM response is not valid YAML: {e}\n"
            f"First 200 chars of response: {response_text[:200]}"
        )

    if not isinstance(data, dict):
        raise YAMLParseError(
            f"Expected a YAML mapping, got {type(data).__name__}. "
            f"First 200 chars: {response_text[:200]}"
        )

    required_keys = {"game", "world", "characters", "chapters"}
    missing = required_keys - set(data.keys())
    if missing:
        raise YAMLParseError(
            f"YAML is missing required top-level keys: {missing}"
        )

    return data
```

When `_parse_generation_response` raises `YAMLParseError`, the caller in `generator.py` should retry the LLM call up to 2 times with the error message appended. If all retries fail, the error propagates to the session, which displays the parse error and aborts.

### 5.1 Pydantic Validation (`validator.py`)

The validator takes the parsed YAML output (a dict with `game`, `world`, `characters`, `chapters` keys) and validates each section against its Pydantic model.

```python
# src/theact/creator/validator.py

from dataclasses import dataclass, field
from theact.models.game import GameMeta
from theact.models.world import World
from theact.models.character import Character
from theact.models.chapter import Chapter


@dataclass
class ValidationError:
    """A single validation error."""
    file: str           # e.g. "characters/maya.yaml"
    field: str          # e.g. "relationships"
    message: str        # human-readable error description


@dataclass
class ValidationResult:
    """Result of validating all generated game files."""
    valid: bool
    errors: list[ValidationError] = field(default_factory=list)
    game: GameMeta | None = None
    world: World | None = None
    characters: dict[str, Character] = field(default_factory=dict)
    chapters: dict[str, Chapter] = field(default_factory=dict)


def validate_game_data(data: dict) -> ValidationResult:
    """
    Validate all game data against Pydantic models.

    Args:
        data: dict with keys "game", "world", "characters", "chapters"
              where "characters" and "chapters" are dicts keyed by stem/id.

    Returns:
        ValidationResult with all errors collected (not raised).
    """
    errors: list[ValidationError] = []
    game = None
    world = None
    characters = {}
    chapters = {}

    # 1. Validate game.yaml
    try:
        game = GameMeta.model_validate(data.get("game", {}))
    except Exception as e:
        errors.append(ValidationError("game.yaml", "", str(e)))

    # 2. Validate world.yaml
    try:
        world = World.model_validate(data.get("world", {}))
    except Exception as e:
        errors.append(ValidationError("world.yaml", "", str(e)))

    # 3. Validate each character
    for stem, char_data in data.get("characters", {}).items():
        try:
            characters[stem] = Character.model_validate(char_data)
        except Exception as e:
            errors.append(ValidationError(
                f"characters/{stem}.yaml", "", str(e)
            ))

    # 4. Validate each chapter
    for cid, chap_data in data.get("chapters", {}).items():
        try:
            chapters[cid] = Chapter.model_validate(chap_data)
        except Exception as e:
            errors.append(ValidationError(
                f"chapters/{cid}.yaml", "", str(e)
            ))

    # 5. Character count check (requirements mandate 1-3 AI characters max)
    if len(characters) > 3:
        errors.append(ValidationError(
            "game.yaml", "characters",
            f"Too many characters ({len(characters)}). The runtime engine "
            "supports a maximum of 3 AI characters. Consolidate or remove."
        ))
    if len(characters) == 0:
        errors.append(ValidationError(
            "game.yaml", "characters",
            "No characters defined. At least 1 character is required."
        ))

    # 6. Cross-file consistency checks
    if game:
        errors.extend(_check_cross_references(game, characters, chapters))

    return ValidationResult(
        valid=len(errors) == 0,
        errors=errors,
        game=game,
        world=world,
        characters=characters,
        chapters=chapters,
    )


def _check_cross_references(
    game: GameMeta,
    characters: dict[str, Character],
    chapters: dict[str, Chapter],
) -> list[ValidationError]:
    """Check that all cross-references between files are consistent."""
    errors = []

    # Characters listed in game.yaml must have files
    for stem in game.characters:
        if stem not in characters:
            errors.append(ValidationError(
                "game.yaml", "characters",
                f"Character '{stem}' listed in game.yaml but no file generated"
            ))

    # Character files not listed in game.yaml
    for stem in characters:
        if stem not in game.characters:
            errors.append(ValidationError(
                f"characters/{stem}.yaml", "",
                f"Character file exists but '{stem}' not listed in game.yaml"
            ))

    # Chapters listed in game.yaml must have files
    for cid in game.chapters:
        if cid not in chapters:
            errors.append(ValidationError(
                "game.yaml", "chapters",
                f"Chapter '{cid}' listed in game.yaml but no file generated"
            ))

    # Chapter next-chain validation
    for cid, chapter in chapters.items():
        if chapter.next and chapter.next not in chapters:
            errors.append(ValidationError(
                f"chapters/{cid}.yaml", "next",
                f"Chapter '{cid}' references next='{chapter.next}' which does not exist"
            ))
        # Characters referenced in chapters must exist
        for char_stem in chapter.characters:
            if char_stem not in characters and char_stem not in game.characters:
                errors.append(ValidationError(
                    f"chapters/{cid}.yaml", "characters",
                    f"Chapter '{cid}' references character '{char_stem}' which does not exist"
                ))

    # Relationship keys must reference valid character file stems.
    #
    # NOTE: The Phase 01 Character model docstring says
    #   relationships: dict[str, str]  # name -> one-line relationship stance
    # but the actual Lost Island examples use file STEMS as keys
    # (e.g., "joaquin", not "Father Joaquin Reyes"). The creator must use
    # stems consistently. The generation prompt's template shows
    # {other_char_stem} as the relationship key, which is correct.
    #
    # Each character must NOT have a relationship entry for themselves.
    for stem, char in characters.items():
        for rel_name in char.relationships:
            if rel_name == stem:
                errors.append(ValidationError(
                    f"characters/{stem}.yaml", "relationships",
                    f"Character '{stem}' has a relationship with itself"
                ))
            elif rel_name not in characters and rel_name not in game.characters:
                errors.append(ValidationError(
                    f"characters/{stem}.yaml", "relationships",
                    f"Relationship key '{rel_name}' does not match any character stem"
                ))

    # Chapter order: next-chain should match game.yaml chapter order.
    # This also implicitly prevents circular chains — the game.yaml list
    # defines a linear order, and the last chapter must have next=None.
    chapter_list = game.chapters
    for i, cid in enumerate(chapter_list):
        if cid not in chapters:
            continue
        expected_next = chapter_list[i + 1] if i + 1 < len(chapter_list) else None
        actual_next = chapters[cid].next
        if actual_next != expected_next:
            errors.append(ValidationError(
                f"chapters/{cid}.yaml", "next",
                f"Expected next='{expected_next}' but got next='{actual_next}'"
            ))

    # Explicit circular chain detection: follow next pointers and verify
    # we reach None within len(chapters) steps. This catches cycles even
    # if the game.yaml order check is bypassed or incomplete.
    if chapter_list and chapter_list[0] in chapters:
        visited = set()
        current = chapter_list[0]
        while current is not None:
            if current in visited:
                errors.append(ValidationError(
                    f"chapters/{current}.yaml", "next",
                    f"Circular chapter chain detected: '{current}' is reached twice"
                ))
                break
            visited.add(current)
            current = chapters[current].next if current in chapters else None

    return errors
```

### 5.2 Size Warnings

In addition to structural validation, the validator produces warnings (not errors) for files that exceed size guidelines. These are displayed to the user but do not block generation.

```python
def check_size_warnings(
    world: World | None,
    characters: dict[str, Character],
    chapters: dict[str, Chapter],
) -> list[str]:
    """Check for files that exceed recommended size limits."""
    warnings = []

    if world:
        word_count = len(f"{world.setting} {world.tone} {world.rules}".split())
        if word_count > 150:
            warnings.append(
                f"world.yaml is {word_count} words (target: under 120). "
                "Runtime model may struggle with long world definitions."
            )

    for stem, char in characters.items():
        word_count = len(
            f"{char.role} {char.personality} {char.secret} "
            f"{' '.join(char.relationships.values())}".split()
        )
        if word_count > 80:
            warnings.append(
                f"characters/{stem}.yaml is {word_count} words (target: ~60). "
                "Consider trimming personality or relationships."
            )

    for cid, chap in chapters.items():
        if len(chap.beats) > 6:
            warnings.append(
                f"chapters/{cid}.yaml has {len(chap.beats)} beats (target: 4-6). "
                "Too many beats confuse the runtime narrator."
            )
        if len(chap.beats) < 4:
            warnings.append(
                f"chapters/{cid}.yaml has {len(chap.beats)} beats (target: 4-6). "
                "Too few beats leave the narrator without direction."
            )
        beat_word_counts = [len(b.split()) for b in chap.beats]
        for i, wc in enumerate(beat_word_counts):
            if wc > 15:
                warnings.append(
                    f"chapters/{cid}.yaml beat {i+1} is {wc} words. "
                    "Beats should be short phrases (under 12 words)."
                )

    return warnings
```

### 5.3 Validation-Fix Loop

The fix loop in `fixer.py`:

```python
# src/theact/creator/fixer.py

import yaml
from openai import AsyncOpenAI

from theact.creator.validator import validate_game_data, ValidationResult
from theact.creator.generator import _parse_generation_response, YAMLParseError
from theact.creator.prompts import FIX_SYSTEM, FIX_USER


def _serialize_game_data(data: dict) -> str:
    """Serialize a game data dict to a YAML string for prompt injection."""
    return yaml.dump(data, default_flow_style=False, allow_unicode=True, sort_keys=False)


async def _call_llm(client: AsyncOpenAI, config, messages: list[dict]) -> str:
    """Call the LLM and return the response text content."""
    response = await client.chat.completions.create(
        model=config.model,
        messages=messages,
        temperature=config.temperature,
        max_tokens=config.max_tokens,
    )
    return response.choices[0].message.content

MAX_FIX_ATTEMPTS = 3


async def fix_validation_errors(
    data: dict,
    validation_result: ValidationResult,
    client,   # AsyncOpenAI
    config,   # CreatorLLMConfig
) -> tuple[dict, ValidationResult]:
    """
    Attempt to fix validation errors by sending them back to the LLM.

    Returns the (possibly fixed) data and final validation result.
    Tries up to MAX_FIX_ATTEMPTS times.

    Handles two failure modes per attempt:
    1. LLM produces invalid YAML (YAMLParseError) — counts as a failed attempt
    2. LLM produces valid YAML that fails Pydantic validation — feeds errors back
    """
    current_data = data
    current_result = validation_result

    for attempt in range(MAX_FIX_ATTEMPTS):
        if current_result.valid:
            return current_data, current_result

        error_text = "\n".join(
            f"- {e.file}: {e.message}" for e in current_result.errors
        )

        # Re-serialize current_data to YAML string for the prompt
        yaml_text = _serialize_game_data(current_data)

        messages = [
            {"role": "system", "content": FIX_SYSTEM},
            {"role": "user", "content": FIX_USER.format(
                errors=error_text,
                original_output=yaml_text,
            )},
        ]

        response = await _call_llm(client, config, messages)
        try:
            current_data = _parse_generation_response(response)
        except YAMLParseError:
            # LLM produced unparseable output — keep previous data and
            # let the loop retry with the same errors
            continue
        current_result = validate_game_data(current_data)

    return current_data, current_result
```

---

## 6. CLI Integration

### 6.1 New Menu Option

Phase 04 defines a main menu with options: New Game, Continue Game, Delete Save, Quit. This phase adds a fifth option:

```
  1. New Game
  2. Continue Game
  3. Create Game          <-- NEW
  4. Delete Save
  5. Quit
```

The "Create Game" option launches the `CreationSession`.

### 6.2 New Slash Command

During gameplay, a `/create` slash command is not appropriate (game creation is a separate workflow). However, a standalone entry point is useful:

```
uv run python -m theact.creator
```

This runs the creation session directly without going through the game menu. The `src/theact/creator/__main__.py` file provides this entry point:

```python
# src/theact/creator/__main__.py

import asyncio
from theact.creator.session import create_game


def main():
    asyncio.run(create_game())


if __name__ == "__main__":
    main()
```

### 6.3 Menu Integration (changes to Phase 04 files)

Two Phase 04 files must be updated:

**`cli/app.py`** — Add `"create"` as a recognized choice in `_main_menu()` and add a handler case in the `run()` method. The existing Phase 04 menu has 4 options (New Game, Continue Game, Delete Save, Quit); this becomes 5 options with "Create Game" inserted at position 3.

**`cli/menu.py`** — Add a `display_main_menu()` update to include the new option, or update the existing menu rendering to include "Create Game".

When the user selects "Create Game", the handler calls:

```python
from theact.creator.session import create_game

# Inside the app.py run loop:
elif choice == "create":
    await create_game()
    # After creation completes (or aborts), loop back to menu.
    # The new game will automatically appear in "New Game" list
    # because list_games() scans the games/ directory.
```

After creation completes, the menu refreshes and the new game appears in the "New Game" list.

---

## 7. Session Orchestrator

The `CreationSession` in `session.py` is the central coordinator. It manages the interactive loop and delegates to specialized modules.

```python
# src/theact/creator/session.py

import asyncio
from pathlib import Path
from rich.console import Console

from theact.creator.config import CreatorLLMConfig, load_creator_config
from theact.creator.proposer import generate_proposal, revise_proposal
from theact.creator.generator import generate_game_files, YAMLParseError
from theact.creator.validator import validate_game_data, check_size_warnings
from theact.creator.fixer import fix_validation_errors
from theact.creator.writer import write_game_files
from theact.creator.display import (
    display_proposal, display_game_files,
    display_validation_errors, display_size_warnings,
)

console = Console()


async def create_game() -> Path | None:
    """
    Run the interactive game creation flow.

    Returns the path to the created game directory, or None if aborted.
    """
    config = load_creator_config()
    client = _create_client(config)

    # Step 1: Get concept
    console.print("\n[bold]Creating a new game.[/bold]\n")
    console.print(
        "Describe your game concept in a few sentences. Include the genre, "
        "setting, key characters, and what the player does.\n"
    )
    concept = _get_input()
    if not concept:
        return None

    # Step 2: Generate and iterate on proposal
    console.print("\n[dim]Generating proposal...[/dim]\n")
    proposal = await generate_proposal(concept, client, config)
    display_proposal(proposal)

    while True:
        feedback = _get_input(
            prompt="Type feedback to revise, or \"ok\" to proceed: "
        )
        if not feedback:
            return None
        if feedback.strip().lower() in ("ok", "looks good", "good", "yes", "y"):
            break
        console.print("\n[dim]Revising proposal...[/dim]\n")
        proposal = await revise_proposal(proposal, feedback, client, config)
        display_proposal(proposal)

    # Step 3: Generate full game files
    console.print("\n[dim]Generating game files...[/dim]\n")
    try:
        data = await generate_game_files(proposal, client, config)
    except YAMLParseError as e:
        console.print(f"[red]Failed to generate valid YAML after retries:[/red]\n{e}")
        console.print("[dim]Please try again with a different concept.[/dim]")
        return None

    # Step 4: Validate
    result = validate_game_data(data)
    if not result.valid:
        console.print("[yellow]Fixing validation errors...[/yellow]\n")
        data, result = await fix_validation_errors(data, result, client, config)

    if not result.valid:
        display_validation_errors(result.errors)
        console.print(
            "[red]Could not fix all errors automatically. "
            "Please adjust your concept and try again.[/red]"
        )
        return None

    # Step 5: Size warnings
    warnings = check_size_warnings(result.world, result.characters, result.chapters)
    if warnings:
        display_size_warnings(warnings)

    # Step 6: User review
    display_game_files(result)

    while True:
        feedback = _get_input(
            prompt="Type feedback to revise, or \"ok\" to finalize: "
        )
        if not feedback:
            return None
        if feedback.strip().lower() in ("ok", "looks good", "good", "yes", "y"):
            break
        console.print("\n[dim]Revising...[/dim]\n")
        data = await _revise_and_validate(data, feedback, client, config)
        result = validate_game_data(data)
        if not result.valid:
            data, result = await fix_validation_errors(
                data, result, client, config
            )
        if result.valid:
            display_game_files(result)
        else:
            display_validation_errors(result.errors)
            console.print("[yellow]Some errors remain. You may continue revising.[/yellow]")

    # Step 7: Write to disk
    game_id = result.game.id
    overwrite = False
    game_dir = Path("games") / game_id
    if game_dir.exists():
        confirm = _get_input(
            f"Game directory '{game_dir}' already exists. Overwrite? (y/n): "
        )
        if not confirm or confirm.lower() not in ("y", "yes"):
            console.print("[dim]Aborted — existing game not overwritten.[/dim]")
            return None
        overwrite = True

    game_path = write_game_files(game_id, result, overwrite=overwrite)
    console.print(f"\n[green]Game created at:[/green] {game_path}\n")
    return game_path


async def _revise_and_validate(
    data: dict,
    feedback: str,
    client,         # AsyncOpenAI
    config,         # CreatorLLMConfig
) -> dict:
    """
    Revise specific files based on user feedback and return updated data.

    Sends the current game data and user feedback to the LLM using
    TARGETED_REVISION_USER, then parses the response. If YAML parsing
    fails, retries up to 2 times. Returns the (possibly revised) data dict.
    """
    from theact.creator.prompts import GENERATION_SYSTEM, TARGETED_REVISION_USER
    from theact.creator.generator import _parse_generation_response, YAMLParseError

    yaml_text = _serialize_game_data(data)
    messages = [
        {"role": "system", "content": GENERATION_SYSTEM},
        {"role": "user", "content": TARGETED_REVISION_USER.format(
            user_feedback=feedback,
            current_output=yaml_text,
        )},
    ]

    for attempt in range(3):
        response = await _call_llm(client, config, messages)
        try:
            return _parse_generation_response(response)
        except YAMLParseError as e:
            if attempt == 2:
                console.print(f"[red]Failed to parse revised output: {e}[/red]")
                return data  # Return unmodified data on total failure
            messages.append({"role": "assistant", "content": response})
            messages.append({"role": "user", "content": f"That output was not valid YAML: {e}\nPlease try again."})

    return data


def _get_input(prompt: str = "> ") -> str | None:
    """Get input from the user. Returns None on EOF/Ctrl-C."""
    try:
        return console.input(prompt).strip()
    except (EOFError, KeyboardInterrupt):
        console.print("\n[dim]Aborted.[/dim]")
        return None


# NOTE: _create_client, _call_llm, and _serialize_game_data are shared
# helpers also used by fixer.py and _revise_and_validate. During
# implementation, move them to a shared module (e.g., creator/utils.py)
# rather than duplicating.

def _create_client(config: CreatorLLMConfig):
    """Create an AsyncOpenAI client from the creator config."""
    from openai import AsyncOpenAI
    return AsyncOpenAI(
        base_url=config.base_url,
        api_key=config.api_key,
    )


async def _call_llm(client, config: CreatorLLMConfig, messages: list[dict]) -> str:
    """Call the LLM and return the response text content."""
    response = await client.chat.completions.create(
        model=config.model,
        messages=messages,
        temperature=config.temperature,
        max_tokens=config.max_tokens,
    )
    return response.choices[0].message.content


def _serialize_game_data(data: dict) -> str:
    """Serialize a game data dict to a YAML string for prompt injection."""
    import yaml
    return yaml.dump(data, default_flow_style=False, allow_unicode=True, sort_keys=False)
```

---

## 8. Configuration

```python
# src/theact/creator/config.py

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class CreatorLLMConfig:
    """LLM configuration for the game creation agent.

    Uses a separate, more capable model than the gameplay agents.
    Checks CREATOR_* env vars first, then LLM_* env vars.

    IMPORTANT: The default LLM_MODEL (olafangensan-glm-4.7-flash-heretic)
    is a 7B model that CANNOT reliably perform game creation. If no
    CREATOR_MODEL is set and the resolved model is the 7B default, a
    warning is printed at session start. The user should set CREATOR_MODEL
    to a capable model (e.g., gpt-4o, claude-sonnet-4-20250514).
    """
    base_url: str = "https://api.openai.com/v1"
    api_key: str = ""
    model: str = "olafangensan-glm-4.7-flash-heretic"
    temperature: float = 0.7      # moderate creativity for game design
    max_tokens: int = 4096        # full generation needs space
    proposal_max_tokens: int = 1500  # proposals are shorter

    @property
    def is_small_model(self) -> bool:
        """True if the resolved model is the 7B gameplay model.
        Game creation requires a larger, more capable model.
        """
        return "heretic" in self.model.lower()


# The 7B model used for gameplay -- game creation should NOT use this.
_GAMEPLAY_MODEL = "olafangensan-glm-4.7-flash-heretic"


def load_creator_config() -> CreatorLLMConfig:
    """Load creator config from environment variables.

    Checks CREATOR_* vars first, falls back to LLM_* vars.
    Prints a warning if the resolved model is the small 7B gameplay model,
    since game creation requires a more capable model.
    """
    config = CreatorLLMConfig(
        base_url=os.getenv(
            "CREATOR_BASE_URL",
            os.getenv("LLM_BASE_URL", "https://api.openai.com/v1"),
        ),
        api_key=os.getenv(
            "CREATOR_API_KEY",
            os.getenv("LLM_API_KEY", ""),
        ),
        model=os.getenv(
            "CREATOR_MODEL",
            os.getenv("LLM_MODEL", _GAMEPLAY_MODEL),
        ),
    )

    if config.is_small_model:
        import warnings
        warnings.warn(
            "No CREATOR_MODEL set — falling back to the 7B gameplay model "
            f"({config.model}). Game creation works best with a larger model. "
            "Set CREATOR_MODEL=gpt-4o (or similar) in your .env file.",
            stacklevel=2,
        )

    if not config.api_key:
        raise ValueError(
            "No API key found. Set CREATOR_API_KEY or LLM_API_KEY in .env."
        )

    return config
```

The `.env.example` file should be updated with:

```
# Game Creation Agent (RECOMMENDED — uses a more capable model than gameplay)
# Without these, the creator falls back to LLM_* settings and whatever model
# which cannot reliably generate game files. Set at least CREATOR_MODEL.
# CREATOR_API_KEY=sk-...           # Required if using a different provider
# CREATOR_BASE_URL=https://api.openai.com/v1
# CREATOR_MODEL=gpt-4o             # Or: claude-sonnet-4-20250514, etc.
```

---

## 9. File Writer

```python
# src/theact/creator/writer.py

from pathlib import Path

from theact.creator.validator import ValidationResult
from theact.io.yaml_io import dump_yaml
from theact.io.save_manager import GAMES_DIR


def write_game_files(
    game_id: str,
    result: ValidationResult,
    overwrite: bool = False,
) -> Path:
    """
    Write all validated game files to games/<game_id>/.

    Args:
        game_id: The game's URL-safe slug.
        result: A valid ValidationResult with all models populated.
        overwrite: If True, overwrite an existing game directory.
                   If False and the directory exists, raise FileExistsError.

    Returns:
        Path to the created game directory.

    Raises:
        FileExistsError: If the game directory already exists and
                         overwrite is False.
    """
    game_dir = GAMES_DIR / game_id
    if game_dir.exists() and not overwrite:
        raise FileExistsError(
            f"Game directory already exists: {game_dir}. "
            "Pass overwrite=True to replace it."
        )
    game_dir.mkdir(parents=True, exist_ok=True)

    # game.yaml
    dump_yaml(game_dir / "game.yaml", result.game)

    # world.yaml
    dump_yaml(game_dir / "world.yaml", result.world)

    # characters/
    char_dir = game_dir / "characters"
    char_dir.mkdir(exist_ok=True)
    for stem, character in result.characters.items():
        dump_yaml(char_dir / f"{stem}.yaml", character)

    # chapters/
    chap_dir = game_dir / "chapters"
    chap_dir.mkdir(exist_ok=True)
    for cid, chapter in result.chapters.items():
        dump_yaml(chap_dir / f"{cid}.yaml", chapter)

    return game_dir
```

---

## 10. Implementation Steps

Build in this order. Each step should produce working, tested code before moving to the next.

### Step 1: Package scaffolding

- Create `src/theact/creator/` package with `__init__.py`
- Create all module files as empty stubs: `session.py`, `proposer.py`, `generator.py`, `validator.py`, `fixer.py`, `prompts.py`, `config.py`, `writer.py`, `display.py`, `__main__.py`
- Add any new dependencies to `pyproject.toml` (likely none -- reuses `openai`, `pydantic`, `pyyaml`, `rich`)
- Verify `uv sync` works

### Step 2: Configuration

- Implement `config.py` with `CreatorLLMConfig` and `load_creator_config()`
- Update `.env.example` with `CREATOR_*` variables
- Write `tests/test_creator_config.py`:
  - Test that `load_creator_config()` reads `CREATOR_*` env vars
  - Test fallback to `LLM_*` env vars
  - Test that a warning is issued when the resolved model is the 7B gameplay model
  - Test that `ValueError` is raised when no API key is found (no `CREATOR_API_KEY` or `LLM_API_KEY`)
  - Test `is_small_model` property returns True for the 7B model and False for other models

### Step 3: Prompt templates

- Implement `prompts.py` with all prompt constants from Section 4
- Write `tests/test_creator_prompts.py`:
  - Test that all prompts are non-empty strings
  - Test that format placeholders exist where expected (e.g., `{current_proposal}` in `PROPOSAL_REVISION_USER`)
  - Test that no prompt exceeds a reasonable token estimate (e.g., under 2000 tokens each)

### Step 4: Validator

- Implement `validator.py` with `validate_game_data()`, `_check_cross_references()`, and `check_size_warnings()`
- This can be tested independently of any LLM calls using hand-crafted data dicts
- Write `tests/test_creator_validator.py`:
  - Test validation passes for correctly structured data (use Lost Island as reference)
  - Test each Pydantic validation error is caught and reported (missing fields, wrong types, extra fields)
  - Test cross-reference errors: missing character file, broken chapter chain, invalid relationship key
  - Test character count limits: 0 characters produces error, 4+ characters produces error, 1-3 characters passes
  - Test self-referencing relationship: character with a relationship key pointing to itself
  - Test circular chapter chain: chapter A -> B -> A detected as error
  - Test size warnings: oversized character, too many beats, verbose world file
  - Test that a fully valid game produces `ValidationResult(valid=True)`

### Step 5: Writer

- Implement `writer.py` with `write_game_files()`
- Write `tests/test_creator_writer.py`:
  - Test that all expected files are created in the correct directory structure
  - Test that written files can be loaded back through `yaml_io.load_yaml()` and validate against Pydantic models
  - Test that the game directory structure matches the Phase 01 spec
  - Use `tmp_path` fixture to avoid polluting the real filesystem

### Step 6: Proposer

- Implement `proposer.py` with `generate_proposal()` and `revise_proposal()`
- These functions call the LLM, parse the YAML response, and return a proposal dict
- Write `tests/test_creator_proposer.py`:
  - Test with a mock LLM client that returns a canned YAML response
  - Test that the parsed proposal has required keys: `title`, `id`, `setting`, `tone`, `rules`, `characters`, `chapters`
  - Test revision: mock LLM receives previous proposal + feedback in its messages

### Step 7: Generator

- Implement `generator.py` with `generate_game_files()` and `_parse_generation_response()`
- Takes a proposal dict, calls the LLM, parses the full YAML output into a data dict
- Implements YAML parse retry: up to 2 retries on `YAMLParseError`, with the error message fed back to the LLM
- Write `tests/test_creator_generator.py`:
  - Test with a mock LLM client returning a canned full-generation YAML response
  - Test that the output dict has the correct structure (`game`, `world`, `characters`, `chapters` keys)
  - Test `_parse_generation_response` with YAML inside fenced code blocks
  - Test `_parse_generation_response` with raw YAML (no fencing)
  - Test `_parse_generation_response` raises `YAMLParseError` on malformed YAML
  - Test `_parse_generation_response` raises `YAMLParseError` when required top-level keys are missing
  - Test retry behavior: mock LLM returns bad YAML once, then good YAML

### Step 8: Fixer

- Implement `fixer.py` with `fix_validation_errors()`
- Write `tests/test_creator_fixer.py`:
  - Test with a mock LLM that returns corrected output on the first fix attempt
  - Test that the loop terminates after `MAX_FIX_ATTEMPTS` if errors persist
  - Test that already-valid data passes through without LLM calls

### Step 9: Display functions

- Implement `display.py` with `display_proposal()`, `display_game_files()`, `display_validation_errors()`, `display_size_warnings()`
- These use Rich to format output for the terminal
- Manual testing is sufficient here -- visual output is hard to unit test

### Step 10: Session orchestrator

- Implement `session.py` with `create_game()` and the interactive loop
- Implement `__main__.py` for standalone execution
- Write `tests/test_creator_session.py`:
  - Test the full flow with mocked LLM and mocked user input (monkeypatch `console.input`)
  - Test abort at each stage (concept, proposal review, final review)
  - Test the revision loop (user gives feedback, proposal is revised)
  - Test validation failure triggers fix loop

### Step 11: CLI menu integration

- Update `cli/menu.py` to add the "Create Game" option
- The handler calls `await create_game()` and returns to the menu on completion
- Manual testing: run the CLI, select "Create Game", verify the flow works end-to-end

### Step 12: End-to-end test

- Write `tests/test_creator_e2e.py`:
  - A full integration test using a mock LLM that simulates the complete flow: concept -> proposal -> approval -> generation -> validation -> write
  - Verify the output directory contains all expected files
  - Verify all files pass Pydantic validation
  - Verify file sizes are within guidelines

---

## 11. Verification

Phase 06 is complete when all of the following pass:

1. **Unit tests pass:** `uv run pytest tests/test_creator_*.py` -- all green
2. **Standalone execution:** `uv run python -m theact.creator` launches the interactive creation flow
3. **CLI integration:** The main menu shows "Create Game" and the option works
4. **Validation thoroughness:** Intentionally malformed LLM output is caught and either fixed or reported. This includes:
   - Invalid YAML (parse errors) — caught by `YAMLParseError`, retried
   - Valid YAML with wrong structure — caught by Pydantic `extra="forbid"`, fed to fix loop
   - Cross-reference errors (broken chapter chain, invalid relationship keys) — caught by `_check_cross_references`
   - Character count > 3 — caught by validator
   - Circular chapter chain — caught by explicit cycle detection
5. **Size compliance:** Generated games pass size checks:
   - `world.yaml` under 150 words
   - Each character YAML under 80 words
   - Each chapter has 4-6 beats
   - Each beat is under 15 words
6. **Round-trip test:** A game created by the agent can be loaded by `save_manager.load_save()` after `save_manager.create_save()` and played by the turn engine (Phase 03)
7. **Lost Island parity:** The agent can reproduce a game of similar quality and size to the hand-crafted Lost Island example from Phase 05

### 11.1 Live Testing & Regression Capture

**Step 1 — Create 2-3 games with different concepts:**
- Run the creation flow with varied concepts: a sci-fi game, a mystery game, a fantasy game. For each:
  - Does the proposal make sense? Are characters distinct?
  - Does the generated YAML pass Pydantic validation on the first try, or does the fix loop engage?
  - Are file sizes within constraints? Check word counts.
  - Does the chapter `next` chain form a valid sequence?
  - Can you create a save and run 5 turns with the playtest framework?

**Step 2 — Test the iteration loop:**
- During creation, provide critical feedback: "Change the first character to be more antagonistic" or "Add a fourth chapter." Verify the agent modifies the proposal and regenerated files correctly.
- Try vague concepts: "A game about friendship." The agent will attempt to generate a proposal from minimal input. Verify the proposal is reasonable. If the proposal is too generic, the user can revise it in the iteration loop (Step 5). The agent does NOT ask clarifying questions — it always generates a proposal, and the user iterates.

**Step 3 — Fix and capture:**
- For validation failures the fix loop misses, add the pattern to `validator.py`'s checks.
- For size violations the model consistently makes (e.g., always writes 100-word personalities), adjust the prompt's size constraints or add few-shot examples.
- Write regression tests: `test_validate_game_oversized_character()`, `test_validate_broken_chapter_chain()`, etc.

**Step 4 — End-to-end validation:**
- Run `uv run pytest tests/ -v` — all tests pass.
- Create one final game, create a save, run a 10-turn playtest. The generated game should be playable.

---

## 12. Dependencies

No new packages are required. The creator module reuses:
- **openai** -- LLM calls (AsyncOpenAI)
- **pydantic** -- validation (via `theact.models`)
- **pyyaml** -- YAML parsing and serialization (via `theact.io.yaml_io`)
- **rich** -- terminal display (via `theact.cli`)
- **python-dotenv** -- environment variable loading

The `pyproject.toml` does not need changes unless we want to add the creator as a console script entry point:

```toml
[project.scripts]
theact-create = "theact.creator.__main__:main"
```

This is optional -- `uv run python -m theact.creator` works without it.

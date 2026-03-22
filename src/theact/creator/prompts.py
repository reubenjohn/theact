"""Prompt templates for the game creation agent.

Phase 12 decomposition: each prompt does one focused task.
Prompts are grouped by phase:
  - Brainstorm: freeform idea exploration
  - Proposal: decomposed into setting → characters → chapters
  - Generation: per-file (world, character, chapter)
  - Fix: per-file validation error repair
  - Classify: targeted revision routing
  - Legacy: monolithic prompts retained for fallback
"""

# ---------------------------------------------------------------------------
# Brainstorm prompts
# ---------------------------------------------------------------------------

BRAINSTORM_SYSTEM = """\
You are a game designer brainstorming text RPG ideas with a collaborator.

Help them explore concepts: settings, characters, tone, plot hooks, themes.
Be creative but concise. Ask questions to draw out their vision.
Suggest concrete details -- names, places, conflicts -- not abstractions.
Keep responses to 2-4 sentences. Build on their ideas, don't overwrite them.
Never introduce yourself or state your name. Jump straight into the ideas."""


BRAINSTORM_SUMMARIZE_SYSTEM = """\
Summarize this game brainstorm into a concept paragraph.
Include: genre, setting, key characters, what the player does, and tone.
3-5 sentences. This will be the input to a game creation tool."""


# ---------------------------------------------------------------------------
# Decomposed proposal prompts
# ---------------------------------------------------------------------------

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


SETTING_USER = """\
Game concept:
{concept}

Generate the game's setting, tone, and rules in the YAML format specified."""


SETTING_REVISION_USER = """\
Current setting:

```yaml
{current_setting}
```

Requested changes: {user_feedback}

Output the revised YAML. Same format."""


def characters_system_prompt(hint_count: int | None = None) -> str:
    """Build the characters proposal system prompt with dynamic count."""
    count_line = (
        f"Exactly {hint_count} characters." if hint_count else "1-3 characters."
    )
    return f"""\
You are a game designer. Given a game setting, propose characters.

Output YAML:

```yaml
characters:
  - stem: "lowercase-stem"
    name: "Display Name"
    role: "One-line role in the story"
```

{count_line} Each role is one sentence. Stems are lowercase, no spaces.
Characters must have distinct personalities and conflicting goals."""


PROPOSAL_CHARACTERS_SYSTEM = characters_system_prompt()


def characters_user_prompt(
    title: str,
    setting: str,
    tone: str,
    concept: str | None = None,
    character_names: list[str] | None = None,
) -> str:
    """Build the characters proposal user prompt with optional concept."""
    text = f"""\
Game: {title}
Setting: {setting}
Tone: {tone}"""
    if concept:
        text += f"\n\nOriginal concept:\n{concept}"
    if character_names:
        text += f"\n\nThe user specifically requested these characters: {', '.join(character_names)}"
    text += "\n\nPropose characters for this game in the YAML format specified."
    return text


PROPOSAL_CHARACTERS_USER = """\
Game: {title}
Setting: {setting}
Tone: {tone}

Propose characters for this game in the YAML format specified."""


CHARACTERS_REVISION_USER = """\
Current characters:

```yaml
{current_characters}
```

Game setting: {setting}

Requested changes: {user_feedback}

Output the revised YAML. Same format."""


def chapters_system_prompt(hint_count: int | None = None) -> str:
    """Build the chapters proposal system prompt with dynamic count."""
    count_line = f"Exactly {hint_count} chapters." if hint_count else "3-5 chapters."
    return f"""\
You are a game designer. Given a game setting and characters, outline the chapters.

Output YAML:

```yaml
chapters:
  - id: "01-slug"
    title: "Chapter Title"
    summary: "One sentence about what happens"
```

{count_line} Each covers 5-10 turns of gameplay. Summaries are one sentence.
Chapter IDs are numbered slugs (e.g., "01-the-crash")."""


PROPOSAL_CHAPTERS_SYSTEM = chapters_system_prompt()


def chapters_user_prompt(
    title: str,
    setting: str,
    character_list: str,
    concept: str | None = None,
) -> str:
    """Build the chapters proposal user prompt with optional concept."""
    text = f"""\
Game: {title}
Setting: {setting}
Characters: {character_list}"""
    if concept:
        text += f"\n\nOriginal concept:\n{concept}"
    text += "\n\nOutline the chapter arc in the YAML format specified."
    return text


PROPOSAL_CHAPTERS_USER = """\
Game: {title}
Setting: {setting}
Characters: {character_list}

Outline the chapter arc in the YAML format specified."""


CHAPTERS_REVISION_USER = """\
Current chapters:

```yaml
{current_chapters}
```

Game: {title}
Characters: {character_list}

Requested changes: {user_feedback}

Output the revised YAML. Same format."""


# ---------------------------------------------------------------------------
# Per-file generation prompts
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Per-file fix prompts
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Targeted revision classifier
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Targeted revision user prompt (per-file with feedback)
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Legacy monolithic prompts (retained for fallback / generate_game_files())
# ---------------------------------------------------------------------------

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


PROPOSAL_USER = """\
Game concept:
{concept}

Generate a structured game proposal in the YAML format specified."""


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


LEGACY_GENERATION_SYSTEM = """\
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


LEGACY_GENERATION_USER = """\
Generate all game definition files for this approved proposal:

```yaml
{proposal}
```

Output ALL files in a single YAML block with this exact structure:

```yaml
game:
  id: "url-safe-slug"
  title: "Display Title"
  description: "One-sentence pitch"
  characters:
    - "char_stem_1"
    - "char_stem_2"
  chapters:
    - "01-chapter-slug"
    - "02-chapter-slug"

world:
  setting: |
    2-3 sentences.
  tone: |
    2 sentences.
  rules: |
    2 sentences.

characters:
  char_stem_1:
    name: "Display Name"
    role: "One-line role"
    personality: |
      2-3 short sentences.
    secret: "One sentence."
    relationships:
      other_char_stem: "One-line stance"

  char_stem_2:
    name: "Display Name"
    role: "One-line role"
    personality: |
      2-3 short sentences.
    secret: "One sentence."
    relationships:
      other_char_stem: "One-line stance"

chapters:
  01-chapter-slug:
    id: "01-chapter-slug"
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
      - "char_stem"
    next: "02-chapter-slug"

  02-chapter-slug:
    id: "02-chapter-slug"
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
      - "char_stem"
    next: null
```

Remember: CHARACTER FILES ~60 WORDS. WORLD FILE ~6 SENTENCES. BEATS ARE
SHORT PHRASES. This is not creative writing -- it is compressed game data
that a small model will parse."""


# Backward-compatible aliases for generator.py's monolithic path
GENERATION_SYSTEM = LEGACY_GENERATION_SYSTEM
GENERATION_USER = LEGACY_GENERATION_USER

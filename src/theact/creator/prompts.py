"""Prompt templates for the game creation agent."""

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

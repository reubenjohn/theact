# Phase 11: Small Model Hardening -- Prompt Engineering Sprint

> **Prerequisite:** This phase depends on Phase 09 (Observability Infrastructure) and Phase 10 (Turn Debugger). The diagnostic tools, call logger, context profiler, and turn debugger must be operational before starting this work. Every change in this phase is validated using those tools.

## 1. Overview

Phases 01-05 built the turn engine, agents, and playtest framework. Phases 09-10 built the observability and debugging tools. This phase uses those tools to systematically fix every known prompt issue with the 7B thinking model (`olafangensan-glm-4.7-flash-heretic`).

This is an iterative engineering sprint, not a linear implementation. Each section modifies `src/theact/agents/prompts.py`, `src/theact/llm/config.py`, or `src/theact/llm/parsing.py`, and each change must be validated against the live model before moving on.

### Known Issues from Live Testing

These are the starting problems, discovered during Phase 03/05 integration testing:

1. **Narrator returns `responding_characters: []` every turn.** Characters never get introduced, so no character agents run and no memories are created.
2. **YAML parse failures.** The model does not reliably produce fenced YAML blocks. Missing closing backticks, text before/after the YAML block, inconsistent indentation.
3. **Thinking tokens consume most of `max_tokens` budget.** The model spends 500-2000 tokens reasoning in `<think>` tags before producing content, leaving little room for actual output.
4. **Game state agent parse warnings.** The agent produces valid beat tracking but often outside fenced code blocks, triggering fallback parsing.
5. **No character memories created.** Downstream effect of issue 1 -- characters never respond, so memory updates never run.

### What This Phase Does NOT Do

- No new features. No new agents, no new game mechanics.
- No UI changes. The CLI and web UI are untouched.
- No architecture changes. The turn flow remains: narrator -> characters -> post-turn (parallel).
- No new observability tooling (that was Phase 09).
- No new debugger features (that was Phase 10).

---

## 2. Prompt Iteration Methodology

### 2.1 The Feedback Loop

Every prompt change follows this cycle:

```
Diagnose (Phase 09 tools) -> Hypothesize -> Modify prompt -> Test with debugger (Phase 10)
-> Validate with playtest -> Capture fixture -> Write regression test
```

**Step 1 -- Diagnose.** Use `scripts/diagnose_agent.py` for the specific agent with a representative player input. Examine:
- The exact prompt sent (system + user messages) and its token count
- The raw model response (thinking + content)
- Whether YAML parsing succeeded
- The parsed data fields and their values
- The finish reason (if `length`, the model ran out of budget)
- Thinking vs content token ratio from the call logger

```bash
# Single agent diagnosis
uv run python scripts/diagnose_agent.py narrator "I look for survivors."
uv run python scripts/diagnose_agent.py character "I ask Maya about the water supply." --character maya
uv run python scripts/diagnose_agent.py memory --character maya
uv run python scripts/diagnose_agent.py game_state
```

**Step 2 -- Hypothesize.** Based on the diagnosis, form a specific hypothesis about why the output is wrong. Examples:
- "The model returns `responding_characters: []` because the prompt says 'responding_characters can be empty if no one speaks' -- the model takes the easy path."
- "The model produces thinking tokens that exceed max_tokens because temperature=1.0 encourages verbose reasoning."
- "The YAML block lacks closing backticks because the model ran out of tokens mid-output."

**Step 3 -- Modify prompt.** Edit `src/theact/agents/prompts.py` (all prompts in one file). One change at a time.

**Step 4 -- Test with debugger.** Use the turn debugger's `edit` and `replay` commands to immediately test the change without restarting:

```bash
uv run python scripts/debug_turn.py --game lost-island --input "I look for survivors."
> step          # run narrator with old prompt
> edit          # hot-reload prompts.py
> replay narrator  # re-run with new prompt
> compare narrator # diff old vs new output
```

**Step 5 -- Validate with playtest.** Run a short playtest to confirm the fix works across multiple turns:

```bash
uv run python scripts/playtest.py --game lost-island --turns 5
```

**Step 6 -- Capture fixture.** Once the model produces good output:

```bash
uv run python scripts/diagnose_agent.py --save-fixture narrator "I look for survivors."
```

**Step 7 -- Write regression test.** Create a test in `tests/test_prompt_regression.py` that replays the fixture through the parsing pipeline.

### 2.2 Prompt Engineering Guidelines for 7B Thinking Models

These guidelines are specific to `olafangensan-glm-4.7-flash-heretic` and similar models:

1. **The model reasons in `<think>` tags before responding.** This reasoning consumes `max_tokens`. Budget accordingly: if the model needs 1000 tokens for thinking and 500 for content, set `max_tokens` to at least 1500.

2. **Position matters.** Instructions at the end of the system prompt are followed more reliably than instructions in the middle. Put the output format and critical rules at the end.

3. **Concrete examples beat abstract rules.** Showing a YAML block with `responding_characters: [maya, joaquin]` teaches the format better than explaining it in prose.

4. **One-shot examples work, but the model copies literally.** If the example says `mood: tense`, expect the model to default to "tense" more often. Use varied examples if possible.

5. **"DO NOT" rules are followed inconsistently.** Prefer positive phrasing: "Write only dialogue and actions" instead of "Do not include narration."

6. **Long system prompts degrade output quality.** Every token in the system prompt is a token the model cannot use for reasoning or output. Keep system prompts under 300 tokens. Currently the narrator prompt expands to ~350 tokens after template substitution -- this is already at the limit.

7. **Temperature affects thinking verbosity.** Lower temperature = shorter thinking = more budget for content. For structured output agents (memory, game_state), low temperature (0.2-0.3) is correct. For narrator, temperature 0.8-1.0 is needed for creative prose but burns more thinking tokens.

### 2.3 Prioritization Using Diagnostics Data

Run a baseline 5-turn playtest with full observability before making any changes. Use the LLM call log and context profiler from Phase 09 to prioritize:

1. **Fix the narrator first** (issues 1 and 2). Everything downstream depends on the narrator producing `responding_characters`.
2. **Fix YAML parsing** (issue 2). Shared infrastructure that affects all structured agents.
3. **Fix token budgets** (issue 3). Prevents truncated output.
4. **Fix game state** (issue 4). Low severity but easy to address.
5. **Fix memory** (issue 5). Cannot test until characters respond (requires fix 1).

---

## 3. Narrator Prompt Improvements

### 3.1 Problem: `responding_characters: []` Every Turn

**Root cause analysis.** The current narrator prompt says:

```
- responding_characters can be empty if no one speaks.
```

This gives the model an easy out. A 7B model under token pressure takes the path of least resistance -- returning an empty list avoids the cognitive load of deciding which characters should speak.

Additionally, the prompt lists `ACTIVE CHARACTERS: Maya Chen, Father Joaquin Reyes` using full names, but the expected output format uses character IDs (`maya`, `joaquin`). The model may not know how to map names to IDs.

**Fix: Rewrite the responding_characters instruction.** Replace the permissive "can be empty" with an instruction that actively encourages character inclusion. Add the character ID mapping explicitly.

Modify `NARRATOR_SYSTEM` in `src/theact/agents/prompts.py`:

```python
NARRATOR_SYSTEM = """\
You are the narrator of a text RPG.

SETTING: {world_setting}
TONE: {world_tone}
RULES: {world_rules}

{chapter_context}

ACTIVE CHARACTERS (use these IDs in responding_characters):
{active_characters_with_ids}

YOUR TASK:
1. Write narration responding to the player's action. 150-300 words. Second person present tense.
2. Pick which characters respond. If the player is near a character or their action relates to a character, include that character.
3. Guide the story toward unfinished beats. Do NOT skip beats.

Output a YAML block:

```yaml
narration: |
  You step into the clearing. The air smells wrong -- metallic,
  like a storm that never came. Something crunches under your boot.
responding_characters:
  - maya
  - joaquin
mood: tense
```

OUTPUT RULES:
- Use character IDs (lowercase) in responding_characters.
- Include at least one character if any are nearby or relevant.
- Only omit all characters if the player is truly alone with no one in earshot.
- mood is one of: tense, calm, urgent, mysterious, humorous, dramatic, melancholic.
- Never speak for the player. Never decide what the player does next."""
```

**Changes from current prompt:**
1. `ACTIVE CHARACTERS` now includes `(use these IDs in responding_characters)` and uses `{active_characters_with_ids}` which formats as `maya (Maya Chen), joaquin (Father Joaquin Reyes)`.
2. Task item 2 changed from "Decide which characters respond" to "Pick which characters respond. If the player is near a character or their action relates to a character, include that character."
3. Removed "responding_characters can be empty if no one speaks."
4. Added "Include at least one character if any are nearby or relevant."
5. Added "Only omit all characters if the player is truly alone with no one in earshot."

### 3.2 Context Assembly Change

Update `build_narrator_messages()` in `src/theact/engine/context.py` to format characters with IDs:

```python
# Replace the current char_names formatting:
char_entries = []
for cid in active_chars:
    if cid in game.characters:
        char_entries.append(f"{cid} ({game.characters[cid].name})")
active_characters_with_ids = ", ".join(char_entries)
```

Update the `NARRATOR_SYSTEM.format()` call to use `active_characters_with_ids=active_characters_with_ids` instead of `active_characters=char_names`.

### 3.3 YAML Output Reliability

**Symptoms.** The model sometimes:
- Omits the closing ``` backticks
- Puts text before or after the YAML block
- Uses indentation inconsistently in multi-line strings
- Outputs YAML without the ```yaml fence

**Improvements:**

1. **Ensure the example YAML matches the exact format we parse.** The current example uses `|` (literal block scalar) for narration. Verify the model follows this consistently. If not, accept both `|` and quoted strings.

2. **Add a closing backtick reminder.** After the example YAML block in the system prompt, add: "End the YAML block with ```."

3. **Improve `extract_yaml_block()` in `src/theact/llm/parsing.py`** -- see Section 6 for parsing changes.

### 3.4 Test Matrix for Narrator

Run `scripts/diagnose_agent.py narrator` with each input at least 3 times and verify correct output. Capture fixtures for each:

| Input | Expected Behavior |
|-------|-------------------|
| `"I open my eyes."` | Opening scene, at least one character introduced |
| `"I look for survivors."` | Should find Maya or Joaquin, list in responding_characters |
| `"I search the wreckage for supplies."` | Exploration, may or may not include characters |
| `"I ask Maya about the water."` | Maya must be in responding_characters |
| `"I punch Joaquin."` | Combat/conflict, both characters likely respond |
| `"I sit quietly and do nothing."` | Minimal action, narrator should still advance story |
| `"ok"` | Very short input, narrator should handle gracefully |
| `"I try to build a radio from the wreckage parts."` | Long-term goal, narrator steers toward beats |
| `""` (empty) | Opening narration, sets the scene |

---

## 4. Character Agent Hardening

### 4.1 Current State

The character agent produces unstructured text (no YAML parsing). The main risks are:
- Out-of-character responses (Maya sounds like Joaquin or vice versa)
- Responses that narrate rather than dialogue/act
- Responses that speak for the player
- Overly long or overly short responses
- Repetitive phrasing across turns

### 4.2 Prompt Refinements

**Improvement 1 -- Stronger personality guardrails.** Add explicit constraints to prevent common 7B failure modes.

Modify `CHARACTER_SYSTEM` in `src/theact/agents/prompts.py`:

```python
CHARACTER_SYSTEM = """\
You are {name} in a text RPG. Stay in character.

ROLE: {role}
PERSONALITY: {personality}
SECRET: {secret}
{relationships}

{memory_block}

Write {name}'s response to what just happened. Dialogue and actions only.
50-150 words. Stay in character. Do not narrate for others.
Do not use quotation marks around actions -- write actions as plain text.
Never speak for the player or other characters.
Never break character to explain or comment.

Example format:
She sets down the wrench and wipes her hands on her jeans. "Three days. That's how long the water will last if we're careful." She glances toward the tree line. "Less if we're not.\""""
```

**Changes:** Added "Never speak for the player or other characters" and "Never break character to explain or comment." Removed "(for illustration only)" from the example label -- the model should treat the example as the canonical format.

**Improvement 2 -- Empty response retry.** If the character response is empty or under 10 characters after stripping, retry once with a slightly higher temperature. If still empty, use a fallback.

Modify `run_character()` in `src/theact/agents/character.py`:

```python
content = "".join(content_parts).strip()

if len(content) < 10:
    logger.warning(
        "Character %s produced very short response (%d chars), retrying once.",
        character.name, len(content),
    )
    # Retry with slightly higher temperature
    retry_config = AgentLLMConfig(
        temperature=(CHARACTER_CONFIG.temperature or 1.0) + 0.1,
        max_tokens=CHARACTER_CONFIG.max_tokens,
    )
    content_parts = []
    async for chunk in await stream(
        messages=messages, llm_config=llm_config, agent_config=retry_config
    ):
        if chunk.content:
            content_parts.append(chunk.content)
            if on_token:
                await on_token(chunk.content)
    content = "".join(content_parts).strip()

return CharacterResponse(
    character=character.name,
    response=content or f"*{character.name} remains silent.*",
)
```

### 4.3 Sequential Response Coherence

When Joaquin responds after Maya, he should acknowledge what Maya said. The context already includes prior responses via `build_character_messages()`, so this should work -- but needs live validation.

**Test procedure:**
1. Run `scripts/diagnose_agent.py character "What should we do about water?" --character maya`
2. Take Maya's response, then manually test Joaquin with the same context plus Maya's response
3. Verify Joaquin's response references or reacts to Maya's statement

If Joaquin ignores Maya, the context assembly may need a stronger signal: add "React to what others just said" to the `CHARACTER_SYSTEM` prompt.

### 4.4 Test Matrix for Character Agent

| Input | Character | Expected Behavior |
|-------|-----------|-------------------|
| `"What do you think about this place?"` | maya | Direct, practical assessment |
| `"What do you think about this place?"` | joaquin | Cryptic, parable-like response |
| `"Tell me your secret."` | maya | Deflection or partial revelation |
| `"Tell me your secret."` | joaquin | Evasion, gets quieter |
| `"We need to leave."` | maya | Agrees pragmatically |
| `"We need to leave."` | joaquin | Hesitates, hints at unfinished business |
| `"ok"` | maya | Short but in-character response |

---

## 5. Structured Output Reliability

### 5.1 Streaming Parse Failure Recovery

**Problem.** The `stream_structured()` function streams tokens for live display, then parses YAML from collected content. If YAML parsing fails, the narrator agent catches `YAMLParseError` and falls back to raw text -- losing structured data (responding_characters, mood).

**Fix: Add a non-streaming retry after streaming parse failure.** Modify `run_narrator()` in `src/theact/agents/narrator.py`:

```python
async def run_narrator(
    game: LoadedGame,
    player_input: str,
    llm_config: LLMConfig,
    on_token: StreamCallback | None = None,
) -> NarratorOutput:
    messages = build_narrator_messages(game, player_input, llm_config)

    try:
        stream_iter, result_future = await stream_structured(
            messages=messages,
            llm_config=llm_config,
            agent_config=NARRATOR_CONFIG,
            yaml_hint=(
                "narration: |\\n  ...\\n"
                "responding_characters:\\n  - ...\\n"
                "mood: tense|calm|urgent|mysterious|humorous|dramatic|melancholic"
            ),
        )

        async for chunk in stream_iter:
            if on_token and chunk.content:
                await on_token(chunk.content)

        result = await result_future
        data = result.data

    except YAMLParseError as e:
        logger.warning("Narrator streaming YAML parse failed: %s. Retrying non-streaming.", e)
        try:
            result = await complete_structured(
                messages=messages,
                llm_config=llm_config,
                agent_config=NARRATOR_CONFIG,
                yaml_hint=(
                    "narration: |\\n  ...\\n"
                    "responding_characters:\\n  - ...\\n"
                    "mood: tense|calm|urgent|mysterious|humorous|dramatic|melancholic"
                ),
            )
            data = result.data
        except YAMLParseError:
            logger.warning("Narrator YAML parse failed after all retries.")
            raw = e.raw_content if hasattr(e, "raw_content") else ""
            return NarratorOutput(
                narration=raw.strip() or "(The narrator is silent.)",
                responding_characters=[],
                mood="neutral",
            )

    return NarratorOutput(
        narration=data.get("narration", "").strip(),
        responding_characters=data.get("responding_characters") or [],
        mood=data.get("mood", "neutral") or "neutral",
    )
```

This adds `complete_structured` as an import in `narrator.py`.

### 5.2 YAML Field Validation

Wire `validate_yaml_fields()` from `src/theact/llm/parsing.py` into each agent's output processing. Missing required fields should produce warnings but not failures:

- **Narrator:** Required: `narration`. Optional: `responding_characters`, `mood`.
- **Memory:** Required: `summary`. Optional: `add`, `remove`, `update`.
- **Game state:** Required: `chapter_complete`. Optional: `reason`, `new_beats`.

Add validation calls in each agent after successful YAML parsing. Log warnings for missing optional fields but do not retry.

### 5.3 Retry Behavior Analysis

Current retry configuration in `src/theact/llm/config.py`:

| Agent | max_retries | retry_temperature_bump |
|-------|-------------|----------------------|
| Narrator | 2 | 0.1 |
| Memory | 2 | 0.1 |
| Game State | 2 | 0.1 |

This means up to 3 total attempts (1 initial + 2 retries). Validate with profiling:

1. **Verify retry context growth is acceptable.** Each retry appends the failed response (truncated to 200 chars) and a correction message. After 2 retries, the context has grown by ~150 tokens. With an 8K window, this is acceptable.

2. **Test whether temperature bumping helps.** Run `diagnose_agent.py` with `--save-fixture` 5 times for each agent. Target: 90%+ parse success rate on first attempt.

---

## 6. YAML Parsing Improvements

### 6.1 Unclosed Backtick Handling

The model sometimes runs out of tokens mid-output, producing ```yaml blocks without closing ```. Add fallback matching in `extract_yaml_block()` in `src/theact/llm/parsing.py`:

```python
def extract_yaml_block(text: str) -> str:
    """Extract YAML content from a fenced code block in the response."""
    # Try ```yaml ... ``` first (take last match).
    matches = re.findall(r"```yaml\s*\n(.*?)```", text, re.DOTALL)
    if matches:
        return matches[-1].strip()

    # Try generic ``` ... ```
    matches = re.findall(r"```\s*\n(.*?)```", text, re.DOTALL)
    if matches:
        return matches[-1].strip()

    # Try ```yaml without closing backticks (model ran out of tokens)
    match = re.search(r"```yaml\s*\n(.+)", text, re.DOTALL)
    if match:
        logger.warning("YAML block missing closing backticks; using content until EOF.")
        return match.group(1).strip()

    # Try ``` without closing backticks
    match = re.search(r"```\s*\n(.+)", text, re.DOTALL)
    if match:
        logger.warning("Code block missing closing backticks; using content until EOF.")
        return match.group(1).strip()

    # No code block found -- try the whole text as YAML.
    logger.warning(
        "No fenced YAML block found in response; attempting to parse "
        "entire text as YAML."
    )
    return text.strip()
```

### 6.2 Tab Normalization

Add tab-to-space normalization before YAML parsing in `parse_yaml_response()`:

```python
def parse_yaml_response(text: str) -> dict[str, Any]:
    yaml_str = extract_yaml_block(text)
    yaml_str = yaml_str.replace("\t", "  ")  # Normalize tabs
    # ... rest of parsing
```

### 6.3 Partial YAML Recovery

Add a repair function for common YAML malformations. Create `repair_yaml_text()` in `src/theact/llm/parsing.py`:

```python
def repair_yaml_text(text: str) -> str:
    """Attempt to fix common YAML issues from 7B model output.

    Applied before yaml.safe_load() as a best-effort repair.
    """
    # Fix missing newline after `|` in block scalars
    text = re.sub(r"(\w+): \|(\S)", r"\1: |\n  \2", text)

    # Fix trailing content after YAML (model continues after the block)
    lines = text.split("\n")
    yaml_lines = []
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("-") and ":" not in stripped and not line.startswith(" "):
            break
        yaml_lines.append(line)

    return "\n".join(yaml_lines)
```

Wire into `parse_yaml_response()` as a fallback: if `yaml.safe_load()` fails on the extracted block, try `repair_yaml_text()` and parse again before raising `YAMLParseError`.

### 6.4 Tests for New Parsing Cases

Add unit tests in `tests/test_parsing.py` for:
- Missing closing backticks
- Tab indentation
- Missing newline after `|` in block scalars
- Trailing prose after YAML block
- Mixed content before and after YAML

---

## 7. Memory Update Quality

### 7.1 Validation Strategy

Once characters start responding (after fixing Section 3), memory updates will begin flowing. Validate by:

1. **Run a 5-turn playtest.** After each turn, inspect `saves/<save_id>/memory/<character>.yaml`:
   - Summary is coherent and incorporates new events
   - Key facts are specific and accurate (not hallucinated)
   - Key facts from previous turns are preserved (not dropped)
   - Fact count stays at or below 10

2. **Test edge cases with `diagnose_agent.py memory`:**
   - Turn where nothing relevant to the character happened
   - Turn with a dramatic revelation (secret-related)
   - Turn where old facts should be updated, not added

### 7.2 Prompt Simplification

The memory agent's `remove` and `update` operations require exact text matching of existing facts. 7B models rarely reproduce text verbatim. The current `_apply_memory_diff()` in `src/theact/engine/turn.py` uses exact matching, which means these operations will frequently fail silently.

**Fix: De-emphasize remove/update.** The `summary` field is the reliable mechanism -- the model replaces the whole summary each turn. For key facts, `add` works reliably. Modify `MEMORY_UPDATE_SYSTEM` in `src/theact/agents/prompts.py`:

```python
MEMORY_UPDATE_SYSTEM = """\
You manage {name}'s memory in a text RPG.

Read what happened this turn. Update {name}'s memory.
Only include things {name} witnessed or learned.
Do NOT include things {name} would not know.

Output a YAML block:

```yaml
summary: |
  Updated 3-5 sentence summary of what {name} knows, feels, and has experienced.
  Merge new information into the existing summary. Drop minor old details
  to keep it under 5 sentences.
add:
  - "New fact {name} learned this turn"
remove: []
update: []
```

RULES:
- The summary replaces the old summary entirely. Include all important information.
- add: only new facts from THIS turn. Short, specific statements.
- remove and update: leave empty unless a fact is clearly wrong or outdated.
- Max 10 key facts total. If over 10, drop the least important.
- If nothing meaningful changed, keep the summary and leave add empty."""
```

**Changes:** Moved summary to the top of the YAML example (position emphasis). Set `remove: []` and `update: []` as defaults in the example. Added "Include all important information" to prevent summary drift.

### 7.3 Memory Growth Monitoring

After implementing the fixes, run a 10-turn playtest and check:
- Do key_facts stay under 10 per character?
- Does the summary grow then stabilize in length?
- Are facts from turn 1 still present at turn 10 (if still relevant)?

Add memory quality detectors to `PlaytestRunner._detect_issues()`:

```python
# Memory quality checks
for diff in result.memory_diffs:
    if diff.new_summary == diff.old_summary and diff.new_facts != diff.old_facts:
        issues.append(f"memory_summary_unchanged:{diff.character}")
    if not diff.new_summary.strip():
        issues.append(f"memory_empty_summary:{diff.character}")
```

---

## 8. Token Budget Optimization

### 8.1 Baseline Profiling

Before adjusting any budgets, use the Phase 09 context profiler and call logger to capture a full picture. Run context profiling at turn 1 and turn 10 during a playtest:

```bash
uv run python scripts/diagnose_agent.py --profile-context all "I search for water."
```

Current budgets and expected usage:

| Agent | max_tokens | Expected Thinking | Expected Content |
|-------|-----------|-------------------|-----------------|
| Narrator | 2000 | 500-1500 | 300-500 |
| Character | 1500 | 300-1000 | 100-300 |
| Memory | 1500 | 300-800 | 200-400 |
| Game State | 1000 | 200-600 | 50-150 |
| Summarizer | 1000 | 200-500 | 100-200 |

### 8.2 Budget Adjustment Strategy

**If the model finishes with `finish_reason: "length"` (budget exhausted):**
- Increase `max_tokens` for that agent
- But check total context: prompt_tokens + max_tokens must be < 8192

**If the model wastes tokens on excessive thinking:**
- Lower temperature (reduces thinking verbosity)
- For simple agents (game_state), temperature 0.1 may produce tighter reasoning

**If prompt tokens are too high:**
- Trim conversation history (reduce `max_turns` in `get_recent_conversation()`)
- Compress chapter context (shorter beat descriptions)
- Remove redundant instructions from the system prompt

### 8.3 Specific Optimizations to Try

These are starting points -- adjust based on profiling data:

1. **Game state agent: reduce max_tokens to 800.** This agent produces the smallest output (~50 tokens). Even with 500 tokens of thinking, 800 is enough.

2. **Memory agent: reduce temperature to 0.2.** Memory updates are deterministic -- the model should not be creative about what happened. Lower temperature reduces thinking verbosity.

3. **Player agent: keep max_tokens at 150.** If finish_reason is "length" frequently, bump to 200.

4. **Narrator: keep 2000 but monitor.** If thinking consistently exceeds 1500 tokens, the content is being squeezed. Consider bumping to 2500 if context allows.

Modify `src/theact/llm/config.py` based on profiling results:

```python
GAME_STATE_CONFIG = AgentLLMConfig(
    temperature=0.2,
    max_tokens=800,   # was 1000
    structured=True,
    max_retries=2,
)

MEMORY_UPDATE_CONFIG = AgentLLMConfig(
    temperature=0.2,  # was 0.3
    max_tokens=1500,
    structured=True,
    max_retries=2,
)
```

### 8.4 Context Window Budget Per Turn

Each LLM call is independent (they don't share context), so these are parallel budgets:

```
Narrator:   ~400 prompt + 2000 max_tokens = 2400 of 8192
Character:  ~350 prompt + 1500 max_tokens = 1850 of 8192 (per character)
Memory:     ~300 prompt + 1500 max_tokens = 1800 of 8192 (per character)
Game State: ~250 prompt +  800 max_tokens = 1050 of 8192
```

The constraint is: prompt_tokens + max_tokens <= 8192 per call. Monitor with the diagnostic tool. If any call exceeds the budget, the model's output will be truncated.

Run the profiler at turn 1, turn 10, and turn 20 to track growth. History should plateau once the rolling summary kicks in. If it does not, the summarizer is broken.

---

## 9. Model Quirks Investigation

### 9.1 Controlled Experiments

Use the turn debugger and diagnostic tool to run controlled experiments. Each experiment: 5 runs per variant with the same input, compare YAML parse success rate, response quality, and token usage.

**Header formatting.** Test `### SECTION` markdown headers versus `SECTION:` plain labels in system prompts. Some models respond better to markdown structure; others find it noisy.

**YAML fence styles.** Test whether the model is more reliable with ` ```yaml ` fences versus ` ``` ` generic fences versus no fence at all in the example output. Also test whether indentation style (2 spaces vs 4 spaces) affects output consistency.

**Instruction ordering.** Test whether placing the YAML format example before vs after the task instructions changes compliance.

**Positive vs negative framing.** For each "DO NOT" rule in current prompts, create a positive-framing variant and compare. Track which framing produces better compliance. Example: "Never speak for the player" vs "Write only your own character's dialogue and actions."

### 9.2 Record Findings

Record all findings in `docs/model-quirks.yaml`:

```yaml
model: olafangensan-glm-4.7-flash-heretic
experiments:
  - name: header_format
    winner: "SECTION: labels"
    notes: "Markdown headers cause the model to emit markdown in its response"
    tested: 2026-03-XX
  - name: yaml_fence
    winner: "```yaml"
    notes: "Generic ``` fences sometimes produce JSON instead"
    tested: 2026-03-XX
  - name: instruction_ordering
    winner: "example after instructions"
    notes: "Model follows the format more reliably when example is last"
    tested: 2026-03-XX
```

Apply winning variants to prompts in `src/theact/agents/prompts.py`.

---

## 10. Golden Scenario Suite

### 10.1 Motivation

Unit tests verify parsing logic. Playtests verify overall quality. But neither catches specific behavioral regressions like "Maya stopped responding after we changed the narrator prompt" or "Beat X is never hit anymore." A golden scenario suite fills this gap: scripted multi-turn scenarios with behavioral assertions that run as a regression gate after every prompt change.

### 10.2 Design

Create `tests/golden_scenarios/` with YAML scenario files. Each scenario defines:

```yaml
# tests/golden_scenarios/crash_opening.yaml
name: Crash Opening Sequence
description: Verify the first 5 turns produce a coherent crash scene with character introductions.
game: lost-island
turns:
  - input: null  # opening narration
    expect:
      narrator_not_empty: true
  - input: "I try to free my arm and look around."
    expect:
      narrator_not_empty: true
      narrator_word_count_min: 80
  - input: "I look for other survivors."
    expect:
      narrator_not_empty: true
      characters_responded_min: 1
  - input: "I ask her what she knows about the crash."
    expect:
      characters_responded_includes: maya
  - input: "Let's set up a camp before dark."
    expect:
      narrator_not_empty: true
      beats_hit_any: true
```

**Assertions are behavioral, not textual.** They check structural properties (did Maya respond? was a beat hit?) rather than exact text. This makes them resilient to prompt changes that improve quality without breaking behavior.

### 10.3 Runner

Create `scripts/run_golden.py`:

```bash
uv run python scripts/run_golden.py
# Runs all scenarios in tests/golden_scenarios/

uv run python scripts/run_golden.py --scenario crash_opening
# Run a single scenario
```

The runner:
1. Loads the scenario YAML
2. Creates a fresh save
3. Runs each turn with the specified input (no player agent -- inputs are scripted)
4. After each turn, evaluates the `expect` assertions
5. Reports pass/fail per turn, per scenario

### 10.4 Suggested Scenarios

| Scenario | Turns | Tests |
|----------|-------|-------|
| `crash_opening` | 5 | Character introductions happen, opening narration works |
| `maya_dialogue` | 3 | Maya responds in character, personality markers present |
| `joaquin_dialogue` | 3 | Joaquin responds in character, cryptic/calm tone |
| `beat_progression` | 8 | At least 3 beats hit in Chapter 1 over 8 turns |
| `memory_persistence` | 6 | Facts from turn 2 still in memory at turn 6 |
| `chapter_transition` | 10 | Chapter 1 completes and Chapter 2 begins |
| `short_input` | 3 | System handles "ok", "sure", "yes" without breaking |
| `adversarial_input` | 4 | System handles nonsense, fourth-wall breaks, contradictions |
| `both_characters` | 4 | Both Maya and Joaquin respond in the same turn at least once |
| `idle_turn` | 3 | "I do nothing" still produces narration and story progression |

### 10.5 Integration with CI

The golden scenario suite is slow (real LLM calls). It is NOT part of `uv run pytest` -- it is a separate script run manually or in a scheduled CI job.

---

## 11. Response Quality Scoring

### 11.1 Per-Turn Quality Heuristics

Implement automated quality checks in `src/theact/playtest/scoring.py`:

```python
@dataclass
class TurnQualityScore:
    """Quality assessment for a single turn."""
    narration_length_ok: bool       # 150-300 words?
    yaml_first_attempt: bool        # parsed without retry?
    character_personality: float    # 0.0-1.0, personality marker match
    memory_relevance: bool          # memory update references turn events?
    composite: float                # weighted average

def score_turn(turn_log: TurnLog, character_defs: dict[str, Character]) -> TurnQualityScore:
    """Compute quality score for a turn."""

    # 1. Narration length in expected range
    word_count = len(turn_log.narrator_text.split())
    narration_length_ok = 150 <= word_count <= 300

    # 2. YAML well-formed on first attempt
    yaml_first_attempt = not any("yaml" in issue.lower() for issue in turn_log.issues)

    # 3. Character responses mention personality markers
    personality_scores = []
    for char_name, text in turn_log.character_texts.items():
        if char_name in character_defs:
            markers = _extract_personality_markers(character_defs[char_name])
            score = _check_personality_markers(text, markers)
            personality_scores.append(score)
    character_personality = sum(personality_scores) / max(len(personality_scores), 1)

    # 4. Memory updates reference things that actually happened
    memory_relevance = _check_memory_relevance(
        turn_log.memory_updates,
        turn_log.narrator_text,
        turn_log.character_texts,
    )

    # 5. Composite score (weighted)
    composite = (
        0.3 * float(narration_length_ok)
        + 0.2 * float(yaml_first_attempt)
        + 0.3 * character_personality
        + 0.2 * float(memory_relevance)
    )

    return TurnQualityScore(
        narration_length_ok=narration_length_ok,
        yaml_first_attempt=yaml_first_attempt,
        character_personality=character_personality,
        memory_relevance=memory_relevance,
        composite=composite,
    )
```

### 11.2 Personality Marker Extraction

Derive markers from the character YAML's `personality` field using keyword extraction (no LLM call):

```python
def _extract_personality_markers(character: Character) -> list[str]:
    """Extract keyword markers from personality description."""
    words = character.personality.lower().split()
    stop = {"that", "this", "with", "from", "about", "their", "would", "could"}
    return [w.strip(".,;:") for w in words if len(w) > 4 and w not in stop]

def _check_personality_markers(response: str, markers: list[str]) -> float:
    """Score how many personality markers appear in the response."""
    if not markers:
        return 0.5
    response_lower = response.lower()
    hits = sum(1 for m in markers if m in response_lower)
    return min(hits / max(len(markers) * 0.3, 1), 1.0)
```

### 11.3 Quality Score Integration

Add quality scores to the playtest report:

```markdown
## Quality Scores

| Turn | Narration Length | YAML First Try | Personality | Memory | Composite |
|------|-----------------|----------------|-------------|--------|-----------|
| 1    | ok (185 words)  | yes            | 0.7         | yes    | 0.82      |
| 2    | short (120)     | yes            | 0.5         | yes    | 0.62      |
| 3    | ok (220 words)  | no (retry)     | 0.8         | no     | 0.56      |

**Mean composite:** 0.71
**Trend:** stable
```

---

## 12. A/B Prompt Testing

### 12.1 Framework Design

Extend the playtest framework to run the same N-turn scenario with two different prompt variants and produce a comparison report.

Create `scripts/ab_test.py`:

```bash
uv run python scripts/ab_test.py \
    --game lost-island \
    --turns 10 \
    --variant-a "current" \
    --variant-b "src/theact/agents/prompts_v2.py" \
    --runs 3
```

**How it works:**

1. **Variant A** runs with the current `prompts.py` (baseline).
2. **Variant B** runs with an alternative prompts file. The A/B script monkey-patches `src/theact/agents.prompts` with the variant module before running.
3. Each variant runs `--runs` times (default 3) with the same opening action and random seed for the player agent.
4. Both variants use the Phase 09 `LLMCallLog` instrumentation.

### 12.2 Comparison Report

```markdown
# A/B Test Report

**Variant A:** prompts.py (current)
**Variant B:** prompts_v2.py
**Game:** lost-island | **Turns:** 10 | **Runs:** 3 each

## Metrics Comparison

| Metric | Variant A (mean) | Variant B (mean) | Delta |
|--------|-------------------|-------------------|-------|
| YAML parse success | 90% | 97% | +7% |
| Character response rate | 60% | 83% | +23% |
| Avg narration words | 180 | 210 | +30 |
| Avg thinking tokens | 720 | 580 | -140 |
| Total token cost | 14200 | 13800 | -400 |
| Mean turn latency | 14.2s | 12.8s | -1.4s |
| Beats hit (ch 01) | 3.0 | 4.3 | +1.3 |
```

### 12.3 Implementation Notes

- Reuses `PlaytestRunner` and `LLMCallLog` -- just wraps them with module swapping.
- Random seed ensures both variants face the same player action sequence within a run. Use `random.seed(run_number)`.
- The comparison report is pure arithmetic on logged metrics. No LLM call.
- Store results in `playtests/ab-tests/<timestamp>/` with `variant-a/` and `variant-b/` subdirectories.

---

## 13. Edge Case Injection Enhancements

### 13.1 New Edge Case Categories

Expand the player agent's edge case prompts in `src/theact/playtest/player_agent.py`:

**Direct string injection (bypass player agent entirely):**

```python
DIRECT_EDGE_CASES = [
    "ok",
    "sure",
    "yes",
    "no",
    ".",
    "I wait.",
]
```

When a direct edge case triggers (separate probability, default 5%), the player agent is skipped and the string is used as-is.

**Nonsensical inputs:**

```python
NONSENSE_EDGE_CASES = [
    "asdf jkl;",
    "THE QUICK BROWN FOX THE QUICK BROWN FOX",
    "sudo rm -rf /",
]
```

**Very long inputs:**

```python
"Write a very long, detailed action -- describe exactly what you're doing step by step, at least 5 sentences."
```

**Fourth-wall breaks:**

```python
"I know this is a game. What's my hit points? Can I see the map?"
```

**Contradictory actions:**

```python
"I both leave the camp and stay at the camp at the same time."
```

**Repeated identical inputs.** Add a mode where the player agent repeats its previous action verbatim for 2-3 turns.

### 13.2 Configuration

Update `PlaytestConfig` in `src/theact/playtest/config.py`:

```python
@dataclass
class PlaytestConfig:
    # ... existing fields ...
    edge_case_frequency: float = 0.15         # 15% edge cases via player agent prompts
    direct_edge_case_frequency: float = 0.05  # 5% direct string injection
    nonsense_frequency: float = 0.03          # 3% nonsensical input
    repeat_frequency: float = 0.03            # 3% repeated previous input
```

---

## 14. Regression Test Infrastructure

### 14.1 Fixture Capture Workflow

The Phase 10 turn debugger's `capture` command and `scripts/diagnose_agent.py --save-fixture` save JSON fixtures to `tests/fixtures/`. Each fixture contains:

```json
{
  "agent": "narrator",
  "content_length": 523,
  "thinking_length": 1205,
  "finish_reason": "stop",
  "content": "```yaml\nnarration: |...",
  "thinking": "<think>\nThe player is...",
  "parsed": {"narration": "...", "responding_characters": ["maya"], "mood": "tense"}
}
```

### 14.2 Naming Convention

```
tests/fixtures/<agent>_<scenario>_<variant>.yaml
```

Examples:
- `narrator_opening_001.yaml`
- `narrator_exploration_001.yaml`
- `narrator_malformed_yaml_001.yaml`
- `character_maya_dialogue_001.yaml`
- `memory_maya_first_turn_001.yaml`
- `game_state_no_beats_001.yaml`

### 14.3 Regression Test Structure

Create `tests/test_prompt_regression.py`:

```python
"""Regression tests for agent output parsing.

Each test loads a fixture (real model response) and verifies the parsing
pipeline produces correct results. These tests do NOT call the LLM --
they test the parsing and output handling code against known responses.
"""

import json
from pathlib import Path

import pytest

from theact.llm.parsing import parse_yaml_response, extract_yaml_block, YAMLParseError

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> dict:
    with open(FIXTURES_DIR / name) as f:
        return yaml.safe_load(f)


class TestNarratorParsing:
    """Tests for narrator YAML output parsing."""

    def test_valid_narrator_output_parses(self):
        fixture = load_fixture("narrator_001.yaml")
        data = parse_yaml_response(fixture["content"])
        assert "narration" in data
        assert isinstance(data.get("responding_characters"), list)
        assert data.get("mood") in [
            "tense", "calm", "urgent", "mysterious",
            "humorous", "dramatic", "melancholic", None
        ]

    def test_narrator_missing_closing_backticks(self):
        content = '```yaml\nnarration: |\n  You wake up.\nresponding_characters:\n  - maya\nmood: tense\n'
        data = parse_yaml_response(content)
        assert data["narration"].strip() == "You wake up."

    def test_narrator_empty_responding_characters(self):
        content = '```yaml\nnarration: |\n  You look around.\nresponding_characters: []\nmood: calm\n```'
        data = parse_yaml_response(content)
        assert data["responding_characters"] == []

    def test_narrator_responding_characters_none(self):
        content = '```yaml\nnarration: |\n  You look around.\nresponding_characters:\nmood: calm\n```'
        data = parse_yaml_response(content)
        assert data.get("responding_characters") is None


class TestMemoryParsing:

    def test_memory_empty_operations(self):
        content = '```yaml\nsummary: |\n  Maya knows they crashed.\nadd: []\nremove: []\nupdate: []\n```'
        data = parse_yaml_response(content)
        assert "summary" in data
        assert data["add"] == []

    def test_memory_with_additions(self):
        content = '```yaml\nsummary: |\n  Maya found water.\nadd:\n  - "Found a freshwater stream"\nremove: []\nupdate: []\n```'
        data = parse_yaml_response(content)
        assert len(data["add"]) == 1


class TestGameStateParsing:

    def test_no_beats_hit(self):
        content = '```yaml\nchapter_complete: false\nreason: "Player has not explored yet"\nnew_beats: []\n```'
        data = parse_yaml_response(content)
        assert data["chapter_complete"] is False
        assert data["new_beats"] == []

    def test_beats_hit(self):
        content = '```yaml\nchapter_complete: false\nreason: "Player woke up"\nnew_beats:\n  - "Player wakes on the beach"\n```'
        data = parse_yaml_response(content)
        assert len(data["new_beats"]) == 1
```

### 14.4 Expanding Fixture Coverage

After each prompt iteration round, capture a full set of fixtures:

```bash
for input in "I open my eyes." "I look for survivors." "I search the wreckage." "I ask Maya about water."; do
    uv run python scripts/diagnose_agent.py --save-fixture narrator "$input"
done

uv run python scripts/diagnose_agent.py --save-fixture character "I look around." --character maya
uv run python scripts/diagnose_agent.py --save-fixture character "I look around." --character joaquin
uv run python scripts/diagnose_agent.py --save-fixture memory --character maya
uv run python scripts/diagnose_agent.py --save-fixture game_state
```

---

## 15. Playtest Framework Enhancements

### 15.1 Token Tracking in Turn Results

Add optional token tracking fields to `NarratorOutput`, `CharacterResponse`, and `MemoryDiff` in `src/theact/engine/types.py`:

```python
@dataclass
class NarratorOutput:
    narration: str
    responding_characters: list[str]
    mood: str
    thinking_tokens: int = 0
    content_tokens: int = 0
```

Populate from LLM results in each agent using `estimate_tokens()`.

### 15.2 Character Response Rate Metric

Track the percentage of turns where at least one character responded. Add to `PlaytestReport`:

```python
character_response_rate: float = 0.0
```

Calculate in `generate_report()`:

```python
turns_with_characters = sum(
    1 for t in logger.turns if t.characters_responded
)
character_response_rate = turns_with_characters / max(turns_played, 1)
```

### 15.3 YAML Parse Success Rate

Track parse failures as a metric. Add to `PlaytestReport`:

```python
yaml_parse_success_rate: float = 0.0
```

This requires agents to report parse attempt counts (available in `StructuredResult.attempts`). Thread this through the turn result.

---

## 16. Implementation Steps

### Step 1: Baseline Capture (uses Phase 09 tools)

**No code changes.** Establish a baseline before modifying anything.

1. Run a 5-turn playtest with full observability: `uv run python scripts/playtest.py --game lost-island --turns 5`
2. Run context profiling: `uv run python scripts/diagnose_agent.py --profile-context all "I search for water."`
3. Save the playtest report and LLM call log as the baseline
4. Note: thinking:content ratios, parse success rates, character response rates

**Verification:**
- Baseline data exists in `playtests/<timestamp>/`
- LLM call log has records for every call
- Context profiles are captured for each agent

### Step 2: Fix Narrator Character Introduction

**Files to modify:**
- `src/theact/agents/prompts.py` (NARRATOR_SYSTEM)
- `src/theact/engine/context.py` (build_narrator_messages -- character ID formatting)

**Changes:**
1. Rewrite `NARRATOR_SYSTEM` per Section 3.1
2. Update `build_narrator_messages()` to format `active_characters_with_ids` per Section 3.2
3. Update the template variable name from `active_characters` to `active_characters_with_ids`

**Verification:**
- Use the turn debugger: `uv run python scripts/debug_turn.py --game lost-island --input "I look for survivors."`
- Step through narrator, verify `responding_characters` is non-empty
- Run `scripts/diagnose_agent.py narrator` at least 3 times with varied inputs
- Verify `responding_characters` is non-empty in at least 2 out of 3 runs
- Run `uv run pytest tests/ -v` to ensure no regressions

### Step 3: Improve YAML Parsing Robustness

**Files to modify:**
- `src/theact/llm/parsing.py`

**Changes:**
1. Add unclosed backtick handling in `extract_yaml_block()` per Section 6.1
2. Add tab normalization in `parse_yaml_response()` per Section 6.2
3. Add `repair_yaml_text()` function per Section 6.3
4. Wire `validate_yaml_fields()` into each agent per Section 5.2

**Verification:**
- Write unit tests for each new parsing case in `tests/test_parsing.py`
- Run `uv run pytest tests/test_parsing.py -v`

### Step 4: Fix Narrator Retry on Streaming Parse Failure

**Files to modify:**
- `src/theact/agents/narrator.py`

**Changes:**
1. Add `complete_structured` import from `theact.llm.inference`
2. Add fallback retry logic per Section 5.1

**Verification:**
- Run a 5-turn playtest: `uv run python scripts/playtest.py --game lost-island --turns 5`
- Check playtest report for YAML parse errors -- should be zero or near-zero

### Step 5: Harden Character Agent

**Files to modify:**
- `src/theact/agents/prompts.py` (CHARACTER_SYSTEM)
- `src/theact/agents/character.py` (empty response retry)

**Changes:**
1. Add prompt guardrails per Section 4.2
2. Add empty response retry logic
3. Add fallback response for persistent empty output

**Verification:**
- Run `scripts/diagnose_agent.py character` for both maya and joaquin
- Verify responses are in-character and non-empty
- Use the turn debugger to test sequential coherence per Section 4.3
- Run `uv run pytest tests/ -v`

### Step 6: Harden Memory Agent

**Files to modify:**
- `src/theact/agents/prompts.py` (MEMORY_UPDATE_SYSTEM)
- `src/theact/playtest/runner.py` (memory quality detectors)

**Changes:**
1. Simplify prompt per Section 7.2
2. Add memory quality issue detectors per Section 7.3

**Verification:**
- Run `scripts/diagnose_agent.py memory --character maya`
- Verify summary is coherent and facts are specific
- Run a 5-turn playtest and check memory state in the report

### Step 7: Optimize Token Budgets

**Files to modify:**
- `src/theact/llm/config.py`

**Changes:**
1. Profile actual token usage per agent using Phase 09 tools
2. Adjust budgets based on profiling data per Section 8.3
3. Starting point: `GAME_STATE_CONFIG.max_tokens`: 1000 -> 800, `MEMORY_UPDATE_CONFIG.temperature`: 0.3 -> 0.2

**Verification:**
- Run full agent diagnostics and verify no `finish_reason: "length"` responses
- Run context profiling at turn 1 and turn 10 to verify history does not blow up
- Run a 5-turn playtest and check for truncated output

### Step 8: Model Quirks Investigation

**Files to create:**
- `docs/model-quirks.yaml`

**Changes:**
1. Run controlled experiments per Section 9.1 (header format, YAML fences, instruction ordering, positive vs negative framing)
2. Record findings in `docs/model-quirks.yaml`
3. Apply any winning variants to prompts in `src/theact/agents/prompts.py`

**Verification:**
- Each experiment has at least 5 runs per variant
- Winning variants are applied and verified with `diagnose_agent.py`

### Step 9: Add Playtest Metrics and Quality Scoring

**Files to create:**
- `src/theact/playtest/scoring.py`

**Files to modify:**
- `src/theact/engine/types.py` (add token tracking fields)
- `src/theact/playtest/logger.py` (populate token fields)
- `src/theact/playtest/report.py` (add character_response_rate, yaml_parse_success_rate, quality scores)
- `src/theact/playtest/runner.py` (integrate quality scoring)

**Changes:**
1. Implement `TurnQualityScore` and `score_turn()` per Section 11
2. Add token tracking to turn result types per Section 15.1
3. Add character response rate metric per Section 15.2
4. Add YAML parse success rate per Section 15.3
5. Add quality scores section to playtest report

**Verification:**
- Run a 10-turn playtest: `uv run python scripts/playtest.py --game lost-island --turns 10`
- Verify playtest report includes all new metrics
- Verify composite quality score is computed for each turn

### Step 10: Enhanced Edge Case Injection

**Files to modify:**
- `src/theact/playtest/player_agent.py` (new edge case categories)
- `src/theact/playtest/config.py` (new frequency parameters)

**Changes:**
1. Add direct edge cases, nonsense inputs, long inputs, fourth-wall breaks, contradictory actions per Section 13
2. Add repeat-previous-input mode
3. Add configuration knobs per Section 13.2

**Verification:**
- Run a 20-turn playtest with `--edge-case-freq 0.3`
- Verify the report shows edge case turns with new categories
- Verify no crashes from adversarial inputs

### Step 11: Build Golden Scenario Suite

**Files to create:**
- `tests/golden_scenarios/crash_opening.yaml`
- `tests/golden_scenarios/maya_dialogue.yaml`
- `tests/golden_scenarios/joaquin_dialogue.yaml`
- `tests/golden_scenarios/beat_progression.yaml`
- `tests/golden_scenarios/short_input.yaml`
- `scripts/run_golden.py`

**Changes:**
1. Define 5+ golden scenarios per Section 10.4
2. Implement the golden scenario runner per Section 10.3
3. Run all scenarios and verify pass rates

**Verification:**
- Run `uv run python scripts/run_golden.py` and verify at least 4/5 scenarios pass
- Fix any prompt issues surfaced by failing scenarios

### Step 12: Build A/B Testing Framework

**Files to create:**
- `scripts/ab_test.py`

**Changes:**
1. Implement variant loading and module patching per Section 12.1
2. Implement comparison report generation per Section 12.2
3. Test with a trivial prompt change to verify the framework works

**Verification:**
- Run `uv run python scripts/ab_test.py --game lost-island --turns 5 --variant-a current --variant-b current --runs 2`
- Verify comparison report is generated with metrics table

### Step 13: Build Regression Test Suite

**Files to create:**
- `tests/test_prompt_regression.py`

**Files to populate:**
- `tests/fixtures/*.yaml` (captured during Steps 2-8)

**Changes:**
1. Create regression test file per Section 14.3
2. Write tests for every fixture captured during hardening
3. Write tests for known edge cases (missing fields, malformed YAML, empty responses)

**Verification:**
- Run `uv run pytest tests/test_prompt_regression.py -v`
- All regression tests pass

### Step 14: Full Validation

**No new code.** Validates the cumulative effect of all improvements.

1. Run a 20-turn playtest: `uv run python scripts/playtest.py --game lost-island --turns 20`
2. Review the full playtest report against success criteria (Section 17)
3. Run all golden scenarios: `uv run python scripts/run_golden.py`
4. If any criteria are not met, identify the failing agent and repeat the relevant step
5. Run `uv run prek run --all-files` to ensure lint/format compliance
6. Run `uv run pytest tests/ -v` for full test suite

---

## 17. Success Criteria

### 17.1 Quantitative Metrics

Measured from a 20-turn playtest run:

| Metric | Target | How to Measure |
|--------|--------|----------------|
| YAML parse success rate (narrator) | >= 90% (18/20 turns) | Count turns without narrator YAML parse failures |
| Character response rate | >= 70% (14/20 turns with >= 1 character) | Count turns where `responding_characters` is non-empty |
| Memory update accuracy | 0 `memory_empty_summary` issues | Check playtest issue log |
| Key facts within limit | 0 `memory_overflow` issues | Check playtest issue log |
| No stuck loops | 0 `narrator_repeating` issues | Check playtest issue log |
| No empty narrator responses | 0 `empty_narrator_response` issues | Check playtest issue log |
| Average thinking:content ratio | <= 4:1 across all agents | Token profiling via LLM call logger |
| Playtest completion | 20/20 turns without fatal errors | Playtest runs to completion |
| Mean composite quality score | >= 0.6 | Quality scoring system |
| No context window overflow | 0 `finish_reason: "length"` for narrator | LLM call log |
| Golden scenario pass rate | >= 80% (4/5 scenarios) | Golden scenario runner |
| Average narration word count | 150-300 words | Quality scoring |

### 17.2 Qualitative Criteria

Checked by reading the playtest conversation log:

1. **Narrator narration is descriptive and advances the story.** Not just "You look around. Nothing happens."
2. **Characters sound distinct.** Maya's responses are short, direct, and practical. Joaquin's are calm, cryptic, and parable-like.
3. **Characters acknowledge each other.** When both respond, the second character reacts to the first.
4. **Memory summaries are coherent.** They read as a natural summary of what the character experienced.
5. **Story beats are hit progressively.** Over 20 turns, at least 3-4 beats from Chapter 1 should be marked as hit.
6. **Game state agent does not false-positive.** Beats are only marked when they clearly happened.

### 17.3 Definition of Done

Phase 11 is complete when:
- A 20-turn playtest passes all quantitative metrics in Section 17.1
- A human review of the playtest log confirms the qualitative criteria in Section 17.2
- All golden scenarios pass (>= 80%)
- All regression tests in `tests/test_prompt_regression.py` pass
- `uv run pytest tests/ -v` passes with no failures
- `uv run prek run --all-files` passes with no errors

---

## 18. Dependencies

### Phase Dependencies

| Phase | What It Provides to Phase 11 |
|-------|------------------------------|
| Phase 09 (Observability) | `LLMCallLog`, `LLMCallRecord`, `scripts/diagnose_agent.py`, context profiling, playtest report metrics |
| Phase 10 (Turn Debugger) | `scripts/debug_turn.py` with step/replay/edit/compare/capture commands |
| Phases 01-05 | Core engine, agents, game files, playtest framework |

### No New Package Dependencies

This phase modifies existing code and adds test/tooling files. No new packages.

| Existing Package | Used For |
|---|---|
| `pyyaml` | YAML parsing improvements, golden scenarios, model-quirks file |
| `openai` | LLM calls (unchanged) |
| `pytest` | Regression tests |
| `difflib` (stdlib) | A/B comparison diffs |
| `importlib` (stdlib) | A/B prompt variant loading |

### Files Modified (Summary)

| File | Changes |
|---|---|
| `src/theact/agents/prompts.py` | Narrator, character, memory prompt revisions |
| `src/theact/engine/context.py` | Character ID formatting in narrator context |
| `src/theact/llm/parsing.py` | Unclosed backticks, tab normalization, YAML repair, validation wiring |
| `src/theact/llm/config.py` | Token budget adjustments |
| `src/theact/agents/narrator.py` | Streaming parse failure retry |
| `src/theact/agents/character.py` | Empty response retry |
| `src/theact/engine/types.py` | Token tracking fields |
| `src/theact/playtest/logger.py` | Token field population |
| `src/theact/playtest/report.py` | Character response rate, YAML parse rate, quality scores |
| `src/theact/playtest/runner.py` | Memory quality issue detectors, quality scoring integration |
| `src/theact/playtest/player_agent.py` | Enhanced edge case injection |
| `src/theact/playtest/config.py` | New edge case frequency parameters |

### Files Created

| File | Purpose |
|---|---|
| `src/theact/playtest/scoring.py` | Response quality scoring heuristics |
| `scripts/run_golden.py` | Golden scenario suite runner |
| `scripts/ab_test.py` | Automated prompt A/B testing |
| `tests/test_prompt_regression.py` | Regression tests for agent output parsing |
| `tests/fixtures/*.yaml` | Captured model responses for regression testing |
| `tests/golden_scenarios/*.yaml` | Golden scenario definitions (5-10 files) |
| `docs/model-quirks.yaml` | Model-specific formatting preferences |

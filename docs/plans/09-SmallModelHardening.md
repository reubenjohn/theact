# Phase 09: Small Model Hardening

> **Implementation note:** This phase is iterative, not linear. Each section produces changes to `src/theact/agents/prompts.py`, `src/theact/llm/config.py`, or `src/theact/llm/parsing.py`, and each change must be validated against the live model before moving on. Use `scripts/diagnose_agent.py` for single-agent testing and `scripts/playtest.py` for multi-turn validation. Capture every fix as a regression test fixture.

## 1. Overview

Phases 01-05 built the turn engine, agents, and playtest framework. Phase 03 integration testing revealed that while the architecture works, the 7B thinking model (`olafangensan-glm-4.7-flash-heretic`) has specific failure modes that degrade gameplay quality:

1. **The narrator never introduces characters.** `responding_characters` is always `[]`, so no character agents run and no memories are created.
2. **YAML parsing fails on streaming.** The `stream_structured()` tee pattern has edge cases where YAML blocks split across chunks fail to parse.
3. **Thinking tokens consume most of `max_tokens`.** The model spends 500-2000 tokens reasoning before producing content, leaving little room for actual output.
4. **Game state YAML output is fragile.** The agent produces valid beat tracking but often outside fenced code blocks, triggering fallback parsing with warnings.
5. **Memory updates are untested.** Because characters never respond (issue 1), the memory pipeline has never run against the live model.

This phase hardens every agent prompt, improves structured output reliability, optimizes token budgets, and builds regression infrastructure to prevent regressions during future prompt iterations.

### What This Phase Does NOT Do

- No new features. No new agents, no new game mechanics.
- No UI changes. The CLI and web UI are untouched.
- No architecture changes. The turn flow remains: narrator -> characters -> post-turn (parallel).

---

## 2. Prompt Iteration Methodology

### 2.1 The Feedback Loop

Every prompt change follows this cycle:

```
Diagnose -> Hypothesize -> Modify prompt -> Re-diagnose -> Capture fixture -> Write regression test
```

**Step 1 -- Diagnose.** Run `scripts/diagnose_agent.py` for the specific agent with a representative player input. Examine:
- The exact prompt sent (system + user messages) and its token count
- The raw model response (thinking + content)
- Whether YAML parsing succeeded
- The parsed data fields and their values
- The finish reason (if `length`, the model ran out of budget)

```bash
# Single agent diagnosis
uv run python scripts/diagnose_agent.py narrator "I look for survivors."
uv run python scripts/diagnose_agent.py character "I ask Maya about the water supply." --character maya
uv run python scripts/diagnose_agent.py memory --character maya
uv run python scripts/diagnose_agent.py game_state

# Diagnose all agents in sequence
uv run python scripts/diagnose_agent.py all "I search the wreckage for supplies."

# Save response as a fixture for regression tests
uv run python scripts/diagnose_agent.py --save-fixture narrator "I look for survivors."
```

**Step 2 -- Hypothesize.** Based on the diagnosis, form a specific hypothesis about why the output is wrong. Examples:
- "The model returns `responding_characters: []` because the prompt says 'responding_characters can be empty if no one speaks' -- the model takes the easy path."
- "The model produces thinking tokens that exceed max_tokens because temperature=1.0 encourages verbose reasoning."
- "The YAML block lacks closing backticks because the model ran out of tokens mid-output."

**Step 3 -- Modify prompt.** Edit `src/theact/agents/prompts.py` (all prompts in one file). Common effective patterns for 7B thinking models:
- **Add positive instructions, not just negatives.** "Include at least one character" beats "Don't leave characters empty."
- **Show the exact output format.** The example YAML block in the prompt is the model's primary format guide.
- **Remove ambiguity.** "responding_characters can be empty" should become "responding_characters: list at least one character if any are nearby."
- **Use short imperative sentences.** "List characters who would speak." not "You should consider which characters might want to respond."
- **Move critical instructions to the end of the system prompt.** 7B models have weak attention to mid-prompt content.

**Step 4 -- Re-diagnose.** Run the same `diagnose_agent.py` command. Compare old vs new output. If fixed, proceed. If not, repeat from Step 2.

**Step 5 -- Capture fixture.** Once the model produces good output with the new prompt, save it:

```bash
uv run python scripts/diagnose_agent.py --save-fixture narrator "I look for survivors."
```

This writes a JSON fixture to `tests/fixtures/narrator_001.json`.

**Step 6 -- Write regression test.** Using the fixture, write a test that verifies the parsing pipeline handles this output correctly. If the fix was to handle missing fields gracefully, test that specifically.

### 2.2 Prompt Engineering Guidelines for 7B Thinking Models

These guidelines are specific to `olafangensan-glm-4.7-flash-heretic` and similar models:

1. **The model reasons in `<think>` tags before responding.** This reasoning consumes `max_tokens`. Budget accordingly: if the model needs 1000 tokens for thinking and 500 for content, set `max_tokens` to at least 1500.

2. **Position matters.** Instructions at the end of the system prompt are followed more reliably than instructions in the middle. Put the output format and critical rules at the end.

3. **Concrete examples beat abstract rules.** Showing a YAML block with `responding_characters: [maya, joaquin]` teaches the format better than explaining it in prose.

4. **One-shot examples work, but the model copies literally.** If the example says `mood: tense`, expect the model to default to "tense" more often than other moods. Use varied examples if possible.

5. **"DO NOT" rules are followed inconsistently.** Prefer positive phrasing: "Write only dialogue and actions" instead of "Do not include narration."

6. **Long system prompts degrade output quality.** Every token in the system prompt is a token the model cannot use for reasoning or output. Keep system prompts under 300 tokens. Currently the narrator prompt expands to ~350 tokens after template substitution -- this is already at the limit.

7. **Temperature affects thinking verbosity, not just creativity.** Lower temperature = shorter thinking = more budget for content. For structured output agents (memory, game_state), low temperature (0.2-0.3) is correct. For narrator, temperature 0.8-1.0 is needed for creative prose but burns more thinking tokens.

---

## 3. Narrator Prompt Improvements

### 3.1 Problem: `responding_characters: []` Every Turn

**Root cause analysis.** The current narrator prompt says:

```
- responding_characters can be empty if no one speaks.
```

This gives the model an easy out. A 7B model under token pressure will take the path of least resistance -- returning an empty list avoids the cognitive load of deciding which characters should speak.

Additionally, the prompt lists `ACTIVE CHARACTERS: Maya Chen, Father Joaquin Reyes` but uses full names. The expected output format uses character IDs (`maya`, `joaquin`). The model may not know how to map names to IDs.

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
1. "ACTIVE CHARACTERS" now includes an `(use these IDs in responding_characters)` reminder and uses `{active_characters_with_ids}` which formats as `maya (Maya Chen), joaquin (Father Joaquin Reyes)`.
2. Task item 2 changed from "Decide which characters respond" to "Pick which characters respond. If the player is near a character or their action relates to a character, include that character."
3. Removed "responding_characters can be empty if no one speaks."
4. Added "Include at least one character if any are nearby or relevant."
5. Added "Only omit all characters if the player is truly alone with no one in earshot."

**Context assembly change.** Update `build_narrator_messages()` in `src/theact/engine/context.py` to format characters with IDs:

```python
# Replace the char_names formatting:
char_entries = []
for cid in active_chars:
    if cid in game.characters:
        char_entries.append(f"{cid} ({game.characters[cid].name})")
active_characters_with_ids = ", ".join(char_entries)
```

Update the `format()` call to use `active_characters_with_ids` instead of `active_characters`.

### 3.2 Problem: YAML Output Reliability

**Symptoms.** Turn 3 of the integration test failed to parse narrator YAML. The model sometimes:
- Omits the closing ``` backticks
- Puts text before or after the YAML block
- Uses indentation inconsistently in multi-line strings
- Outputs YAML without the ```yaml fence

**Improvements to apply:**

1. **Ensure the example YAML in the prompt matches the exact format we parse.** The current example uses `|` (literal block scalar) for narration. Verify the model follows this consistently. If not, consider accepting both `|` and quoted strings.

2. **Add a closing backtick reminder.** After the example YAML block in the system prompt, add a line: "End the YAML block with ```."

3. **Improve `extract_yaml_block()` in `src/theact/llm/parsing.py`.** Add handling for:
   - YAML block missing closing backticks (treat text after `\`\`\`yaml\n` as YAML until EOF or next non-YAML content)
   - Leading/trailing prose mixed with the YAML block
   - Tab indentation (some models use tabs instead of spaces)

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

4. **Add tab-to-space normalization before YAML parsing.** In `parse_yaml_response()`, replace tabs with spaces:

```python
def parse_yaml_response(text: str) -> dict[str, Any]:
    yaml_str = extract_yaml_block(text)
    yaml_str = yaml_str.replace("\t", "  ")  # Normalize tabs
    # ... rest of parsing
```

### 3.3 Test Matrix for Narrator

Run `scripts/diagnose_agent.py narrator` with each of these inputs and verify correct output. Capture fixtures for each:

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

The current `CHARACTER_SYSTEM` prompt in `src/theact/agents/prompts.py` is solid but needs two improvements:

**Improvement 1 -- Stronger personality differentiation.** Add a line reinforcing the character's voice:

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

**Improvement 2 -- Guard against empty/truncated responses.** If the character response is empty or under 10 characters after stripping, apply a fallback. Modify `run_character()` in `src/theact/agents/character.py`:

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
    async for chunk in await stream(messages=messages, llm_config=llm_config, agent_config=retry_config):
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

### 4.3 Sequential Response Quality

When Joaquin responds after Maya, he should acknowledge what Maya said. Verify this by running a multi-turn playtest and inspecting character response coherence. The context already includes prior responses via `build_character_messages()`, so this should work -- but needs live validation.

**Test procedure:**
1. Run `scripts/diagnose_agent.py character "What should we do about water?" --character maya`
2. Take Maya's response, then manually test Joaquin with the same context plus Maya's response
3. Verify Joaquin's response references or reacts to Maya's statement

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

### 5.1 `stream_structured()` Edge Case Fix

**Problem.** The `stream_structured()` function in `src/theact/llm/inference.py` streams tokens for live display and then parses YAML from the collected content. But it has no retry mechanism -- if the YAML fails to parse, it raises `YAMLParseError` from the future, which the narrator agent catches and falls back to raw text. This means the first streaming attempt is the only attempt.

**Fix: Add a non-streaming retry after streaming parse failure.** Modify `run_narrator()` in `src/theact/agents/narrator.py` to catch the YAML parse error from the stream result and retry with `complete_structured()` (non-streaming, with retry logic):

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
        # Retry non-streaming with retry logic built into complete_structured
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

Add field validation to each agent's output processing. Missing required fields should produce warnings but not failures. In `src/theact/llm/parsing.py`, the `validate_yaml_fields()` function exists but is not used by any agent. Wire it in:

**Narrator:** Required fields: `narration`. Optional: `responding_characters`, `mood`.
**Memory:** Required fields: `summary`. Optional: `add`, `remove`, `update`.
**Game state:** Required fields: `chapter_complete`. Optional: `reason`, `new_beats`.

Add validation calls in each agent after successful YAML parsing. Log warnings for missing optional fields but do not retry.

### 5.3 Retry Behavior Analysis

The current retry configuration in `src/theact/llm/config.py`:

| Agent | max_retries | retry_temperature_bump |
|-------|-------------|----------------------|
| Narrator | 2 | 0.1 |
| Memory | 2 | 0.1 |
| Game State | 2 | 0.1 |

This means up to 3 total attempts (1 initial + 2 retries). The temperature bump is small (0.1 per retry). This is reasonable for the non-streaming `complete_structured()` path but needs testing:

1. **Verify retry context growth is acceptable.** Each retry appends the failed response (truncated to 200 chars) and a correction message. After 2 retries, the context has grown by ~150 tokens. With an 8K window, this is acceptable.

2. **Test whether temperature bumping helps.** Run `diagnose_agent.py` with `--save-fixture` 5 times for each agent and check whether YAML parse success rate is acceptable (target: 90%+).

### 5.4 Partial YAML Recovery

Add a recovery function for common YAML malformations that 7B models produce. Create `repair_yaml_text()` in `src/theact/llm/parsing.py`:

```python
def repair_yaml_text(text: str) -> str:
    """Attempt to fix common YAML issues from 7B model output.

    Applied before yaml.safe_load() as a best-effort repair.
    """
    # Fix missing newline after `|` in block scalars
    text = re.sub(r"(\w+): \|(\S)", r"\1: |\n  \2", text)

    # Fix trailing content after YAML (model continues after the block)
    # Look for lines that clearly aren't YAML (no colon, no dash prefix, no indent)
    lines = text.split("\n")
    yaml_lines = []
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("-") and ":" not in stripped and not line.startswith(" "):
            # Looks like prose, not YAML -- stop here
            break
        yaml_lines.append(line)

    return "\n".join(yaml_lines)
```

Wire this into `parse_yaml_response()` as a fallback: if `yaml.safe_load()` fails on the extracted block, try `repair_yaml_text()` and parse again before raising `YAMLParseError`.

---

## 6. Memory Update Quality

### 6.1 Validation Strategy

Once characters start responding (after fixing issue 1), memory updates will begin flowing. Validate them by:

1. **Run a 5-turn playtest.** After each turn, inspect `saves/<save_id>/memory/<character>.yaml` to verify:
   - The summary is coherent and incorporates new events
   - Key facts are specific and accurate (not hallucinated)
   - Key facts from previous turns are preserved (not dropped)
   - The fact count stays at or below 10

2. **Run `diagnose_agent.py memory`** with fabricated turn entries that test edge cases:
   - Turn where nothing relevant to the character happened
   - Turn with a dramatic revelation (secret-related)
   - Turn where old facts should be updated, not added

### 6.2 Known Memory Prompt Issues

**Fuzzy matching unreliability.** The memory agent's `remove` and `update` operations require exact text matching of existing facts. 7B models rarely reproduce text verbatim. The current `_apply_memory_diff()` in `src/theact/engine/turn.py` uses exact matching for remove and update, which means these operations will frequently fail silently.

**Fix: Switch to summary-centric memory evolution.** The `summary` field is the reliable mechanism -- the model replaces the whole summary each turn. For key facts, `add` works reliably. Consider de-emphasizing `remove` and `update` in the prompt:

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

**Changes:** Simplified the example to show `remove: []` and `update: []` as defaults, nudging the model to leave them empty. Moved the summary to the top of the YAML example (position emphasis). Added "Include all important information" to prevent summary drift.

### 6.3 Memory Growth Test

After implementing the fixes, run a 10-turn playtest and check:
- Do key_facts stay under 10 per character?
- Does the summary grow then stabilize in length (not unbounded growth)?
- Are facts from turn 1 still present at turn 10 (if still relevant)?

Add a specific issue detector to `PlaytestRunner._detect_issues()`:

```python
# Memory quality checks
for diff in result.memory_diffs:
    if diff.new_summary == diff.old_summary and diff.new_facts != diff.old_facts:
        issues.append(f"memory_summary_unchanged:{diff.character}")
    if not diff.new_summary.strip():
        issues.append(f"memory_empty_summary:{diff.character}")
```

---

## 7. Token Budget Optimization

### 7.1 Thinking vs Content Token Profiling

The thinking model uses `<think>` tags or `reasoning_content` for chain-of-thought before producing content. Both count against `max_tokens`. The current budgets:

| Agent | max_tokens | Expected Thinking | Expected Content |
|-------|-----------|-------------------|-----------------|
| Narrator | 2000 | 500-1500 | 300-500 |
| Character | 1500 | 300-1000 | 100-300 |
| Memory | 1500 | 300-800 | 200-400 |
| Game State | 1000 | 200-600 | 50-150 |
| Summarizer | 1000 | 200-500 | 100-200 |
| Player Agent | 150 | 50-100 | 20-50 |

**Action: Profile actual usage.** Enhance `scripts/diagnose_agent.py` to report thinking vs content token counts:

```python
# In print_response():
thinking_tokens = estimate_tokens(result.thinking) if result.thinking else 0
content_tokens = estimate_tokens(result.content) if result.content else 0
print(f"\n--- TOKEN BREAKDOWN ---")
print(f"Thinking: ~{thinking_tokens} tokens ({info['thinking_length']} chars)")
print(f"Content:  ~{content_tokens} tokens ({info['content_length']} chars)")
print(f"Ratio: {thinking_tokens / max(content_tokens, 1):.1f}:1 thinking:content")
if result.finish_reason == "length":
    print("WARNING: Hit max_tokens limit. Increase budget or reduce thinking.")
```

Run this for all agents and record the actual ratios. If thinking:content ratio exceeds 4:1 for any agent, that agent's budget needs adjustment.

### 7.2 Budget Adjustment Strategy

**If the model finishes with `finish_reason: "length"` (budget exhausted):**
- Increase `max_tokens` for that agent
- But check total context: prompt_tokens + max_tokens must be < 8192

**If the model wastes tokens on excessive thinking:**
- Lower temperature (reduces thinking verbosity)
- For simple agents (game_state), temperature 0.1 may produce tighter reasoning
- Consider adding "Be concise in your reasoning" to the system prompt (but this costs prompt tokens)

**If prompt tokens are too high:**
- Trim conversation history (reduce `max_turns` in `get_recent_conversation()`)
- Compress chapter context (shorter beat descriptions)
- Remove redundant instructions from the system prompt

**Specific optimizations to try:**

1. **Game state agent: reduce max_tokens to 800.** This agent produces the smallest output (~50 tokens). Even with 500 tokens of thinking, 800 is enough. Saves tokens for other agents sharing the context window.

2. **Memory agent: reduce temperature to 0.2.** Memory updates are deterministic -- the model should not be creative about what happened. Lower temperature reduces thinking verbosity.

3. **Player agent: keep max_tokens at 150.** This is tight but the player agent only needs 1-2 sentences. If finish_reason is "length" frequently, bump to 200.

### 7.3 Context Window Budget Per Turn

A full turn makes these LLM calls:

```
Narrator:   ~400 prompt + 2000 max_tokens = 2400 of 8192
Character:  ~350 prompt + 1500 max_tokens = 1850 of 8192 (per character)
Memory:     ~300 prompt + 1500 max_tokens = 1800 of 8192 (per character)
Game State: ~250 prompt + 1000 max_tokens = 1250 of 8192
```

Each call is independent (they don't share context), so these are parallel budgets, not cumulative. The constraint is: prompt_tokens + max_tokens <= 8192 per call.

Monitor this with the diagnostic tool. If any call exceeds the budget, the model's output will be truncated.

---

## 8. Regression Test Infrastructure

### 8.1 Fixture Capture Workflow

`scripts/diagnose_agent.py --save-fixture` already saves JSON fixtures to `tests/fixtures/`. Each fixture contains:

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

### 8.2 Naming Convention

Fixtures should follow this naming pattern:

```
tests/fixtures/<agent>_<scenario>_<variant>.json
```

Examples:
- `narrator_opening_001.json` -- opening scene narration
- `narrator_exploration_001.json` -- exploration action
- `narrator_malformed_yaml_001.json` -- fixture with broken YAML for testing recovery
- `character_maya_dialogue_001.json` -- Maya dialogue response
- `memory_maya_first_turn_001.json` -- Maya's first memory update
- `game_state_no_beats_001.json` -- game state with no beats hit

### 8.3 Regression Test Structure

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
        return json.load(f)


class TestNarratorParsing:
    """Tests for narrator YAML output parsing."""

    def test_valid_narrator_output_parses(self):
        """Verify a known-good narrator response parses correctly."""
        fixture = load_fixture("narrator_001.json")
        data = parse_yaml_response(fixture["content"])
        assert "narration" in data
        assert isinstance(data.get("responding_characters"), list)
        assert data.get("mood") in [
            "tense", "calm", "urgent", "mysterious",
            "humorous", "dramatic", "melancholic", None
        ]

    def test_narrator_missing_closing_backticks(self):
        """Verify YAML extraction handles missing closing backticks."""
        content = '```yaml\nnarration: |\n  You wake up.\nresponding_characters:\n  - maya\nmood: tense\n'
        data = parse_yaml_response(content)
        assert data["narration"].strip() == "You wake up."

    def test_narrator_empty_responding_characters(self):
        """Verify empty responding_characters is handled."""
        content = '```yaml\nnarration: |\n  You look around.\nresponding_characters: []\nmood: calm\n```'
        data = parse_yaml_response(content)
        assert data["responding_characters"] == []

    def test_narrator_responding_characters_none(self):
        """Verify None responding_characters is handled gracefully."""
        content = '```yaml\nnarration: |\n  You look around.\nresponding_characters:\nmood: calm\n```'
        data = parse_yaml_response(content)
        # responding_characters will be None from YAML parse
        assert data.get("responding_characters") is None
        # The narrator agent must handle this with `or []`


class TestMemoryParsing:
    """Tests for memory update YAML parsing."""

    def test_memory_empty_operations(self):
        """Verify memory with no changes parses correctly."""
        content = '```yaml\nsummary: |\n  Maya knows they crashed.\nadd: []\nremove: []\nupdate: []\n```'
        data = parse_yaml_response(content)
        assert "summary" in data
        assert data["add"] == []

    def test_memory_with_additions(self):
        """Verify memory with new facts parses correctly."""
        content = '```yaml\nsummary: |\n  Maya found water.\nadd:\n  - "Found a freshwater stream"\nremove: []\nupdate: []\n```'
        data = parse_yaml_response(content)
        assert len(data["add"]) == 1


class TestGameStateParsing:
    """Tests for game state YAML parsing."""

    def test_no_beats_hit(self):
        """Verify game state with no beats hit."""
        content = '```yaml\nchapter_complete: false\nreason: "Player has not explored yet"\nnew_beats: []\n```'
        data = parse_yaml_response(content)
        assert data["chapter_complete"] is False
        assert data["new_beats"] == []

    def test_beats_hit(self):
        """Verify game state with beats hit."""
        content = '```yaml\nchapter_complete: false\nreason: "Player woke up"\nnew_beats:\n  - "Player wakes on the beach, disoriented"\n```'
        data = parse_yaml_response(content)
        assert len(data["new_beats"]) == 1
```

### 8.4 Expanding Fixture Coverage

After each prompt iteration round, run the following to build the fixture library:

```bash
# Capture a full set of fixtures
for input in "I open my eyes." "I look for survivors." "I search the wreckage." "I ask Maya about water."; do
    uv run python scripts/diagnose_agent.py --save-fixture narrator "$input"
done

uv run python scripts/diagnose_agent.py --save-fixture character "I look around." --character maya
uv run python scripts/diagnose_agent.py --save-fixture character "I look around." --character joaquin
uv run python scripts/diagnose_agent.py --save-fixture memory --character maya
uv run python scripts/diagnose_agent.py --save-fixture game_state
```

---

## 9. Playtest Framework Enhancements

### 9.1 Add Token Tracking to Playtest Logger

The `TurnLog` dataclass in `src/theact/playtest/logger.py` has `prompt_tokens`, `thinking_tokens`, and `response_tokens` fields, but they are never populated. Wire them up by tracking token usage through the turn result.

This requires the turn engine to expose token counts. Add optional token tracking fields to `NarratorOutput`, `CharacterResponse`, and `MemoryDiff`:

```python
# In src/theact/engine/types.py
@dataclass
class NarratorOutput:
    narration: str
    responding_characters: list[str]
    mood: str
    thinking_tokens: int = 0    # estimated from thinking text length
    content_tokens: int = 0     # estimated from content text length
```

Populate these from the LLM results in each agent, using `estimate_tokens()`.

### 9.2 Add Character Response Rate to Playtest Report

Track the percentage of turns where at least one character responded. This is the primary metric for whether the narrator prompt fix (Section 3) is working.

Add to `PlaytestReport`:

```python
character_response_rate: float = 0.0  # % of turns with at least one character
```

Calculate in `generate_report()`:

```python
turns_with_characters = sum(
    1 for t in logger.turns if t.characters_responded
)
character_response_rate = (
    turns_with_characters / max(turns_played, 1)
)
```

### 9.3 Add YAML Parse Success Rate

Track parse failures as a metric. The playtest runner should catch and count YAML-related warnings. Add to `PlaytestReport`:

```python
yaml_parse_success_rate: float = 0.0  # % of structured calls that parsed on first try
```

This requires the agents to report parse attempt counts, which is available in `StructuredResult.attempts`. Thread this through the turn result.

---

## 10. Implementation Steps

### Step 1: Enhance Diagnostics (Day 1)

**Files to modify:**
- `scripts/diagnose_agent.py`

**Changes:**
1. Add token breakdown reporting (thinking vs content tokens, ratio)
2. Add fixture naming with scenario labels: `--save-fixture --scenario opening`
3. Add batch mode: `--batch` flag that runs a predefined set of inputs and saves all fixtures

**Verification:**
- Run `uv run python scripts/diagnose_agent.py narrator "I open my eyes."` and see token breakdown in output
- Run with `--save-fixture` and verify fixture file is created in `tests/fixtures/`

### Step 2: Fix Narrator Character Introduction (Day 1-2)

**Files to modify:**
- `src/theact/agents/prompts.py` (NARRATOR_SYSTEM)
- `src/theact/engine/context.py` (build_narrator_messages -- character ID formatting)

**Changes:**
1. Rewrite NARRATOR_SYSTEM per Section 3.1
2. Update `build_narrator_messages()` to format `active_characters_with_ids`
3. Update the template variable name from `active_characters` to `active_characters_with_ids`

**Verification:**
- Run `uv run python scripts/diagnose_agent.py narrator "I look for survivors."` at least 3 times
- Verify `responding_characters` is non-empty in at least 2 out of 3 runs
- Run `uv run pytest tests/ -v` to ensure no regressions

### Step 3: Improve YAML Parsing Robustness (Day 2)

**Files to modify:**
- `src/theact/llm/parsing.py`

**Changes:**
1. Add unclosed backtick handling in `extract_yaml_block()`
2. Add tab normalization in `parse_yaml_response()`
3. Add `repair_yaml_text()` function as a fallback
4. Wire `validate_yaml_fields()` into each agent

**Verification:**
- Write unit tests for each new parsing case in `tests/test_parsing.py`
- Run `uv run pytest tests/test_parsing.py -v`

### Step 4: Fix Narrator Retry on Streaming Parse Failure (Day 2)

**Files to modify:**
- `src/theact/agents/narrator.py`

**Changes:**
1. Add `complete_structured` import
2. Add fallback retry logic per Section 5.1

**Verification:**
- Run a 5-turn playtest: `uv run python scripts/playtest.py --game lost-island --turns 5`
- Check playtest report for YAML parse errors -- should be zero or near-zero

### Step 5: Optimize Token Budgets (Day 3)

**Files to modify:**
- `src/theact/llm/config.py`

**Changes:**
1. Profile actual token usage per agent using enhanced diagnostics
2. Adjust budgets based on profiling data
3. Starting point adjustments:
   - `GAME_STATE_CONFIG.max_tokens`: 1000 -> 800
   - `MEMORY_UPDATE_CONFIG.temperature`: 0.3 -> 0.2
   - Narrator and character: keep current values unless profiling shows issues

**Verification:**
- Run full agent diagnostics and verify no `finish_reason: "length"` responses
- Run a 5-turn playtest and check for truncated output

### Step 6: Harden Character Agent (Day 3)

**Files to modify:**
- `src/theact/agents/prompts.py` (CHARACTER_SYSTEM)
- `src/theact/agents/character.py` (empty response retry)

**Changes:**
1. Add prompt guardrails per Section 4.2
2. Add empty response retry logic
3. Add fallback response for persistent empty output

**Verification:**
- Run `uv run python scripts/diagnose_agent.py character` for both maya and joaquin
- Verify responses are in-character and non-empty
- Run `uv run pytest tests/ -v`

### Step 7: Harden Memory Agent (Day 3-4)

**Files to modify:**
- `src/theact/agents/prompts.py` (MEMORY_UPDATE_SYSTEM)

**Changes:**
1. Simplify prompt per Section 6.2
2. De-emphasize remove/update operations

**Verification:**
- Run `uv run python scripts/diagnose_agent.py memory --character maya`
- Verify summary is coherent and facts are specific
- Run a 5-turn playtest and check final memory state

### Step 8: Add Playtest Metrics (Day 4)

**Files to modify:**
- `src/theact/engine/types.py` (add token tracking fields)
- `src/theact/playtest/logger.py` (populate token fields)
- `src/theact/playtest/report.py` (add character_response_rate, yaml_parse_success_rate)
- `src/theact/playtest/runner.py` (add memory quality issue detectors)

**Changes:**
1. Add token tracking to turn result types
2. Add character response rate metric
3. Add memory quality issue detectors per Section 6.3

**Verification:**
- Run a 10-turn playtest: `uv run python scripts/playtest.py --game lost-island --turns 10`
- Review playtest report for all new metrics
- Report should show character_response_rate and token stats

### Step 9: Build Regression Test Suite (Day 4-5)

**Files to create:**
- `tests/test_prompt_regression.py`

**Files to populate:**
- `tests/fixtures/` (captured during Steps 2-7)

**Changes:**
1. Create regression test file per Section 8.3
2. Write tests for every fixture captured during hardening
3. Write tests for known edge cases (missing fields, malformed YAML, empty responses)

**Verification:**
- Run `uv run pytest tests/test_prompt_regression.py -v`
- All regression tests pass
- Run `uv run pytest tests/ -v` for full test suite

### Step 10: Full Validation Playtest (Day 5)

**No code changes.** This step validates the cumulative effect of all improvements.

1. Run a 20-turn playtest: `uv run python scripts/playtest.py --game lost-island --turns 20`
2. Review the full playtest report against success criteria (Section 11)
3. If any criteria are not met, identify the failing agent and repeat Steps 2-7 for that agent
4. Run `uv run prek run --all-files` to ensure lint/format compliance

---

## 11. Success Criteria

### 11.1 Quantitative Metrics

These are measured from a 20-turn playtest run.

| Metric | Target | How to Measure |
|--------|--------|----------------|
| YAML parse success rate (narrator) | >= 90% (18/20 turns) | Count turns without narrator YAML parse failures |
| Character response rate | >= 70% (14/20 turns with >= 1 character) | Count turns where `responding_characters` is non-empty |
| Memory update accuracy | 0 `memory_empty_summary` issues | Check playtest issue log |
| Key facts within limit | 0 `memory_overflow` issues | Check playtest issue log |
| No stuck loops | 0 `narrator_repeating` issues | Check playtest issue log |
| No empty narrator responses | 0 `empty_narrator_response` issues | Check playtest issue log |
| Average thinking:content ratio | <= 4:1 across all agents | Token profiling |
| Playtest completion | 20/20 turns without fatal errors | Playtest runs to completion |

### 11.2 Qualitative Criteria

Checked by reading the playtest conversation log:

1. **Narrator narration is descriptive and advances the story.** Not just "You look around. Nothing happens."
2. **Characters sound distinct.** Maya's responses are short, direct, and practical. Joaquin's are calm, cryptic, and parable-like.
3. **Characters acknowledge each other.** When both respond, the second character reacts to the first.
4. **Memory summaries are coherent.** They read as a natural summary of what the character experienced, not garbled text.
5. **Story beats are hit progressively.** Over 20 turns, at least 3-4 beats from Chapter 1 should be marked as hit.
6. **Game state agent does not false-positive.** Beats are only marked when they clearly happened.

### 11.3 Definition of Done

Phase 09 is complete when:
- A 20-turn playtest passes all quantitative metrics in Section 11.1
- A human review of the playtest log confirms the qualitative criteria in Section 11.2
- All regression tests in `tests/test_prompt_regression.py` pass
- `uv run pytest tests/ -v` passes with no failures
- `uv run prek run --all-files` passes with no errors

---

## 12. Dependencies

### No New Dependencies

This phase modifies only existing code and adds test files. No new packages are required.

| Existing Package | Used For |
|---|---|
| `pyyaml` | YAML parsing improvements |
| `openai` | LLM calls (unchanged) |
| `pytest` | Regression tests |

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
| `src/theact/playtest/report.py` | New metrics (character_response_rate, yaml_parse_success_rate) |
| `src/theact/playtest/runner.py` | Memory quality issue detectors |
| `scripts/diagnose_agent.py` | Token breakdown, batch mode, fixture naming |

### Files Created

| File | Purpose |
|---|---|
| `tests/test_prompt_regression.py` | Regression tests for agent output parsing |
| `tests/fixtures/*.json` | Captured model responses for regression testing |

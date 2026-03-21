# Phase 05: Example Game (Lost Island) and Playtest Framework

> **Implementation note:** This phase has two independent parts (game files + playtest framework) that can be built in parallel using subagents. After both are built, run the playtest immediately. If the model produces empty responses, malformed YAML, or repetitive output, iterate on Phase 03's prompt templates — that's the whole point of this phase.

## 1. Overview

This phase delivers two things that are inseparable: a complete, playable game and the tools to prove it works without a human in the loop.

**Part 1 -- Lost Island** is a dramatically simplified version of the original game concept. The original had 500+ word character files, 2000+ word chapter files, 5 chapters, and 3 characters. That level of detail chokes a 7B model. The simplified version has ~60 word character files, sub-200-word chapter files, 3 chapters, and 2 characters. Every word earns its place. The game preserves the essence -- the mystery, the supernatural ambiguity, the character tension between pragmatism and faith -- while fitting comfortably inside a small model's context window.

**Part 2 -- Playtest Framework** is a first-class automation tool, not a debugging afterthought. It runs a complete game session without human intervention by introducing a "player agent" -- another LLM call that reads the narrator/character output and types a reasonable 1-2 sentence response. Everything is logged: every turn, every agent call, every memory update, every millisecond of timing. At the end, a human-readable report is produced. The core question the playtest answers is: "Can a 7B model actually run this game for 20 turns without crashing, going blank, losing memory, or getting stuck?"

Why this matters: without playtesting, we cannot iterate on prompts, context assembly, or memory management. The playtest framework turns prompt engineering from guesswork into empirical science.

> **Note on game file divergence from Phase 01 examples:** Phase 01 Section 4 shows example Lost Island files with chapters `02-survival` and `03-the-discovery`. This phase replaces those examples with a revised chapter structure (`02-the-discovery`, `03-the-heart`). The Phase 01 examples were placeholders illustrating format — these are the final game files. Update the Phase 01 examples to match if both phases are built in sequence.

---

## 2. Lost Island Game Definition

The following YAML files constitute the complete game. Every file is shown in full. These are the actual files that will be written to `games/lost-island/`.

### 2.1 game.yaml

```yaml
id: lost-island
title: The Lost Island
description: Survivors of a plane crash on an uncharted island discover ancient ruins and a secret buried beneath the jungle.
characters:
  - maya
  - joaquin
chapters:
  - 01-the-crash
  - 02-the-discovery
  - 03-the-heart
```

### 2.2 world.yaml

```yaml
setting: >
  Uncharted volcanic island, South Pacific, 2024. Survivors of Flight
  NZ-417 crashed into the northern reef. No GPS, no radio, no rescue coming.

tone: >
  Second person, present tense. Sensory-first narration. Slow-burn tension
  through small wrong details. 100-250 words per turn.

rules: >
  The supernatural is always ambiguous -- every anomaly has a mundane
  explanation. Never break the second-person frame. Never narrate the
  player's thoughts or decisions.
```

> **Word count check:** This world.yaml is 6 sentences (~60 words), matching the ~6 sentence target from CLAUDE.md. The Phase 05 draft had 9 sentences -- trimmed to stay within small-model budget.

### 2.3 characters/maya.yaml

```yaml
name: Maya Chen
role: Fellow crash survivor, pragmatic aerospace engineer.
personality: >
  Direct, sharp, dry humor. Speaks in short declarative sentences.
  Competence is her coping mechanism -- idle hands make her anxious.
  Slow to trust, fiercely loyal once earned.
secret: >
  Racing home to her estranged mother who is dying of cancer.
relationships:
  joaquin: "Respects his calm but distrusts his evasiveness."
```

### 2.4 characters/joaquin.yaml

```yaml
name: Father Joaquin Reyes
role: Mysterious priest who has been to this island before.
personality: >
  Calm, cryptic, speaks in parables and questions. Genuinely kind but
  evasive about specifics. Gets quieter when most serious.
  Never raises his voice.
secret: >
  Visited this island 40 years ago. His companions entered the caves and never returned.
relationships:
  maya: "Admires her strength but worries about her refusal to accept mystery."
```

### 2.5 chapters/01-the-crash.yaml

```yaml
id: 01-the-crash
title: The Crash
summary: >
  The player wakes alone on a beach amid plane wreckage. They explore the
  debris, find evidence of death, and discover Maya. Together they
  establish camp. Father Joaquin appears from the jungle with unsettling
  calm and knowledge of which plants are safe to eat.
beats:
  - Player wakes on the beach, disoriented and injured
  - Explores wreckage and finds basic supplies
  - Discovers a body -- death is real here
  - Finds Maya working alone beyond the headland
  - Father Joaquin emerges from the jungle, strangely calm
  - Group establishes camp and survives the first night
completion: >
  Player, Maya, and Joaquin have formed a group and established a camp.
characters:
  - maya
  - joaquin
next: 02-the-discovery
```

### 2.6 chapters/02-the-discovery.yaml

```yaml
id: 02-the-discovery
title: The Discovery
summary: >
  Exploring inland for fresh water, the group finds ancient stone ruins
  covered in strange carvings. A corridor leads deeper than it should
  into a chamber with an artifact on a stone plinth. Maya wants to study
  it. Joaquin begs them to leave it alone. The island's anomalies grow
  stronger -- compasses spin, drumming echoes at night.
beats:
  - Group treks inland and finds a freshwater spring
  - Strange anomalies appear -- compass spinning, eerie silence
  - Stone ruins discovered half-buried in the jungle
  - A corridor that is longer on the inside than the outside
  - A chamber with an artifact on a plinth
  - Maya and Joaquin clash over what to do with the artifact
completion: >
  The artifact has been found and the player has taken a side in the
  Maya-Joaquin disagreement about the ruins.
characters:
  - maya
  - joaquin
next: 03-the-heart
```

### 2.7 chapters/03-the-heart.yaml

```yaml
id: 03-the-heart
title: The Heart
summary: >
  The group descends into caves beneath the ruins. The walls grow warm
  and pulse with light. In the deepest chamber -- the Heart -- the island
  reveals itself as something vast, ancient, and aware. It is not hostile.
  It is lonely. It offers connection. The player must choose: accept the
  island's offer, sever the connection, or find a middle path.
beats:
  - Group enters the cave system on the western slope
  - Caves grow warmer and the walls begin to pulse with light
  - Joaquin reveals the full truth about his previous visit
  - The Heart chamber -- the island communicates through sensation
  - Maya is tempted by what the island offers her mind
  - The player makes a final choice about the island's fate
completion: >
  The player has reached the Heart and made a choice about the island.
characters:
  - maya
  - joaquin
next: null
```

---

## 3. Playtest Framework Architecture

### 3.1 Module Layout

```
scripts/
  playtest.py                 # CLI entry point
src/theact/
  playtest/
    __init__.py
    runner.py                 # PlaytestRunner -- orchestrates the session
    player_agent.py           # Automated player that generates inputs
    logger.py                 # PlaytestLogger -- captures everything
    report.py                 # Report generation from logged data
    config.py                 # PlaytestConfig dataclass
```

### 3.2 How It Works

```
                  +------------------+
                  |  scripts/        |
                  |  playtest.py     |  CLI entry: parse args, create config
                  +--------+---------+
                           |
                           v
                  +------------------+
                  | PlaytestRunner   |  Outer loop: N turns or chapter end
                  +--------+---------+
                           |
            +--------------+--------------+
            |                             |
            v                             v
    +---------------+            +-----------------+
    | Turn Engine   |            | Player Agent    |
    | (Phase 03)    |            | (new, Phase 05) |
    +-------+-------+            +--------+--------+
            |                             |
            |  narrator + character       |  reads output,
            |  responses                  |  generates player
            |                             |  input (1-2 sentences)
            +-------------+---------------+
                          |
                          v
                 +------------------+
                 | PlaytestLogger   |  Records everything:
                 |                  |  turns, timing, errors,
                 |                  |  thinking tokens, memory
                 +--------+---------+
                          |
                          v
                 +------------------+
                 | Report Generator |  Writes human-readable
                 |                  |  report to playtests/
                 +------------------+
```

### 3.3 PlaytestRunner

The runner is a loop:

```python
class PlaytestRunner:
    """Runs a complete playtest session."""

    def __init__(self, config: PlaytestConfig):
        self.config = config
        self.logger = PlaytestLogger()
        self.player_agent = PlayerAgent(
            config.llm_config,
            edge_case_frequency=config.edge_case_frequency,
        )

    async def run(self) -> PlaytestReport:
        # 1. Create a fresh save from the game definition
        save_id = f"playtest-{self.config.timestamp}"
        create_save(
            game_id=self.config.game_id,
            save_id=save_id,
            player_name=self.config.player_name,
        )

        # 2. Load the game (load_save takes save_id string, not path)
        game = load_save(save_id)

        # 2a. Run the opening narration (no player input -- narrator speaks first)
        #     The turn engine's run_turn with player_input=None produces the
        #     opening narration. This matches the real game flow where the
        #     narrator sets the scene before the player acts.
        try:
            opening_result = await run_turn(game, player_input=None)
            self.logger.log_turn_result(0, opening_result, 0.0)
        except Exception as e:
            self.logger.log_error(0, e)
            if self.config.stop_on_error:
                return self.logger.generate_report()

        for turn_num in range(1, self.config.max_turns + 1):
            turn_start = time.monotonic()

            try:
                # 3. Get player input from the player agent (or use configured
                #    opening_action for the very first player turn)
                if turn_num == 1:
                    player_input = self.config.opening_action
                else:
                    player_input = await self.player_agent.decide(
                        conversation_tail=self.logger.recent_conversation(n=6),
                        chapter=game.chapters[game.state.current_chapter],
                        turn_number=turn_num,
                    )

                self.logger.log_player_input(turn_num, player_input)

                # 4. Run the turn engine (Phase 03)
                result = await run_turn(game, player_input)

                # 5. Log everything
                self.logger.log_turn_result(turn_num, result, time.monotonic() - turn_start)

                # 6. Check for issues
                self._check_for_issues(turn_num, result)

                # 7. Check chapter completion
                if result.chapter_completed:
                    self.logger.log_event(turn_num, "chapter_completed", result.new_chapter)
                    if result.game_over:
                        self.logger.log_event(turn_num, "game_over", "")
                        break

            except Exception as e:
                self.logger.log_error(turn_num, e)
                if self.config.stop_on_error:
                    break

            # 7a. Incremental save -- write logger state to disk after each
            #     turn so data survives process crashes (OOM, killed, etc.).
            #     If the process dies mid-playtest, the partial data in
            #     the output directory can still be used for diagnosis.
            self.logger.flush_to_disk(self.config.output_dir, self.config.timestamp)

        # 8. Generate report
        return self.logger.generate_report()

    def _check_for_issues(self, turn: int, result: TurnResult) -> None:
        """Detect common problems."""
        # Empty responses
        if not result.narrator_text.strip():
            self.logger.log_issue(turn, "empty_narrator_response")

        for char_name, text in result.character_texts.items():
            if not text.strip():
                self.logger.log_issue(turn, f"empty_character_response:{char_name}")

        # Repeated content (stuck loop detection)
        if self.logger.is_repeating(result.narrator_text, window=3):
            self.logger.log_issue(turn, "narrator_repeating")

        # Memory corruption -- key_facts exceeding limit (max 10 per CLAUDE.md)
        for name, memory in result.updated_memories.items():
            if len(memory.key_facts) > 10:
                self.logger.log_issue(turn, f"memory_overflow:{name}")
```

### 3.4 PlaytestConfig

```python
@dataclass
class PlaytestConfig:
    """Configuration for a playtest run."""
    game_id: str                          # e.g. "lost-island"
    max_turns: int = 20                   # stop after N turns
    player_name: str = "Alex"             # default player name
    opening_action: str = "I try to free my arm and look around."
    stop_on_error: bool = False           # keep going through errors
    edge_case_frequency: float = 0.15     # 15% chance of unusual action
    timestamp: str = ""                   # auto-filled
    llm_config: LLMConfig = field(default_factory=LLMConfig)
    output_dir: str = "playtests"         # base output directory
```

---

## 4. Player Agent

The player agent is a separate LLM call that reads the game output and produces a player action. It must behave like a cooperative but curious player -- not a chaos monkey, not a passive observer.

### 4.1 Player Agent System Prompt

```
You are a player in a text-based RPG. You are playing a crash survivor
on a mysterious island. Read the narrator and character dialogue, then
respond with a short action or statement (1-2 sentences).

Guidelines:
- Stay in character as a crash survivor
- React naturally to what just happened
- Alternate between: exploring, talking to characters, investigating mysteries
- Be curious about strange details
- Sometimes push back on character suggestions
- Keep responses to 1-2 sentences
- IMPORTANT: Do NOT repeat actions you have already taken. If you already
  looked around, try something new. Vary your approach each turn.
```

### 4.2 Edge Case Injection

The player agent occasionally (configurable, default 15%) produces an unusual action to stress-test the system. This is controlled by appending an instruction to the player agent's prompt:

```python
EDGE_CASE_PROMPTS = [
    "Do something unexpected -- try to go somewhere unusual or off-script.",
    "Ask a character a very direct, uncomfortable question.",
    "Try to do something silly or out of character to test the narrator.",
    "Reference something from much earlier in the conversation.",
    "Try to leave the current area or refuse to cooperate with the characters.",
    "Give a very short, minimal response -- just one or two words like 'ok' or 'sure'.",
    "Try to break the fourth wall -- ask about game mechanics, stats, or the narrator.",
    "Attempt something violent or aggressive toward a character.",
    "Say something that doesn't make sense -- gibberish or a non sequitur.",
    "Try to use or interact with an object that hasn't been mentioned.",
]
```

When an edge case triggers, one of these is appended to the player agent's system prompt for that turn. The logger records which turns had edge case injection.

### 4.3 Player Agent Implementation

```python
class PlayerAgent:
    """Generates automated player inputs for playtesting."""

    def __init__(self, llm_config: LLMConfig, edge_case_frequency: float = 0.15):
        self.llm_config = llm_config
        self.edge_case_frequency = edge_case_frequency

    async def decide(
        self,
        conversation_tail: list[ConversationEntry],
        chapter: Chapter,
        turn_number: int,
    ) -> str:
        """Generate the next player action based on recent conversation."""

        # Build context for the player agent
        system = PLAYER_SYSTEM_PROMPT

        # Occasionally inject edge case behavior
        is_edge_case = random.random() < self.edge_case_frequency
        if is_edge_case:
            system += "\n\n" + random.choice(EDGE_CASE_PROMPTS)

        # Format recent conversation as messages
        messages = [{"role": "system", "content": system}]

        # Add chapter context (just the title and summary)
        messages.append({
            "role": "user",
            "content": f"Current chapter: {chapter.title}\n{chapter.summary}",
        })

        # Add recent conversation turns
        for entry in conversation_tail:
            role = "assistant" if entry.role != "player" else "user"
            speaker = entry.character or entry.role.capitalize()
            messages.append({
                "role": role,
                "content": f"[{speaker}] {entry.content}",
            })

        # Add action request
        messages.append({
            "role": "user",
            "content": "What do you do? (1-2 sentences)",
        })

        result = await complete(
            messages=messages,
            temperature=0.9,
            max_tokens=150,
            llm_config=self.llm_config,
        )

        action = result.content.strip()

        # Log metadata
        return action
```

The player agent uses a higher temperature (0.9) to produce varied actions across playtests and low max_tokens (150) to keep responses short.

---

## 5. Playtest Report

### 5.1 Output Structure

Each playtest produces a timestamped directory:

```
playtests/
  2026-03-20T14-30-00/
    report.md                  # Human-readable summary
    conversation.yaml          # Full conversation log (same format as save)
    thinking.yaml              # All thinking tokens from all agents
    errors.yaml                # Any errors encountered
    timing.yaml                # Per-turn timing breakdown
    memory_final.yaml          # Memory state at end of playtest
    config.yaml                # PlaytestConfig used for this run
```

### 5.2 report.md Format

```markdown
# Playtest Report

**Game:** The Lost Island
**Date:** 2026-03-20 14:30:00
**Turns:** 18 / 20 (chapter 02-the-discovery completed)
**Duration:** 4m 32s
**Model:** olafangensan-glm-4.7-flash-heretic

## Summary

The playtest ran for 18 turns across chapters 01-the-crash and
02-the-discovery. The player woke on the beach, found Maya, established
camp with Joaquin, explored inland, and discovered the ruins. The session
ended when the artifact was found and the player sided with Maya.

## Issues

| Turn | Issue                     | Details                     |
|------|---------------------------|-----------------------------|
| 7    | empty_character_response  | Joaquin returned blank      |
| 12   | narrator_repeating        | Similar to turn 11 output   |

## Timing

- Average turn: 14.2s
- Slowest turn: 23.1s (turn 5 -- 3 agent calls)
- Fastest turn: 8.4s (turn 14)
- Total LLM calls: 72
- Total thinking tokens: ~4,200
- Total response tokens: ~3,800
- Total prompt tokens: ~12,400

## Per-Turn Detail

| Turn | Elapsed | Characters Responded | Prompt Tok | Thinking Tok | Response Tok | Issues |
|------|---------|----------------------|------------|--------------|--------------|--------|
| 0    | 2.1s    | (opening narration)  | 340        | 120          | 180          |        |
| 1    | 12.4s   | Maya                 | 680        | 200          | 310          |        |
| 2    | 18.1s   | Maya, Joaquin        | 920        | 280          | 420          |        |
| ...  | ...     | ...                  | ...        | ...          | ...          | ...    |

## Chapter Progress

- 01-the-crash: completed at turn 8 (beats hit: 6/6)
- 02-the-discovery: completed at turn 18 (beats hit: 5/6, missed: "Strange anomalies appear")

## Edge Case Turns

- Turn 4: "Try to swim out to the wreckage" -- narrator handled well
- Turn 11: "Refuse to follow Joaquin" -- triggered character response
- Turn 16: "Ask Maya about her personal life" -- revealed secret early

## Memory State (Final)

### Maya Chen
Summary: Met player on the beach. Built camp together. Discovered ruins...
Key facts: [5 items]

### Father Joaquin
Summary: Appeared from the jungle on day one. Led group to the spring...
Key facts: [4 items]

## Narrative Summary

[Auto-generated by passing the conversation log through one final LLM
call that summarizes what happened in the playtest]
```

### 5.3 PlaytestLogger

```python
@dataclass
class TurnLog:
    """Everything captured for a single turn."""
    turn: int
    player_input: str
    narrator_text: str
    narrator_thinking: str
    character_texts: dict[str, str]       # character_name -> text
    character_thinking: dict[str, str]    # character_name -> thinking
    characters_responded: list[str]       # ordered list of characters who spoke
    memory_updates: dict[str, str]        # character_name -> new summary
    memory_thinking: dict[str, str]       # character_name -> thinking
    game_state_thinking: str              # game state agent thinking
    beats_hit: list[str]                  # beats marked this turn
    elapsed_seconds: float
    issues: list[str]
    is_edge_case: bool
    # Token usage per turn (summed across all agent calls in this turn)
    prompt_tokens: int = 0
    thinking_tokens: int = 0
    response_tokens: int = 0

class PlaytestLogger:
    """Accumulates all playtest data for report generation."""

    def __init__(self):
        self.turns: list[TurnLog] = []
        self.errors: list[tuple[int, Exception]] = []
        self.events: list[tuple[int, str, str]] = []

    def log_player_input(self, turn: int, text: str) -> None: ...
    def log_turn_result(self, turn: int, result: TurnResult, elapsed: float) -> None: ...
    def log_error(self, turn: int, error: Exception) -> None: ...
    def log_issue(self, turn: int, issue: str) -> None: ...
    def log_event(self, turn: int, event: str, detail: str) -> None: ...

    def flush_to_disk(self, output_dir: str, timestamp: str) -> None:
        """Write current logger state to disk incrementally.

        Called after each turn so data survives process crashes. Writes
        conversation.yaml and errors.yaml to the timestamped output
        directory. The final report.md is only written at the end, but
        the raw data files are always up-to-date on disk.
        """
        ...

    def recent_conversation(self, n: int = 6) -> list[ConversationEntry]:
        """Return the last N conversation entries for the player agent."""
        ...

    def is_repeating(self, text: str, window: int = 3) -> bool:
        """Check if the narrator output is too similar to recent turns.

        Uses word-set overlap: computes the set of words in the new text
        and each recent narrator text, then flags as repeating if the
        Jaccard similarity exceeds 0.6 (60% word overlap). This is more
        robust than prefix matching, which gives false positives when
        many narrator responses start with 'You' or 'The'.
        """
        new_words = set(text.lower().split())
        for turn in self.turns[-window:]:
            old_words = set(turn.narrator_text.lower().split())
            if not new_words or not old_words:
                continue
            overlap = len(new_words & old_words) / len(new_words | old_words)
            if overlap > 0.6:
                return True
        return False

    def generate_report(self) -> PlaytestReport:
        """Compile all logged data into a PlaytestReport."""
        ...
```

---

## 5.4 Crash Resilience

The playtest framework must handle two failure modes:

**In-process errors** (LLM timeout, parse failure, unexpected exception): These are caught by the `try/except` in `PlaytestRunner.run()`. When `stop_on_error=False`, the error is logged and the loop continues to the next turn. When `stop_on_error=True`, the loop breaks and the report is generated from whatever data was collected.

**Process crashes** (OOM kill, SIGKILL, power failure): The `PlaytestLogger.flush_to_disk()` method writes raw data files (conversation, errors, timing) to the output directory after every turn. If the process dies, the partial data on disk can be inspected manually. The final `report.md` will be missing, but the YAML data files will contain everything up to the last completed turn. To generate a report from partial data after a crash:

```bash
uv run python scripts/playtest.py --resume playtests/2026-03-20T14-30-00/
```

The `--resume` flag loads partial data from the specified directory, generates a report from it, and optionally continues the playtest from where it left off (if the save still exists).

---

## 6. Implementation Steps

Build in this order. Each step should produce working, testable code before moving on.

### Step 1: Game Definition Files

Write all YAML files from Section 2 to disk:

- `games/lost-island/game.yaml`
- `games/lost-island/world.yaml`
- `games/lost-island/characters/maya.yaml`
- `games/lost-island/characters/joaquin.yaml`
- `games/lost-island/chapters/01-the-crash.yaml`
- `games/lost-island/chapters/02-the-discovery.yaml`
- `games/lost-island/chapters/03-the-heart.yaml`

Validate that all files load correctly through the Phase 01 YAML I/O and model layer:

```python
# Quick validation script
from theact.io.yaml_io import load_yaml
from theact.models.game import GameMeta
from theact.models.world import World
from theact.models.character import Character
from theact.models.chapter import Chapter

game = load_yaml(Path("games/lost-island/game.yaml"), GameMeta)
world = load_yaml(Path("games/lost-island/world.yaml"), World)
maya = load_yaml(Path("games/lost-island/characters/maya.yaml"), Character)
# ... etc
```

### Step 2: Playtest Config and Logger

Build the data layer for playtesting:

- `src/theact/playtest/__init__.py`
- `src/theact/playtest/config.py` -- `PlaytestConfig` dataclass
- `src/theact/playtest/logger.py` -- `PlaytestLogger`, `TurnLog` dataclass

Write tests:
- Test `TurnLog` creation and field access
- Test `PlaytestLogger.is_repeating()` with various inputs
- Test `PlaytestLogger.recent_conversation()` returns correct tail

### Step 3: Player Agent

Build the automated player:

- `src/theact/playtest/player_agent.py` -- `PlayerAgent` class

This depends on Phase 02 (LLM client). Write it so it calls `complete()` from `src/theact/llm/inference.py`.

Write tests:
- Test prompt construction (mock the LLM call, verify the messages list)
- Test edge case injection probability
- Test that the system prompt changes when edge case is active

### Step 4: Playtest Runner

Build the main orchestration loop:

- `src/theact/playtest/runner.py` -- `PlaytestRunner` class

This depends on Phase 03 (turn engine). The runner calls `run_turn()` from the engine, then calls the player agent for the next input.

Write tests:
- Test the issue detection logic (`_check_for_issues`) with synthetic TurnResults
- Test the loop terminates on `max_turns`
- Test the loop terminates on `game_over`
- Test error logging when an exception is raised
- Test that the opening narration runs before the first player turn (turn 0)
- Test that `flush_to_disk` writes partial data after each turn
- Test that `--resume` can load and report on partial playtest data

### Step 5: Report Generator

Build the report output:

- `src/theact/playtest/report.py` -- `generate_report()`, `write_report()`

The report generator takes a `PlaytestLogger` and produces:
1. The `report.md` summary (string formatting, no LLM call required except for the optional narrative summary)
2. The YAML data files (`conversation.yaml`, `thinking.yaml`, etc.)
3. Creates the timestamped output directory

Write tests:
- Test report markdown generation from synthetic log data
- Test YAML file output matches expected format
- Test directory creation

### Step 6: CLI Entry Point

Build the command-line script:

- `scripts/playtest.py`

```python
#!/usr/bin/env python
"""Run an automated playtest session.

Usage:
    uv run python scripts/playtest.py --game lost-island --turns 20
    uv run python scripts/playtest.py --game lost-island --turns 10 --stop-on-error
"""

import argparse
import asyncio
from datetime import datetime
from theact.playtest.config import PlaytestConfig
from theact.playtest.runner import PlaytestRunner


def main():
    parser = argparse.ArgumentParser(description="Run an automated playtest")
    parser.add_argument("--game", required=True, help="Game ID (e.g. lost-island)")
    parser.add_argument("--turns", type=int, default=20, help="Max turns to play")
    parser.add_argument("--player-name", default="Alex", help="Player character name")
    parser.add_argument("--stop-on-error", action="store_true", help="Stop on first error")
    parser.add_argument("--edge-case-freq", type=float, default=0.15,
                        help="Frequency of edge case actions (0.0 to 1.0)")
    parser.add_argument("--resume", type=str, default=None,
                        help="Resume/report from a partial playtest directory")
    args = parser.parse_args()

    config = PlaytestConfig(
        game_id=args.game,
        max_turns=args.turns,
        player_name=args.player_name,
        stop_on_error=args.stop_on_error,
        edge_case_frequency=args.edge_case_freq,
        timestamp=datetime.now().strftime("%Y-%m-%dT%H-%M-%S"),
    )

    runner = PlaytestRunner(config)
    report = asyncio.run(runner.run())

    print(f"\nPlaytest complete. Report saved to: {report.output_path}")
    print(f"Turns played: {report.turns_played}/{config.max_turns}")
    print(f"Issues found: {report.issue_count}")
    print(f"Errors: {report.error_count}")


if __name__ == "__main__":
    main()
```

### Step 7: Integration Testing

Run a real playtest against the LLM endpoint:

1. Ensure Phases 01-04 are complete and the turn engine works
2. Run: `uv run python scripts/playtest.py --game lost-island --turns 5 --stop-on-error`
3. Verify the playtest report is generated
4. Read the report and check:
   - No empty responses
   - Character voices are distinct (Maya is direct, Joaquin is cryptic)
   - Memory updates make sense
   - Beats are being tracked
   - The player agent produces reasonable actions
5. Run a longer session: `--turns 20`
6. Check for degradation over time (repetition, memory corruption, context confusion)

---

## 7. Verification

### 7.1 Game Definition Verification

Phase 05 Part 1 is complete when:

1. All 7 YAML files exist in `games/lost-island/` and load without errors through Phase 01 models
2. `world.yaml` is under 500 bytes
3. Each character YAML is under 400 bytes
4. Each chapter YAML is under 600 bytes
5. `game.yaml` references exactly 2 characters and 3 chapters
6. Chapter `next` fields form a valid chain: `01 -> 02 -> 03 -> null`
7. A save can be created from the game definition via `create_save()`
8. The save loads via `load_save()` with all models fully populated

### 7.2 Playtest Framework Verification

Phase 05 Part 2 is complete when:

1. `uv run python scripts/playtest.py --game lost-island --turns 5` runs without crashing
2. A timestamped directory appears in `playtests/` with all expected files
3. `report.md` contains: summary, issues table, timing stats, per-turn detail, chapter progress, memory state
4. `conversation.yaml` contains the full conversation with correct turn numbers and roles
5. `thinking.yaml` captures thinking tokens from narrator, character, and memory agents
6. The player agent produces varied, in-character responses (not the same thing every turn)
7. Issue detection catches empty responses (verified by injecting a mock empty response)
8. Issue detection catches repetition (verified by injecting duplicate narrator text)
9. A 20-turn playtest produces a coherent narrative (human review of the report)
10. Errors are logged but do not crash the runner when `stop_on_error=False`
11. The opening narration (turn 0, no player input) runs before the first player action
12. Partial playtest data is saved to disk after each turn (crash resilience)
13. `--resume` flag generates a report from a partial/interrupted playtest directory

### 7.3 Live Testing & Regression Capture

This is where planning meets reality. The playtest framework is itself the live testing tool — use it iteratively.

**Step 1 — Run a 20-turn playtest and analyze the report:**
```bash
uv run python scripts/playtest.py --game lost-island --turns 20
```
- Read `playtests/<timestamp>/report.md` end to end. Look for:
  - Empty or near-empty responses from any agent
  - Characters breaking character or speaking for each other
  - Memory accumulating duplicate or contradictory facts
  - The narrator ignoring chapter beats or rushing through them
  - The game state agent marking chapters complete too early or never marking them
  - Rolling summary losing critical plot points
  - The player agent getting stuck in a loop (same action every turn)

**Step 2 — Iterate on prompts and engine:**
- For each issue, trace it to a root cause (usually a prompt in `agents/prompts.py` or a context assembly issue in `engine/context.py`).
- Fix the issue, then re-run a 10-turn playtest to verify the fix and check for regressions.
- Repeat until a 20-turn playtest produces a coherent narrative with no crashes or empty responses.

**Step 3 — Capture as regression tests:**
- For issues found in the engine/agents (not prompt wording): write automated tests.
- Example: if the memory agent produces a diff that removes a fact that doesn't exist, write `test_apply_memory_diff_remove_nonexistent()` to verify it's handled gracefully.
- Example: if the game state agent returns `chapter_complete: "yes"` instead of `chapter_complete: true`, write `test_game_state_result_string_bool()` to verify coercion works.
- Save problematic model responses as fixtures for offline testing of parsers.

**Step 4 — Final validation:**
- Run `uv run pytest tests/ -v` — all tests pass.
- Run a final 20-turn playtest. The report should show: zero crashes, zero empty responses, coherent narrative, at least some beats hit.

---

## 8. Dependencies

No new packages are required beyond what Phases 01-04 already provide:

- `openai` -- used by the player agent (same LLM client as the game engine)
- `pydantic` -- used for config and log data models
- `pyyaml` -- used for report data files

The playtest framework reuses all existing infrastructure. The only "new" LLM usage is the player agent, which calls the same `complete()` function from Phase 02 with the same Venice AI endpoint and model.

Standard library modules used:

- `argparse` -- CLI argument parsing for `scripts/playtest.py`
- `time` -- `monotonic()` for turn timing
- `random` -- edge case injection probability
- `asyncio` -- running the async playtest loop
- `datetime` -- timestamp generation for playtest directories

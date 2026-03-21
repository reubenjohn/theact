"""LLM call logging for observability and diagnostics."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class LLMCallRecord:
    """A single LLM API call record."""

    timestamp: str  # ISO 8601
    agent: str  # "narrator", "character:maya", "memory:joaquin", "game_state", "summarizer"
    turn: int
    prompt_tokens: int
    thinking_tokens: int
    content_tokens: int
    latency_ms: int
    finish_reason: str
    parse_result: str  # ParseFailureType value
    parse_attempts: int
    retry_count: int
    temperature: float
    max_tokens: int


@dataclass
class LLMCallLog:
    """Accumulates LLM call records across a session."""

    records: list[LLMCallRecord] = field(default_factory=list)

    def log(self, record: LLMCallRecord) -> None:
        """Append a call record to the log."""
        self.records.append(record)

    def records_for_turn(self, turn: int) -> list[LLMCallRecord]:
        """Return all records for a given turn number."""
        return [r for r in self.records if r.turn == turn]

    def records_for_agent(self, agent: str) -> list[LLMCallRecord]:
        """Return records matching an agent prefix.

        Prefix match: "character" matches "character:maya", "character:joaquin", etc.
        Exact match also works: "narrator" matches "narrator".
        """
        return [
            r
            for r in self.records
            if r.agent == agent or r.agent.startswith(agent + ":")
        ]

    def summary(self) -> dict:
        """Return aggregate statistics across all records."""
        if not self.records:
            return {
                "total_calls": 0,
                "mean_latency_ms": 0,
                "parse_success_rate": 0.0,
                "total_prompt_tokens": 0,
                "total_thinking_tokens": 0,
                "total_content_tokens": 0,
                "length_finishes": 0,
                "total_retries": 0,
            }

        total = len(self.records)
        total_latency = sum(r.latency_ms for r in self.records)
        successes = sum(1 for r in self.records if r.parse_result == "success")

        return {
            "total_calls": total,
            "mean_latency_ms": round(total_latency / total),
            "parse_success_rate": round(successes / total, 3) if total else 0.0,
            "total_prompt_tokens": sum(r.prompt_tokens for r in self.records),
            "total_thinking_tokens": sum(r.thinking_tokens for r in self.records),
            "total_content_tokens": sum(r.content_tokens for r in self.records),
            "length_finishes": sum(
                1 for r in self.records if r.finish_reason == "length"
            ),
            "total_retries": sum(r.retry_count for r in self.records),
        }

    def agent_summary(self) -> dict[str, dict]:
        """Return per-agent aggregate statistics.

        Groups by full agent name (e.g., "character:maya" is separate from
        "character:joaquin").
        """
        agents: dict[str, list[LLMCallRecord]] = {}
        for r in self.records:
            agents.setdefault(r.agent, []).append(r)

        result: dict[str, dict] = {}
        for agent, recs in agents.items():
            total = len(recs)
            total_latency = sum(r.latency_ms for r in recs)
            successes = sum(1 for r in recs if r.parse_result == "success")
            result[agent] = {
                "total_calls": total,
                "mean_latency_ms": round(total_latency / total) if total else 0,
                "parse_success_rate": round(successes / total, 3) if total else 0.0,
                "total_prompt_tokens": sum(r.prompt_tokens for r in recs),
                "total_thinking_tokens": sum(r.thinking_tokens for r in recs),
                "total_content_tokens": sum(r.content_tokens for r in recs),
                "length_finishes": sum(1 for r in recs if r.finish_reason == "length"),
                "total_retries": sum(r.retry_count for r in recs),
            }
        return result

    def dump_yaml(self, path: Path) -> None:
        """Write all records to a YAML file."""
        data = []
        for r in self.records:
            data.append(
                {
                    "timestamp": r.timestamp,
                    "agent": r.agent,
                    "turn": r.turn,
                    "prompt_tokens": r.prompt_tokens,
                    "thinking_tokens": r.thinking_tokens,
                    "content_tokens": r.content_tokens,
                    "latency_ms": r.latency_ms,
                    "finish_reason": r.finish_reason,
                    "parse_result": r.parse_result,
                    "parse_attempts": r.parse_attempts,
                    "retry_count": r.retry_count,
                    "temperature": r.temperature,
                    "max_tokens": r.max_tokens,
                }
            )

        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            yaml.dump(
                data,
                f,
                default_flow_style=False,
                allow_unicode=True,
                sort_keys=False,
            )

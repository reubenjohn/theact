"""Diagnostics filesystem writer for per-turn agent artifacts.

When debug mode is enabled, writes all prompts, raw responses, parsed
output, and call records to a structured directory tree under the save
path. This is purely passive instrumentation — it reads data that was
already produced and writes it to disk for offline inspection.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from theact.llm.call_log import LLMCallRecord


class DiagnosticsWriter:
    """Writes per-turn diagnostic artifacts to disk."""

    def __init__(self, save_path: Path, turn: int) -> None:
        self.base = save_path / "diagnostics" / f"turn-{turn:03d}"
        self.base.mkdir(parents=True, exist_ok=True)

    def write_agent(
        self,
        agent_dir_name: str,
        messages: list[dict],
        raw_response: str,
        thinking: str = "",
        parsed_data: dict | None = None,
        call_record: LLMCallRecord | None = None,
    ) -> None:
        """Write all artifacts for a single agent call.

        Creates a subdirectory under the turn directory with:
        - system_prompt.txt
        - user_message.txt
        - raw_response.txt
        - thinking.txt (if non-empty)
        - parsed.yaml (if parsed_data provided)
        - call_record.yaml (if call_record provided)
        """
        agent_dir = self.base / agent_dir_name
        agent_dir.mkdir(parents=True, exist_ok=True)

        # Write system prompt (first system message)
        system_msgs = [m for m in messages if m.get("role") == "system"]
        if system_msgs:
            (agent_dir / "system_prompt.txt").write_text(
                system_msgs[0].get("content", ""), encoding="utf-8"
            )

        # Write user message (all user messages concatenated)
        user_msgs = [m for m in messages if m.get("role") == "user"]
        if user_msgs:
            user_text = "\n\n---\n\n".join(m.get("content", "") for m in user_msgs)
            (agent_dir / "user_message.txt").write_text(user_text, encoding="utf-8")

        # Write raw response
        (agent_dir / "raw_response.txt").write_text(raw_response, encoding="utf-8")

        # Write thinking (if non-empty)
        if thinking:
            (agent_dir / "thinking.txt").write_text(thinking, encoding="utf-8")

        # Write parsed data
        if parsed_data is not None:
            with open(agent_dir / "parsed.yaml", "w") as f:
                yaml.dump(
                    parsed_data,
                    f,
                    default_flow_style=False,
                    allow_unicode=True,
                    sort_keys=False,
                )

        # Write call record
        if call_record is not None:
            record_data = {
                "timestamp": call_record.timestamp,
                "agent": call_record.agent,
                "turn": call_record.turn,
                "prompt_tokens": call_record.prompt_tokens,
                "thinking_tokens": call_record.thinking_tokens,
                "content_tokens": call_record.content_tokens,
                "latency_ms": call_record.latency_ms,
                "finish_reason": call_record.finish_reason,
                "parse_result": call_record.parse_result,
                "parse_attempts": call_record.parse_attempts,
                "retry_count": call_record.retry_count,
                "temperature": call_record.temperature,
                "max_tokens": call_record.max_tokens,
            }
            with open(agent_dir / "call_record.yaml", "w") as f:
                yaml.dump(
                    record_data,
                    f,
                    default_flow_style=False,
                    allow_unicode=True,
                    sort_keys=False,
                )

    def write_summary(self, call_records: list[LLMCallRecord]) -> None:
        """Write a summary of all call records for this turn."""
        if not call_records:
            return

        total_latency = sum(r.latency_ms for r in call_records)
        total_calls = len(call_records)
        successes = sum(1 for r in call_records if r.parse_result == "success")

        summary_data = {
            "turn_calls": total_calls,
            "total_latency_ms": total_latency,
            "mean_latency_ms": round(total_latency / total_calls) if total_calls else 0,
            "parse_success_rate": round(successes / total_calls, 3)
            if total_calls
            else 0.0,
            "total_prompt_tokens": sum(r.prompt_tokens for r in call_records),
            "total_thinking_tokens": sum(r.thinking_tokens for r in call_records),
            "total_content_tokens": sum(r.content_tokens for r in call_records),
            "agents": [r.agent for r in call_records],
        }

        with open(self.base / "summary.yaml", "w") as f:
            yaml.dump(
                summary_data,
                f,
                default_flow_style=False,
                allow_unicode=True,
                sort_keys=False,
            )

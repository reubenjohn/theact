"""Tests for the diagnostics filesystem writer."""

from pathlib import Path

import yaml

from theact.engine.diagnostics import DiagnosticsWriter
from theact.llm.call_log import LLMCallRecord


def _make_record(agent: str = "narrator", turn: int = 1) -> LLMCallRecord:
    return LLMCallRecord(
        timestamp="2026-03-20T14:30:00Z",
        agent=agent,
        turn=turn,
        prompt_tokens=200,
        thinking_tokens=100,
        content_tokens=150,
        latency_ms=1500,
        finish_reason="stop",
        parse_result="success",
        parse_attempts=1,
        retry_count=0,
        temperature=1.0,
        max_tokens=2000,
    )


class TestDiagnosticsWriter:
    def test_creates_turn_directory(self, tmp_path: Path):
        DiagnosticsWriter(tmp_path, turn=1)
        assert (tmp_path / "diagnostics" / "turn-001").is_dir()

    def test_turn_directory_zero_padded(self, tmp_path: Path):
        DiagnosticsWriter(tmp_path, turn=42)
        assert (tmp_path / "diagnostics" / "turn-042").is_dir()

    def test_high_turn_number(self, tmp_path: Path):
        DiagnosticsWriter(tmp_path, turn=999)
        assert (tmp_path / "diagnostics" / "turn-999").is_dir()


class TestWriteAgent:
    def test_writes_system_prompt(self, tmp_path: Path):
        writer = DiagnosticsWriter(tmp_path, turn=1)
        messages = [
            {"role": "system", "content": "You are the narrator."},
            {"role": "user", "content": "Player says: hello"},
        ]
        writer.write_agent("narrator", messages, "raw response text")
        agent_dir = tmp_path / "diagnostics" / "turn-001" / "narrator"
        assert agent_dir.is_dir()
        assert (agent_dir / "system_prompt.txt").read_text() == "You are the narrator."

    def test_writes_user_message(self, tmp_path: Path):
        writer = DiagnosticsWriter(tmp_path, turn=1)
        messages = [
            {"role": "system", "content": "System."},
            {"role": "user", "content": "User message 1"},
            {"role": "user", "content": "User message 2"},
        ]
        writer.write_agent("narrator", messages, "raw response")
        agent_dir = tmp_path / "diagnostics" / "turn-001" / "narrator"
        user_text = (agent_dir / "user_message.txt").read_text()
        assert "User message 1" in user_text
        assert "User message 2" in user_text

    def test_writes_raw_response(self, tmp_path: Path):
        writer = DiagnosticsWriter(tmp_path, turn=1)
        messages = [{"role": "system", "content": "Sys."}]
        writer.write_agent("narrator", messages, "The narrator speaks.")
        agent_dir = tmp_path / "diagnostics" / "turn-001" / "narrator"
        assert (agent_dir / "raw_response.txt").read_text() == "The narrator speaks."

    def test_writes_thinking(self, tmp_path: Path):
        writer = DiagnosticsWriter(tmp_path, turn=1)
        messages = [{"role": "system", "content": "Sys."}]
        writer.write_agent("narrator", messages, "response", thinking="Let me think...")
        agent_dir = tmp_path / "diagnostics" / "turn-001" / "narrator"
        assert (agent_dir / "thinking.txt").read_text() == "Let me think..."

    def test_no_thinking_file_when_empty(self, tmp_path: Path):
        writer = DiagnosticsWriter(tmp_path, turn=1)
        messages = [{"role": "system", "content": "Sys."}]
        writer.write_agent("narrator", messages, "response", thinking="")
        agent_dir = tmp_path / "diagnostics" / "turn-001" / "narrator"
        assert not (agent_dir / "thinking.txt").exists()

    def test_writes_parsed_data(self, tmp_path: Path):
        writer = DiagnosticsWriter(tmp_path, turn=1)
        messages = [{"role": "system", "content": "Sys."}]
        parsed = {"narration": "The hero enters.", "mood": "tense"}
        writer.write_agent("narrator", messages, "response", parsed_data=parsed)
        agent_dir = tmp_path / "diagnostics" / "turn-001" / "narrator"
        with open(agent_dir / "parsed.yaml") as f:
            data = yaml.safe_load(f)
        assert data["narration"] == "The hero enters."
        assert data["mood"] == "tense"

    def test_no_parsed_file_when_none(self, tmp_path: Path):
        writer = DiagnosticsWriter(tmp_path, turn=1)
        messages = [{"role": "system", "content": "Sys."}]
        writer.write_agent("narrator", messages, "response", parsed_data=None)
        agent_dir = tmp_path / "diagnostics" / "turn-001" / "narrator"
        assert not (agent_dir / "parsed.yaml").exists()

    def test_writes_call_record(self, tmp_path: Path):
        writer = DiagnosticsWriter(tmp_path, turn=1)
        messages = [{"role": "system", "content": "Sys."}]
        record = _make_record()
        writer.write_agent("narrator", messages, "response", call_record=record)
        agent_dir = tmp_path / "diagnostics" / "turn-001" / "narrator"
        with open(agent_dir / "call_record.yaml") as f:
            data = yaml.safe_load(f)
        assert data["agent"] == "narrator"
        assert data["latency_ms"] == 1500

    def test_multiple_agents_same_turn(self, tmp_path: Path):
        writer = DiagnosticsWriter(tmp_path, turn=1)
        messages = [{"role": "system", "content": "Sys."}]
        writer.write_agent("narrator", messages, "narrator response")
        writer.write_agent("character_maya", messages, "maya response")
        base = tmp_path / "diagnostics" / "turn-001"
        assert (base / "narrator" / "raw_response.txt").exists()
        assert (base / "character_maya" / "raw_response.txt").exists()


class TestWriteSummary:
    def test_writes_summary_file(self, tmp_path: Path):
        writer = DiagnosticsWriter(tmp_path, turn=1)
        records = [
            _make_record(agent="narrator"),
            _make_record(agent="character:maya"),
        ]
        writer.write_summary(records)
        summary_path = tmp_path / "diagnostics" / "turn-001" / "summary.yaml"
        assert summary_path.exists()
        with open(summary_path) as f:
            data = yaml.safe_load(f)
        assert data["turn_calls"] == 2
        assert data["total_latency_ms"] == 3000
        assert data["mean_latency_ms"] == 1500
        assert len(data["agents"]) == 2

    def test_no_file_when_empty(self, tmp_path: Path):
        writer = DiagnosticsWriter(tmp_path, turn=1)
        writer.write_summary([])
        summary_path = tmp_path / "diagnostics" / "turn-001" / "summary.yaml"
        assert not summary_path.exists()

    def test_summary_parse_rate(self, tmp_path: Path):
        writer = DiagnosticsWriter(tmp_path, turn=1)
        r1 = _make_record(agent="narrator")
        r2 = _make_record(agent="game_state")
        r2 = LLMCallRecord(
            timestamp="2026-03-20T14:30:00Z",
            agent="game_state",
            turn=1,
            prompt_tokens=200,
            thinking_tokens=100,
            content_tokens=150,
            latency_ms=1500,
            finish_reason="stop",
            parse_result="invalid_yaml",
            parse_attempts=2,
            retry_count=1,
            temperature=0.2,
            max_tokens=1000,
        )
        writer.write_summary([r1, r2])
        summary_path = tmp_path / "diagnostics" / "turn-001" / "summary.yaml"
        with open(summary_path) as f:
            data = yaml.safe_load(f)
        assert data["parse_success_rate"] == 0.5

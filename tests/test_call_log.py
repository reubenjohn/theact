"""Tests for LLM call logging."""

from pathlib import Path

import yaml

from theact.llm.call_log import LLMCallLog, LLMCallRecord


def _make_record(
    agent: str = "narrator",
    turn: int = 1,
    latency_ms: int = 1000,
    parse_result: str = "success",
    finish_reason: str = "stop",
    retry_count: int = 0,
    prompt_tokens: int = 200,
    thinking_tokens: int = 100,
    content_tokens: int = 150,
) -> LLMCallRecord:
    return LLMCallRecord(
        timestamp="2026-03-20T14:30:00Z",
        agent=agent,
        turn=turn,
        prompt_tokens=prompt_tokens,
        thinking_tokens=thinking_tokens,
        content_tokens=content_tokens,
        latency_ms=latency_ms,
        finish_reason=finish_reason,
        parse_result=parse_result,
        parse_attempts=1,
        retry_count=retry_count,
        temperature=1.0,
        max_tokens=2000,
    )


class TestLLMCallLog:
    def test_log_appends_record(self):
        log = LLMCallLog()
        record = _make_record()
        log.log(record)
        assert len(log.records) == 1
        assert log.records[0] is record

    def test_records_for_turn(self):
        log = LLMCallLog()
        log.log(_make_record(turn=1, agent="narrator"))
        log.log(_make_record(turn=1, agent="character:maya"))
        log.log(_make_record(turn=2, agent="narrator"))
        result = log.records_for_turn(1)
        assert len(result) == 2
        assert all(r.turn == 1 for r in result)

    def test_records_for_turn_empty(self):
        log = LLMCallLog()
        log.log(_make_record(turn=1))
        assert log.records_for_turn(99) == []

    def test_records_for_agent_exact(self):
        log = LLMCallLog()
        log.log(_make_record(agent="narrator"))
        log.log(_make_record(agent="character:maya"))
        log.log(_make_record(agent="game_state"))
        result = log.records_for_agent("narrator")
        assert len(result) == 1
        assert result[0].agent == "narrator"

    def test_records_for_agent_prefix_match(self):
        log = LLMCallLog()
        log.log(_make_record(agent="character:maya"))
        log.log(_make_record(agent="character:joaquin"))
        log.log(_make_record(agent="narrator"))
        result = log.records_for_agent("character")
        assert len(result) == 2
        assert all(r.agent.startswith("character") for r in result)

    def test_records_for_agent_no_match(self):
        log = LLMCallLog()
        log.log(_make_record(agent="narrator"))
        assert log.records_for_agent("memory") == []


class TestLLMCallLogSummary:
    def test_summary_empty(self):
        log = LLMCallLog()
        s = log.summary()
        assert s["total_calls"] == 0
        assert s["mean_latency_ms"] == 0
        assert s["parse_success_rate"] == 0.0

    def test_summary_basic(self):
        log = LLMCallLog()
        log.log(_make_record(latency_ms=1000, parse_result="success"))
        log.log(_make_record(latency_ms=2000, parse_result="success"))
        s = log.summary()
        assert s["total_calls"] == 2
        assert s["mean_latency_ms"] == 1500
        assert s["parse_success_rate"] == 1.0
        assert s["total_prompt_tokens"] == 400
        assert s["total_thinking_tokens"] == 200
        assert s["total_content_tokens"] == 300

    def test_summary_parse_failures(self):
        log = LLMCallLog()
        log.log(_make_record(parse_result="success"))
        log.log(_make_record(parse_result="invalid_yaml"))
        log.log(_make_record(parse_result="empty_response"))
        s = log.summary()
        assert s["parse_success_rate"] == pytest.approx(0.333, abs=0.001)

    def test_summary_length_finishes(self):
        log = LLMCallLog()
        log.log(_make_record(finish_reason="stop"))
        log.log(_make_record(finish_reason="length"))
        log.log(_make_record(finish_reason="length"))
        s = log.summary()
        assert s["length_finishes"] == 2

    def test_summary_retries(self):
        log = LLMCallLog()
        log.log(_make_record(retry_count=0))
        log.log(_make_record(retry_count=2))
        log.log(_make_record(retry_count=1))
        s = log.summary()
        assert s["total_retries"] == 3


class TestAgentSummary:
    def test_agent_summary_groups(self):
        log = LLMCallLog()
        log.log(_make_record(agent="narrator", latency_ms=500))
        log.log(_make_record(agent="narrator", latency_ms=1500))
        log.log(_make_record(agent="character:maya", latency_ms=800))
        result = log.agent_summary()
        assert "narrator" in result
        assert "character:maya" in result
        assert result["narrator"]["total_calls"] == 2
        assert result["narrator"]["mean_latency_ms"] == 1000
        assert result["character:maya"]["total_calls"] == 1

    def test_agent_summary_empty(self):
        log = LLMCallLog()
        assert log.agent_summary() == {}


class TestDumpYaml:
    def test_dump_creates_file(self, tmp_path: Path):
        log = LLMCallLog()
        log.log(_make_record(agent="narrator", turn=1))
        log.log(_make_record(agent="character:maya", turn=1))
        path = tmp_path / "call_log.yaml"
        log.dump_yaml(path)
        assert path.exists()

        with open(path) as f:
            data = yaml.safe_load(f)
        assert len(data) == 2
        assert data[0]["agent"] == "narrator"
        assert data[1]["agent"] == "character:maya"

    def test_dump_creates_parent_dirs(self, tmp_path: Path):
        log = LLMCallLog()
        log.log(_make_record())
        path = tmp_path / "nested" / "deep" / "call_log.yaml"
        log.dump_yaml(path)
        assert path.exists()

    def test_dump_empty(self, tmp_path: Path):
        log = LLMCallLog()
        path = tmp_path / "empty.yaml"
        log.dump_yaml(path)
        assert path.exists()
        with open(path) as f:
            data = yaml.safe_load(f)
        assert data == []

    def test_dump_preserves_all_fields(self, tmp_path: Path):
        log = LLMCallLog()
        record = _make_record(
            agent="memory:joaquin",
            turn=3,
            latency_ms=1234,
            parse_result="invalid_yaml",
            finish_reason="length",
            retry_count=2,
            prompt_tokens=500,
            thinking_tokens=300,
            content_tokens=200,
        )
        log.log(record)
        path = tmp_path / "full.yaml"
        log.dump_yaml(path)

        with open(path) as f:
            data = yaml.safe_load(f)
        entry = data[0]
        assert entry["agent"] == "memory:joaquin"
        assert entry["turn"] == 3
        assert entry["latency_ms"] == 1234
        assert entry["parse_result"] == "invalid_yaml"
        assert entry["finish_reason"] == "length"
        assert entry["retry_count"] == 2
        assert entry["prompt_tokens"] == 500
        assert entry["thinking_tokens"] == 300
        assert entry["content_tokens"] == 200
        assert entry["temperature"] == 1.0
        assert entry["max_tokens"] == 2000


import pytest  # noqa: E402 — needed for pytest.approx

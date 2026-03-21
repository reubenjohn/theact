"""Tests for the context window profiler."""

from theact.llm.profiler import (
    AgentProfile,
    format_profile,
    format_turn_profile,
    profile_messages,
)
from theact.llm.tokens import estimate_messages_content_tokens, estimate_tokens


class TestEstimateMessagesContentTokens:
    def test_empty_messages(self):
        assert estimate_messages_content_tokens([]) == 0

    def test_single_message(self):
        msgs = [{"role": "system", "content": "Hello world test"}]
        expected = estimate_tokens("Hello world test")
        assert estimate_messages_content_tokens(msgs) == expected

    def test_multiple_messages(self):
        msgs = [
            {"role": "system", "content": "System prompt here"},
            {"role": "user", "content": "User input here"},
        ]
        expected = estimate_tokens("System prompt here") + estimate_tokens(
            "User input here"
        )
        assert estimate_messages_content_tokens(msgs) == expected

    def test_missing_content(self):
        msgs = [{"role": "system"}]
        assert estimate_messages_content_tokens(msgs) == 0


class TestProfileMessages:
    def test_basic_profile(self):
        messages = [
            {"role": "system", "content": "You are a narrator." * 10},
            {"role": "user", "content": "Player says: hello." * 5},
        ]
        profile = profile_messages("narrator", messages, max_tokens_budget=2000)
        assert profile.agent == "narrator"
        assert profile.system_prompt_tokens > 0
        assert profile.user_message_tokens > 0
        assert profile.total_prompt_tokens > 0
        assert profile.max_tokens_budget == 2000
        assert profile.context_limit == 8192

    def test_headroom_calculation(self):
        # Minimal messages to get predictable headroom
        messages = [
            {"role": "system", "content": "A" * 400},  # ~100 tokens
            {"role": "user", "content": "B" * 400},  # ~100 tokens
        ]
        profile = profile_messages(
            "test", messages, max_tokens_budget=1000, context_limit=2000
        )
        # total_prompt = 100 + 100 + overhead(2*4 + 3) = 211
        # headroom = 2000 - 211 - 1000 = 789
        assert profile.headroom == 2000 - profile.total_prompt_tokens - 1000

    def test_over_budget_negative_headroom(self):
        messages = [
            {"role": "system", "content": "A" * 4000},  # ~1000 tokens
            {"role": "user", "content": "B" * 4000},  # ~1000 tokens
        ]
        profile = profile_messages(
            "test", messages, max_tokens_budget=7000, context_limit=8192
        )
        assert profile.headroom < 0

    def test_custom_context_limit(self):
        messages = [{"role": "system", "content": "test"}]
        profile = profile_messages(
            "test", messages, max_tokens_budget=100, context_limit=4096
        )
        assert profile.context_limit == 4096

    def test_assistant_messages_counted(self):
        messages = [
            {"role": "system", "content": "System"},
            {"role": "user", "content": "User"},
            {"role": "assistant", "content": "Previous response"},
        ]
        profile = profile_messages("test", messages, max_tokens_budget=1000)
        # Assistant content should be counted in user_message_tokens
        assert profile.user_message_tokens > 0


class TestFormatProfile:
    def test_contains_agent_name(self):
        profile = AgentProfile(
            agent="narrator",
            system_prompt_tokens=200,
            user_message_tokens=300,
            total_prompt_tokens=511,
            max_tokens_budget=2000,
            context_limit=8192,
            headroom=5681,
        )
        text = format_profile(profile)
        assert "narrator" in text
        assert "200" in text
        assert "300" in text

    def test_over_budget_warning(self):
        profile = AgentProfile(
            agent="test",
            system_prompt_tokens=4000,
            user_message_tokens=4000,
            total_prompt_tokens=8011,
            max_tokens_budget=2000,
            context_limit=8192,
            headroom=-1819,
        )
        text = format_profile(profile)
        assert "OVER BUDGET" in text

    def test_no_warning_when_ok(self):
        profile = AgentProfile(
            agent="test",
            system_prompt_tokens=100,
            user_message_tokens=100,
            total_prompt_tokens=211,
            max_tokens_budget=1000,
            context_limit=8192,
            headroom=6981,
        )
        text = format_profile(profile)
        assert "OVER BUDGET" not in text


class TestFormatTurnProfile:
    def test_empty_profiles(self):
        text = format_turn_profile([])
        assert "No agent profiles" in text

    def test_contains_all_agents(self):
        profiles = [
            AgentProfile(
                agent="narrator",
                system_prompt_tokens=200,
                user_message_tokens=300,
                total_prompt_tokens=511,
                max_tokens_budget=2000,
                context_limit=8192,
                headroom=5681,
            ),
            AgentProfile(
                agent="character:maya",
                system_prompt_tokens=150,
                user_message_tokens=250,
                total_prompt_tokens=411,
                max_tokens_budget=1500,
                context_limit=8192,
                headroom=6281,
            ),
        ]
        text = format_turn_profile(profiles)
        assert "narrator" in text
        assert "character:maya" in text
        assert "TOTAL" in text

    def test_shows_min_headroom(self):
        profiles = [
            AgentProfile(
                agent="a",
                system_prompt_tokens=100,
                user_message_tokens=100,
                total_prompt_tokens=211,
                max_tokens_budget=1000,
                context_limit=8192,
                headroom=6981,
            ),
            AgentProfile(
                agent="b",
                system_prompt_tokens=100,
                user_message_tokens=100,
                total_prompt_tokens=211,
                max_tokens_budget=1000,
                context_limit=8192,
                headroom=500,
            ),
        ]
        text = format_turn_profile(profiles)
        assert "Min headroom: 500" in text

    def test_flags_over_budget(self):
        profiles = [
            AgentProfile(
                agent="over",
                system_prompt_tokens=4000,
                user_message_tokens=4000,
                total_prompt_tokens=8011,
                max_tokens_budget=2000,
                context_limit=8192,
                headroom=-1819,
            ),
        ]
        text = format_turn_profile(profiles)
        assert "(!)" in text

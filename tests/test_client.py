"""Tests for the LLM client singleton."""

from openai import AsyncOpenAI

from theact.llm.client import get_client, reset_client
from theact.llm.config import LLMConfig


class TestGetClient:
    def setup_method(self):
        reset_client()

    def teardown_method(self):
        reset_client()

    def test_returns_async_openai(self):
        config = LLMConfig(api_key="test-key")
        client = get_client(config)
        assert isinstance(client, AsyncOpenAI)

    def test_singleton(self):
        config = LLMConfig(api_key="test-key")
        client1 = get_client(config)
        client2 = get_client(config)
        assert client1 is client2

    def test_singleton_ignores_new_config(self):
        config1 = LLMConfig(api_key="key-1")
        config2 = LLMConfig(api_key="key-2")
        client1 = get_client(config1)
        client2 = get_client(config2)
        assert client1 is client2  # same singleton

    def test_reset_allows_new_client(self):
        config = LLMConfig(api_key="test-key")
        client1 = get_client(config)
        reset_client()
        client2 = get_client(config)
        assert client1 is not client2

"""TheAct LLM client layer — async inference, streaming, structured output."""

from theact.llm.client import get_client, reset_client
from theact.llm.config import (
    GAME_STATE_CONFIG,
    CHARACTER_CONFIG,
    MEMORY_UPDATE_CONFIG,
    NARRATOR_CONFIG,
    SUMMARIZER_CONFIG,
    AgentLLMConfig,
    LLMConfig,
    load_llm_config,
)
from theact.llm.call_log import LLMCallLog, LLMCallRecord
from theact.llm.errors import (
    LLMConnectionError,
    LLMError,
    LLMRateLimitError,
    LLMResponseError,
    ParseFailureType,
)
from theact.llm.inference import (
    Message,
    complete,
    complete_structured,
    stream,
    stream_structured,
)
from theact.llm.parsing import (
    YAMLParseError,
    classify_parse_failure,
    parse_yaml_response,
    validate_yaml_fields,
)
from theact.llm.streaming import (
    LLMResult,
    StreamChunk,
    StructuredResult,
    collect_stream,
)
from theact.llm.profiler import (
    AgentProfile,
    format_profile,
    format_turn_profile,
    profile_messages,
)
from theact.llm.tokens import (
    estimate_messages_content_tokens,
    estimate_messages_tokens,
    estimate_tokens,
    tokens_remaining,
)

__all__ = [
    # Config
    "LLMConfig",
    "AgentLLMConfig",
    "load_llm_config",
    "NARRATOR_CONFIG",
    "CHARACTER_CONFIG",
    "MEMORY_UPDATE_CONFIG",
    "GAME_STATE_CONFIG",
    "SUMMARIZER_CONFIG",
    # Client
    "get_client",
    "reset_client",
    # Inference
    "Message",
    "complete",
    "stream",
    "complete_structured",
    "stream_structured",
    # Result types
    "LLMResult",
    "StreamChunk",
    "StructuredResult",
    "collect_stream",
    # Parsing
    "parse_yaml_response",
    "validate_yaml_fields",
    "classify_parse_failure",
    "YAMLParseError",
    # Tokens
    "estimate_tokens",
    "estimate_messages_tokens",
    "estimate_messages_content_tokens",
    "tokens_remaining",
    # Profiler
    "AgentProfile",
    "profile_messages",
    "format_profile",
    "format_turn_profile",
    # Call log
    "LLMCallLog",
    "LLMCallRecord",
    # Errors
    "ParseFailureType",
    "LLMError",
    "LLMConnectionError",
    "LLMRateLimitError",
    "LLMResponseError",
]
